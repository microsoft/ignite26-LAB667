# Lost in the City workshop

A hands-on workshop for building AI agents with the Microsoft Agent Framework,
Model Context Protocol (MCP), Agent-to-Agent (A2A), memory, logging, and
retrieval. Participants build an agent that plays **Lost in the City**, a
narrative quest game where the player has to cross a city, solve guidebook
clues, and reach the final destination before time runs out.

The default seed game is **Lost in San Francisco**, but the game server supports
multiple city games. Each game has its own MCP endpoint, dashboard, quest list,
players, and leaderboard.

## What's in this repo

| Path | Purpose |
| --- | --- |
| [src/services/game-server/](../src/services/game-server/) | Multi-game MCP server, read-only room dashboard, and FastAPI admin UI. State is stored in Azure Tables. |
| [src/services/agent42/](../src/services/agent42/) | Standalone A2A transport expert. It compares car, walking, and bike routes using weather, traffic, Azure Maps, and rendered route maps. |
| [src/agents/player/](../src/agents/player/) | Complete reference agent that connects to the game MCP server, asks Agent42 over A2A, queries the city guide, remembers `player_id`, and writes session logs. |
| [data/city-guide/](../data/city-guide/) | San Francisco guide chapters used as source material for the retrieval challenge. |
| [instructions/](../instructions/README.md) | Step-by-step attendee workshop instructions. |
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
4. The server tracks progress, failed answer attempts, elapsed time, and final
    score.
5. The dashboard and admin UI show player status and leaderboards for each game.

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
and replace the default password. You can then create games, edit quests,
import [quests.json](../src/services/game-server/quests.json), reset players, and
watch leaderboards. See the [game-server README](../src/services/game-server/README.md) for the
full tool reference, quest schema, storage model, and deployment notes.

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
AZURE_SEARCH_KNOWLEDGE_BASE_NAME=city-knowledgebase
AZURE_SEARCH_KEY=<your-azure-ai-search-key>
GAME_MCP_URL=http://localhost:8000/san-francisco/mcp
AGENT42_URL=http://localhost:8042/
```

To use a different model deployment for the city-guide specialist, also set:

```env
CITY_GUIDE_AZURE_OPENAI_DEPLOYMENT_NAME=<your-city-guide-deployment>
```

If that deployment is on a different Azure OpenAI resource, also set
`CITY_GUIDE_AZURE_OPENAI_ENDPOINT` and `CITY_GUIDE_AZURE_OPENAI_API_KEY`.

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

The player now uses the A2A 1.x integration. Upgrade the deployed Agent42 service
before running the updated player against it; see the
[Agent42 upgrade notes](../src/services/agent42/README.md#install-local).

The agent will start or resume a game, save the assigned `player_id` in
`src/agents/player/memory.json` (created at runtime), call Agent42 through the
`ask_agent42` tool, call the city-guide specialist for retrieval, and write a
per-session log under `src/agents/player/logs/`.

## Workshop flow

The attendee workshop is split into numbered steps:

1. [Step into your workspace](../instructions/00_step_into_your_workspace.md)
2. [Get Azure OpenAI details from Microsoft Foundry](../instructions/01_get_azure_openai_details_from_foundry.md)
3. [Create a hello world agent](../instructions/02_create_hello_world_agent.md)
4. [Connect to the gaming MCP server](../instructions/03_connect_to_the_gaming_mcp_server.md)
5. [Add memory for the player ID](../instructions/04_add_memory_for_the_player_id.md)
6. [Add session logging](../instructions/05_add_session_logging.md)
7. [Test Agent42 transport specialist](../instructions/06_test_agent42_transport_specialist.md)
8. [Test the city guide agent](../instructions/07_test_the_city_guide_agent.md)
9. [Bring the specialist agents into the main agent](../instructions/08_bring_specialists_into_main_agent.md)
10. [Lab recap](../instructions/09_lab_recap.md)

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
- If no games exist, the game server seeds `DEFAULT_GAME_SLUG` from
   [quests.json](../src/services/game-server/quests.json).
- Quest content can be edited through the admin UI or imported from
   [quests.json](../src/services/game-server/quests.json) into a draft. The
   **Edit game** page shows the story timeline and location map. Publishing
   creates a version for new players; existing players keep their assigned
   version. The **Dashboard** page shows live progress and recorded game
   positions, not GPS locations.
- Agent session logs under `src/agents/player/logs/` and Agent42 rendered maps in
   blob storage are ephemeral and safe to delete.
- The server is intended for short-lived workshop use, not production.
