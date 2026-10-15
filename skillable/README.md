# Skillable

Skillable-specific documentation and infrastructure are kept here, separate
from the shared-service deployment managed by Azure Developer CLI.

| Folder | Contents |
| --- | --- |
| [docs/](docs/skillable.md) | Skillable formatting, export, and publishing reference |
| [infra/](infra/skillable.bicep) | Skillable lab resources for Microsoft Foundry, model deployments, Azure AI Search, storage, role assignments, and city-guide upload |

The infrastructure template still references the original hosted city-guide
ZIP. It is independent of `azd up` and does not deploy the shared Container
Apps.

## Redeploying existing lab resources

The [infrastructure template](infra/skillable.bicep) is a single, self-contained
Bicep file. An inline nested ARM deployment waits for the managed identities to
exist so their principal IDs can be used in role assignment names. No separate
module file is required.

The nested `template` must be a Bicep object, not `json('...')`: Azure
deserializes it as an object before evaluating expressions. Its native Bicep
expressions read the nested deployment's parameter values through
[`deployment()`](https://learn.microsoft.com/azure/azure-resource-manager/templates/template-functions-deployment#deployment),
so they compile to executable ARM expressions instead of escaped strings.

Before uploading an updated template, run:

```bash
bash scripts/test-skillable-template.sh
```

This compiles the single file with Azure CLI/Bicep and uses jq to check the
nested template shape, scope, parameter bindings, and role-assignment expressions.
It does not provision resources or replace validation in the target subscription.

Role assignment names are derived from the assignment scope, managed identity
principal ID, and role definition ID. Repeated deployments keep the same names;
recreating a managed identity produces new names automatically. The former
`roleAssignmentSuffix` parameter is no longer needed; remove it from any external
deployment parameter files or commands.

Before the first deployment of this naming scheme to an existing lab, identify
the five role assignments created by the previous template. If equivalent
assignments still exist for the same principal, role, and scope under the old
names, remove only those confirmed legacy assignments by their assignment IDs,
then redeploy promptly. This temporarily interrupts the affected permissions.
Otherwise Azure can reject the new names with `RoleAssignmentExists`.
Incremental deployments do not remove the old assignments automatically.
New lab resource groups do not need this migration.
