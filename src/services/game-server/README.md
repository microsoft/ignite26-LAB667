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
├── server.py          # MCP server. Mounts /<slug>/mcp per game (port 8000).
├── dashboard.py       # Public dashboard and Player pages (port 8090).
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
| `games` | `"games"` | `slug` | `display_name`, `created_at`, UTC `starts_at` / `ends_at`, IANA `timezone`, `player_mode`, `competitive_mode`, `schedule_revision` |
| `quests` | `slug` | `"quests"` | Published `payload`, editable `draft_payload`, version and draft revision |
| `quests` | `slug` | `"v1"`, `"v2"`, ... | Immutable story snapshots and publication timestamps |
| `players` | `slug` | `player_id` | JSON player state, including its pinned `game_version` |

On startup, the server adds either built-in game when it is missing:

- **Microsoft Ignite** — **Lost in San Francisco**, from `quests.json`
- **Open Hack Philadelphia** — **Lost in Philadelphia** in Challenge Mode,
  from `quests-philadelphia.json`

`DEFAULT_GAME_SLUG`, `DEFAULT_GAME_NAME`, and `DEFAULT_EVENT_NAME` can rename
the San Francisco seed. Existing games are never overwritten during startup.

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

The quest document has top-level `city` and `story` values used by the public
player experience. Each quest has a `begin` prompt, an `end` prompt, and
one or more `missions`.
Movement lives on missions: every mission has `start_address` and
`end_address`. If either address is empty, no movement is required for that
mission. The quest start location is derived from the first mission's
`start_address`; the quest end location is derived from the last mission's
`end_address`. Use full geocodable postal addresses with street number, street,
ZIP/postal code, city, state or region when relevant, and country.

```json
{
  "city": "San Francisco",
  "story": "Public game introduction shown to the player.",
  "quests": [
    {
      "id": 1,
      "name": "Example Quest",
      "city_guide": "# Example Quest City Guide\n\nThe evidence needed to solve this route's question.",
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
  ]
}
```

`question` missions validate `answer` against `valid_answers`
case-insensitively. `move` missions default to `car`, `walking`, and `bike`
as valid answers and use a private `route_ref` for route animation. Quests with
city-guide question missions must include a Markdown `city_guide`; a question
with `"uses_city_guide": false`, such as the secret note, does not require it.
City-guide mission prompts tell players to use Foundry IQ and the provided data
already in the lab's Blob Storage. They do not return a guide download URL or
ask players to upload a document. Note-image missions still return their image
resource for the Note Reader.

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

```bash
python server.py
# -> http://localhost:8000/<slug>/mcp
```

| Variable | Default | Notes |
| --- | --- | --- |
| `AZURE_TABLES_CONNECTION_STRING` | — | Required. Storage account or `UseDevelopmentStorage=true`. |
| `MCP_HOST` | `0.0.0.0` | HTTP bind address |
| `MCP_PORT` | `8000` | HTTP bind port |
| `DEFAULT_GAME_SLUG` | `san-francisco` | Slug for the San Francisco seed game |
| `DEFAULT_GAME_NAME` | `Lost in San Francisco` | Display name for the San Francisco seed game |
| `DEFAULT_EVENT_NAME` | `Microsoft Ignite` | Event name shown above the San Francisco challenge |

The server checks the games table when MCP requests arrive and lazily creates
the MCP app for each slug. Games added through the admin UI are routable
immediately at `/<slug>/mcp`.

### MCP SDK compatibility

The server uses the **official MCP Python SDK 2.x** (`mcp>=2.2.0,<3`),
validated with 2.3.0. It imports `MCPServer` from `mcp.server.mcpserver`;
the separate `fastmcp` package is not required.

The server exposes seven game tools and `game_play_prompt` at per-game
`/<slug>/mcp` URLs, using stateless Streamable HTTP with SSE responses for legacy
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

The player now uses Agent Framework **1.23.0** with MCP **2.3.0**, validated
against this server over real HTTP. Separate service environments are still
recommended for isolation, but are no longer required by conflicting MCP
major versions. Upgrade the player's Agent Framework and MCP packages
together using its [requirements](../../agents/player/requirements.txt).

Run `python dashboard.py` separately to serve the live room dashboard at
`http://localhost:8090/<slug>/dashboard`. The departure board on the left
shows up to 50 attendees in two columns and flips to the next group every
10 seconds. You can pause the rotation without stopping live updates or
route animations on the map to the right.

For the activity view, open `http://localhost:8090/<slug>/dashboard-v2` or
select **Open display v2** in the game admin. The newest quest events appear
on the left without showing clue answers. On the right, the map marks the
start, checkpoints, and finish. Players with a known game location appear on
the map; recent travel replays with a transport icon and a name bubble.
Stationary players at a quest pin are hidden to keep the pin clear. Hover
over a stationary dot elsewhere to see the player's name.
New quest completions show a postcard over the map for four seconds,
stamped **Destination reached** with the player's name. With reduced motion
enabled, the postcard appears without animation.

## Run the admin UI

```bash
python admin.py
# open http://localhost:8080
```

For local HTTP, set `ADMIN_COOKIE_SECURE=false` (included in `.env.example`).
Leave it `true`, the default, for HTTPS deployments.

For local development, set `ADMIN_DEVELOPMENT_MODE=true` (also included in
`.env.example`) to keep the built-in **admin / admin** credentials without a
forced password change. Never enable development mode in a deployed
environment.

In a deployment, sign in with **admin / admin** on first start. Before managing
any games, you must choose a new password of **12-128 characters**, different
from your current password. After changing it, sign in again. Use **Password**
in the header to change it later, or **Sign out** to end the current session.

Credentials and sessions are stored in the same Azure Storage account as game
state, in `adminusers` and `adminsessions`; `adminloginattempts` holds the shared
sign-in throttle. Passwords use salted PBKDF2-SHA256 hashes, never plaintext.
Sessions expire after eight hours, use HttpOnly/SameSite cookies, and all sessions
are invalidated when the password or account access changes. State-changing requests require a
CSRF token and same-origin requests. Sign-in and password checks share a limit
of ten attempts per five minutes across all accounts, including successful
attempts and attempts with unknown usernames.
Admin pages and game
management APIs both require operator authentication. The public dashboard
does not require an operator login; MCP requests require a player bearer API key.

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
open the separate creation page (`/games/new`). Enter the name, city, and slug,
and optionally the start/end date and time plus timezone. The city seeds the
new quest document; after creation, edit `city` with the rest of the story
content. Creation opens the story editor for the new unpublished draft. Import
JSON or build the story there, then publish when ready. Duplicate slugs are
rejected without modifying the existing game; `new` is reserved for the
creation route.

The admin uses a warm, light interface with dark typography, pill-shaped
controls, terracotta highlights and lime primary actions. Login, game management,
story editing and maps share the same responsive styles; no external fonts or
third-party brand assets are required.

Each game has two authenticated subpages:

- **Dashboard** (`/games/<slug>`): player counts, current mission/progress,
  details, leaderboard, and recorded story locations for the latest published
  version, which is shown beside the game title. Players pinned to historical
  versions remain available for version-management safeguards but are not mixed
  into the live operational view. The MCP endpoint, public player experience, and
  public in-room display are grouped as game assets. Resetting players removes
  their runs; they must register again to receive the latest story.
- **Edit game** (`/games/<slug>/edit`): quest navigation and an opening /
  missions / ending timeline. Edit scenes, questions, accepted answers and
  locations, duplicate quests or missions, and reorder/remove missions.
  Every mission shows its **Start**, **Answer**, and **Complete** phases without
  collapsing the completion scene. Travel answers include a compact Azure Maps
  route preview; question answers are shown as operator-only chips. Editing
  opens in an overlay, and mission actions are grouped under one menu.
  **Story preview** hides editing controls and accepted answers. The same page
  contains the live play window and player links. Operators choose **Guided
  Mode** for the complete workshop lessons or **Challenge Mode** for a compact
  setup, goal, and success brief without step-by-step guidance. The selected
  mode is shown as a pill throughout the admin. Times are
  entered in an IANA timezone and stored as UTC. Both dates/times must be set
  together, with end after start. Leave both empty for unrestricted play.
  Nonexistent or ambiguous daylight-saving local times are rejected. Schedule
  changes use optimistic concurrency and remain independent of story publishing.
  Published-version management is also in the editor toolbar. Historical story
  versions can be deleted only when no players are assigned to them; the current
  version cannot be deleted. The legacy `/games/<slug>/settings` URL redirects
  here.

The editor uses one responsive story view. Each travel mission includes its own
noninteractive Azure Maps preview with start and end markers; dashed connections
represent story order, not calculated travel routes. Dashboard player pins
represent game-state positions, not GPS.

Set `AZURE_MAPS_KEY` on the admin service to enable maps and address lookup.
The azd template supplies it through a secret; as with the public dashboard,
the map control receives this key in the browser. Address lookup shows
candidates for operator confirmation, never silently chooses a city centroid.
Coordinates can also be edited directly. Missing pins produce warnings; the
editor remains usable when Maps is unavailable.

**Import JSON** validates and previews a file before replacing the in-memory
draft. **Export JSON** includes current unsaved edits and preserves unknown
fields. A raw JSON editor remains under **Advanced**. The document must have a `quests` array, unique positive quest IDs, and unique
mission IDs per quest. Top-level `city` and `story` values supply the public
player introduction.
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

### Player modes and gameplay windows

The dashboard serves `/<slug>/player` and, in Guided Mode,
`/<slug>/player/<lesson>`. Legacy `/<slug>/instructions` URLs permanently
redirect to the equivalent player URL.
The admin serves the same public pages for previews; settings and editing still
require operator authentication. Shared [player sources](../../../player/README.md)
are bundled with the admin/dashboard images, including screenshots. Game
variables are escaped text substitutions, never executable templates.
Do not put secrets in this public player content.

Set `GAME_SERVER_URL` and `AGENT42_URL` on both dashboard and admin so code
examples use the deployed service URLs. The shared-service Bicep wires these
automatically. The old Skillable export is no longer the delivery path.

Player registration checks the current schedule, as do MCP session
start/resume, quest start, and answer submission. Play is allowed at the start instant and
blocked at or after the end instant. Rejected calls do not modify player state.
Outside the window, the Player page returns a closed-window screen without
lesson navigation or lesson HTML. During the final 24 hours before opening,
that screen shows a live **Enter the city in** countdown and reloads when it
reaches zero. Status, leaderboard, and abandonment remain available outside
the window. Existing games without schedule fields keep unrestricted play.

`PUT /api/games/<slug>/schedule` accepts `starts_at`, `ends_at`, `timezone`,
`player_mode` (`guided` or `challenge`), `competitive_mode` (boolean), and
`revision` (the current game's
`schedule_revision`). Naive ISO datetimes use
the selected timezone; datetimes with explicit offsets specify exact instants.
Send both timestamps as `null` to remove the restriction. Stale revisions
return HTTP 409; invalid schedules return HTTP 422.

### Test the admin

From this directory, in a virtual environment:

```bash
pip install -r requirements-test.txt
python -m playwright install --with-deps chromium
PYTHON_DOTENV_DISABLED=1 python -m unittest discover -s tests -p 'test_*.py' -v
```

On PowerShell, set `$env:PYTHON_DOTENV_DISABLED = "1"` first, then run the
`python -m unittest` command without the Bash environment-variable prefix.
The test requirements include Agent Framework and the player dependencies
for client/server integration coverage; production server dependencies remain
in **requirements.txt**.

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
cache replacement/shutdown. Agent Framework tests connect with a real MCP 2
client, discover tools and prompts, invoke generated functions through an
entire quest, check structured results, and verify tool filtering without
prompt loading. These use fake storage only and make no model or Azure calls.
For transport-only validation, use `-p 'test_mcp_transport.py'`; Chromium is
not needed for that subset.

## Deploy with azd

From the repository root, follow the [azd deployment guide](../../../infra/README.md)
to deploy the MCP server, dashboard, admin UI, and Agent42 together. It
provisions shared storage and Maps, wires the service URLs, and supplies keys
through Container Apps secrets. The admin requires authentication, with
HTTPS-only session cookies enabled by the template. Complete the initial
password change before sharing access. MCP requests require a player bearer
API key issued through public registration. Agent42 advice requires the same
key; its discovery card and the dashboard remain public. Do not treat this as
a production deployment.

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

Admin and dashboard Dockerfiles now require the **repository root** as their
build context so they can include shared instructions. The active azd
configuration sets this automatically. For manual builds, run from the root:

```bash
docker build -f src/services/game-server/Dockerfile.admin -t game-admin .
docker build -f src/services/game-server/Dockerfile.dashboard -t game-dashboard .
```

The MCP Dockerfile still uses the game-server folder as its context. Before
reactivating the legacy workflow, update its admin/dashboard build contexts
and Dockerfile paths to match.

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
| Dashboard | `AZURE_TABLES_CONNECTION_STRING`, `DASHBOARD_HOST=0.0.0.0`, `DASHBOARD_PORT=8090`, `GAME_SERVER_URL`, `AGENT42_URL` for instructions, `AZURE_MAPS_KEY` for map rendering |
| Admin | `AZURE_TABLES_CONNECTION_STRING`, `ADMIN_PORT=8080`, `GAME_SERVER_URL=https://<mcp-app-url>`, `DASHBOARD_URL=https://<dashboard-app-url>`, `AGENT42_URL` for instructions, `AZURE_MAPS_KEY` for maps/address lookup |

The admin UI can create games, edit quests, and reset players, so protect the
admin container app with the same access controls you use for workshop
operators.

## Connect an agent (MCP client config)

Register with a nickname at **http://localhost:8090/san-francisco/player** and
copy your private API key. Configure your MCP client's authorization header
with that key; never commit a populated configuration or share it publicly.

```json
{
  "mcpServers": {
    "lost-in-san-francisco": {
      "url": "http://localhost:8000/san-francisco/mcp",
      "headers": {
        "Authorization": "Bearer <copy-from-the-player-page>"
      }
    }
  }
}
```

## MCP tools exposed (per game)

| Tool | Purpose |
| --- | --- |
| `begin_session()` | Entry point. Return the authenticated player's current session and next action. |
| `resume_player()` | Resume the authenticated player's session. |
| `start_quest()` | Begin the authenticated player's quest. |
| `submit_mission_answer(answer, route_ref?)` | Submit the current mission answer and advance. |
| `abandon_quest(reason?)` | Give up. |
| `get_leaderboard()` | Top 10 for this game. |
| `get_player_status()` | Inspect the authenticated player's state. |

Registration happens on the Player page, not through an MCP tool. Player
identity comes from the bearer key, so tools do not take a `player_id` argument.

## Scoring

Competitive Mode is disabled by default for every game. When enabled under
**Schedule & player**, completed runs receive points and appear in rankings and
leaderboards:

`score = 1000 - 50 * failed_answer_attempts - 10 * minutes_taken` (floored at 0).

When Competitive Mode is disabled, quests still track elapsed time and complete
normally, but no score is stored or shown and the leaderboard is unavailable.

## Notes

- All state lives in Azure Tables — no local files are written at runtime.
- MCP apps are cached per game slug after first use and are refreshed if a game
  is recreated with the same slug.
