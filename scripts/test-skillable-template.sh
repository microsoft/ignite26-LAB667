#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$#" -gt 1 ]]; then
  echo "Usage: bash scripts/test-skillable-template.sh [compiled-template.json]" >&2
  exit 2
fi

if [[ "$#" == 1 ]]; then
  template="$1"
else
  template="$(mktemp)"
  trap 'rm -f "$template"' EXIT
  az bicep build --file skillable/infra/skillable.bicep --outfile "$template"
fi

jq -e '
  [.resources[] | select(.type == "Microsoft.Resources/deployments")] as $deployments |
  (if ($deployments | length) != 1 then
    error("Expected one inline role-assignment deployment")
  else $deployments[0] end) as $deployment |
  $deployment.properties.template as $nested |
  if ($nested | type) != "object" then
    error("Nested template must be a JSON object, not a json() expression string")
  elif (
    $deployment.properties.mode != "Incremental" or
    $deployment.properties.expressionEvaluationOptions.scope != "inner" or
    ($nested.languageVersion // "1.0") != "1.0" or
    ($deployment.properties.parameters | keys) != ($nested.parameters | keys) or
    ($deployment.dependsOn | length) != 4
  ) then
    error("Nested deployment scope, parameter bindings, or dependencies changed")
  elif (
    ($nested.resources | length) != 5 or
    any($nested.resources[];
      .type != "Microsoft.Authorization/roleAssignments" or
      .properties.principalType != "ServicePrincipal" or
      (.name | startswith("[guid(") | not) or
      (.name | contains("deployment().properties.parameters.") | not) or
      (.properties.principalId | startswith("[deployment().properties.parameters.") | not)
    ) or
    any($nested | .. | strings; startswith("[["))
  ) then
    error("Expected five executable, principal-based role assignments")
  else
    "PASS: nested template is an object with inner evaluation, five role assignments, and unescaped ARM expressions."
  end
' "$template"
