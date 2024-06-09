#!/bin/bash

# Namespaces from which to remove finalizers, delete pods, and then delete the namespace
namespaces=("argocd" "hoarder" "longhorn-system" "mealie" "rss" "media" "ingress-nginx")

# Function to remove finalizers from all resources, delete pods, and delete the namespace
process_namespace() {
  namespace=$1
  echo "Processing namespace: $namespace"

  # Remove finalizers from all resources
  for resource in $(kubectl api-resources --verbs=list --namespaced -o name | grep -v "events")
  do
    for name in $(kubectl -n "$namespace" get "$resource" -o name)
    do
      kubectl patch "$name" -n "$namespace" -p '{"metadata":{"finalizers":[]}}' --type=merge
    done
  done

  # Force delete all pods
  echo "Force deleting all pods in namespace: $namespace"
  kubectl delete pods --all --namespace="$namespace" --force --grace-period=0

  # Delete the namespace
  echo "Deleting namespace: $namespace"
}

# Loop through each namespace and process it
for namespace in "${namespaces[@]}"
do
  process_namespace "$namespace"
done

echo "Namespace processing completed."
