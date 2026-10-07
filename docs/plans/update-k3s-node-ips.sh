#!/usr/bin/env bash
# Update k3s control-plane nodes to use LAN InternalIPs.
# Run this from a machine that can SSH to the Tailscale IPs of m1/m2/m3.
set -euo pipefail

SSH_USER="${SSH_USER:-ubuntu}"

# m1 must be updated first because m2/m3 use m1's LAN IP as the server URL.
nodes=(
  "m1:100.106.227.127:192.168.0.90"
  "m2:100.106.10.114:192.168.0.76"
  "m3:100.121.32.66:192.168.0.158"
)

for entry in "${nodes[@]}"; do
  IFS=':' read -r name ts_ip lan_ip <<< "$entry"

  echo "==> Updating $name ($ts_ip -> $lan_ip)"

  if [[ "$name" == "m1" ]]; then
    ssh "${SSH_USER}@${ts_ip}" "sudo tee /etc/rancher/k3s/config.yaml" <<EOF
cluster-init: true
node-ip: ${lan_ip}
tls-san:
  - k8s.int.kyledev.co
  - 192.168.0.20
  - ${lan_ip}
EOF
  else
    ssh "${SSH_USER}@${ts_ip}" "sudo tee /etc/rancher/k3s/config.yaml" <<EOF
server: https://192.168.0.90:6443
node-ip: ${lan_ip}
tls-san:
  - k8s.int.kyledev.co
  - 192.168.0.20
  - ${lan_ip}
EOF
  fi

  ssh "${SSH_USER}@${ts_ip}" "sudo systemctl restart k3s"

  echo "==> Waiting for $name to be Ready..."
  kubectl wait --for=condition=Ready "node/${name}" --timeout=120s

  got_ip=$(kubectl get "node/${name}" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
  echo "==> $name InternalIP is now: $got_ip"

  if [[ "$got_ip" != "$lan_ip" ]]; then
    echo "ERROR: $name did not switch to $lan_ip" >&2
    exit 1
  fi
done

echo "==> All control-plane nodes updated. Verifying kubernetes Endpoints..."
kubectl get endpoints kubernetes
echo "==> Expected endpoints: 192.168.0.90:6443, 192.168.0.76:6443, 192.168.0.158:6443"
