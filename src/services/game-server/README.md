# Lost in the City — Multi-Game MCP Server

A **Model Context Protocol (MCP)** server that powers the *Lost in the City*
workshop game family. This workshop uses *Lost in San Francisco*. The server
supports multiple games with independent quests, players, and leaderboards.
All state lives in **Azure Tables**.

Ships with a FastAPI **admin UI** for managing games, editing quest content,
watching leaderboards, and resetting state.

## Project layout

```
game-server/
├── server.py          # MCP server. Mounts /<slug>/mcp and /<slug>/dashboard per game.
├── admin.py           # FastAPI admin UI (port 8080)
├── admin_auth.py      # Table-backed credentials, sessions, and login protection
├── templates/         # Jinja2 HTML templates for admin and dashboard pages
├── static/            # Shared CSS and browser JavaScript
├── storage.py         # Azure Tables-backed storage (games, quests, players)
├── init.py            # Destructive reset + first-game setup helper
├── quests.json        # Seed quests; can be imported into a game from admin
├── requirements.txt
├── Dockerfile.mcp
├── Dockerfile.dashboard
├── Dockerfile.admin
├── .env.example
└── README.md
```

## Storage

Three game-state tables are created automatically on first start:

| Table | PartitionKey | RowKey | Payload |
| --- | --- | --- | --- |
| `games` | `"games"` | `slug` | `display_name`, `created_at` |
| `quests` | `slug` | `"quests"` | Published `payload`, editable `draft_payload`, version and draft revision |
| `quests` | `slug` | `"v1"`, `"v2"`, ... | Immutable story snapshots and publication timestamps |
| `players` | `slug` | `player_id` | JSON player state, including its pinned `game_version` |

If no games exist on first start, one is seeded from `quests.json` using
`DEFAULT_GAME_SLUG` / `DEFAULT_GAME_NAME` (defaults: `san-francisco`,
`Lost in San Francisco`).

After editing `quests.json`, import it into Azure Tables either from the admin
editor with **Advanced > Import seed quests**, or for the default game by running:

```bash
python storage.py
```

Both operations update the **draft only**. Publish it in the admin editor when
ready. Existing unversioned content is preserved automatically as version 1;
existing players continue on that version. Newly created admin games start
unpublished; the first-run default game is seeded and published automatically.

To wipe all game-server storage data and recreate the first game from
`quests.json`, run:

```bash
python init.py --yes
```

This deletes all entities in the `games`, `quests`, and `players` tables.
Use `--slug` and `--name` to override the recreated first game's defaults.
Admin credentials and sessions are separate and are not reset by this command.

## Quest schema

Each quest has a `begin` prompt, an `end` prompt, and one or more `missions`.
Movement lives on missions: every mission has `start_address` and
`end_address`. If either address is empty, no movement is required for that
mission. The quest start location is derived from the first mission's
`start_address`; the quest end location is derived from the last mission's
`end_address`. Use full geocodable postal addresses with street number, street,
ZIP/postal code, city, state or region when relevant, and country.

```json
{
  "id": 1,
  "name": "Example Quest",
  "begin": {"prompt": "Opening scene"},
  "missions": [
    {
      "id": "transport-1",
      "type": "move",
      "start_address": "515 Valencia St, San Francisco, CA 94110, United States",
      "end_address": "544 Hayes St, San Francisco, CA 94102, United States",
      "arrival_prompt": "Scene shown when the mission starts.",
      "complete_prompt": "Scene shown after the mission is completed."
    },
    {
      "id": "secret-code",
      "type": "question",
      "mission": "What is the secret code?",
      "arrival_prompt": "Scene shown when the question starts.",
      "complete_prompt": "Scene shown after the correct answer.",
      "valid_answers": ["CODE42"]
    }
  ],
  "end": {"prompt": "Closing scene"}
}
```

`question` missions validate `answer` against `valid_answers`
case-insensitively. `move` missions default to `car`, `walking`, and `bike`
as valid answers and use a private `route_ref` for route animation.

## Install

```bash
cd src/services/game-server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set AZURE_TABLES_CONNECTION_STRING
```

For local development you can run **Azurite** instead of a real storage
account:

```bash
npm install -g azurite
azurite --silent --location /tmp/azurite
# in .env:
# AZURE_TABLES_CONNECTION_STRING=UseDevelopmentStorage=true
```

## Run the MCP server

 "begin": {
   "prompt": "Opening scene shown after START.",
   "flavor": "Optional extra atmosphere."
 },
 "end": {
   "prompt": "Final completion message."
 }
python server.py
# -> http://localhost:8000/<slug>/mcp
```

| Variable | Default | Notes |
| --- | --- | --- |
| `AZURE_TABLES_CONNECTION_STRING` | — | Required. Storage account or `UseDevelopmentStorage=true`. |
| `MCP_HOST` | `0.0.0.0` | HTTP bind address |
| `MCP_PORT` | `8000` | HTTP bind port |
| `DEFAULT_GAME_SLUG` | `san-francisco` | Slug for the first-run seed game |
| `DEFAULT_GAME_NAME` | `Lost in San Francisco` | Display name for the seed game |

The server checks the games table when MCP requests arrive and lazily creates
the MCP app for each slug. Games added through the admin UI are routable
immediately at `/<slug>/mcp`.

### MCP SDK compatibility

The server uses the **official MCP Python SDK 2.x** (`mcp>=2.2.0,<3`),
validated with 2.2.0. It imports `MCPServer` from `mcp.server.mcpserver`;
the separate `fastmcp` package is not required.

The migration preserves all eight game tools, `game_play_prompt`, per-game
`/<slug>/mcp` URLs, and stateless Streamable HTTP with SSE responses for legacy
clients. Initialization-based clients remain supported, alongside SDK 2's
modern discovery/per-request protocol. Tool response JSON remains camelCase
on the wire; SDK 2 Python result objects use attributes such as
`structured_content` and `is_error`.

Each dynamically created game app has a lifespan-owned session manager.
Cached apps drain active requests before closing on replacement or deletion.
Synchronous game tools run in SDK worker threads. SDK 2 also applies a default
4 MiB MCP request-body limit.

Reinstall requirements and restart/rebuild the MCP service to apply the
upgrade; changing the admin UI alone does not update the deployed MCP service.
No game-data migration or player reset is required.

Keep the game-server environment separate from the player-agent environment.
Agent Framework 1.19's MCP integration requires `mcp<2`; do not force SDK 2
into that environment. The player agent can continue using SDK 1 as an HTTP
client of this SDK 2 server.

Each game also has a live room dashboard at `/<slug>/dashboard`. It shows up
to 50 player slots on the left side of the screen and refreshes player status,
quest progress, and leaderboard data every few seconds.

## Run the admin UI

```bash
python admin.py
# open http://localhost:8080
```

For local HTTP, set `ADMIN_COOKIE_SECURE=false` (included in `.env.example`).
Leave it `true`, the default, for HTTPS deployments.

Sign in with **admin / admin** on first start. Before managing any games, you
must choose a new password of **12-128 characters**, different from your
current password. After changing it, sign in again. Use **Password** in the
header to change it later, or **Sign out** to end the current session.

Credentials and sessions are stored in the same Azure Storage account as game
state, in `adminusers` and `adminsessions`; `adminloginattempts` holds the shared
sign-in throttle. Passwords use salted PBKDF2-SHA256 hashes, never plaintext.
Sessions expire after eight hours, use HttpOnly/SameSite cookies, and all sessions
are invalidated when the password or account access changes. State-changing requests require a
CSRF token and same-origin requests. Sign-in and password checks share a limit
of ten attempts per five minutes across all accounts, including successful
attempts and attempts with unknown usernames.
Admin pages and game
management APIs both require authentication; the dashboard and MCP service
remain unchanged.

The initial account is created only when missing; restarting or redeploying
does not reset its password. **Keep access restricted during first-run setup:**
anyone who knows the public default credentials could otherwise claim the
account first. Do not use the default credentials for a running workshop.

### Users and roles

Administrators use **Users** (`/users`) to create accounts, change roles,
disable or re-enable access, and reset passwords:

| Role | Access |
| --- | --- |
| Administrator | Manage all games and operator accounts |
| Editor | Create, edit, publish, reset and delete all games; no user management |

The existing `admin` account retains administrator access when upgrading; its
password and active sessions are preserved. New accounts default to Editor.
Usernames are case-insensitive, stored in lowercase, and contain 1-64 letters,
numbers, dashes or underscores, starting with a letter or number. They cannot
be renamed. Use disabling rather than deleting accounts.

Provide a **12-128 character temporary password**, share it privately, and have
the user replace it at first sign-in. Password resets follow the same mandatory
change flow; no invitation or reset emails are sent. Changing a role, disabling
or re-enabling an account, or resetting its password revokes its existing
sessions. Concurrent account edits are rejected; refresh Users before retrying.
Passwords and password hashes are never returned by the user-management API.

To prevent lockout, the built-in `admin` cannot be disabled or demoted. You
cannot change your own role/access from Users; use **Password** in the header
for your own password. Another administrator can reset the built-in admin's
password if needed.

### Create and manage games

Choose **Create game** in navigation or **Create a game** on the Games page to
open the separate creation page (`/games/new`). Enter the name and slug;
creation opens the story editor for the new unpublished draft. Import JSON or
build the story there, then publish when ready. Duplicate slugs are rejected
without modifying the existing game; `new` is reserved for the creation route.

The admin uses a warm, light interface with dark typography, pill-shaped
controls, terracotta highlights and lime primary actions. Login, game management,
story editing and maps share the same responsive styles; no external fonts or
third-party brand assets are required.

Each game has two authenticated subpages:

- **Dashboard** (`/games/<slug>`): player counts, current mission/progress,
  details, leaderboard, and recorded story locations. Filter by published
  version to inspect different runs. The public projector display remains a
  separate link. Resetting players removes their runs; they must register
  again to receive the latest story.
- **Edit game** (`/games/<slug>/edit`): quest navigation and an opening /
  missions / ending timeline. Edit scenes, questions, accepted answers and
  locations, duplicate quests or missions, and reorder/remove missions.
  **Story preview** hides editing controls and accepted answers.

Use **Story**, **Story + map**, or **Full map** views. Maps show numbered,
shared location markers and color-coded quests; clicking a marker lets you
select its scene. Dashed connections represent story order, not calculated
travel routes. Dashboard player pins represent game-state positions, not GPS.
Use **Fit all points**, fullscreen, and quest filters to explore the whole game.
At tablet widths, Story + map places the map beneath the story, beside the
sticky quest navigation. On phones, navigation, story, and map stack vertically.

Set `AZURE_MAPS_KEY` on the admin service to enable maps and address lookup.
The azd template supplies it through a secret; as with the public dashboard,
the map control receives this key in the browser. Address lookup shows
candidates for operator confirmation, never silently chooses a city centroid.
Coordinates can be edited directly or placed by clicking the map. Missing
pins produce warnings; the editor remains usable when Maps is unavailable.

**Import JSON** validates and previews a file before replacing the in-memory
draft. **Export JSON** includes current unsaved edits and preserves unknown
fields. A raw JSON editor remains under **Advanced**. The document must have a
`quests` array, unique positive quest IDs, and unique mission IDs per quest.
Publication additionally requires named quests, opening/ending scenes, at
least one mission per quest, movement addresses, and accepted question answers.
Invalid/out-of-range coordinates are rejected; missing coordinates are shown
as warnings. Documents are limited to 64,000 UTF-16 bytes by the current Azure
Table string-property storage design; split larger stories into separate games.

**Save draft** never changes a live story. **Publish** atomically creates an
immutable version for new registrations. Existing players keep the version
assigned when they registered, including its questions, answers and scoring
content. Concurrent edits/publications return a conflict rather than
overwriting another operator's work; export local edits before reloading.
Published versions are retained until the game is deleted.

The API follows the same boundary: `GET/PUT /api/games/<slug>/draft` uses a
`revision` and `document`; `POST /publish` uses the saved draft's `revision`.
`POST /validate` checks a candidate document without saving it. The former
direct `PUT /quests` endpoint returns a conflict directing callers to the
draft/publish workflow. Seed import also requires a revision.

The admin UI and MCP server both pick up new games without a restart.

### Test the admin

From this directory, in a virtual environment:

```bash
pip install -r requirements-test.txt
python -m playwright install --with-deps chromium
python -m unittest discover -s tests -p 'test_*.py' -v
```

Authentication tests use fake Azure Tables; browser tests use deterministic
API fixtures, plus a full browser login/password-change/game-creation flow
against the real admin backend with fake storage. They do not connect to or
modify your Azure account. Browser
coverage includes login/password forms, game creation/deletion, visual story
editing, JSON import/export, map point handling, player resets, error feedback,
and mobile layouts. Versioning tests exercise actual MCP tools with fake
storage, including legacy migration and old/new players completing different
published stories. Transport tests exercise the actual per-game HTTP
dispatcher, legacy protocol initialization, modern SDK clients over a local
HTTP server, tool/prompt schemas and responses, concurrent requests, and
cache replacement/shutdown. These also use fake storage only.

## Deploy with azd

From the repository root, follow the [azd deployment guide](../../../infra/README.md)
to deploy the MCP server, dashboard, admin UI, and Agent42 together. It
provisions shared storage and Maps, wires the service URLs, and supplies keys
through Container Apps secrets. The admin requires authentication, with
HTTPS-only session cookies enabled by the template. Complete the initial
password change before sharing access; other service endpoints are still
public without authentication. Do not treat this as a production deployment.

## Legacy deployment reference

The [legacy game-server workflow](../../../infra/legacy-workflows/game-server.yml)
mirrors the Agent42 Azure Container Apps deployment. It is preserved outside
`.github/workflows/` and is not active. Its source paths match this repository,
but its Azure resources and credentials still refer to the old workshop.
It defines builds and deployments for three container apps from this folder:

| Container app | Dockerfile | Public port | Purpose |
| --- | --- | --- | --- |
| `game-server-mcp` | `Dockerfile.mcp` | `8000` | MCP endpoints at `/<slug>/mcp` |
| `game-server-dashboard` | `Dockerfile.dashboard` | `8090` | Room dashboard at `/<slug>/dashboard` |
| `game-server-admin` | `Dockerfile.admin` | `8080` | Admin UI |

The workflow uses the same Azure and registry GitHub secrets as Agent42:

```text
AGENT42_AZURE_CLIENT_ID
AGENT42_AZURE_TENANT_ID
AGENT42_AZURE_SUBSCRIPTION_ID
AGENT42_REGISTRY_USERNAME
AGENT42_REGISTRY_PASSWORD
```

If your Azure Container Apps use different names, resource group, or registry,
edit the `env:` block in the
[legacy workflow](../../../infra/legacy-workflows/game-server.yml) before enabling it.

The Azure identity behind `AGENT42_AZURE_CLIENT_ID` must be able to read and
update the three game-server Container Apps. The simplest assignment is
Contributor on the resource group that contains them:

```bash
az role assignment create \
  --assignee <AGENT42_AZURE_CLIENT_ID> \
  --role Contributor \
  --scope /subscriptions/<subscription-id>/resourceGroups/lab530_RG
```

The deployment error `Microsoft.App/containerApps/read` means this role
assignment is missing for the identity used by `azure/login`.

Configure the deployed container apps with these environment variables:

| App | Required settings |
| --- | --- |
| MCP | `AZURE_TABLES_CONNECTION_STRING`, `MCP_HOST=0.0.0.0`, `MCP_PORT=8000` |
| Dashboard | `AZURE_TABLES_CONNECTION_STRING`, `DASHBOARD_HOST=0.0.0.0`, `DASHBOARD_PORT=8090`, `AZURE_MAPS_KEY` for map rendering |
| Admin | `AZURE_TABLES_CONNECTION_STRING`, `ADMIN_PORT=8080`, `GAME_SERVER_URL=https://<mcp-app-url>`, `DASHBOARD_URL=https://<dashboard-app-url>`, `AZURE_MAPS_KEY` for maps/address lookup |

The admin UI can create games, edit quests, and reset players, so protect the
admin container app with the same access controls you use for workshop
operators.

## Connect an agent (MCP client config)

```json
{
  "mcpServers": {
    "lost-in-san-francisco": {
      "url": "http://localhost:8000/san-francisco/mcp"
    }
  }
}
```

## MCP tools exposed (per game)

| Tool | Purpose |
| --- | --- |
| `begin_session(player_id?)` | Entry point. Resolves new vs returning player. |
| `register_player(name)` | Register a new player and assign a random quest. |
| `resume_player(player_id)` | Resume an existing in-progress player. |
| `start_quest(player_id)` | Begin the quest. |
| `submit_mission_answer(player_id, answer, route_ref?)` | Submit the current mission answer and advance. |
| `abandon_quest(player_id, reason?)` | Give up. |
| `get_leaderboard()` | Top 10 for this game. |
| `get_player_status(player_id)` | Inspect a player's state. |

## Scoring

`score = 1000 - 50 * failed_answer_attempts - 10 * minutes_taken` (floored at 0).

## Notes

- All state lives in Azure Tables — no local files are written at runtime.
- MCP apps are cached per game slug after first use and are refreshed if a game
  is recreated with the same slug.
