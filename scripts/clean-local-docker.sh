#!/usr/bin/env bash
set -euo pipefail

mode="${1:---dry-run}"
if [[ $# -gt 1 || ( "$mode" != "--dry-run" && "$mode" != "--apply" ) ]]; then
  echo "Usage: bash scripts/clean-local-docker.sh [--dry-run|--apply]" >&2
  exit 2
fi
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
candidates="$(jq -r '
  [.[] | select(
    (.Repository | test("^(?:[^/]+/)?lost-in-san-francisco/(admin|dashboard|mcp|agent42)-[a-zA-Z0-9_-]+$"))
    and (.Tag | test("^azd-deploy-[0-9]+$"))
  )]
  | group_by(.Repository)[]
  | sort_by(.Tag | sub("^azd-deploy-"; "") | tonumber)
  | .[:-1][]
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
    echo "Removing old local deployment tag: $reference"
    docker image rm "$reference"
  else
    echo "Would remove old local deployment tag: $reference"
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
