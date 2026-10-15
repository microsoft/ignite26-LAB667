#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
export RESTORE_TEST_LOG="$log"
export AZURE_ENV_NAME="restore-test"
export RESTORE_TEST_MODE="existing"

az() {
  case "$1 ${2:-}" in
    "group exists")
      [[ "$*" == "group exists --name rg-restore-test --output tsv" ]]
      case "$RESTORE_TEST_MODE" in
        new) echo false ;;
        group-failure) echo "Simulated authorization failure" >&2; return 1 ;;
        unexpected-group) echo unknown ;;
        *) echo true ;;
      esac
      ;;
    "resource list")
      if [[ "$RESTORE_TEST_MODE" == "list-failure" ]]; then
        echo "Simulated listing failure" >&2
        return 1
      fi
      if [[ "$RESTORE_TEST_MODE" == "partial" ]]; then
        echo '[{"id":"mcp","tags":{"azd-service-name":"mcp"}}]'
      elif [[ "$RESTORE_TEST_MODE" == "malformed-list" ]]; then
        echo 'not JSON'
      elif [[ "$RESTORE_TEST_MODE" == "duplicate" ]]; then
        echo '[{"id":"mcp-1","tags":{"azd-service-name":"mcp"}},{"id":"mcp-2","tags":{"azd-service-name":"mcp"}}]'
      else
        echo '[{"id":"mcp","tags":{"azd-service-name":"mcp"}},{"id":"dashboard","tags":{"azd-service-name":"dashboard"}},{"id":"admin","tags":{"azd-service-name":"admin"}},{"id":"agent42","tags":{"azd-service-name":"agent42"}},{"id":"unrelated","tags":{"azd-service-name":"other"}}]'
      fi
      ;;
    "resource show")
      [[ "$3" == "--ids" ]]
      case "$RESTORE_TEST_MODE" in
        empty-image) echo "" ;;
        null-image) echo null ;;
        show-failure) echo "Simulated read failure" >&2; return 1 ;;
        *) echo "registry.example/$4:current" ;;
      esac
      ;;
    *) echo "Unexpected Azure CLI command: $*" >&2; return 1 ;;
  esac
}

azd() {
  [[ "$1 $2" == "env set" ]]
  if [[ "$RESTORE_TEST_MODE" == "save-failure" ]]; then
    echo "Simulated environment write failure" >&2
    return 1
  fi
  printf '%s=%s\n' "$3" "$4" >> "$RESTORE_TEST_LOG"
}
export -f az azd

bash scripts/restore-azd-images.sh
expected=$'SERVICE_MCP_IMAGE_NAME=registry.example/mcp:current\nSERVICE_DASHBOARD_IMAGE_NAME=registry.example/dashboard:current\nSERVICE_ADMIN_IMAGE_NAME=registry.example/admin:current\nSERVICE_AGENT42_IMAGE_NAME=registry.example/agent42:current'
[[ "$(cat "$log")" == "$expected" ]]

>"$log"
RESTORE_TEST_MODE=new bash scripts/restore-azd-images.sh
[[ ! -s "$log" ]]

>"$log"
RESTORE_TEST_MODE=partial bash scripts/restore-azd-images.sh
[[ "$(cat "$log")" == "SERVICE_MCP_IMAGE_NAME=registry.example/mcp:current" ]]

for mode in duplicate empty-image null-image group-failure unexpected-group list-failure malformed-list show-failure save-failure; do
  >"$log"
  if RESTORE_TEST_MODE="$mode" bash scripts/restore-azd-images.sh; then
    echo "Expected $mode to fail." >&2
    exit 1
  fi
  [[ ! -s "$log" ]]
done

if AZURE_ENV_NAME="" bash scripts/restore-azd-images.sh; then
  echo "Expected a missing environment name to fail." >&2
  exit 1
fi
echo "PASS: image restoration, new/partial deployments, unrelated apps, duplicates, and explicit error propagation."
