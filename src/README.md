# Application code

| Folder | Purpose |
| --- | --- |
| [services/game-server/](services/game-server/) | Shared MCP game server, dashboard, and admin UI, with Azure Tables storage |
| [services/agent42/](services/agent42/) | Shared A2A transport specialist using weather, Azure Maps, and route blobs |
| [agents/player/](agents/player/) | Reference attendee agent with MCP, specialist calls, memory, and session logging |

The game server's three processes stay together because they share storage,
quest logic, and web assets. Each service keeps its own Dockerfiles and
dependencies; the player agent runs separately.

See the [workshop overview](../docs/workshop-overview.md) for setup and run
commands, or start the [attendee walkthrough](../instructions/README.md).
Deployment material lives in [infra/](../infra/README.md).
