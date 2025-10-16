# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a declarative K3s homelab cluster managed via GitOps with ArgoCD. The repository contains Kubernetes manifests organized into four main projects:

- **apps**: Personal projects and open source applications
- **infra**: Critical cluster infrastructure (ArgoCD, cert-manager, sealed-secrets, envoy-gateway, metallb, etc.)
- **media**: *arr stack for media management (Plex, Sonarr, Radarr, Prowlarr, etc.)
- **monitoring**: Observability stack (Prometheus, Grafana, CrowdSec, Trivy)

## Architecture

### ArgoCD App-of-Apps Pattern

The repository uses ArgoCD's app-of-apps pattern with a parent application that manages child applications:

1. **Parent Application** (`projects/parent-app.yaml`): Bootstraps the entire cluster by syncing from the root of this repo
2. **Project Definitions** (`projects/*.yaml`): Define ArgoCD AppProjects (apps, infra, media, monitoring) with RBAC and source repo whitelists
3. **Application Manifests** (`*/applications/*.yaml`): Individual ArgoCD Application resources that reference subdirectories

Each subdirectory (e.g., `apps/hoarder/`, `infra/argocd/`) contains Kustomize manifests for that specific application.

### Directory Structure

```
.
├── apps/                    # User-facing applications
│   ├── applications/        # ArgoCD Application manifests
│   └── {app-name}/          # Kustomize manifests per app
├── infra/                   # Infrastructure components
│   ├── applications/        # ArgoCD Application manifests
│   └── {component}/         # Kustomize manifests per component
├── media/                   # Media stack applications
│   ├── applications/        # ArgoCD Application manifests
│   └── {app-name}/          # Kustomize manifests per app
├── monitoring/              # Monitoring and security
│   ├── applications/        # ArgoCD Application manifests
│   └── {component}/         # Kustomize manifests per component
└── projects/                # ArgoCD project definitions
```

### Secrets Management

Secrets are encrypted using **Sealed Secrets** before committing to git:
- Encrypted secrets have `-sealedsecret.yaml` or `sealedsecret.yaml` suffix
- The sealed-secrets controller decrypts them in-cluster
- Never commit unencrypted secrets (check `.gitignore`)

### Networking Stack

**Ingress**: Envoy Gateway is the primary ingress controller
- Gateway definition: `infra/envoy-gateway/gateway.yaml`
- Applications use `HTTPRoute` resources (not traditional Ingress)
- Routes reference the `homelab` Gateway in `envoy-gateway-system` namespace

**Load Balancer**: MetalLB provides LoadBalancer services on bare metal

**Service Mesh/Security**:
- CrowdSec for application security (AppSec, WAF)
- SecurityPolicy resources attach CrowdSec's envoy-proxy-bouncer to HTTPRoutes for external authentication
- Example: `apps/bluesky/securitypolicy.yaml` protects the bluesky HTTPRoute

**DNS/Tunneling**:
- Cloudflared for external access via Cloudflare Tunnel
- Tailscale for private VPN access (some services use LoadBalancer with `loadBalancerClass: tailscale`)

### CrowdSec Security Architecture

CrowdSec has three components in `monitoring/crowdsec/`:
1. **LAPI** (`lapi.yaml`): Local API that receives alerts from agents
2. **Agent** (`agent.yaml`): DaemonSet that reads Kubernetes audit logs
3. **AppSec** (`appsec.yaml`): Application security component (WAF) with 2 replicas
4. **Profiles** (`profiles.yaml`): ConfigMap defining remediation profiles (ban duration, etc.)
5. **Envoy Proxy Bouncer** (`monitoring/envoy-proxy-bouncer/`): gRPC service that enforces CrowdSec decisions on Envoy Gateway

Applications protected by CrowdSec have SecurityPolicy resources that reference the bouncer service.

## Common Development Tasks

### Adding a New Application

1. Create directory under appropriate project (apps/media/etc): `mkdir apps/myapp`
2. Add Kustomize manifests in `apps/myapp/kustomization.yaml`
3. Create ArgoCD Application manifest in `apps/applications/myapp.yaml`:
   ```yaml
   apiVersion: argoproj.io/v1alpha1
   kind: Application
   metadata:
     name: myapp
     namespace: argocd
     finalizers:
       - resources-finalizer.argocd.argoproj.io
   spec:
     destination:
       namespace: myapp
       server: "https://kubernetes.default.svc"
     source:
       path: apps/myapp
       repoURL: "https://github.com/kdwils/homelab"
       targetRevision: HEAD
     project: apps
     syncPolicy:
       automated:
         prune: true
         selfHeal: true
   ```
4. If exposing via HTTP, create HTTPRoute referencing the `homelab` Gateway:
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata:
     name: myapp
     namespace: myapp
   spec:
     hostnames:
       - myapp.kyledev.co
     parentRefs:
       - name: homelab
         namespace: envoy-gateway-system
     rules:
       - backendRefs:
           - name: myapp
             port: 8080
   ```
5. (Optional) Add SecurityPolicy for CrowdSec protection:
   ```yaml
   apiVersion: gateway.envoyproxy.io/v1alpha1
   kind: SecurityPolicy
   metadata:
     name: myapp
     namespace: myapp
   spec:
     targetRefs:
       - group: gateway.networking.k8s.io
         kind: HTTPRoute
         name: myapp
     extAuth:
       grpc:
         backendRefs:
           - group: ""
             kind: Service
             name: homelab-envoy-proxy-bouncer
             port: 8080
             namespace: envoy-gateway-system
   ```

### Managing Secrets

To create a sealed secret:
```bash
# Create a regular secret (DO NOT commit this)
kubectl create secret generic mysecret --from-literal=password=mypassword --dry-run=client -o yaml > secret.yaml

# Seal it using kubeseal (requires access to the cluster)
kubeseal -f secret.yaml -w sealedsecret.yaml --controller-name=sealed-secrets --controller-namespace=kube-system

# Commit the sealed secret
git add sealedsecret.yaml
```

### Updating Container Images

Renovate Bot automatically creates PRs for image updates based on `renovate.json` configuration:
- Patch/minor updates are grouped weekly (Mondays before 6am)
- Major updates require manual approval via dependency dashboard
- Security-critical apps (vaultwarden, pocketid) always require approval

To manually update an image in a kustomization.yaml:
```yaml
images:
  - name: original/image
    newName: registry/actual-image
    newTag: v1.2.3  # Update this version
```

### Kustomize Usage

All applications use Kustomize for manifest generation. Common patterns:

**Simple app** (`kustomization.yaml`):
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespace.yaml
  - deployment.yaml
  - service.yaml
  - httproute.yaml
```

**With patches**:
```yaml
resources:
  - https://raw.githubusercontent.com/example/app/v1.0.0/manifests.yaml
namespace: myapp
patches:
  - target:
      kind: ConfigMap
      name: app-config
    path: config-patch.yaml
```

**Image transformation**:
```yaml
images:
  - name: app
    newName: ghcr.io/user/app
    newTag: v2.0.0
```

## Personal Projects

This homelab includes several custom projects:

- **tinyauth** (`apps/tinyauth/`): Custom authentication service (v4 tag in git)
- **pocketid** (`apps/pocketid/`): Identity provider with RBAC
- **blog** (`apps/applications/blog.yaml`): Blog deployment from separate repo with Kargo-based promotion (dev → prod)

The blog uses Kargo for progressive delivery with dev/prod environments managed in a separate repository (`kdwils/blog-deploy`).

## Monitoring and Observability

- **Prometheus** (`monitoring/prometheus/`): Metrics collection
- **Grafana** (`monitoring/grafana/`): Metrics visualization
- **CrowdSec** (`monitoring/crowdsec/`): Security monitoring with AppSec/WAF

ServiceMonitor resources are used for Prometheus scraping (e.g., `infra/envoy-gateway/servicemonitor.yaml`).

## Important Notes

- **Always use Kustomize**: All manifests should be managed via kustomization.yaml files
- **Namespace per app**: Each application typically gets its own namespace
- **SyncPolicy automation**: Apps use `prune: true` and `selfHeal: true` for automatic reconciliation
- **HTTPRoute not Ingress**: Use Gateway API HTTPRoutes, not traditional Ingress resources
- **Security by default**: Consider adding SecurityPolicy resources for internet-facing services
- **Sealed secrets only**: Never commit unencrypted secrets; use kubeseal first
- **Git is source of truth**: ArgoCD syncs from main branch; changes must be committed to take effect
