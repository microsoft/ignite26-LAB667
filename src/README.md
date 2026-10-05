# Application code

| Folder | Purpose |
| --- | --- |
| [services/game-server/](services/game-server/) | Shared MCP game server, dashboard, and admin UI, with Azure Tables storage |
| [services/agent42/](services/agent42/) | Shared A2A transport specialist using weather, Azure Maps, and route blobs |
| [agents/player/](agents/player/) | Reference attendee agent with MCP, specialist calls, memory, and session logging |

The game server's three processes stay together because they share storage,
quest logic, and web assets. Each service keeps its own Dockerfiles and
dependencies; the player agent runs separately.

The runnable player and specialist smoke tests use their own
[requirements](agents/player/requirements.txt) and
[environment example](agents/player/.env.example). Keep that Python environment
separate from the game server's MCP 2 environment. The player reads **.env**
and saves **memory.json** beside **agent.py**, writes **logs/** beside **log.py**,
and closes its network clients through asynchronous context managers.

For offline player tests and checks that the lesson samples match the runnable
code, use the [player validation command](../docs/workshop-overview.md#validate-the-player-offline).
No live credentials or packages beyond the player requirements are needed.

See the [workshop overview](../docs/workshop-overview.md) for setup and run
commands, or start the [Player experience](../player/README.md).
Deployment material lives in [infra/](../infra/README.md).
