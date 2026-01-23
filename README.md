# Homelab Deployment Branch

This branch contains only rendered Kubernetes manifests for deployment to the homelab cluster.

Structure:
- apps/{app}/manifest.yaml - Application manifests
- infra/{component}/manifest.yaml - Infrastructure component manifests  
- media/{app}/manifest.yaml - Media application manifests

ArgoCD syncs from this branch for all managed applications.
