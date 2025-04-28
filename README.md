# Homelab

| Project  | Badge  | Description |
|----------|--------|--------|
| Apps | ![apps](https://argocd.kyledev.co/api/badge?project=apps&revision=true) | personal projects, open source apps, etc.|
| Infra | ![infra](https://argocd.kyledev.co/api/badge?project=infra&revision=true) | software critical to the cluster being operational |
| Media | ![media](https://argocd.kyledev.co/api/badge?project=media&revision=true) | *arr stack for media managemet and viewing |
| Monitoring | ![monitoring](https://argocd.kyledev.co/api/badge?project=monitoring&revision=true) | cluster monitoring |

# About
This repo contains my declarative setup for my home k3s cluster. Applications are synced to the cluster via ArogCD, and the applications live under the `/apps` folder. I also manage ArgoCD itself via this repository after an initial manual deployment.


# Declarative Secrets
Secrets are managed via the [SealedSecrets](https://github.com/bitnami-labs/sealed-secrets) operator. Secrets are encrypted prior to checking them into git, and then are decrypted by the operator once deployed to the cluster.
