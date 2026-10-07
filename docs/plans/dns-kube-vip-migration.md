# Plan: Declarative DNS (Blocky) + k3s API LB (kube-vip)

## Objective

Migrate DNS and ad-blocking from the Raspberry Pi Pi-hole to a declarative,
GitOps-managed deployment on Kubernetes using **Blocky**, and replace the Pi's
k3s API load balancer with **kube-vip** fronted by a LAN VIP.

Pi-hole will remain running during the transition as a backup DNS server.

## Current setup

### k3s control-plane nodes

| Node | Current `InternalIP` | LAN IP       |
|------|----------------------|--------------|
| m1   | `100.106.227.127`    | `192.168.0.90`  |
| m2   | `100.106.10.114`     | `192.168.0.76`  |
| m3   | `100.121.32.66`      | `192.168.0.158` |

Current API endpoint from the workstation:

```bash
kubectl config view -o jsonpath='{.clusters[?(@.name=="default")].cluster.server}'
# https://k8s.int.kyledev.co:6443
```

### Current k3s API load balancer

Pi-hole is running haproxy on TCP `6443` and forwards to both Tailscale and LAN
addresses for each control-plane node:

```cfg
backend k3s-backend
    mode tcp
    option tcp-check
    balance roundrobin
    default-server inter 10s downinter 5s
    server m1-ts 100.106.227.127:6443 check
    server m1-lan 192.168.0.90:6443 check
    server m2-ts 100.106.10.114:6443 check
    server m2-lan 192.168.0.76:6443 check
    server m3-ts 100.121.32.66:6443 check
    server m3-lan 192.168.0.158:6443 check
```

### MetalLB

Pool: `192.168.0.230-192.168.0.250`

Envoy Gateway already occupies `192.168.0.249`.

## Decisions

| Item | Choice |
|---|---|
| DNS backend | **Blocky** |
| Blocky LAN IP | `192.168.0.21` via MetalLB |
| Blocky tailnet exposure | Yes, via Tailscale `LoadBalancer` class |
| k3s API VIP | `192.168.0.20` via kube-vip on `eth0` |
| Pi-hole | Keep running as backup; no DNS cutover yet |
| Tailscale subnet routes | None required |
| kube-vip backend IPs | **LAN IPs of `m1/m2/m3`** |

## Step 1: Reconfigure k3s control-plane nodes to use LAN IPs

`m1`, `m2`, and `m3` currently report their Kubernetes `InternalIP` as Tailscale
addresses. kube-vip would use those Tailscale IPs as IPVS backends, making the
API load balancer depend on Tailscale.

To remove that dependency, reconfigure each k3s server to use its LAN IP as
`--node-ip`.

### 1.1 Update k3s server configuration

For each node, edit the k3s server configuration at `/etc/rancher/k3s/config.yaml`:

```yaml
# m1
node-ip: 192.168.0.90
tls-san:
  - k8s.int.kyledev.co
  - 192.168.0.20

# m2
node-ip: 192.168.0.76
tls-san:
  - k8s.int.kyledev.co
  - 192.168.0.20

# m3
node-ip: 192.168.0.158
tls-san:
  - k8s.int.kyledev.co
  - 192.168.0.20
```

If using systemd drop-in or command-line flags, add:

```bash
--node-ip 192.168.0.90   # m1
--node-ip 192.168.0.76   # m2
--node-ip 192.168.0.158  # m3
```

### 1.2 Cutover procedure (one node at a time)

To avoid losing quorum, update and restart one control-plane node at a time.

1. Update `m1` first (the other servers join through it).
2. Update its k3s config with the LAN IP and `tls-san` entries.
3. Restart k3s:
   ```bash
   sudo systemctl restart k3s
   ```
4. Wait for the node to become `Ready`:
   ```bash
   kubectl wait --for=condition=Ready node/m1 --timeout=120s
   ```
5. Verify its `InternalIP` is now the LAN IP:
   ```bash
   kubectl get node m1 -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'
   ```
6. Update `m2` and `m3`, setting their `server:` URL to `https://192.168.0.90:6443`
   (m1's LAN IP) instead of the Tailscale hostname.
7. Repeat the restart/verify steps for `m2`, then `m3`.

After all three are restarted, verify the cluster Endpoints are using the LAN
IPs:

```bash
kubectl get nodes -o wide
kubectl get endpoints kubernetes
```

Expected output for the `kubernetes` Endpoints:

```yaml
subsets:
- addresses:
  - ip: 192.168.0.90
  - ip: 192.168.0.76
  - ip: 192.168.0.158
```

**Do not proceed to Step 2 until the Endpoints show the LAN IPs.**

### 1.3 Rollback per node

If a node does not come back after switching to its LAN IP:

1. Revert the config change on that node.
2. Restart k3s again:
   ```bash
   sudo systemctl restart k3s
   ```
3. Verify the node returns to `Ready` with its Tailscale `InternalIP`.

## Step 2: Publish `homelab-chart` 0.2.0

The upstream chart at `github.com/kdwils/helm-charts/charts/homelab-chart` has
been updated with:

- `DaemonSet` support (`templates/daemonset.yaml`)
- `hostNetwork`, `hostPID`, `hostIPC`, `dnsPolicy` for Deployment/DaemonSet
- `extraServices` support (`templates/extraservices.yaml`)
- RBAC support (`templates/rbac.yaml`)
- Chart version bumped to `0.2.0`

Publish the OCI artifact to `ghcr.io/kdwils/charts/homelab-chart:0.2.0`.

## Step 3: Update the consolidated `charts/homelab` meta-chart

`charts/homelab/Chart.yaml` now requires `^0.2.0` and includes two new aliases:

```yaml
version: 0.2.0
dependencies:
  - name: homelab-chart
    version: ^0.2.0
    repository: oci://ghcr.io/kdwils/charts
    alias: blocky
  - name: homelab-chart
    version: ^0.2.0
    repository: oci://ghcr.io/kdwils/charts
    alias: kube-vip
  # ... existing aliases bumped to ^0.2.0
```

Then update cached dependencies:

```bash
cd charts/homelab && helm dependency update
```

## Step 4: Create source values files

### `infra/blocky/environments/homelab/homelab.yaml`

```yaml
blocky:
  serviceAccount:
    create: true

  deployment:
    create: true
    replicas: 2
    image:
      repository: ghcr.io/0xerr0r/blocky
      tag: v0.35.0
    args:
      - --config
      - /app/config/config.yml
    env:
      TZ: America/New_York
    resources:
      limits:
        memory: 256Mi
        cpu: 500m
      requests:
        memory: 128Mi
        cpu: 100m
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app.kubernetes.io/name: blocky
            topologyKey: kubernetes.io/hostname

  configmap:
    create: true
    configmaps:
      - name: blocky-config
        mountPath: /app/config
        readOnly: true
        data:
          config.yml: |
            upstreams:
              groups:
                default:
                  - 1.1.1.1
                  - 9.9.9.9
            bootstrapDns:
              - tcp+udp:1.1.1.1
            customDNS:
              customTTL: 1h
              mapping:
                int.kyledev.co: 192.168.0.249
                nas.int.kyledev.co: 192.168.0.170
                k8s.int.kyledev.co: 192.168.0.20
                ts.kyledev.co: 100.89.149.17
            blocking:
              denylists:
                ads:
                  - https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts
                  - https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/pro.txt
              clientGroupsBlock:
                default:
                  - ads
              blockType: zeroIp
              loading:
                refreshPeriod: 24h
            ports:
              dns: 5353
              http: 4000
            log:
              level: info

  service:
    create: true
    type: LoadBalancer
    annotations:
      metallb.universe.tf/loadBalancerIPs: "192.168.0.21"
    ports:
      - name: dns-udp
        port: 53
        targetPort: 5353
        protocol: UDP
      - name: dns-tcp
        port: 53
        targetPort: 5353
        protocol: TCP
      - name: http
        port: 4000
        targetPort: 4000
        protocol: TCP

  extraServices:
    - name: tailscale
      type: LoadBalancer
      loadBalancerClass: tailscale
      annotations:
        tailscale.com/expose: "true"
      ports:
        - name: dns-udp
          port: 53
          targetPort: 5353
          protocol: UDP
        - name: dns-tcp
          port: 53
          targetPort: 5353
          protocol: TCP

  httproute:
    create: false

  pvc:
    create: false
```

### `infra/kube-vip/environments/homelab/homelab.yaml`

```yaml
kube-vip:
  serviceAccount:
    create: true
    automount: true

  deployment:
    create: false

  daemonset:
    create: true
    hostNetwork: true
    dnsPolicy: ClusterFirstWithHostNet
    nodeSelector:
      node-role.kubernetes.io/control-plane: "true"
    tolerations:
      - effect: NoSchedule
        operator: Exists
      - effect: NoExecute
        operator: Exists
    image:
      repository: ghcr.io/kube-vip/kube-vip
      tag: v1.2.4
    args:
      - manager
    securityContext:
      capabilities:
        add:
          - NET_ADMIN
          - NET_RAW
          - SYS_TIME
    env:
      vip_arp: "true"
      vip_interface: eth0
      address: 192.168.0.20
      port: "6443"
      vip_subnet: "32"
      cp_enable: "true"
      cp_namespace: kube-system
      lb_enable: "true"
      svc_enable: "false"
      vip_leaderelection: "true"
      vip_leaseduration: "5"
      vip_renewdeadline: "3"
      vip_retryperiod: "1"

  rbac:
    create: true
    rules:
      - apiGroups: [""]
        resources: ["nodes", "services", "endpoints", "pods"]
        verbs: ["get", "list", "watch"]
      - apiGroups: ["coordination.k8s.io"]
        resources: ["leases"]
        verbs: ["get", "create", "update"]

  service:
    create: false

  pvc:
    create: false

  httproute:
    create: false
```

## Step 5: Create ArgoCD applications

### `infra/applications/blocky.yaml`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: blocky
  namespace: argocd
  annotations:
    kargo.akuity.io/authorized-stage: blocky:homelab
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: dns
    server: "https://kubernetes.default.svc"
  source:
    path: infra/blocky/environments/homelab
    repoURL: "https://github.com/kdwils/homelab"
    targetRevision: homelab
  sources: []
  project: infra
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### `infra/applications/kube-vip.yaml`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kube-vip
  namespace: argocd
  annotations:
    kargo.akuity.io/authorized-stage: kube-vip:homelab
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    namespace: kube-system
    server: "https://kubernetes.default.svc"
  source:
    path: infra/kube-vip/environments/homelab
    repoURL: "https://github.com/kdwils/homelab"
    targetRevision: homelab
  sources: []
  project: infra
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

Add both to `infra/applications/kustomization.yaml`.

## Step 6: Create Kargo projects

### `apps/kargo/resources/projects/blocky.yaml`

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: Project
metadata:
  name: blocky
  annotations:
    kargo.akuity.io/keep-namespace: "true"
---
apiVersion: kargo.akuity.io/v1alpha1
kind: ProjectConfig
metadata:
  name: blocky
  namespace: blocky
spec:
  promotionPolicies:
    - stageSelector:
        name: main
      autoPromotionEnabled: true
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Warehouse
metadata:
  name: blocky
  namespace: blocky
spec:
  interval: "1h0m0s"
  subscriptions:
    - image:
        repoURL: ghcr.io/0xerr0r/blocky
        constraint: ^0.25.0
        strictSemvers: false
    - git:
        repoURL: https://github.com/kdwils/homelab.git
        branch: main
        includePaths:
          - glob:infra/blocky/environments/**
          - glob:charts/homelab/**
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: main
  namespace: blocky
spec:
  requestedFreight:
    - origin:
        kind: Warehouse
        name: blocky
      sources:
        direct: true
  promotionTemplate:
    spec:
      vars:
        - name: targetBranch
          value: main
        - name: warehouse
          value: blocky
        - name: imageRepo
          value: ghcr.io/0xerr0r/blocky
        - name: valuesFilePath
          value: infra/blocky/environments/homelab/homelab.yaml
        - name: imageTagYamlPath
          value: blocky.deployment.image.tag
      steps:
        - task:
            name: update-source-main
            kind: ClusterPromotionTask
```

### `apps/kargo/resources/projects/kube-vip.yaml`

```yaml
apiVersion: kargo.akuity.io/v1alpha1
kind: Project
metadata:
  name: kube-vip
  annotations:
    kargo.akuity.io/keep-namespace: "true"
---
apiVersion: kargo.akuity.io/v1alpha1
kind: ProjectConfig
metadata:
  name: kube-vip
  namespace: kube-vip
spec:
  promotionPolicies:
    - stageSelector:
        name: main
      autoPromotionEnabled: true
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Warehouse
metadata:
  name: kube-vip
  namespace: kube-vip
spec:
  interval: "1h0m0s"
  subscriptions:
    - image:
        repoURL: ghcr.io/kube-vip/kube-vip
        constraint: ^0.8.0
        strictSemvers: false
    - git:
        repoURL: https://github.com/kdwils/homelab.git
        branch: main
        includePaths:
          - glob:infra/kube-vip/environments/**
          - glob:charts/homelab/**
---
apiVersion: kargo.akuity.io/v1alpha1
kind: Stage
metadata:
  name: main
  namespace: kube-vip
spec:
  requestedFreight:
    - origin:
        kind: Warehouse
        name: kube-vip
      sources:
        direct: true
  promotionTemplate:
    spec:
      vars:
        - name: targetBranch
          value: main
        - name: warehouse
          value: kube-vip
        - name: imageRepo
          value: ghcr.io/kube-vip/kube-vip
        - name: valuesFilePath
          value: infra/kube-vip/environments/homelab/homelab.yaml
        - name: imageTagYamlPath
          value: kube-vip.daemonset.image.tag
      steps:
        - task:
            name: update-source-main
            kind: ClusterPromotionTask
```

Add both to `apps/kargo/resources/projects/kustomization.yaml`.

## Step 7: Update the global render task

Add two `helm-template` steps to `apps/kargo/resources/tasks/render-homelab.yaml`
before the `git-commit` step:

```yaml
- uses: helm-template
  as: render-blocky
  config:
    path: ./source/charts/homelab
    valuesFiles:
      - ./source/infra/blocky/environments/homelab/homelab.yaml
    namespace: dns
    releaseName: blocky
    outPath: ./target/infra/blocky/environments/homelab/manifest.yaml
- uses: helm-template
  as: render-kube-vip
  config:
    path: ./source/charts/homelab
    valuesFiles:
      - ./source/infra/kube-vip/environments/homelab/homelab.yaml
    namespace: kube-system
    releaseName: kube-vip
    outPath: ./target/infra/kube-vip/environments/homelab/manifest.yaml
```

## Step 8: Commit and let Kargo render

1. Commit all source changes to `main` and push.
2. The per-app Kargo projects will auto-promote image updates on `main`.
3. The global `homelab-project` will detect `main` changes, render manifests,
   and open a PR against the `homelab` branch.
4. Merge the PR; ArgoCD will sync `blocky` and `kube-vip`.

## Step 9: Verify deployments

### kube-vip

```bash
kubectl get daemonset -n kube-system kube-vip
kubectl get endpoints kubernetes
# endpoints should still be the LAN IPs of m1/m2/m3
```

Temporarily point `k8s.int.kyledev.co` to the VIP in `/etc/hosts`:

```bash
192.168.0.20 k8s.int.kyledev.co
```

Then test:

```bash
kubectl get nodes
```

### Blocky

```bash
dig @192.168.0.21 k8s.int.kyledev.co
dig @192.168.0.21 nas.int.kyledev.co
dig @192.168.0.21 doubleclick.net
```

## Step 10: Cut over DNS

When Blocky and kube-vip are stable:

1. Update router/DHCP:
   - Primary DNS → `192.168.0.21`
   - Secondary DNS → Pi-hole IP
2. Update Tailscale global nameserver to Blocky's tailnet IP (from the
   `blocky-tailscale` Tailscale Service).
3. Remove the temporary `/etc/hosts` entry for `k8s.int.kyledev.co` once the
   LAN DNS record resolves to `192.168.0.20`.

## Step 11: Decommission Pi-hole and haproxy

After Blocky has been the primary DNS for a satisfactory period:

1. Disable or remove the haproxy k3s API load balancer on the Pi-hole box.
2. Decommission Pi-hole or repurpose the device.
3. Update `docs/diagrams/network-architecture.yaml` and regenerate diagrams:
   - Replace Pi-hole DNS node with Blocky.
   - Add kube-vip node/VIP for `k8s.int.kyledev.co`.
   - Update routing edges accordingly.

## Risks and notes

- **k3s node IP change** is the riskiest step. Perform one node at a time and
  verify cluster health before continuing.
- **Blocky wildcard override**: verify that `nas.int.kyledev.co` overrides
  `int.kyledev.co`. If not, switch `customDNS` to a zone file.
- **kube-proxy IPVS mode**: if k3s is using IPVS proxy mode, kube-proxy may
  delete kube-vip's IPVS rules. k3s defaults to iptables, but confirm if IPVS
  is enabled.
- **Cluster-down = LAN DNS down** for clients using Blocky. Keeping Pi-hole as
  secondary mitigates this.
- Do **not** switch the router or Tailscale DNS until Blocky and kube-vip are
  verified.
