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
