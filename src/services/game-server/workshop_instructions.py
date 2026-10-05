"""Public shared workshop lessons with allowlisted, escaped game variables."""
from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

import storage
from game_schedule import game_availability, local_fields

BASE_DIR = Path(__file__).resolve().parent
PLAYER_DIR = (
    BASE_DIR / "player" if (BASE_DIR / "player").is_dir()
    else BASE_DIR.parents[2] / "player"
)
GUIDED_DIR = PLAYER_DIR / "guided"
CHALLENGE_DIR = PLAYER_DIR / "challenge"
TEMPLATES = Jinja2Templates(directory=BASE_DIR / "templates")
VARIABLE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")


def public_url(name: str, default: str) -> str:
    value = os.environ.get(name, default).rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must be a public HTTP(S) base URL without credentials, query, or fragment.")
    return value


def render_lesson(source: str, variables: dict[str, str]) -> str:
    source = source.replace("../assets/", "/player-assets/").replace("./assets/", "/player-assets/")
    source = re.sub(r"^> \[!Hint\]\s*", "> **Hint:** ", source, flags=re.MULTILINE)
    rendered = MarkdownIt("commonmark", {"html": False}).enable("table").render(source)

    def substitute(match: re.Match[str]) -> str:
        name = match[1]
        if name not in variables:
            raise ValueError(f"Unknown workshop instruction variable: {name}")
        return escape(variables[name], quote=True)

    return VARIABLE.sub(substitute, rendered)


def instruction_story(document: dict[str, object], city: str) -> str:
    story = document.get("story")
    if isinstance(story, str) and story.strip():
        return story.strip()
    return f"You've just arrived in {city}. Your agent must navigate the city, solve its missions, and complete the adventure."


def instruction_city(document: dict[str, object], legacy_city: str) -> str:
    city = document.get("city")
    if isinstance(city, str) and city.strip():
        return city.strip()
    return legacy_city


def instructions_page(request: Request) -> HTMLResponse:
    game = storage.get_game(request.path_params["slug"])
    if game is None:
        raise HTTPException(404, "Game not found")
    schedule = local_fields(game)
    start_date, _, start_time = schedule["starts_at"].partition("T")
    end_date, _, end_time = schedule["ends_at"].partition("T")
    document = storage.load_quests(game["slug"])
    city = instruction_city(document, game["city"])
    variables = {
        "game_name": game["display_name"],
        "game_city": city,
        "game_story": instruction_story(document, city),
        "game_slug": game["slug"],
        "game_mcp_url": f"{public_url('GAME_SERVER_URL', 'http://localhost:8000')}/{game['slug']}/mcp",
        "agent42_url": public_url("AGENT42_URL", "https://agent42.workshop.agentcon.dev") + "/",
        "game_start_date": start_date or "Not scheduled",
        "game_start_time": start_time or "Not scheduled",
        "game_end_date": end_date or "Not scheduled",
        "game_end_time": end_time or "Not scheduled",
        "game_timezone": schedule["timezone"],
    }
    player_mode = game.get("player_mode", "guided")
    content_dir = CHALLENGE_DIR if player_mode == "challenge" else GUIDED_DIR
    lessons = sorted(content_dir.glob("[0-9][0-9]_*.md"))
    if not lessons:
        raise RuntimeError(f"Shared {player_mode} player content was not packaged with this service.")
    selected = request.path_params.get("lesson", lessons[0].stem)
    lesson = next((path for path in lessons if path.stem == selected), None)
    if lesson is None:
        raise HTTPException(404, "Player lesson not found")
    navigation = [
        {"slug": path.stem, "title": path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ")}
        for path in lessons
    ]
    index = lessons.index(lesson)
    response = TEMPLATES.TemplateResponse(request, "workshop_instructions.html", {
        "game": game, "variables": variables, "availability": game_availability(game),
        "player_mode": player_mode,
        "lessons": navigation, "selected": selected,
        "previous": navigation[index - 1] if index else None,
        "next": navigation[index + 1] if index + 1 < len(navigation) else None,
        "content": render_lesson(lesson.read_text(encoding="utf-8"), variables),
    })
    response.headers.update({
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; style-src 'self'; frame-ancestors 'none'; base-uri 'none'",
    })
    return response


def legacy_instructions_redirect(request: Request) -> RedirectResponse:
    slug = request.path_params["slug"]
    lesson = request.path_params.get("lesson")
    suffix = f"/{lesson}" if lesson else ""
    return RedirectResponse(f"/{slug}/player{suffix}", status_code=308)


def instruction_routes() -> list[Mount | Route]:
    return [
        Mount("/player-assets", app=StaticFiles(directory=PLAYER_DIR / "assets"), name="player-assets"),
        Mount("/instruction-assets", app=StaticFiles(directory=PLAYER_DIR / "assets"), name="legacy-instruction-assets"),
        Route("/{slug}/player", endpoint=instructions_page),
        Route("/{slug}/player/", endpoint=instructions_page),
        Route("/{slug}/player/{lesson}", endpoint=instructions_page),
        Route("/{slug}/instructions", endpoint=legacy_instructions_redirect),
        Route("/{slug}/instructions/", endpoint=legacy_instructions_redirect),
        Route("/{slug}/instructions/{lesson}", endpoint=legacy_instructions_redirect),
    ]
