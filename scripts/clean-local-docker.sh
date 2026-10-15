#!/usr/bin/env bash
set -euo pipefail

mode="--dry-run"
mode_set=false
remove_all_deployment_images=false
for argument in "$@"; do
  case "$argument" in
    --dry-run|--apply)
      if [[ "$mode_set" == "true" ]]; then
        echo "Specify only one of --dry-run or --apply." >&2
        exit 2
      fi
      mode="$argument"
      mode_set=true
      ;;
    --all-deployment-images)
      remove_all_deployment_images=true
      ;;
    *)
      echo "Usage: bash scripts/clean-local-docker.sh [--dry-run|--apply] [--all-deployment-images]" >&2
      exit 2
      ;;
  esac
done
trap 'echo "Local Docker cleanup failed; review the error above before retrying." >&2' ERR
command -v docker >/dev/null
command -v jq >/dev/null

endpoint="${DOCKER_HOST:-}"
if [[ -z "$endpoint" ]]; then
  endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
fi
if [[ "$endpoint" != unix://* ]]; then
  echo "Refusing cleanup: the Docker endpoint is not a local Unix socket." >&2
  exit 1
fi
docker info >/dev/null
if ! docker buildx prune --help | grep -q -- '--max-used-space'; then
  echo "Cleanup requires Docker Buildx with --max-used-space support." >&2
  exit 1
fi

images="$(docker image ls --no-trunc --format '{{json .}}' | jq -s '.')"
candidates="$(jq -r --argjson remove_all "$remove_all_deployment_images" '
  def deployment_images:
    [.[] | select(
      (.Repository | test("^(?:[^/]+/)?lost-in-san-francisco/(admin|dashboard|mcp|agent42)-[a-zA-Z0-9_-]+$"))
      and (.Tag | test("^azd-deploy-[0-9]+$"))
    )]
    | group_by(.Repository)[]
    | sort_by(.Tag | sub("^azd-deploy-"; "") | tonumber)
    | if $remove_all then .[] else .[:-1][] end;
  def local_build_images:
    .[] | select(
      $remove_all
      and (.Repository | test("^lost-in-san-francisco-(admin|dashboard|mcp|agent42)$"))
      and .Tag == "latest"
    );
  [deployment_images, local_build_images][]
  | [.ID, (.Repository + ":" + .Tag)] | @tsv
' <<< "$images")"

containers="$(docker ps -aq)"
used_images=""
if [[ -n "$containers" ]]; then
  while IFS= read -r container; do
    used_images+="$(docker container inspect --format '{{.Image}}' "$container")"$'\n'
  done <<< "$containers"
fi

while IFS=$'\t' read -r image_id reference; do
  [[ -n "$reference" ]] || continue
  if grep -Fxq "$image_id" <<< "$used_images"; then
    echo "Keeping container-referenced image: $reference"
    continue
  fi
  if [[ "$mode" == "--apply" ]]; then
    echo "Removing local deployment artifact: $reference"
    docker image rm "$reference"
  else
    echo "Would remove local deployment artifact: $reference"
  fi
done <<< "$candidates"

if [[ "$mode" == "--apply" ]]; then
  # Build cache is shared by projects; active and image-shared layers may remain.
  docker buildx prune --builder default --force --max-used-space 1GB
  docker system df
else
  echo "Would trim unused default-builder cache toward 1 GB (shared across projects)."
  echo "No changes made. Pass --apply to clean. Containers and volumes are never removed."
fi
