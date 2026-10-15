#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
export CLEANUP_TEST_LOG="$log"

docker() {
  case "$1 ${2:-}" in
    "context inspect") echo "${CLEANUP_TEST_ENDPOINT:-unix:///var/run/docker.sock}" ;;
    "info ") ;;
    "image ls")
      cat <<'JSON'
{"Repository":"lost-in-san-francisco/admin-dev","Tag":"azd-deploy-9","ID":"sha256:old"}
{"Repository":"lost-in-san-francisco/admin-dev","Tag":"azd-deploy-10","ID":"sha256:new"}
{"Repository":"registry.example/lost-in-san-francisco/admin-dev","Tag":"azd-deploy-9","ID":"sha256:old"}
{"Repository":"registry.example/lost-in-san-francisco/admin-dev","Tag":"azd-deploy-10","ID":"sha256:new"}
{"Repository":"lost-in-san-francisco/mcp-dev","Tag":"azd-deploy-1","ID":"sha256:used"}
{"Repository":"lost-in-san-francisco/mcp-dev","Tag":"azd-deploy-2","ID":"sha256:new-mcp"}
{"Repository":"lost-in-san-francisco/admin-prod","Tag":"azd-deploy-1","ID":"sha256:prod"}
{"Repository":"another-project/admin-dev","Tag":"azd-deploy-1","ID":"sha256:other"}
{"Repository":"another-project/admin-dev","Tag":"azd-deploy-2","ID":"sha256:other-new"}
{"Repository":"lost-in-san-francisco/admin-dev","Tag":"latest","ID":"sha256:latest"}
{"Repository":"lost-in-san-francisco-admin","Tag":"latest","ID":"sha256:local-build"}
JSON
      ;;
    "ps -aq") echo "stopped-container" ;;
    "container inspect") echo "sha256:used" ;;
    "image rm") printf '%s\n' "$3" >> "$CLEANUP_TEST_LOG" ;;
    "buildx prune")
      if [[ "$3" == "--help" ]]; then
        echo "--max-used-space"
      else
        [[ "$*" == "buildx prune --builder default --force --max-used-space 1GB" ]]
        echo "cache" >> "$CLEANUP_TEST_LOG"
      fi
      ;;
    "system df") ;;
    *) echo "Unexpected Docker command: $*" >&2; return 1 ;;
  esac
}
export -f docker
unset DOCKER_HOST
preview="$(bash scripts/clean-local-docker.sh)"
[[ ! -s "$log" ]]
[[ "$preview" == *"Keeping container-referenced image:"* ]]
[[ "$preview" == *"Would remove local deployment artifact: lost-in-san-francisco/admin-dev:azd-deploy-9"* ]]
bash scripts/clean-local-docker.sh --apply
expected=$'lost-in-san-francisco/admin-dev:azd-deploy-9\nregistry.example/lost-in-san-francisco/admin-dev:azd-deploy-9\ncache'
[[ "$(cat "$log")" == "$expected" ]]
>"$log"
bash scripts/clean-local-docker.sh --all-deployment-images --apply
expected=$'lost-in-san-francisco/admin-dev:azd-deploy-9\nlost-in-san-francisco/admin-dev:azd-deploy-10\nlost-in-san-francisco/admin-prod:azd-deploy-1\nlost-in-san-francisco/mcp-dev:azd-deploy-2\nregistry.example/lost-in-san-francisco/admin-dev:azd-deploy-9\nregistry.example/lost-in-san-francisco/admin-dev:azd-deploy-10\nlost-in-san-francisco-admin:latest\ncache'
[[ "$(cat "$log")" == "$expected" ]]
if CLEANUP_TEST_ENDPOINT=ssh://remote bash scripts/clean-local-docker.sh --apply; then
  echo "Remote Docker endpoint was not rejected." >&2
  exit 1
fi
[[ "$(cat "$log")" == "$expected" ]]
if bash scripts/clean-local-docker.sh --invalid; then
  echo "Invalid arguments were not rejected." >&2
  exit 1
fi
echo "PASS: dry run, numeric retention, registry tags, environments, container protection, cache target and remote guard."
