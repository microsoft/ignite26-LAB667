"""Agent42 — an A2A-enabled local transport expert for 'Lost in the City'.

Exposes an `agent_framework.Agent` over the Agent-to-Agent (A2A) protocol so
that other agents (like the workshop's player agent) can ask it for transport
advice. Uses Open-Meteo for live weather and Azure Maps for routing (driving
with real-time traffic, walking, and biking) plus static-map rendering.
"""
from __future__ import annotations

import contextvars
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
import httpx
from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    InternalError,
    TaskNotCancelableError,
)
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from azure.identity import AzureCliCredential
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from tools import get_current_weather, get_route, render_route_map

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent42")
PLAYER_API_KEY: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "agent42_player_api_key", default=None
)


def _game_server_url() -> str:
    return os.environ.get("GAME_SERVER_URL", "http://localhost:8000").rstrip("/")


async def validate_player_key(api_key: str) -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            f"{_game_server_url()}/player/auth",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    response.raise_for_status()
    return response.json()


async def record_player_event(api_key: str, summary: str) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.post(
            f"{_game_server_url()}/player/events/agent42",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"summary": summary},
        )
    response.raise_for_status()


class PlayerBearerAuthMiddleware:
    """Authenticate A2A calls while leaving the public agent card discoverable."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or str(scope.get("path", "")).startswith("/.well-known/"):
            await self.app(scope, receive, send)
            return
        authorization = Headers(scope=scope).get("authorization", "")
        scheme, separator, api_key = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not api_key.strip():
            await JSONResponse(
                {"error": "A valid player API key is required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        api_key = api_key.strip()
        try:
            await validate_player_key(api_key)
        except httpx.HTTPStatusError as exc:
            status = 401 if exc.response.status_code == 401 else 503
            log.warning("Agent42 player authentication failed with status %s", exc.response.status_code)
            await JSONResponse(
                {"error": "Player authentication failed."},
                status_code=status,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        except httpx.HTTPError:
            log.exception("Agent42 could not reach the player authentication service")
            await JSONResponse(
                {"error": "Player authentication is temporarily unavailable."},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        context_token = PLAYER_API_KEY.set(api_key)
        try:
            await self.app(scope, receive, send)
        finally:
            PLAYER_API_KEY.reset(context_token)


def _configured_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("your-") or "your-" in value:
        return None
    return value


AGENT_INSTRUCTIONS = """\
You are Agent42, a streetwise local transport expert. Other agents consult
you when their human player needs to get from one place to another in any
city in the world. Your job is to recommend the BEST single transport
option for the requested trip.

When you are asked a question:
1. Identify the origin and destination from the question.
2. Call `get_current_weather` for the origin (so you know if it's raining,
   cold, windy, etc.).
3. Call `get_route` THREE times: once with mode='car', once with
   mode='walking', and once with mode='bike'. Read these fields from each
   response:
     - distance_km
     - travel_time_seconds
     - traffic_delay_seconds (only meaningful for car)
     - no_traffic_travel_time_seconds (only meaningful for car)
4. Convert numbers for the human:
     - miles = distance_km * 0.621
     - Show distances in both kilometers and miles, kilometers first,
       each rounded to one decimal place (e.g. "2.9 km / 1.8 miles").
     - minutes = round(travel_time_seconds / 60)
     - For CAR: people don't actually drive themselves — they take a ride
       (Uber / Lyft / Bolt / Waymo). ALWAYS add 5 minutes of wait time for
       pickup. If traffic_delay_seconds > 0 OR
       (travel_time_seconds - no_traffic_travel_time_seconds) > 120, the
       roads are busy, so add 10 minutes of wait time instead of 5.
     - Report car traffic delta as: travel_time_seconds minus
       no_traffic_travel_time_seconds, rounded to whole minutes, only if
       it's at least 1 minute. Otherwise omit the "+ X minutes for traffic"
       part.

OUTPUT FORMAT (plain text, no markdown, no asterisks, no backticks):

Weather: <temperature_c>°C / <temperature_f>°F, <short condition summary>

Options:
Car: <X.X> km / <Y.Y> miles, <N> minutes + <T> minutes for traffic + <W> minutes pickup wait
Bike: <X.X> km / <Y.Y> miles, <N> minutes
Walking: <X.X> km / <Y.Y> miles, <N> minutes

Reasoning: <2-3 short sentences. Mention weather only if it affects the
choice (rain favors car, light drizzle is still fine to bike/walk, heavy
rain or wind discourages bike/walk). Mention traffic if it's significant.
Remember the car option includes the rideshare pickup wait.>

map: <url returned by render_route_map for the recommended mode>
directions: <directions_url returned by render_route_map>
recommendation: <one of: car, walking, bike>
recommendation code: <recommendation_code returned by render_route_map>

After you've decided on a recommendation, call `render_route_map(origin,
destination, mode=<recommendation>)` exactly ONCE — using the SAME mode as
your final `recommendation:` line so the drawn route matches what you told
the human to do — and put the returned `url` field on the `map:` line,
the returned `directions_url` field on the `directions:` line, and the
returned `recommendation_code` field on the `recommendation code:` line.

Rules:
- Always show both Celsius and Fahrenheit in the Weather line, using
  `temperature_c` and `temperature_f` from `get_current_weather`, for example
  "Weather: 12°C / 53.6°F, light rain". If you mention feels-like temperature,
  use both `feels_like_c` and `feels_like_f`. If temperature values are missing
  or null, say "temperature unavailable" instead of inventing numbers.
- Always include all three options even if one is obviously bad.
- If `get_route` returns `{"error": "too_far", ...}` on the FIRST call, stop
  immediately. Do not call it for other modes and do not call
  `render_route_map`. Reply with one short paragraph explaining the two
  places are too far apart (show both `straight_line_distance_km` and
  `straight_line_distance_miles`, kilometers first),
  suggest a flight / train / long-distance bus instead, and finish with
  `recommendation: none`. Skip the Options and map lines.
- If the caller restricts the choice set (e.g. "taxi, walking, or bike"),
  treat "taxi" as the car option but keep the label "Car" in the Options
  list. The final `recommendation:` line MUST use one of: car, walking, bike.
- Never invent route or weather data — always call the tools. If a tool
  errors, say so honestly in the Reasoning and recommend car as the safe
  default.
- The `recommendation:` line MUST be exactly `recommendation: <choice>` in
  lowercase, and the `recommendation code:` line MUST be the exact 15-character
  code returned by `render_route_map` (omit it only when recommendation is
  `none`)."""


def build_agent() -> Agent:
    """Build the underlying agent. Supports Azure AI Foundry or Azure OpenAI."""
    deployment = _configured_env("AZURE_AI_FOUNDRY_DEPLOYMENT")
    foundry_endpoint = _configured_env("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
    if deployment and foundry_endpoint:
        from agent_framework_foundry import FoundryChatClient  # lazy import

        client = FoundryChatClient(
            model=deployment,
            credential=AzureCliCredential(),
            project_endpoint=foundry_endpoint,
        )
    else:
        azure_endpoint = _configured_env("AZURE_OPENAI_ENDPOINT")
        api_key = _configured_env("AZURE_OPENAI_API_KEY")
        model = _configured_env("AZURE_OPENAI_DEPLOYMENT_NAME")
        if not all((azure_endpoint, api_key, model)):
            raise RuntimeError(
                "Configure either AZURE_AI_FOUNDRY_DEPLOYMENT + "
                "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT, or AZURE_OPENAI_ENDPOINT + "
                "AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT_NAME."
            )
        client = OpenAIChatClient(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            model=model,
        )

    return Agent(
        client=client,
        name="Agent42",
        instructions=AGENT_INSTRUCTIONS,
        tools=[get_current_weather, get_route, render_route_map],
    )


class AgentFrameworkExecutor(AgentExecutor):
    """Bridges incoming A2A requests to an `agent_framework.Agent`."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input() or ""
        log.info("Agent42 received: %s", query)
        # The A2A handler logs execution failures and returns protocol errors.
        result = await self._agent.run(query)
        if not result.text:
            log.error("Agent42 returned an empty response")
            raise InternalError("Agent42 returned an empty response.")
        api_key = PLAYER_API_KEY.get()
        if api_key:
            try:
                await record_player_event(api_key, result.text)
            except httpx.HTTPError:
                log.exception("Agent42 route advice could not be added to the player timeline")
        await event_queue.enqueue_event(
            new_text_message(result.text, context_id=context.context_id)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise TaskNotCancelableError("Agent42 returns messages, not cancelable tasks.")


def build_agent_card(public_url: str) -> AgentCard:
    skill = AgentSkill(
        id="transport-advice",
        name="Local transport advice",
        description=(
            "Given an origin and destination anywhere in the world, recommends "
            "the best transport option (car/taxi, walking, or bike) using live "
            "weather and real-time traffic-aware routing, and returns a static "
            "map of the chosen route."
        ),
        tags=["maps", "weather", "transport", "routing", "navigation"],
        examples=[
            "I'm in The Mission and need to get to Hayes Valley in San Francisco. Taxi, walking, or bike?",
            "Best way from Brandenburg Gate to Alexanderplatz in Berlin right now?",
            "How should I get from Shibuya Station to Tokyo Tower?",
        ],
    )
    return AgentCard(
        name="Agent42",
        version="1.0.0",
        description=(
            "Local transport expert for any city. Picks the best way to get "
            "around using real-time weather and traffic."
        ),
        supported_interfaces=[
            AgentInterface(
                url=public_url,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            ),
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        skills=[skill],
        default_input_modes=["text"],
        default_output_modes=["text"],
    )


def build_app() -> Starlette:
    host = os.environ.get("AGENT42_HOST", "0.0.0.0")
    port = int(os.environ.get("AGENT42_PORT", "8042"))
    # 0.0.0.0 is a valid bind address but not a useful URL to advertise.
    advertise_host = "localhost" if host in ("0.0.0.0", "::") else host
    public_url = os.environ.get("AGENT42_PUBLIC_URL") or f"http://{advertise_host}:{port}"

    agent = build_agent()
    executor = AgentFrameworkExecutor(agent)
    card = build_agent_card(public_url)
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await handler.aclose()

    return Starlette(
        lifespan=lifespan,
        middleware=[Middleware(PlayerBearerAuthMiddleware)],
        routes=[
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, "/", enable_v0_3_compat=True),
        ],
    )


def main() -> None:
    host = os.environ.get("AGENT42_HOST", "0.0.0.0")
    port = int(os.environ.get("AGENT42_PORT", "8042"))
    app = build_app()
    log.info("Agent42 starting on http://%s:%d (A2A card at /.well-known/agent-card.json)", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
