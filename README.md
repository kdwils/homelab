# Homelab

[![argo badge](https://argocd.kyledev.co/api/badge?name=apps&revision=true)](https://argocd.kyledev.co/api/badge?project=media&revision=true)

# About
This repo contains my declarative setup for my home k3s cluster. Applications are synced to the cluster via ArogCD, and the applications live under the `/apps` folder. I also manage ArgoCD itself via this repository after an initial manual deployment.


# Declarative Secrets
Secrets are managed via the [SealedSecrets](https://github.com/bitnami-labs/sealed-secrets) operator. Secrets are encrypted prior to checking them into git, and then are decrypted by the operator once deployed to the cluster.
