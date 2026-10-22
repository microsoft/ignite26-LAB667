"""Public shared workshop lessons with allowlisted, escaped game variables."""
from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from azure.core.exceptions import ResourceNotFoundError
from markdown_it import MarkdownIt
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
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
MORE_DIR = PLAYER_DIR / "more"
MORE_LINK = re.compile(r'href="#more-([a-z0-9-]+)"')
CHALLENGE_DIR = PLAYER_DIR / "challenge"
TEMPLATES = Jinja2Templates(directory=BASE_DIR / "templates")
VARIABLE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
# Filled in by player.js after sign-in; the server never knows the player's name or API key.
PLAYER_NAME_MARKUP = '<span data-player-name>player</span>'
PLAYER_API_KEY_MARKUP = '<span data-player-api-key>&lt;copy-from-this-player-page&gt;</span>'
PLAYER_MARKUP = {
    "player_name": PLAYER_NAME_MARKUP,
    "player_api_key": PLAYER_API_KEY_MARKUP,
    "player_quest": '<span data-player-quest>your quest</span>',
}
GUIDED_MISSIONS = (
    {
        "label": "Mission 1",
        "name": "Get Ready and Start the Game",
        "lessons": (
            "00_step_into_your_workspace",
            "01_get_azure_openai_details_from_foundry",
            "02_create_hello_world_agent",
            "03_connect_to_the_gaming_mcp_server",
            "05_add_session_logging",
        ),
    },
    {
        "label": "Mission 2",
        "name": "Use Agent42 to Travel",
        "lessons": ("06_test_agent42_transport_specialist",),
    },
    {
        "label": "Mission 3",
        "name": "Solve Your City Guide Question with Foundry IQ",
        "lessons": (
            "07_test_the_city_guide_agent",
            "08_bring_specialists_into_main_agent",
        ),
    },
    {
        "label": "Arrived",
        "name": "Complete the Game",
        "lessons": ("09_lab_recap",),
    },
)


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
        if name in PLAYER_MARKUP:
            return PLAYER_MARKUP[name]
        if name not in variables:
            raise ValueError(f"Unknown workshop instruction variable: {name}")
        return escape(variables[name], quote=True)

    return VARIABLE.sub(substitute, rendered)


def more_info_panels(content: str, variables: dict[str, str]) -> list[dict[str, str]]:
    """Render the player/more/<slug>.md panels linked from a lesson as #more-<slug>."""
    panels = []
    for slug in dict.fromkeys(MORE_LINK.findall(content)):
        path = MORE_DIR / f"{slug}.md"
        if not path.is_file():
            raise ValueError(f"Unknown player read-more panel: {slug}")
        title, _, body = path.read_text(encoding="utf-8").partition("\n")
        panels.append({
            "slug": slug,
            "title": title.removeprefix("# ").strip(),
            "content": render_lesson(body, variables),
        })
    return panels


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


def guided_mission_navigation(
    navigation: list[dict[str, str]],
) -> list[dict[str, object]]:
    items = {item["slug"]: item for item in navigation}
    configured = {
        lesson
        for mission in GUIDED_MISSIONS
        for lesson in mission["lessons"]
    }
    if configured != set(items):
        missing = sorted(set(items) - configured)
        stale = sorted(configured - set(items))
        raise RuntimeError(
            f"Guided mission mapping is out of date. Unmapped: {missing}; missing files: {stale}."
        )
    return [
        {
            "label": mission["label"],
            "name": mission["name"],
            "lessons": [items[slug] for slug in mission["lessons"]],
        }
        for mission in GUIDED_MISSIONS
    ]


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
        "game_event": str(game.get("event_name") or "").strip() or "this event",
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
    availability = game_availability(game)
    player_mode = game.get("player_mode", "guided")
    content_dir = CHALLENGE_DIR if player_mode == "challenge" else GUIDED_DIR
    lessons = sorted(content_dir.glob("[0-9][0-9]_*.md"))
    if not lessons:
        raise RuntimeError(f"Shared {player_mode} player content was not packaged with this service.")
    selected = request.path_params.get("lesson", lessons[0].stem)
    navigation: list[dict[str, str]] = []
    content = ""
    previous = None
    next_lesson = None
    mission_navigation: list[dict[str, object]] = []
    current_mission: dict[str, object] | None = None
    more_info: list[dict[str, str]] = []
    if availability["state"] == "open":
        lesson = next((path for path in lessons if path.stem == selected), None)
        if lesson is None:
            raise HTTPException(404, "Player lesson not found")
        navigation = [
            {"slug": path.stem, "title": path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ")}
            for path in lessons
        ]
        index = lessons.index(lesson)
        content = render_lesson(lesson.read_text(encoding="utf-8"), variables)
        more_info = more_info_panels(content, variables)
        previous = navigation[index - 1] if index else None
        next_lesson = navigation[index + 1] if index + 1 < len(navigation) else None
        if player_mode == "guided":
            mission_navigation = guided_mission_navigation(navigation)
            current_mission = next(
                mission
                for mission in mission_navigation
                if any(item["slug"] == selected for item in mission["lessons"])
            )
    response = TEMPLATES.TemplateResponse(request, "workshop_instructions.html", {
        "game": game, "variables": variables, "availability": availability,
        "player_mode": player_mode,
        "lessons": navigation, "selected": selected,
        "previous": previous,
        "next": next_lesson,
        "content": content,
        "mission_navigation": mission_navigation,
        "current_mission": current_mission,
        "more_info": more_info,
    })
    response.headers.update({
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        # Inline styles let browser tooling, such as VS Code's element picker, draw overlays; scripts stay same-origin.
        "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    })
    return response


def legacy_instructions_redirect(request: Request) -> RedirectResponse:
    slug = request.path_params["slug"]
    lesson = request.path_params.get("lesson")
    suffix = f"/{lesson}" if lesson else ""
    return RedirectResponse(f"/{slug}/player{suffix}", status_code=308)


def city_guide_download(request: Request) -> Response:
    slug = request.path_params["slug"]
    game = storage.get_game(slug)
    if game is None:
        raise HTTPException(404, "Game not found")
    if game_availability(game)["state"] != "open":
        raise HTTPException(403, "Player window is closed.")
    try:
        version = int(request.path_params["version"])
        document = storage.load_quests(slug, version)
    except (KeyError, ResourceNotFoundError, TypeError, ValueError):
        raise HTTPException(404, "City guide not found") from None
    quest_id = request.path_params["quest_id"]
    quest = next(
        (item for item in document.get("quests", []) if str(item.get("id")) == quest_id),
        None,
    )
    content = str((quest or {}).get("city_guide") or "").strip()
    if not content:
        raise HTTPException(404, "City guide not found")
    filename = re.sub(r"[^a-z0-9]+", "-", str(quest.get("name") or "city-guide").lower()).strip("-")
    return Response(
        content + "\n",
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{filename or "city-guide"}.md"',
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


def instruction_routes() -> list[Mount | Route]:
    return [
        Mount("/player-assets", app=StaticFiles(directory=PLAYER_DIR / "assets"), name="player-assets"),
        Mount("/instruction-assets", app=StaticFiles(directory=PLAYER_DIR / "assets"), name="legacy-instruction-assets"),
        Route("/{slug}/guides/{version:int}/{quest_id}.md", endpoint=city_guide_download),
        Route("/{slug}/player", endpoint=instructions_page),
        Route("/{slug}/player/", endpoint=instructions_page),
        Route("/{slug}/player/{lesson}", endpoint=instructions_page),
        Route("/{slug}/instructions", endpoint=legacy_instructions_redirect),
        Route("/{slug}/instructions/", endpoint=legacy_instructions_redirect),
        Route("/{slug}/instructions/{lesson}", endpoint=legacy_instructions_redirect),
    ]
