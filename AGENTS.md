# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Repository Overview

This is a GitOps-managed homelab Kubernetes cluster (k3s) using ArgoCD for continuous deployment and Kargo for progressive delivery. Applications are organized into four ArgoCD projects: **infra** (infrastructure), **apps** (personal projects), **media** (*arr stack), and **monitoring** (observability).

Source-of-truth Helm values live on `main`. Kargo renders those values into plain Kubernetes manifests and pushes them to the shared **`homelab`** branch. ArgoCD then syncs from the `homelab` branch for rendered apps, or directly from `main` for simple Kustomize apps.

## Essential Commands

### Cluster Interaction
```bash
# View cluster resources
kubectl get applications -n argocd
kubectl get appprojects -n argocd
kubectl get stages,warehouses -A  # Kargo resources

# Sync an ArgoCD application manually
kubectl patch app <app-name> -n argocd -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}' --type merge

# Check Kargo promotion status
kubectl get freight -n <namespace>
kubectl describe stage <stage-name> -n <namespace>
```

### Local Development
```bash
# Validate Kubernetes manifests
kubectl apply --dry-run=client -f <file>

# Build manifests with Kustomize
kustomize build <directory>

# Validate Helm chart
helm template <release-name> <chart-path> -f <values-file>

# Create/update sealed secrets
kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system -o yaml < secret.yaml > sealedsecret.yaml

# Regenerate the network/platform diagram (source of truth is the YAML, not the HTML/SVG)
cd docs/diagrams && python3 generate_diagrams.py && python3 export_svgs.py
```

## Architecture

### GitOps Workflow

1. **Parent Application** (`projects/parent-app.yaml`) - Bootstrap application that manages everything
2. **Top-level Kustomization** (`kustomization.yaml`) - References all project application directories
3. **ArgoCD Projects** (`projects/*.yaml`) - Define project boundaries and permissions
4. **ArgoCD Applications** (`*/applications/*.yaml`) - Point either to rendered manifests on the `homelab` branch or to Kustomize directories on `main`

### Kargo Progressive Delivery

Kargo resources live under `apps/kargo/`. There are two kinds of Kargo projects in this repo:

#### 1. Per-Application Projects (`apps/kargo/resources/projects/<app>.yaml`)

Each app has a project/warehouse/stage that watches:
- The app's container image (semver)
- Git paths under the app's `environments/**` directory
- `charts/homelab/**` (for apps using the consolidated chart)

When new freight is available, the `main` stage opens a PR against `main` that updates image tags (or chart versions) in the source values files. `autoPromotionEnabled: true` means this happens automatically.

#### 2. Global Render Project (`apps/kargo/resources/projects/homelab-project.yaml`)

- **Warehouse** `homelab-project` watches all source files on `main` (`apps/**`, `infra/**`, `media/**`, `monitoring/**`, `charts/**`)
- **Stage** `deploy` runs the `render-homelab` ClusterPromotionTask
- The `render-homelab` task (`apps/kargo/resources/tasks/render-homelab.yaml`) runs `helm template` for every app and writes the rendered manifests to the `homelab` branch
- It then opens a PR against `homelab`; once merged, ArgoCD syncs

**Promotion Flow**:
```
New image/chart -> App project updates source values on main (PR) -> PR merged ->
homelab-project detects main change -> render-homelab renders all manifests -> PR opened against homelab ->
manual approval -> ArgoCD syncs
```

When adding or removing an app, update the `render-homelab` ClusterPromotionTask so the new app is rendered and obsolete apps are removed.

### Application Patterns

**Pattern A: Consolidated `homelab-chart` (most apps and media)**

The majority of apps use the shared `homelab-chart` via a single consolidated meta-chart at `charts/homelab`. The meta-chart declares each app as a dependency with an alias:

```yaml
# charts/homelab/Chart.yaml snippet
dependencies:
  - name: homelab-chart
    version: ^0.1.0
    repository: oci://ghcr.io/kdwils/charts
    alias: radarr
```

Directory layout:
```
apps/<app>/
  environments/
    homelab/
      homelab.yaml       # values under the alias key (e.g. "radarr:")
    # some apps have multiple environments, e.g. blog/dev and blog/prod

media/<app>/
  environments/
    homelab/
      homelab.yaml       # values under the alias key
```

ArgoCD Application:
```yaml
source:
  path: apps/<app>/environments/homelab   # or media/<app>/environments/homelab
  targetRevision: homelab
```

On `main`, that path contains `homelab.yaml` (source values). On the `homelab` branch, Kargo writes `manifest.yaml` (rendered manifests) to the same path.

Apps using this pattern include: blog, bluesky, baldsky, mealie, pocketid, rss, vaultwarden, events, and most media apps (radarr, sonarr, bazarr, prowlarr, byparr, flaresolverr, plex, transmission, mgnx, mediaz).

**Pattern A2: Third-party chart wrapper** (`charts/<component>/`)

Used for upstream infrastructure components that have their own Helm chart. The wrapper chart depends on both the upstream chart (aliased to the component name) and `homelab-chart` (aliased `homelab`) for HTTPRoute/SecurityPolicy extras.

```
charts/<component>/
  Chart.yaml                 # upstream chart + homelab-chart dependency
  charts/                    # cached .tgz dependencies
<project>/<component>/
  environments/homelab/
    homelab.yaml             # values for both the upstream chart and homelab-chart
```

Examples: argocd, cert-manager, cloudflared, cnpg, coder, crowdsec, envoy-gateway, envoy-proxy-bouncer, kargo, kube-prometheus-stack, longhorn, nats, sealedsecrets, seerr, tailscale, vpa.

**Pattern B: Simple Kustomize**

Direct Kubernetes manifests with a `kustomization.yaml`. ArgoCD points to the directory on `main` (`targetRevision: HEAD`). Renovate manages image updates.

Examples: `apps/excalidraw/`, `apps/hoarder/`.

### Infrastructure Components (Critical Deployment Order)

1. **SealedSecrets** - Encrypts secrets in git, decrypts in cluster
2. **ArgoCD** - GitOps controller
3. **Cert-Manager** - TLS certificate management
4. **Envoy Gateway** - Gateway API ingress controller, terminates TLS
5. **Storage** - NFS provisioner, Longhorn

All managed as ArgoCD applications with automated sync.

### Secrets Management

Secrets use the SealedSecrets operator:
- Encrypted with `kubeseal` before committing to git
- Stored as `SealedSecret` resources with `encryptedData`
- Automatically decrypted by the controller in cluster
- Apps reference the decrypted `Secret` via `envFrom.secretRef`

**Common Pattern in Helm Values**:
```yaml
sealedsecrets:
  - name: <app>-secret
    data:
      KEY_NAME: AgAr...  # Encrypted value
```

The `homelab-chart` template creates both the SealedSecret and references it in pods.

### Ingress Pattern

All applications use Envoy Gateway with HTTPRoute resources:

```yaml
httproute:
  create: true
  hostnames:
    - <app>.kyledev.co         # Public
    - <app>.int.kyledev.co     # Internal
    - <app>.ts.kyledev.co      # Tailscale
  parentRefs:
    - name: homelab
      namespace: envoy-gateway-system
```

See `docs/diagrams/` for the full picture of how these hostnames resolve and route into the gateway (Cloudflare Tunnel, the Plex VPS+Caddy exception, Pihole DNS, cert-manager, CrowdSec ext-authz) and how Kargo/ArgoCD fit around it.

### Authentication

Many apps integrate with **PocketID** (self-hosted OIDC provider):
- OIDC configuration URL: `https://pocketid.kyledev.co/.well-known/openid-configuration`
- Client credentials stored as SealedSecrets
- User groups: `friends`, `admins`

Some apps also use **CrowdSec** with an Envoy proxy bouncer for security:
```yaml
securityPolicy:
  extAuth:
    grpc:
      backendRefs:
        - name: homelab-envoy-proxy-bouncer
          namespace: envoy-gateway-system
```

### Dependency Updates

**Renovate** (`renovate.json`):
- Runs Monday mornings
- Auto-updates patch/minor versions (grouped weekly)
- Major versions require dashboard approval
- Pinned versions for security-critical apps (vaultwarden, pocketid)
- Custom regex manager detects images in Kustomize files

**Kargo**:
- Watches for new images/charts automatically
- App projects create PRs that update source values on `main`
- The global `homelab-project` renders manifests and opens a PR against `homelab`

## Working with Applications

### Adding a New Application

#### Option 1: Consolidated `homelab-chart` Application (Pattern A)

For most apps and media workloads.

1. Add a dependency to `charts/homelab/Chart.yaml`:
```yaml
dependencies:
  - name: homelab-chart
    version: ^0.1.0
    repository: oci://ghcr.io/kdwils/charts
    alias: <app>
```

2. Update `charts/homelab/Chart.lock` and cached deps:
```bash
cd charts/homelab && helm dependency update
```

3. Create values files:
```bash
mkdir -p apps/<app>/environments/homelab   # or media/<app>/environments/homelab
```
Write `homelab.yaml` with values under the alias key (`<app>:`).

4. Create ArgoCD Application (`apps/applications/<app>.yaml` or `media/applications/<app>.yaml`):
```yaml
source:
  path: apps/<app>/environments/homelab
  targetRevision: homelab
```

5. Add the application file to the relevant `applications/kustomization.yaml`.

6. Create Kargo project: `apps/kargo/resources/projects/<app>.yaml` (copy from an existing one, e.g. `bluesky.yaml` or `blog.yaml`).

7. Add the Kargo project to `apps/kargo/resources/projects/kustomization.yaml`.

8. Update `apps/kargo/resources/tasks/render-homelab.yaml` to render the new app:
```yaml
- uses: helm-template
  as: render-<app>
  config:
    path: ./source/charts/homelab
    valuesFiles:
      - ./source/apps/<app>/environments/homelab/homelab.yaml
    namespace: <namespace>
    releaseName: <app>
    outPath: ./target/apps/<app>/environments/homelab/manifest.yaml
```

9. Commit and push. The app project will auto-promote source changes; the global `homelab-project` will render manifests and open a PR against `homelab`.

#### Option 2: Third-Party Chart Wrapper (Pattern A2)

For infrastructure components with an upstream Helm chart.

1. Create `charts/<component>/Chart.yaml` with the upstream chart and `homelab-chart` aliased as `homelab`.
2. Download dependencies: `cd charts/<component> && helm dependency update`.
3. Create `<project>/<component>/environments/homelab/homelab.yaml` with values.
4. Create ArgoCD Application (`<project>/applications/<component>.yaml`) with `targetRevision: homelab`.
5. Create Kargo project: `apps/kargo/resources/projects/<component>.yaml`.
6. Add to `apps/kargo/resources/projects/kustomization.yaml`.
7. Update `apps/kargo/resources/tasks/render-homelab.yaml` to render the new component using its own chart path.

#### Option 3: Simple Kustomize Application (Pattern B)

1. Create directory with manifests:
```bash
mkdir apps/<app>   # or infra/, monitoring/, media/
# Add deployment.yaml, service.yaml, httproute.yaml, etc.
```

2. Create `kustomization.yaml`.

3. Create ArgoCD Application (`targetRevision: HEAD`) and add it to that project's `applications/kustomization.yaml`.

### Updating an Application

**Kargo-Managed Apps (Patterns A and A2)**:
- App projects update source values on `main` automatically
- Review and merge those PRs
- The global `homelab-project` will detect the change, render manifests, and open a PR against `homelab`
- Review/merge the `homelab` PR to trigger ArgoCD sync

**Simple Apps (Pattern B)**:
- Update image tags or manifests directly
- Commit and push to `main` - ArgoCD syncs automatically

### Debugging Application Issues

```bash
# Check ArgoCD sync status
kubectl get app <app> -n argocd -o yaml

# View application logs
kubectl logs -n <namespace> -l app=<app>

# Check Kargo freight status
kubectl get freight -n <namespace>
kubectl describe freight <freight-name> -n <namespace>

# View promotion status
kubectl describe stage <stage-name> -n <namespace>

# Check sealed secret decryption
kubectl get secret <secret-name> -n <namespace>
```

## Project Structure

```
/
  projects/                    # ArgoCD AppProjects and parent app
    parent-app.yaml            # Bootstrap application
    apps.yaml / infra.yaml / media.yaml / monitoring.yaml
  apps/                        # Personal projects + shared Kargo config
    applications/               # ArgoCD Application resources
    kargo/                      # Kargo config shared by ALL projects
      environments/homelab/     # Kargo installation values
      resources/
        projects/               # One file per Kargo project
        tasks/                  # Shared ClusterPromotionTasks
    <app>/                      # Per-app values (Pattern A) or Kustomize manifests (Pattern B)
      environments/
        homelab/
          homelab.yaml
  infra/                        # Critical infrastructure components
    applications/                # ArgoCD Application resources
    <component>/                 # Values for Pattern A2 components
  media/                        # Media management apps
    applications/
    <app>/
      environments/homelab/
        homelab.yaml
  monitoring/                   # Observability and security
    applications/
    <component>/
      environments/homelab/
        homelab.yaml
  charts/                       # Top-level Pattern A2 chart wrappers + consolidated homelab chart
    homelab/                    # Meta-chart that declares all Pattern A apps as aliases
    <component>/                # One per Pattern A2 component
  docs/diagrams/                # Generated network/platform architecture diagram
  kustomization.yaml            # Top-level orchestration
```

## Shared Helm Chart

Most applications use the `homelab-chart` (https://github.com/kdwils/helm-charts) which provides:
- Standardized Deployment template
- Service creation
- HTTPRoute (Gateway API) ingress
- PersistentVolumeClaim management
- SealedSecret creation
- SecurityPolicy (external auth) support
- VerticalPodAutoscaler support

Pattern A apps consume it through the consolidated `charts/homelab` meta-chart. Pattern A2 apps consume it directly as a chart dependency aliased `homelab`.

**Common Values Structure (Pattern A alias key)**:
```yaml
<app>:
  serviceAccount:
    create: true
  deployment:
    image:
      repository: <image>
      tag: <version>
    env: {}
    envFrom: []
    resources:
      limits: {}
      requests: {}
  service:
    create: true
    port: <port>
  httproute:
    create: true
    hostnames: []
  pvc:
    create: true
    pvcs: []
  sealedsecrets: []
  securityPolicy: {}
  verticalPodAutoscaler:
    enabled: false
```

## Coder Templates

Coder workspace templates and modules can be stored under `apps/coder/templates/` and consumed by the in-cluster Coder deployment. Agent-specific skill instructions for building registry-style templates and modules live outside this repo at `~/.agents/skills/coder-templates/SKILL.md` and `~/.agents/skills/coder-modules/SKILL.md`.

## Important Notes

- All ArgoCD applications use automated sync with prune and self-heal
- Kargo-managed apps sync from the shared `homelab` branch, which only Kargo pushes to
- Simple Kustomize apps sync directly from `main`
- Never commit unencrypted secrets - always use `kubeseal`
- Infrastructure apps must remain operational - they are critical dependencies
- When adding or removing a Kargo-managed app, update both the per-app Kargo project and the global `render-homelab` ClusterPromotionTask
- Review Kargo PRs carefully - they modify deployment manifests
- Do not commit `secrets/`, `secret.yaml`, `values.yaml`, or `.terraform/` directories
