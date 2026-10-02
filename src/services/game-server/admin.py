"""FastAPI admin UI for the multi-game 'Lost in the City' workshop server.

The HTML, CSS, and JS live under templates/ and static/. This module only
wires up routes and JSON APIs.
"""
from __future__ import annotations

import hmac
import logging
import os
import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

from dotenv import load_dotenv
from azure.core.exceptions import AzureError, ResourceExistsError
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import storage
from admin_auth import AuthStore, COOKIE_NAME, SESSION_SECONDS, Role, Session
from dashboard import Dashboard
from quest_validation import validate_document

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
GAME_SERVER_URL = os.environ.get("GAME_SERVER_URL", "http://localhost:8000").rstrip("/")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8090").rstrip("/")

logger = logging.getLogger(__name__)


def cookie_secure() -> bool:
    value = os.environ.get("ADMIN_COOKIE_SECURE", "true").lower()
    if value not in ("true", "false"):
        raise ValueError("ADMIN_COOKIE_SECURE must be true or false")
    return value == "true"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.cookie_secure = cookie_secure()
    await run_in_threadpool(storage.init_storage)
    application.state.auth = AuthStore(storage._svc())
    await run_in_threadpool(application.state.auth.initialize)
    yield


app = FastAPI(
    title="Lost in the City \u2014 Admin", lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.middleware("http")
async def admin_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://atlas.microsoft.com; "
        "style-src 'self' 'unsafe-inline' https://atlas.microsoft.com; "
        "img-src 'self' data: blob: https://*.atlas.microsoft.com https://atlas.microsoft.com; "
        "connect-src 'self' https://*.atlas.microsoft.com https://atlas.microsoft.com; worker-src blob:; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    )
    return response


@app.exception_handler(AzureError)
async def storage_unavailable(request: Request, exc: AzureError) -> JSONResponse:
    logger.error("Admin storage request failed (%s)", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": "Storage is temporarily unavailable. Please try again."},
    )


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> Response:
    if request.url.path.startswith(("/api/users", "/api/auth/")):
        # Pydantic's default error body echoes input values, including passwords.
        return JSONResponse(status_code=422, content={"detail": "Invalid account request. Check the required fields, role, and password length."})
    return await request_validation_exception_handler(request, exc)


def auth_store(request: Request) -> AuthStore:
    return request.app.state.auth


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin or request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "A same-origin browser request is required")
    # Container Apps terminates TLS before forwarding to the application.
    scheme = "https" if request.app.state.cookie_secure else request.url.scheme
    try:
        expected = urlsplit(f"{scheme}://{request.url.netloc}")
        actual = urlsplit(origin)
        expected_port = expected.port or (443 if expected.scheme == "https" else 80)
        actual_port = actual.port or (443 if actual.scheme == "https" else 80)
    except ValueError as exc:
        raise HTTPException(403, "Invalid request origin") from exc
    if (actual.scheme, actual.hostname, actual_port) != (expected.scheme, expected.hostname, expected_port):
        raise HTTPException(403, "A same-origin browser request is required")


def require_session(request: Request) -> Session:
    session = auth_store(request).get_session(request.cookies.get(COOKIE_NAME))
    if session is None:
        raise HTTPException(401, "Please sign in")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        require_same_origin(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), session.csrf_token.encode()):
            raise HTTPException(403, "Invalid CSRF token. Reload the page and try again.")
    return session


def require_operator(session: Session = Depends(require_session)) -> Session:
    if session.must_change_password:
        raise HTTPException(403, "Password change required")
    return session


def require_administrator(session: Session = Depends(require_operator)) -> Session:
    if session.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return session


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


async def limit_auth_body(request: Request) -> None:
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 4096:
            raise HTTPException(413, "Authentication request is too large")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    session = auth_store(request).get_session(request.cookies.get(COOKIE_NAME))
    if session:
        return RedirectResponse("/password" if session.must_change_password else "/", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {})


@app.get("/password", response_class=HTMLResponse)
def password_page(request: Request) -> Response:
    session = auth_store(request).get_session(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "admin_password.html", AuthStore.context(session))


@app.post("/api/auth/login", dependencies=[Depends(require_same_origin), Depends(limit_auth_body)])
def login(payload: LoginBody, request: Request) -> JSONResponse:
    token, session = auth_store(request).login(payload.username.strip(), payload.password)
    response = JSONResponse({"ok": True, "redirect": "/password" if session.must_change_password else "/"})
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
        secure=request.app.state.cookie_secure, samesite="strict", path="/",
    )
    return response


@app.post("/api/auth/logout")
def logout(request: Request, session: Session = Depends(require_session)) -> JSONResponse:
    auth_store(request).logout(session)
    response = JSONResponse({"ok": True, "redirect": "/login"})
    response.delete_cookie(COOKIE_NAME, path="/", secure=request.app.state.cookie_secure, httponly=True, samesite="strict")
    return response


@app.post("/api/auth/password", dependencies=[Depends(limit_auth_body)])
def change_password(
    payload: PasswordBody, request: Request, session: Session = Depends(require_session),
) -> JSONResponse:
    auth_store(request).change_password(session, payload.current_password, payload.new_password)
    response = JSONResponse({"ok": True, "redirect": "/login"})
    response.delete_cookie(COOKIE_NAME, path="/", secure=request.app.state.cookie_secure, httponly=True, samesite="strict")
    return response


# ---------- pages ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Response:
    session = auth_store(request).get_session(request.cookies.get(COOKIE_NAME))
    if session is None or session.must_change_password:
        return RedirectResponse("/password" if session else "/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_home.html",
        {"game_server_url": GAME_SERVER_URL, "dashboard_url": DASHBOARD_URL, **AuthStore.context(session)},
    )


@app.get("/games/new", response_class=HTMLResponse)
def create_game_page(request: Request) -> Response:
    session = auth_store(request).get_session(request.cookies.get(COOKIE_NAME))
    if session is None or session.must_change_password:
        return RedirectResponse("/password" if session else "/login", status_code=303)
    return templates.TemplateResponse(request, "admin_create_game.html", AuthStore.context(session))


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request) -> Response:
    session = auth_store(request).get_session(request.cookies.get(COOKIE_NAME))
    if session is None or session.must_change_password:
        return RedirectResponse("/password" if session else "/login", status_code=303)
    if session.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return templates.TemplateResponse(request, "admin_users.html", AuthStore.context(session))


@app.get("/games/{slug}", response_class=HTMLResponse)
def game_page(slug: str, request: Request) -> Response:
    return render_game_page(slug, request, "dashboard")


@app.get("/games/{slug}/edit", response_class=HTMLResponse)
def edit_game_page(slug: str, request: Request) -> Response:
    return render_game_page(slug, request, "edit")


def render_game_page(slug: str, request: Request, page: str) -> Response:
    session = auth_store(request).get_session(request.cookies.get(COOKIE_NAME))
    if session is None or session.must_change_password:
        return RedirectResponse("/password" if session else "/login", status_code=303)
    game = storage.get_game(slug)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return templates.TemplateResponse(
        request,
        "admin_editor.html" if page == "edit" else "admin_game.html",
        {"game": game, "game_server_url": GAME_SERVER_URL, "dashboard_url": DASHBOARD_URL,
         "game_page": page, **AuthStore.context(session)},
    )


# ---------- JSON API ----------

class UserCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    role: Role = "editor"
    temporary_password: str = Field(min_length=12, max_length=128)


class UserUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    enabled: StrictBool
    revision: str = Field(min_length=1, max_length=128)
    temporary_password: str | None = Field(default=None, min_length=12, max_length=128)


@app.get("/api/users")
def api_users(request: Request, session: Session = Depends(require_administrator)) -> dict[str, Any]:
    return {"users": auth_store(request).list_users(session)}


@app.post("/api/users", dependencies=[Depends(limit_auth_body)])
def api_create_user(
    payload: UserCreateBody, request: Request, session: Session = Depends(require_administrator),
) -> dict[str, Any]:
    return {"ok": True, "user": auth_store(request).create_user(
        session, payload.username, payload.role, payload.temporary_password,
    )}


@app.patch("/api/users/{username}", dependencies=[Depends(limit_auth_body)])
def api_update_user(
    username: str, payload: UserUpdateBody, request: Request, session: Session = Depends(require_administrator),
) -> dict[str, Any]:
    return {"ok": True, "user": auth_store(request).update_user(
        session, username, payload.role, payload.enabled, payload.revision, payload.temporary_password,
    )}


@app.get("/api/games", dependencies=[Depends(require_operator)])
def api_list_games() -> dict[str, Any]:
    return {"games": storage.list_games()}


class GameCreateBody(BaseModel):
    slug: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=150)


@app.post("/api/games", dependencies=[Depends(require_operator)])
def api_create_game(payload: GameCreateBody) -> dict[str, Any]:
    slug = payload.slug.strip().lower()
    display_name = payload.display_name.strip()
    if not slug or not display_name:
        raise HTTPException(422, "Slug and game name are required.")
    if slug == "new":
        raise HTTPException(422, "The slug 'new' is reserved. Choose another slug.")
    if storage.get_game(slug):
        raise HTTPException(409, f"A game with slug '{slug}' already exists.")
    try:
        g = storage.create_game(slug, display_name)
    except ResourceExistsError as exc:
        raise HTTPException(409, "A game with this slug already exists.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "game": g}


@app.delete("/api/games/{slug}", dependencies=[Depends(require_operator)])
def api_delete_game(slug: str) -> dict[str, Any]:
    storage.delete_game(slug)
    return {"ok": True}


@app.get("/api/games/{slug}/quests", dependencies=[Depends(require_operator)])
def api_get_quests(slug: str) -> dict[str, Any]:
    if not storage.get_game(slug):
        raise HTTPException(status_code=404, detail="Game not found")
    return storage.load_quests(slug)


@app.put("/api/games/{slug}/quests", dependencies=[Depends(require_operator)])
def api_put_quests(slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    raise HTTPException(409, "Direct live editing is disabled. Save a revision-checked draft and publish it instead.")


class RevisionBody(BaseModel):
    revision: int = Field(ge=1)


class DraftBody(RevisionBody):
    document: dict[str, Any]


class ValidateBody(BaseModel):
    document: Any
    publish: bool = False


def existing_game(slug: str) -> dict[str, Any]:
    game = storage.get_game(slug)
    if game is None:
        raise HTTPException(404, "Game not found")
    return game


@app.exception_handler(storage.ContentConflict)
async def content_conflict(request: Request, exc: storage.ContentConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/api/games/{slug}/draft", dependencies=[Depends(require_operator)])
def api_draft(slug: str) -> dict[str, Any]:
    existing_game(slug)
    return storage.load_draft(slug)


@app.put("/api/games/{slug}/draft", dependencies=[Depends(require_operator)])
def api_save_draft(slug: str, payload: DraftBody) -> dict[str, Any]:
    existing_game(slug)
    errors = validate_document(payload.document)["errors"]
    if errors:
        raise HTTPException(422, "\n".join(errors))
    return storage.save_draft(slug, payload.document, payload.revision)


@app.post("/api/games/{slug}/validate", dependencies=[Depends(require_operator)])
def api_validate(slug: str, payload: ValidateBody) -> dict[str, Any]:
    existing_game(slug)
    return validate_document(payload.document, publish=payload.publish)


@app.post("/api/games/{slug}/publish", dependencies=[Depends(require_operator)])
def api_publish(slug: str, payload: RevisionBody) -> dict[str, Any]:
    existing_game(slug)
    try:
        return storage.publish_draft(slug, payload.revision)
    except storage.ContentConflict:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/games/{slug}/activity", dependencies=[Depends(require_operator)])
def api_activity(slug: str) -> dict[str, Any]:
    game = existing_game(slug)
    current, _ = storage.load_published(slug)
    data = Dashboard().build_data(game, limit=None)
    versions = storage.list_versions(slug)
    data.update(
        published_version=current, versions=versions,
        documents={str(v["version"]): storage.load_quests(slug, v["version"]) for v in versions},
    )
    return data


@app.post("/api/games/{slug}/quests/import-seed", dependencies=[Depends(require_operator)])
def api_import_seed_quests(slug: str, payload: RevisionBody) -> dict[str, Any]:
    existing_game(slug)
    return storage.save_draft(slug, storage.load_seed_quests(), payload.revision)


@app.get("/api/maps/config", dependencies=[Depends(require_operator)])
def api_map_config() -> dict[str, str]:
    key = os.environ.get("AZURE_MAPS_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Maps are not configured. Set AZURE_MAPS_KEY on the admin service.")
    return {"key": key}


@app.get("/api/maps/geocode", dependencies=[Depends(require_operator)])
async def api_geocode(query: str = Query(min_length=3, max_length=500)) -> dict[str, Any]:
    key = api_map_config()["key"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get("https://atlas.microsoft.com/geocode", params={
                "api-version": "2025-01-01", "subscription-key": key, "query": query, "top": 5,
            })
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("Admin address lookup failed (%s)", type(exc).__name__)
        raise HTTPException(502, "Address lookup failed. Check the address or enter coordinates manually.") from exc
    candidates = []
    for feature in data.get("features", []):
        coords = feature.get("geometry", {}).get("coordinates", [])
        props = feature.get("properties", {})
        if len(coords) >= 2:
            candidates.append({
                "lat": coords[1], "lng": coords[0],
                "label": props.get("address", {}).get("formattedAddress") or props.get("name") or query,
                "confidence": props.get("confidence", "Not provided"),
            })
    return {"candidates": candidates}


@app.get("/api/games/{slug}/leaderboard", dependencies=[Depends(require_operator)])
def api_leaderboard(slug: str) -> dict[str, Any]:
    return {"leaderboard": storage.get_leaderboard(slug, limit=10)}


@app.get("/api/games/{slug}/players", dependencies=[Depends(require_operator)])
def api_players(slug: str) -> dict[str, Any]:
    return {"players": storage.list_players(slug)}


@app.delete("/api/games/{slug}/players/{player_id}", dependencies=[Depends(require_operator)])
def api_reset_player(slug: str, player_id: str) -> dict[str, Any]:
    storage.delete_player(slug, player_id)
    return {"ok": True}


@app.delete("/api/games/{slug}/players", dependencies=[Depends(require_operator)])
def api_reset_all(slug: str) -> dict[str, Any]:
    storage.delete_all_players(slug)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("ADMIN_PORT", "8080")))
