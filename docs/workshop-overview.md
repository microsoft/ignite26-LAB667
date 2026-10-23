# Lost in the City workshop

A hands-on workshop for building AI agents with the Microsoft Agent Framework,
Model Context Protocol (MCP), Agent-to-Agent (A2A), memory, logging, and
retrieval. Participants build an agent that plays **Lost in the City**, a
narrative quest game where the player has to cross a city, solve guidebook
clues, and reach the final destination before time runs out.

The default seed game is **Lost in San Francisco**, but the game server supports
multiple city games. Each game has its own MCP endpoint, dashboard, Player URL,
player mode, optional play window, optional Competitive Mode, quest list, and
players.

## What's in this repo

| Path | Purpose |
| --- | --- |
| [src/services/game-server/](../src/services/game-server/) | Multi-game MCP server, read-only room dashboard, and FastAPI admin UI. State is stored in Azure Tables. |
| [src/services/agent42/](../src/services/agent42/) | Standalone A2A transport expert. It compares car, walking, and bike routes using weather, traffic, Azure Maps, and rendered route maps. |
| [src/agents/player/](../src/agents/player/) | Complete reference agent that connects to the game MCP server, asks Agent42 over A2A, queries the city guide, remembers `player_id`, and writes session logs. |
| [data/city-guide/](../data/city-guide/) | San Francisco guide chapters used as source material for the retrieval challenge. |
| [player/](../player/README.md) | Guided and Challenge Mode chapters used by the public Player experience. |
| [docs/](README.md) | Supporting gameplay, setup, and authoring documentation. |
| [infra/](../infra/README.md) | Shared-service infrastructure and inactive legacy deployment workflows. |
| [skillable/](../skillable/README.md) | Skillable-specific documentation and infrastructure. |
| [scripts/](../scripts/README.md) | Workshop export and local load-testing utilities. |

## How the game works

1. The player agent connects to the MCP endpoint for a game, such as
    `http://localhost:8000/san-francisco/mcp`.
2. The agent starts or resumes a session, registers the player if needed, and
    receives a random quest.
3. Quests are made of missions:
    - Move missions ask the player to choose `car`, `walking`, or `bike`. The
       agent can call Agent42 for weather-aware route advice.
    - Question missions ask the player to recover a secret answer from the city
      guide knowledge base.
4. The server tracks progress, failed answer attempts, and elapsed time. Games
    with Competitive Mode enabled also calculate a final score.
5. The dashboard and admin UI show player status and, for competitive games,
    leaderboards.

## Prerequisites

- Python 3.11+
- Azure OpenAI or Microsoft Foundry model access for the agents
- Azure AI Search knowledge base for the city-guide challenge
- Azure Maps key for Agent42 and the dashboard map
- Azure Storage account for Azure Tables game state
- Optional for local game-server development: Azurite with table support

## Quick start

Start each service's setup from the repository root in a separate terminal.

### 1. Run the game server

The game server needs Azure Tables. For local development, you can use Azurite
and set `AZURE_TABLES_CONNECTION_STRING=UseDevelopmentStorage=true`.

```bash
cd src/services/game-server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set AZURE_TABLES_CONNECTION_STRING
python server.py
```

The default game is mounted at:

```text
http://localhost:8000/san-francisco/mcp
```

Run the live room dashboard in a second terminal:

```bash
cd src/services/game-server
source .venv/bin/activate
python dashboard.py
```

Open the default dashboard at:

```text
http://localhost:8090/san-francisco/dashboard
```

Run the admin UI in a third terminal:

```bash
cd src/services/game-server
source .venv/bin/activate
python admin.py
```

For local HTTP, set `ADMIN_COOKIE_SECURE=false` as in the environment example.
Open the admin UI at `http://localhost:8080`, sign in with `admin` / `admin`,
and keep those development credentials when `ADMIN_DEVELOPMENT_MODE=true`.
Never enable development mode in a deployed environment. You can then create
games, edit quests, import [quests.json](../src/services/game-server/quests.json),
reset players, and watch leaderboards. See the
[game-server README](../src/services/game-server/README.md) for the full tool
reference, quest schema, storage model, and deployment notes.

### Per-game Player mode and schedule

Open **Manage > Schedule & player** to choose Guided or Challenge Mode, enable
Competitive Mode, and set a start date/time, end date/time, and IANA timezone.
Competitive Mode is off by default; enable it to calculate points and show
rankings and leaderboards. You can also set these options when creating a game.
Both schedule endpoints are optional together; existing games remain unrestricted
until a schedule is set. Settings take effect immediately, separately from story
publication.

Share `http://localhost:8090/<slug>/player` with players (use the dashboard host
in Azure). Guided Mode renders the nine step-by-step chapters; Challenge Mode
renders four outcome-focused game stages: setup and MCP, Agent42 travel, a
Foundry IQ grounded question, and final arrival. Both use the game's name,
endpoint, dates, times, and timezone. **Preview player** serves the same content
through the admin host for local development. No player login is required and no
credentials are published.

The MCP server enforces `start <= current UTC time < end`: starting/resuming
sessions, registration, quest starts, and answer submissions are blocked outside
the window, including for existing players. The Player page does not send lesson
content or navigation outside the window. It shows **Player window is closed** and,
during the final 24 hours before opening, a live **Enter the city in** countdown.
Status and abandoning a quest remain available. Leaderboards remain available for
games with Competitive Mode enabled. All checks use the latest saved schedule.

### 2. Run Agent42

Agent42 is a separate A2A service. Run it locally when you want to develop or
test transport advice; otherwise point the sample agent at a deployed Agent42
URL.

```bash
cd src/services/agent42
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and set AZURE_MAPS_KEY, model credentials, and AGENT42_BLOB_CONNECTION_STRING
python server.py
```

Agent42 listens on `http://localhost:8042` and publishes its AgentCard at
`http://localhost:8042/.well-known/agent-card.json`. See
[Agent42 README](../src/services/agent42/README.md) for environment variables, output format,
and deployment notes.

### 3. Run the sample agent

The sample agent uses Azure OpenAI via the Microsoft Agent Framework. Start from
the example environment file:

```bash
cd src/agents/player
cp .env.example .env
```

Set at least these values in `src/agents/player/.env`:

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<your-azure-openai-key>
AZURE_OPENAI_DEPLOYMENT_NAME=<your-main-agent-deployment>
AZURE_SEARCH_ENDPOINT=https://<your-search-service>.search.windows.net
AZURE_SEARCH_KNOWLEDGE_BASE_NAME=san-francisco-cityguide
AZURE_SEARCH_KEY=<your-azure-ai-search-key>
GAME_MCP_URL=http://localhost:8000/san-francisco/mcp
AGENT42_URL=http://localhost:8042/
```

To use a different model deployment for the city-guide specialist, also set:

```env
CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME=<your-city-guide-deployment>
```

The override is optional: an unset, empty, or whitespace-only value falls back
to `AZURE_OPENAI_DEPLOYMENT_NAME`. The Search settings are required. The city
guide reaches the Foundry IQ knowledge base through its MCP endpoint, which
accepts a Search admin key (query keys are rejected).

Then run the agent:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade --upgrade-strategy eager -r requirements.txt
python agent.py
```

For an existing player environment, activate it and rerun the install command
to select the latest compatible dependencies. Keep it separate from the game
server's Python environment: the player can call the MCP SDK 2 server while
using Agent Framework's supported MCP client SDK.

The player requirements currently start at `agent-framework>=1.19.0` and
`agent-framework-a2a>=1.0.0b260918`. The explicit A2A prerelease minimum is
intentional; do not add a blanket `--pre` or force MCP 2 into this environment.
The verified combination uses Agent Framework 1.19.0, its A2A integration
1.0.0b260918, A2A SDK 1.2.1, and MCP client 1.30.0 with the separately hosted
MCP 2.2 server. Use `python -m pip check` after an upgrade.

The player now uses the A2A 1.x integration. Upgrade the deployed Agent42 service
before running the updated player against it; see the
[Agent42 upgrade notes](../src/services/agent42/README.md#install-local).

The agent will start or resume a game, save the assigned `player_id` in
`src/agents/player/memory.json` (created at runtime), call Agent42 through the
`ask_agent42` tool, call the city-guide specialist for retrieval, and write a
per-session log under `src/agents/player/logs/`.
The `.env` and memory paths are relative to the Python files, not the terminal's
working directory. Logs and memory use UTF-8. Invalid memory JSON or an invalid
saved player ID produces an explicit error; correct the file before retrying
rather than accidentally starting a different player.

Type `exit` or `quit` to leave the chat loop. The main model client, MCP
connection, A2A agent, and city-guide model/search resources are managed with
`async with` so they also close on errors and cancellation. Tool builders accept
the existing specialist agents and do not create hidden connections.

To test a specialist separately with the same environment, run one of:

```bash
python agent_agent42.py
python agent_city_guide.py
```

These smoke tests make live service/model requests. The complete copied samples
in [Steps 5–8](../player/guided/05_add_session_logging.md) match the logging
helper, specialist helpers, and final player; earlier lessons intentionally
introduce only a subset of the final capabilities.

### Validate the player offline

From the repository root, activate a Python environment with the
[player requirements](../src/agents/player/requirements.txt) installed, then run:

```bash
PYTHON_DOTENV_DISABLED=1 python -m unittest discover -s src/agents/player/tests -p 'test_*.py' -v
```

If that environment is the repository-root **.venv**, you can instead use
`.venv/bin/python` without activating it. On PowerShell, set
`$env:PYTHON_DOTENV_DISABLED = "1"` first, then run the `python -m unittest`
command without the Bash environment-variable prefix.

These tests need no packages beyond the player requirements and make no
Azure, model, or game-service calls. They cover player behavior and resource
cleanup, compile and import the full lesson samples without credentials, and
compare the Step 5 logging helper, Step 6–7 specialists, and Step 8 player
against their canonical source using Python's abstract syntax tree.

## Workshop flow

The attendee workshop is split into numbered steps:

1. [Step into your workspace](../player/guided/00_step_into_your_workspace.md)
2. [Get Azure OpenAI details from Microsoft Foundry](../player/guided/01_get_azure_openai_details_from_foundry.md)
3. [Create a hello world agent](../player/guided/02_create_hello_world_agent.md)
4. [Connect to the gaming MCP server](../player/guided/03_connect_to_the_gaming_mcp_server.md)
5. [Add memory for the player ID](../player/guided/04_add_memory_for_the_player_id.md)
6. [Add session logging](../player/guided/05_add_session_logging.md)
7. [Test Agent42 transport specialist](../player/guided/06_test_agent42_transport_specialist.md)
8. [City Guide part 1: create the knowledge base](../player/guided/07_create_the_city_guide_knowledge_base.md)
9. [City Guide part 2: connect the knowledge base to your agent](../player/guided/07_test_the_city_guide_agent.md)
10. [Bring the specialist agents into the main agent](../player/guided/08_bring_specialists_into_main_agent.md)
11. [Lab recap](../player/guided/09_lab_recap.md)

## Deployment

Use [Azure Developer CLI](../infra/README.md) from the repository root to
provision and deploy the four shared services with `azd up`. This includes
Agent42's dedicated model, storage, Maps, and service configuration, but not
attendee model/search resources. The admin endpoint requires a login and a
mandatory change of its initial `admin` / `admin` password; other service
endpoints remain unauthenticated. Review the access limitations before deployment.

The repository preserves inactive legacy GitHub Actions workflows for Agent42
and the game-server container apps:

- [Agent42 workflow](../infra/legacy-workflows/agent42.yml)
- [Game-server workflow](../infra/legacy-workflows/game-server.yml)

They are outside `.github/workflows/` and do not run automatically. See
[infrastructure notes](../infra/README.md) before adapting them for this session.

The game-server deployment builds three separate containers: MCP server,
dashboard, and admin UI. Configure the deployed apps with the environment
variables documented in the [environment example](../src/services/game-server/.env.example)
and [game-server README](../src/services/game-server/README.md).

## Repository notes

- Game state lives in Azure Tables: `games`, `quests`, and `players`.
- On startup, the game server adds any missing built-in games: Microsoft
  Ignite — Lost in San Francisco from
  [quests.json](../src/services/game-server/quests.json), and Open Hack
  Philadelphia — Lost in Philadelphia from
  [quests-philadelphia.json](../src/services/game-server/quests-philadelphia.json).
  Existing games are not overwritten.
- Quest content can be edited through the admin UI or imported from
   [quests.json](../src/services/game-server/quests.json) into a draft. The
   **Edit game** page shows the story timeline and location map. Publishing
   creates a version for new players; existing players keep their assigned
   version. The **Dashboard** page shows live progress and recorded game
   positions, not GPS locations.
- Agent session logs under `src/agents/player/logs/` and Agent42 rendered maps in
   blob storage are ephemeral and safe to delete.
- The server is intended for short-lived workshop use, not production.
