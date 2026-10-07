# Homelab network diagram

One diagram documents how networking and the key platform pieces fit
together. The source of truth is
[`network-architecture.yaml`](./network-architecture.yaml), not the HTML.

`homelab-network.html` / `homelab-network.svg` shows, top to bottom:

- How `*.kyledev.co`, `*.int.kyledev.co`, and `*.ts.kyledev.co` resolve and
  route from the public internet / Tailscale / LAN into the cluster
  (Cloudflare Tunnel, the Plex VPS+Caddy exception terminating at an
  in-cluster Tailscale Proxy pod — not the gateway directly — Blocky primary
  DNS, Pi-hole secondary DNS, and kube-vip k3s API LB) down into **Envoy
  Gateway**, which now terminates TLS itself rather than being described via
  a separate MetalLB node.
- What sits directly below the gateway inside the cluster: cert-manager
  (wildcard TLS via Cloudflare DNS-01) and the HTTPRoutes/apps that attach
  to it (in the slot CoreDNS used to occupy — CoreDNS has been removed
  entirely, it added nothing the gateway/Blocky records didn't already
  cover). Below that, Envoy Gateway calls out to
  `envoy-proxy-crowdsec-bouncer` for every request (ext-authz) and gets an
  allow/deny back; CrowdSec feeds ban decisions into that bouncer.
- Kargo (in the cluster) → GitHub repo (`github.com/kdwils/homelab`) →
  ArgoCD (back in the cluster). The repo is drawn as its own row below the
  Home LAN block in column 1 — not inside any zone — since it's genuinely
  external to the cluster, not just to the internet/tailnet zone. Kargo
  renders manifests and pushes them to the repo; ArgoCD syncs from that
  repo — the repo itself is the GitOps handoff, not a direct
  Kargo→ArgoCD edge. None of this is wired to the gateway — GitOps manages
  overall cluster state, it isn't a dependency of (or a traffic path
  through) the ingress gateway specifically.

This intentionally exceeds the `diagram-design` skill's default
per-diagram budget (9 nodes / 12 arrows) as a single "zoned overview" —
it used to be two separate diagrams, merged into one on request. The hard
rules that never relax (max 3 zones, rounded orthogonal connectors,
masked labels with a visible gap, no shared attach points, no label
clipped by a later node) are still respected and validated — see below.

## Regenerating

```bash
pip3 install pyyaml   # once
python3 docs/diagrams/generate_diagrams.py
```

This reads `network-architecture.yaml` and rewrites `homelab-network.html`
in this directory.

The root `README.md` embeds the diagram as `.svg` (GitHub won't render
inline `<svg>`/`<style>` in markdown, but it will render an `<img>` pointing
at a `.svg` file in the repo). After regenerating the HTML, re-export the
SVG so the README stays in sync:

```bash
python3 docs/diagrams/export_svgs.py
```

This rewrites `homelab-network.svg` from `homelab-network.html` (extracts
the `<svg>` node, normalizes `rgba()`/`transparent` fills to hex+opacity,
inlines the Google Fonts `@import`).

## Editing / extending

Everything — nodes, edges, zones, labels, colors, legend — lives in the
YAML file. To add a component:

1. Add a `node` entry (`zone`, `x/y/w/h` on a 4px grid, `name`,
   `sublabel`, `tag`, and a `type` from
   `focal | backend | store | external | input | optional | security`).
2. Add an `edge` entry with `from`/`to` node ids and either:
   - `points: [[x,y], ...]` — a list of axis-aligned waypoints; the
     generator rounds every interior corner automatically, or
   - `path: "..."` — a raw SVG path `d` string, only needed if the new
     connector must cross another one (bridge/hop arc pattern).
3. Pick `style: muted | accent | link` for the arrow color, and set
   `dashed: true` for config/provisioning/security relationships rather
   than live traffic.
4. Keep `label`/`label_pos` short (≤14 chars) and only add a label if the
   relationship isn't already obvious — several short connectors into the
   gateway are left unlabeled on purpose (e.g. `tsproxy -> gateway` has a
   label because there's room; `httproutes -> gateway` and
   `crowdsec -> bouncer` don't, because there wasn't without clipping a
   neighboring node/label).
5. **Zones are capped at 3** for this diagram type — don't add a 4th; fold
   a new grouping into an existing zone instead.
6. Regenerate, re-export the SVG, then validate against the
   `diagram-design` skill's checkers (paths will vary by machine):

   ```bash
   python3 <diagram-design-skill>/scripts/self_check.py docs/diagrams/*.html
   python3 <diagram-design-repo>/scripts/verify-geometry.py docs/diagrams/*.html
   ```

   `self_check.py` verifies the accessible-SVG contract (title/desc,
   `role="img"`) and that the file stays single-file/offline-safe apart
   from the approved Google Fonts stylesheet link. `verify-geometry.py`
   catches arrow labels that end up clipped by a node painted after them.

## Source facts encoded in the diagram

Captured here so future edits don't have to re-derive them by reading the
manifests again:

- **DNS**: Blocky (`192.168.0.21`) is the primary LAN DNS server and is also
  exposed on the tailnet via a Tailscale LoadBalancer. The router/DHCP server
  forwards DNS to Blocky first and to Pi-hole as secondary/backup. Blocky
  answers `*.int.kyledev.co` → the gateway (LAN path) and
  `k8s.int.kyledev.co` → the kube-vip virtual IP.
- **k3s API LB**: kube-vip advertises LAN VIP `192.168.0.20` for
  `k8s.int.kyledev.co` and load-balances `:6443` across the three
  control-plane nodes `m1` (`192.168.0.90`), `m2` (`192.168.0.76`), and
  `m3` (`192.168.0.158`).
- **Public ingress**: Cloudflare Tunnel (`cloudflared`) fronts every
  `*.kyledev.co` hostname except Plex, forwarding to
  `homelab-gateway.envoy-gateway-system.svc.cluster.local:443`.
- **Plex exception**: a VPS running Caddy reverse-proxies
  `plex.kyledev.co` over the tailnet to an in-cluster Tailscale Proxy pod,
  which is the actual tailnet ingress point — traffic doesn't reach the
  gateway directly from the VPS.
- **Gateway exposure / TLS termination**: the gateway terminates TLS
  itself (`:443`/`:80`); how its Service is exposed at the network layer
  (LoadBalancer implementation, IP allocation) is deliberately not part of
  this diagram's story.
- **TLS certs**: `cert-manager`'s `letsencrypt-prod` ClusterIssuer uses a
  Cloudflare API token (DNS-01) to issue one wildcard cert covering
  `*.kyledev.co`, `*.int.kyledev.co`, and `*.ts.kyledev.co`.
- **Security**: CrowdSec feeds ban decisions to
  `envoy-proxy-crowdsec-bouncer`, which Envoy Gateway calls as a gRPC
  `SecurityPolicy` ext-authz backend for every request, and which returns
  an allow/deny back to the gateway.
- **GitOps**: Kargo promotes freight, renders manifests, and pushes them
  to `github.com/kdwils/homelab` — a git repo external to the cluster.
  ArgoCD auto-syncs from that same repo. It's drawn with **no arrow into
  the gateway** — ArgoCD manages overall cluster state, it isn't a runtime
  dependency of (or traffic path through) the gateway specifically.

Not included by design: Sealed Secrets (not directly relevant to the
networking story), media/app workloads, storage (Longhorn/NFS/CNPG), and
monitoring — none of these change the networking story and would blow the
complexity budget further.
