#!/usr/bin/env bash
set -euo pipefail
trap 'echo "Unable to restore deployed image references; refusing to provision with missing state." >&2' ERR

: "${AZURE_ENV_NAME:?Set AZURE_ENV_NAME to the initialized azd environment}"
resource_group="rg-${AZURE_ENV_NAME}"
exists="$(az group exists --name "$resource_group" --output tsv)"
case "$exists" in
  false)
    echo "Resource group $resource_group does not exist; this is a first deployment."
    exit 0
    ;;
  true) ;;
  *) echo "Unexpected resource group existence response: $exists" >&2; exit 1 ;;
esac

apps="$(az resource list --resource-group "$resource_group" \
  --resource-type Microsoft.App/containerApps --output json)"

for service in mcp dashboard admin agent42; do
  matches="$(jq -c --arg service "$service" \
    '[.[] | select(.tags["azd-service-name"] == $service)]' <<< "$apps")"
  count="$(jq 'length' <<< "$matches")"
  case "$count" in
    0)
      echo "No existing $service app; provisioning will create it."
      continue
      ;;
    1) ;;
    *) echo "Multiple apps are tagged for $service in $resource_group; refusing to choose one." >&2; exit 1 ;;
  esac

  app_id="$(jq -r '.[0].id' <<< "$matches")"
  image="$(az resource show --ids "$app_id" --api-version 2024-03-01 \
    --query 'properties.template.containers[0].image' --output tsv)"
  if [[ -z "$image" || "$image" == "null" || "$image" == "None" ]]; then
    echo "No image was returned for $service ($app_id); refusing to overwrite it." >&2
    exit 1
  fi

  azd env set "SERVICE_${service^^}_IMAGE_NAME" "$image"
  echo "Restored the deployed image reference for $service."
done
