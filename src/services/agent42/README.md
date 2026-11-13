# Agent42 — A2A Local Transport Expert

Agent42 is a standalone agent that picks the best way to get around in **any
city in the world**. It exposes itself over the
[**A2A (Agent-to-Agent)** protocol](https://a2aproject.github.io/A2A/) so
the workshop's player agent (or any other A2A client) can call it for
transport advice during the *Lost in the City* quests.

Given a question like *"I'm in The Mission and need to get to Hayes Valley
— taxi, walking, or bike?"* Agent42 looks up the weather, fetches three
routes, draws a static map of the recommended route, and replies with a
short summary ending in a `recommendation: <choice>` line and a
`recommendation code: <code>` line that names the persisted artifacts.

## Tools

| Tool | Source | Notes |
| --- | --- | --- |
| `get_current_weather(location)` | [Open-Meteo](https://open-meteo.com/) (no key) + [Azure Maps geocoding](https://learn.microsoft.com/azure/azure-maps/) | Returns temperature and feels-like temperature in Celsius and Fahrenheit, precipitation, wind, condition. |
| `get_route(origin, destination, mode)` | [Azure Maps Route Directions](https://learn.microsoft.com/rest/api/maps/route/) | `mode` ∈ {`driving`/`taxi`/`car`, `walking`/`pedestrian`, `bike`/`bicycle`}. Car uses traffic data cached for up to 30 minutes. Refuses trips > ~100 mi apart. |
| `render_route_map(origin, destination, mode)` | [Azure Maps Static Image](https://learn.microsoft.com/rest/api/maps/render/get-map-static-image) + [Azure Blob Storage](https://learn.microsoft.com/azure/storage/blobs/) | Uploads `<code>.png` and `<code>.json` and returns readable URLs. `<code>` is a 15-char `[a-z0-9]` "recommendation code". |

Weather results include `temperature_c`, `temperature_f`, `feels_like_c`, and
`feels_like_f`. Fahrenheit values are converted locally from Celsius and rounded
to one decimal place, without extra API calls. Missing temperatures remain null
in both units.

Successful weather lookups are cached for **one hour** per location in the
Agent42 process's memory, avoiding repeated weather and geocoding calls.
Location keys ignore case and extra whitespace. Concurrent requests reuse a
successful lookup; errors are not cached. The cache holds up to 1,024 locations,
evicting the oldest entry when full. Each container replica has its own cache,
which clears on restart.

Successful Azure Maps route responses, including traffic, are cached for
**30 minutes** per origin/destination coordinate pair and travel mode.
Route advice and map rendering share this cache, so mode aliases such as
`taxi` and `car` reuse the same route. Traffic may change during that window;
departure and arrival timestamps remain those of the original lookup.
This cache also holds up to 1,024 entries per process, evicts the oldest entry
when full, clears on restart, and does not cache errors.

Geocoding results are cached for **24 hours**, shared across weather, routes,
and map rendering. Keys ignore case and extra whitespace and include the
configured geocoding bias. The cache holds up to 1,024 locations.

Static map image bytes are cached for **30 minutes** for identical route
geometry and map settings (including pins, colors, zoom, and dimensions),
with up to 128 images in memory. Each rendering still creates a fresh
recommendation code and uploads its own PNG and directions JSON; artifact
URLs are not reused. Both caches are process-local, clear on restart, evict
the oldest entry when full, and never cache failed lookups. Concurrent
requests reuse successful lookups.

## Project layout

```
agent42/
├── server.py          # Agent + A2A server entrypoint (port 8042)
├── tools.py           # Weather, routing, and map-rendering tools
├── test.py            # Interactive A2A client for poking the server
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

## Install (local)

```bash
cd src/services/agent42
python -m venv .venv
source .venv/bin/activate
pip install --upgrade --upgrade-strategy eager -r requirements.txt
cp .env.example .env
# fill in AZURE_MAPS_KEY, your model creds, and AGENT42_BLOB_CONNECTION_STRING
```

Requirements use minimum versions rather than historical exact pins, so this
command selects the latest releases compatible with the upstream packages.
The A2A integration is still a preview package: its explicit minimum prevents
pip from retaining the older preview that required A2A SDK 0.3.

Validated locally together: Agent Framework **1.23.0**, `agent-framework-a2a`
**1.0.0b261022**, `agent-framework-foundry` **1.15.0**, `a2a-sdk` **1.3.0**,
and MCP **2.3.0**. The server uses the SDK's HTTP-server
extra, route factories, protobuf messages, and A2A 1.0 AgentCard schema.
The player's [requirements](../../agents/player/requirements.txt) also require
the current integration. Upgrade/redeploy Agent42 before upgrading existing
players: the new server accepts legacy `message/send` calls, but new clients
send A2A 1.0 requests that an old server does not understand.

Separate service environments remain recommended for isolation, but Agent
Framework 1.23 and the [game server](../game-server/README.md) now both support
MCP SDK 2.x. Upgrade the Agent Framework packages together through this
requirements file. `agent-framework-foundry` 1.15.0 requires
`azure-ai-projects>=2.2.0,<2.8.0`; do not bypass upstream constraints with
`--no-deps` or add a blanket `--pre`. Run `python -m pip check` after upgrading.

## Run

```bash
python server.py
# -> http://localhost:8042
# -> AgentCard at http://localhost:8042/.well-known/agent-card.json
```

In another terminal:

```bash
python test.py
```

The interactive client defaults to `http://localhost:8042`. Set `AGENT42_URL`
to test a deployed server instead. Run the game MCP server too, register on its
Player page, and set `GAME_API_KEY` for the client. Agent42 validates that key
through `GAME_SERVER_URL` and records its advice against the player.

For local A2A regression tests, run from this directory:

```bash
PYTHON_DOTENV_DISABLED=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

The tests exercise A2A routes with a fake agent and make no live model, Maps,
or storage calls. On PowerShell, set `$env:PYTHON_DOTENV_DISABLED = "1"` first,
then run the command without the Bash environment-variable prefix.

## Environment variables

See [.env.example](.env.example) for the full set; required at minimum:

| Variable | Required | Notes |
| --- | --- | --- |
| `AZURE_MAPS_KEY` | yes | Shared key from an Azure Maps account ([docs](https://learn.microsoft.com/azure/azure-maps/how-to-manage-authentication)) |
| `GAME_SERVER_URL` | no | Game MCP service base URL for player authentication and advice events; default `http://localhost:8000`. Required to change when deploying separately. |
| `AGENT42_BLOB_CONNECTION_STRING` | yes | Connection string for the Azure Storage account that hosts rendered maps |
| `AGENT42_BLOB_CONTAINER` | no | Container name (default `agent42-routes`). Created on first use with public-blob access when the storage account allows it. |
| `AGENT42_BLOB_SAS_EXPIRY_HOURS` | no | Expiry, in hours, for generated read-only map / directions SAS URLs when the connection string includes an account key. Default `168`. |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` + `AZURE_AI_FOUNDRY_DEPLOYMENT` | one of two | Foundry path (uses `az login`) |
| `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_DEPLOYMENT_NAME` | one of two | Azure OpenAI path |
| `AGENT42_HOST` | no | Bind address; default `0.0.0.0` |
| `AGENT42_PORT` | no | Port; default `8042` |
| `AGENT42_PUBLIC_URL` | no | URL advertised in the AgentCard. Set when deploying behind a public hostname. |
| `AGENT42_GEOCODE_BIAS` | no | Optional `"lon,lat"` to nudge geocoding toward a specific city for short / ambiguous queries. |

> **Note:** if the storage account does not allow anonymous blob access,
> Agent42 still returns readable URLs by adding read-only SAS tokens when the
> blob connection string includes an account key.

## Output format

```
Weather: 12°C / 53.6°F, light rain
Options:
Car: 2.9 km / 1.8 miles, 9 minutes + 3 minutes for traffic + 5 minutes pickup wait
Bike: 2.9 km / 1.8 miles, 11 minutes
Walking: 2.9 km / 1.8 miles, 36 minutes
Reasoning: <2–3 short sentences>
map: https://<account>.blob.core.windows.net/agent42-routes/<code>.png
directions: https://<account>.blob.core.windows.net/agent42-routes/<code>.json
recommendation: car
recommendation code: a1b2c3d4e5f6g7h
```

If the two places are more than ~100 miles apart, the reply collapses to a
short paragraph showing the straight-line distance in both kilometers and
miles, suggesting a flight / train / long-distance bus, and ending with
`recommendation: none`.

## Talk to Agent42 from another agent

```python
import os

import httpx
from agent_framework.a2a import A2AAgent

async with httpx.AsyncClient(
  headers={"Authorization": f"Bearer {os.environ['GAME_API_KEY']}"},
) as http_client:
  async with A2AAgent(
    name="Agent42",
    url="http://localhost:8042",
    http_client=http_client,
  ) as agent42:
    response = await agent42.run(
      "I'm in The Mission and need to get to Hayes Valley. "
      "Taxi, walking, or bike?"
    )
    print(response.text)
```

Inside an async function, this example uses `GAME_API_KEY` from the process
environment. Never put the key in the prompt or commit it to source control.

Or hit the JSON-RPC endpoint directly: `POST /` with a player
`Authorization: Bearer <GAME_API_KEY>` header, `A2A-Version: 1.0`,
method `SendMessage`, and an A2A 1.0 message payload. Legacy `message/send`
payloads remain accepted with `A2A-Version: 0.3` (or no version header).
Discovery at `/.well-known/agent-card.json` now returns the A2A 1.0 card with
`supportedInterfaces`; clients that parse the old card schema must be updated.

## Offline tests

From this directory, with its environment activated:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m pip check
```

Tests use a fake Agent Framework agent and the real A2A HTTP routes/client.
They cover discovery, exact reply text, the player's specialist tool, legacy
requests, error responses, unsupported streaming/cancellation, and shutdown.
They do not call models, Maps, weather services, or Azure storage.

## Deploy with Docker

```bash
docker build -t agent42 .
docker run --rm -p 8042:8042 --env-file .env agent42
```

For Azure Container Apps / any container host: expose port `8042`, set the
env vars above, and set `AGENT42_PUBLIC_URL` to the externally reachable URL
so the AgentCard advertises the correct address.

## Notes

For a shared workshop deployment, use the
[azd deployment guide](../../../infra/README.md). It provisions Agent42's
dedicated model and configures its Maps key, route storage, and public AgentCard
URL alongside the game services. This path uses the Azure OpenAI API-key option,
not Azure CLI credentials inside the container.

- Agent42 is **stateless** — every A2A request runs the underlying
  `agent_framework.Agent` once and returns a single text reply. The A2A task
  store is in-memory; restarting the server drops in-flight tasks.
- Model failures and empty replies now produce A2A protocol errors, not
  successful transport-advice messages. Failures are logged by the A2A handler.
  Streaming is not supported; message-only replies are not cancelable tasks.
- Azure Maps does not currently offer public-transit routing; the agent
  recommends only `car` / `walking` / `bike` (mapped to Azure's
  `car` / `pedestrian` / `bicycle` travel modes).
- For car routing, Azure Maps defaults `departAt` to "now" when omitted and
  returns traffic-aware travel time plus a no-traffic baseline; Agent42
  uses the delta between those two to detect heavy traffic and pad the
  rideshare pickup wait from 5 to 10 minutes.
