# Application code

| Folder | Purpose |
| --- | --- |
| [services/game-server/](services/game-server/) | Shared MCP game server, dashboard, and admin UI, with Azure Tables storage |
| [services/agent42/](services/agent42/) | Shared A2A transport specialist using weather, Azure Maps, and route blobs |
| [agents/player/](agents/player/) | Reference attendee agent with authenticated MCP, specialist calls, and session logging |

The game server's three processes stay together because they share storage,
quest logic, and web assets. Each service keeps its own Dockerfiles and
dependencies; the player agent runs separately.

The runnable player and specialist smoke tests use their own
[requirements](agents/player/requirements.txt) and
[environment example](agents/player/.env.example). Separate Python environments
are recommended for service isolation, not conflicting MCP versions: Agent
Framework 1.23 and the game server both support MCP SDK 2.x. The player reads **.env**
beside **agent.py**, writes **logs/** beside **log.py**, and closes its network
clients through asynchronous context managers. **GAME_API_KEY** identifies the
player; game progress is stored on the server, not in a local memory file.

For offline player tests and checks that the lesson samples match the runnable
code, use the [player validation command](../docs/workshop-overview.md#validate-the-player-offline).
No live credentials or packages beyond the player requirements are needed.

See the [workshop overview](../docs/workshop-overview.md) for setup and run
commands, or start the [Player experience](../player/README.md).
Deployment material lives in [infra/](../infra/README.md).
