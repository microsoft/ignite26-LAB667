# Contributing

This project welcomes contributions and suggestions. Most contributions require you to
agree to a Contributor License Agreement (CLA) declaring that you have the right to,
and actually do, grant us the rights to use your contribution. For details, visit
https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need
to provide a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the
instructions provided by the bot. You will only need to do this once across all repositories using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/)
or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Working on Lost in San Francisco

This lab teaches Microsoft Agent Framework, MCP, A2A, retrieval, vision, and
logging through a San Francisco quest game. Keep examples and city-guide
questions consistent with that setting.

### Project boundaries

| Area | Responsibility |
| --- | --- |
| [Game server](src/services/game-server/) | Shared MCP endpoint, quest state, scoring, dashboard, and admin UI; state lives in Azure Tables |
| [Agent42](src/services/agent42/) | Shared A2A transport specialist using weather, Azure Maps, and route blobs |
| [Player agent](src/agents/player/) | Reference attendee implementation: authenticates with a player API key, orchestrates the game, calls specialists, and writes session logs |
| [Player](player/README.md) | Guided and challenge chapters plus shared screenshots |
| [City guide](data/city-guide/) | San Francisco source material for retrieval |
| [Infrastructure](infra/README.md) | Lab provisioning and inactive legacy deployment workflows |

The game server does not require its own model deployment or Azure AI Search.
Those dependencies belong to the agents. Keep the server's MCP, dashboard, and
admin processes together in their existing folder because they share code and
assets.

### Local development

The [development container](.devcontainer/devcontainer.json) supplies Python
3.12 (matching the service images), Azure CLI, azd, Bicep, and Docker-in-Docker
with Compose. Create a Codespace, or rebuild your existing Codespace to apply
it. For local VS Code, use **Dev Containers: Reopen in Container**.

After the container finishes setup, verify Docker is running with `docker info`.
The creation log checks `python`, `az`, `az bicep`, `azd`, and Docker/Compose
versions. Azure sign-in is manual and separate for `az` and `azd`; in Codespaces,
use `az login --use-device-code` and `azd auth login --use-device-code` as needed.
No Azure credentials are baked into the image or mounted from the host.

Ports 8000 (MCP), 8090 (dashboard), 8080 (admin), and 8042 (Agent42) are forwarded
when you run the services. Keep their Codespaces visibility **Private**.
Port forwarding does not start services or provide the Azure dependencies.
This is a Linux development environment, not the prepared Windows Skillable VM
described in the attendee walkthrough.

Follow the [workshop overview](docs/workshop-overview.md) for prerequisites,
virtual environments, dependencies, and environment-file setup. Start each
process from its own application directory:

| Working directory | Command | Default port |
| --- | --- | --- |
| `src/services/game-server` | `python server.py` | 8000 |
| `src/services/game-server` | `python dashboard.py` | 8090 |
| `src/services/game-server` | `python admin.py` | 8080 |
| `src/services/agent42` | `python server.py` | 8042 |
| `src/agents/player` | `python agent.py` | Interactive terminal |

All three game-server processes use the same Azure Tables connection. For
local storage, the server supports Azurite with Table Storage enabled.
Keep credentials in local environment files or deployment secrets, never in
source control. Do not commit player API keys or generated session logs.

### Keep code and lessons aligned

- When changing the player agent's tools, prompts, imports, or configuration,
  update the corresponding attendee snippets and checkpoints.
- When changing quest questions or accepted answers, check them against the
  [city guide](data/city-guide/) and keep the San Francisco endpoint consistent.
- Use sentence case for headings and preserve intentional Skillable syntax.
  See the [authoring conventions](docs/authoring/common-knowledge.md) and
  [Skillable reference](skillable/docs/skillable.md).
- Per-game content is served from the Guided and Challenge sources. Redeploy
  the admin and dashboard after lesson or screenshot changes. Regenerate the
  legacy exports with `python scripts/sync-to-skillable.py` only when maintaining
  that legacy delivery path, not for ordinary per-game content changes.
- Check affected relative links and exercise the changed behavior in a
  development environment. Use the [load-test utility](scripts/README.md) only
  against an instance intended for load testing, not a live attendee session.

### Deployment and publication

Use [azd deployment instructions](infra/README.md) for shared-service
provisioning and deployment. Keep service names in [azure.yaml](azure.yaml)
aligned with the `azd-service-name` resource tags and each Dockerfile's port.
Validate infrastructure changes with `az bicep build --file infra/main.bicep`
(or the standalone Bicep CLI); do not provision billable resources just to
check syntax.

The [legacy workflows](infra/legacy-workflows/) are intentionally inactive.
Their resource names, secrets, and publishing destinations still refer to the
old workshop. Review those settings before enabling them. The
[Skillable template](skillable/infra/skillable.bicep) provisions lab resources,
not the shared game-server Container Apps. The admin UI uses table-backed
username/password authentication and requires changing the initial `admin` /
`admin` password before game management. MCP requests require a player bearer
API key; the public Player page issues keys on registration. The dashboard and
Agent42 remain publicly accessible. Restrict admin access to workshop operators
before broader use.

Before publishing, verify the session description, exactly three learning
outcomes, technologies, content owners, and guided/self-paced setup in the
[README](README.md). Confirm delivery links and hosting destinations with the
session owners, check relative links and required assets, and validate the
attendee path against the intended environment. Do not invent missing metadata
or treat removal of the template helpers as proof that the lab is ready.
