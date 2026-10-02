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
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

import storage
from quest_logic import _current_mission_index, _normalize_quest, _player_location

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8090"))
ROUTE_REF_RE = re.compile(r"^[a-z0-9]{15}$")
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

    def build_data(self, game: dict[str, Any], *, limit: int | None = 50) -> dict[str, Any]:
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
                "player_id": player_id,
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
                "score": player.get("score"),
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
            })

        counts["attempts"] = attempts
        players.sort(key=lambda item: (item.get("created_at") or "", str(item.get("name") or "").lower()))
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
            "players": players[:limit] if limit is not None else players,
            "leaderboard": storage.get_leaderboard(slug, limit=10),
            "quest_flow": quest_flow[:12],
        }

    async def fetch_route(self, ref: str) -> dict[str, Any] | None:
        ref = (ref or "").strip().lower()
        if not ROUTE_REF_RE.match(ref) or not self.routes_base_url:
            return None
        url = f"{self.routes_base_url}/{ref}.json"

        def _fetch() -> bytes:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.read()

        try:
            body = await asyncio.to_thread(_fetch)
            return json.loads(body)
        except Exception:
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
    ])


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)
