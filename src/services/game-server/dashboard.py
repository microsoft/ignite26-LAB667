"""Standalone dashboard service for the 'Lost in the City' workshop.

This process serves the read-only per-game room dashboard:

    GET /<slug>/dashboard                    HTML page
    GET /<slug>/dashboard/data               live player + leaderboard JSON
    GET /<slug>/dashboard/quests             quest waypoints for the Azure Map
    GET /<slug>/dashboard/routes/<ref>       proxy for route JSON blobs

Run it independently from the MCP server so heavy work (blob fetches,
template renders) cannot block the MCP event loop, and so it can be scaled
on its own container.

    python dashboard.py   # listens on $DASHBOARD_HOST:$DASHBOARD_PORT (8090)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

import storage
from workshop_instructions import instruction_routes
from game_schedule import game_availability
from player_identity import (
    agent42_route_ref,
    authenticate,
    bearer_token,
    player_state,
    public_agent42_advice,
    register_player,
)
from quest_logic import _current_mission_index, _normalize_quest, _player_location

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8090"))
ROUTE_REF_RE = re.compile(r"^[a-z0-9]{15}$")
AZURE_BLOB_HOST_SUFFIXES = (
    ".blob.core.windows.net",
    ".blob.core.usgovcloudapi.net",
    ".blob.core.chinacloudapi.cn",
    ".blob.core.cloudapi.de",
)
ACTIVE_STATUSES = {"mission"}


def _move_routes_base_url() -> str:
    explicit = os.environ.get("MOVE_ROUTES_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    cs = (
        os.environ.get("MOVE_BLOB_CONNECTION_STRING")
        or os.environ.get("AZURE_TABLES_CONNECTION_STRING")
        or ""
    )
    parts: dict[str, str] = {}
    for item in cs.split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            parts[k] = v
    account = parts.get("AccountName", "")
    suffix = parts.get("EndpointSuffix", "core.windows.net")
    container = os.environ.get("MOVE_BLOB_CONTAINER", "agent42-routes")
    if not account:
        return ""
    return f"https://{account}.blob.{suffix}/{container}"


def _coerce_coord(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _agent42_asset_url(advice: str, ref: str, extension: str) -> str | None:
    field = "directions" if extension == "json" else "map"
    value = _agent42_field(advice, field)
    if not value or not ROUTE_REF_RE.fullmatch(ref) or extension not in {"json", "png"}:
        return None
    parsed = urllib.parse.urlsplit(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not any(host.endswith(suffix) for suffix in AZURE_BLOB_HOST_SUFFIXES)
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or parsed.fragment
        or not parsed.path.endswith(f"/{ref}.{extension}")
    ):
        return None
    return value


class Dashboard:
    """HTML + JSON builders for `/<slug>/dashboard*` paths."""

    def __init__(
        self,
        *,
        azure_maps_key: str | None = None,
        routes_base_url: str | None = None,
    ) -> None:
        self.azure_maps_key = (
            azure_maps_key if azure_maps_key is not None else os.environ.get("AZURE_MAPS_KEY", "")
        )
        self.routes_base_url = (
            routes_base_url if routes_base_url is not None else _move_routes_base_url()
        )
        self.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    def render_html(self, game: dict[str, Any]) -> str:
        return self.templates.get_template("dashboard.html").render(
            display_name=str(game.get("display_name") or game.get("slug") or "Dashboard"),
            slug=str(game.get("slug") or ""),
            azure_maps_key=self.azure_maps_key,
        )

    def build_quest_locations(self, game: dict[str, Any]) -> dict[str, Any]:
        slug = game["slug"]
        current, _ = storage.load_published(slug)
        versions = {int(p["game_version"]) for p in storage.list_players(slug).values()}
        if current:
            versions.add(current)
        quests: list[dict[str, Any]] = []
        for version in sorted(versions):
            for quest in storage.load_quests(slug, version)["quests"]:
                quests.append({**quest, "name": f"{quest.get('name', '')} (v{version})", "game_version": version})
        quests_out: list[dict[str, Any]] = []
        for quest in quests:
            if quest.get("id") is None:
                continue
            normalized = _normalize_quest(quest)
            missions = normalized.get("missions") or []
            raw_points: list[dict[str, Any]] = []
            for mission_index, mission in enumerate(missions):
                for endpoint in ("start", "end"):
                    address = (mission.get(f"{endpoint}_address") or "").strip()
                    lat = _coerce_coord(mission.get(f"{endpoint}_lat"))
                    lng = _coerce_coord(mission.get(f"{endpoint}_lng"))
                    if not address or lat is None or lng is None:
                        continue
                    raw_points.append({
                        "address": address,
                        "lat": lat,
                        "lng": lng,
                        "mission_index": mission_index,
                        "endpoint": endpoint,
                    })
            collapsed: list[dict[str, Any]] = []
            for point in raw_points:
                if collapsed and collapsed[-1]["lat"] == point["lat"] and collapsed[-1]["lng"] == point["lng"]:
                    continue
                collapsed.append(point)
            points: list[dict[str, Any]] = []
            for i, point in enumerate(collapsed):
                if i == 0:
                    kind = "start"
                    label = f"Start \u2022 {normalized.get('name', '')}".strip()
                elif i == len(collapsed) - 1:
                    kind = "end"
                    label = f"End \u2022 {point['address']}"
                else:
                    kind = "mission"
                    label = f"Mission {i} \u2022 {point['address']}"
                points.append({
                    "kind": kind,
                    "label": label,
                    "address": point["address"],
                    "lat": point["lat"],
                    "lng": point["lng"],
                })
            quests_out.append({
                "id": quest.get("id"),
                "name": normalized.get("name", ""),
                "points": points,
            })
        return {"quests": quests_out, "versions": sorted(versions)}

    def build_data(self, game: dict[str, Any]) -> dict[str, Any]:
        slug = game["slug"]
        versions: dict[int, dict[str, Any]] = {}
        players: list[dict[str, Any]] = []
        counts = {"total": 0, "registered": 0, "active": 0, "complete": 0, "abandoned": 0}
        attempts = 0

        for player_id, player in storage.list_players(slug).items():
            status = str(player.get("status") or "registered")
            version = int(player["game_version"])
            if version not in versions:
                versions[version] = {str(q["id"]): _normalize_quest(q) for q in storage.load_quests(slug, version)["quests"]}
            quest = versions[version].get(str(player.get("quest_id"))) or {}
            missions = (quest.get("missions") if quest else []) or []
            current_index = _current_mission_index(player)
            answer_attempts = int(player.get("answer_attempts", player.get("code_attempts", 0)) or 0)
            attempts += answer_attempts
            counts["total"] += 1
            if status in ACTIVE_STATUSES:
                counts["active"] += 1
            elif status in counts:
                counts[status] += 1

            players.append({
                "player_id": player.get("player_ref") or player_id,
                "name": player.get("name") or player_id,
                "quest_id": player.get("quest_id"),
                "game_version": version,
                "location": _player_location(player, quest),
                "current_mission_id": missions[current_index].get("id") if current_index < len(missions) else None,
                "quest_name": quest.get("name", f"Quest {player.get('quest_id')}") if quest else f"Quest {player.get('quest_id')}",
                "status": status,
                "current_mission_index": current_index,
                "mission_count": len(missions),
                "created_at": player.get("created_at"),
                "started_at": player.get("started_at"),
                "completed_at": player.get("completed_at"),
                "last_activity_at": (
                    player.get("completed_at")
                    or player.get("abandoned_at")
                    or player.get("started_at")
                    or player.get("created_at")
                    or ""
                ),
                "answer_attempts": answer_attempts,
                "time_taken_minutes": player.get("time_taken_minutes"),
                "mission_results": [
                    {
                        "mission_index": int(result.get("mission_index", 0) or 0),
                        "route_ref": str(result.get("route_ref") or ""),
                        "completed_at": str(result.get("completed_at") or ""),
                    }
                    for result in (player.get("mission_results") or [])
                    if (result.get("route_ref") or "").strip()
                ],
                **({"score": player.get("score")} if game["competitive_mode"] else {}),
            })

        counts["attempts"] = attempts
        players.sort(key=lambda item: (
            item.get("created_at") or "", str(item.get("name") or "").lower(), item["player_id"],
        ))
        quest_flow = [p for p in players if p["status"] in ACTIVE_STATUSES or p["status"] == "registered"]
        quest_flow.sort(key=lambda item: item.get("last_activity_at") or "", reverse=True)
        current, _ = storage.load_published(slug)
        quest_versions = set(versions)
        if current:
            quest_versions.add(current)

        return {
            "game": game,
            "quest_versions": sorted(quest_versions),
            "counts": counts,
            "players": players,
            "leaderboard": storage.get_leaderboard(slug, limit=10),
            "quest_flow": quest_flow[:12],
        }

    async def fetch_route(self, ref: str, asset_url: str | None = None) -> dict[str, Any] | None:
        body = await self.fetch_route_asset(ref, "json", asset_url)
        if body is None:
            return None
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    async def fetch_route_asset(
        self, ref: str, extension: str, asset_url: str | None = None,
    ) -> bytes | None:
        ref = (ref or "").strip().lower()
        if (
            not ROUTE_REF_RE.fullmatch(ref)
            or extension not in {"json", "png"}
        ):
            return None
        url = asset_url or (
            f"{self.routes_base_url}/{ref}.{extension}" if self.routes_base_url else ""
        )
        if not url:
            return None

        def _fetch() -> bytes:
            accept = "application/json" if extension == "json" else "image/png"
            req = urllib.request.Request(url, headers={"Accept": accept})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read()

        try:
            return await asyncio.to_thread(_fetch)
        except (urllib.error.URLError, TimeoutError):
            return None


# ---------- ASGI app -------------------------------------------------------

dashboard = Dashboard()


async def dashboard_page(request: Request) -> HTMLResponse | JSONResponse:
    slug = request.path_params["slug"]
    game = storage.get_game(slug)
    if not game:
        return JSONResponse({"error": f"Game '{slug}' not found"}, status_code=404)
    return HTMLResponse(dashboard.render_html(game))


async def dashboard_data(request: Request) -> JSONResponse:
    slug = request.path_params["slug"]
    game = storage.get_game(slug)
    if not game:
        return JSONResponse({"error": f"Game '{slug}' not found"}, status_code=404)
    return JSONResponse(dashboard.build_data(game))


async def dashboard_quests(request: Request) -> JSONResponse:
    slug = request.path_params["slug"]
    game = storage.get_game(slug)
    if not game:
        return JSONResponse({"error": f"Game '{slug}' not found"}, status_code=404)
    return JSONResponse(dashboard.build_quest_locations(game))


async def dashboard_route(request: Request) -> JSONResponse:
    payload = await dashboard.fetch_route(request.path_params["code"])
    if payload is None:
        return JSONResponse({"error": "route not available"}, status_code=404)
    return JSONResponse(payload)


async def register_public_player(request: Request) -> JSONResponse:
    slug = request.path_params["slug"]
    game = storage.get_game(slug)
    if not game:
        return JSONResponse({"error": "Game not found."}, status_code=404)
    availability = game_availability(game)
    if availability["state"] != "open":
        return JSONResponse({"error": availability["message"]}, status_code=409)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)
    try:
        api_key, player = register_player(slug, str(payload.get("nickname") or ""))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    response = JSONResponse(
        {"api_key": api_key, "player": player_state(slug, api_key, player)},
        status_code=201,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def public_player_state(request: Request) -> JSONResponse:
    slug = request.path_params["slug"]
    api_key = bearer_token(request.headers)
    if api_key is None:
        return JSONResponse(
            {"error": "A valid player API key is required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
    player = storage.get_player(slug, api_key)
    if player is None:
        return JSONResponse(
            {"error": "A valid player API key is required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
    response = JSONResponse({"player": player_state(slug, api_key, player)})
    response.headers["Cache-Control"] = "no-store"
    return response


def _authenticated_player(
    request: Request,
    slug: str,
) -> tuple[str, dict[str, Any]] | None:
    api_key = bearer_token(request.headers)
    if api_key is None:
        return None
    authenticated = authenticate(api_key, expected_slug=slug)
    if authenticated is None:
        return None
    return api_key, authenticated[1]


def _agent42_field(advice: str, label: str) -> str:
    match = re.search(rf"(?im)^{re.escape(label)}:\s*(.+)$", advice)
    return match.group(1).strip() if match else ""


def _agent42_event(
    request: Request,
) -> tuple[dict[str, Any], str] | JSONResponse:
    slug = request.path_params["slug"]
    authenticated = _authenticated_player(request, slug)
    if authenticated is None:
        return JSONResponse(
            {"error": "A valid player API key is required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
    _, player = authenticated
    try:
        event_index = int(request.path_params["event_index"])
        event = (player.get("timeline") or [])[event_index]
    except (ValueError, IndexError):
        return JSONResponse({"error": "Agent42 advice was not found."}, status_code=404)
    if event_index < 0 or event.get("type") != "agent42":
        return JSONResponse({"error": "Agent42 advice was not found."}, status_code=404)
    return event, agent42_route_ref(event)


async def public_agent42_details(request: Request) -> JSONResponse:
    resolved = _agent42_event(request)
    if isinstance(resolved, JSONResponse):
        return resolved
    event, route_ref = resolved
    raw_advice = str(event.get("detail") or "")
    route_url = _agent42_asset_url(raw_advice, route_ref, "json")
    route = await dashboard.fetch_route(route_ref, route_url) if route_ref else None
    advice = public_agent42_advice(raw_advice)
    safe_route = None
    if route is not None:
        travel_seconds = route.get("travel_time_seconds")
        traffic_seconds = route.get("traffic_delay_seconds")
        safe_route = {
            "mode": route.get("mode"),
            "origin": (route.get("origin") or {}).get("query"),
            "destination": (route.get("destination") or {}).get("query"),
            "distance_km": route.get("distance_km"),
            "travel_time_minutes": (
                round(float(travel_seconds) / 60) if travel_seconds is not None else None
            ),
            "traffic_delay_minutes": (
                round(float(traffic_seconds) / 60) if traffic_seconds is not None else None
            ),
        }
    return JSONResponse(
        {
            "title": str(event.get("title") or "Agent42 route advice"),
            "advice": advice,
            "weather": _agent42_field(advice, "Weather"),
            "recommendation": _agent42_field(advice, "recommendation"),
            "route": safe_route,
            "map_available": route is not None,
        },
        headers={"Cache-Control": "no-store"},
    )


async def public_agent42_map(request: Request) -> Response:
    resolved = _agent42_event(request)
    if isinstance(resolved, JSONResponse):
        return resolved
    event, route_ref = resolved
    map_url = _agent42_asset_url(str(event.get("detail") or ""), route_ref, "png")
    image = await dashboard.fetch_route_asset(route_ref, "png", map_url) if route_ref else None
    if image is None:
        return JSONResponse({"error": "Route map is not available."}, status_code=404)
    return Response(
        image,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def index(_request: Request) -> JSONResponse:
    games = storage.list_games()
    return JSONResponse({
        "service": "lost-in-the-city dashboard",
        "games": [
            {
                "slug": g["slug"],
                "display_name": g["display_name"],
                "dashboard_url": f"/{g['slug']}/dashboard",
            }
            for g in games
        ],
    })


@asynccontextmanager
async def lifespan(application: Starlette) -> AsyncIterator[None]:
    await asyncio.to_thread(storage.init_storage)
    yield


def build_app() -> Starlette:
    return Starlette(lifespan=lifespan, routes=[
        Mount("/static", app=StaticFiles(directory=str(BASE_DIR / "static")), name="static"),
        Route("/", endpoint=index),
        Route("/{slug}/dashboard", endpoint=dashboard_page),
        Route("/{slug}/dashboard/", endpoint=dashboard_page),
        Route("/{slug}/dashboard/data", endpoint=dashboard_data),
        Route("/{slug}/dashboard/quests", endpoint=dashboard_quests),
        Route("/{slug}/dashboard/routes/{code}", endpoint=dashboard_route),
        Route("/api/games/{slug}/players", endpoint=register_public_player, methods=["POST"]),
        Route("/api/games/{slug}/player", endpoint=public_player_state),
        Route(
            "/api/games/{slug}/player/timeline/{event_index:int}/agent42",
            endpoint=public_agent42_details,
        ),
        Route(
            "/api/games/{slug}/player/timeline/{event_index:int}/agent42/map",
            endpoint=public_agent42_map,
        ),
        *instruction_routes(),
    ])


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)
