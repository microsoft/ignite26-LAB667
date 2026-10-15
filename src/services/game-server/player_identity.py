"""Player registration, bearer authentication, and timeline state."""
from __future__ import annotations

import hashlib
import random
import re
import secrets
from typing import Any, Mapping

import storage
from quest_logic import _current_mission_index, _normalize_quest, _quest_missions

API_KEY_RE = re.compile(
    r"^litc\.([a-z0-9][a-z0-9-_]{0,62})\.([A-Za-z0-9_-]{40,})$"
)
MAX_NICKNAME_LENGTH = 40
MAX_TIMELINE_EVENTS = 100
ROUTE_REF_RE = re.compile(r"^[a-z0-9]{15}$")
AGENT42_ROUTE_REF_RE = re.compile(
    r"(?im)^recommendation code:\s*([a-z0-9]{15})\s*$"
)
AGENT42_PRIVATE_LINE_RE = re.compile(
    r"(?im)^(?:map|directions|recommendation code):[^\r\n]*(?:\r?\n|$)"
)


def parse_api_key(api_key: str) -> str | None:
    match = API_KEY_RE.fullmatch((api_key or "").strip())
    return match.group(1) if match else None


def bearer_token(headers: Mapping[str, str]) -> str | None:
    authorization = headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return None
    token = token.strip()
    return token if parse_api_key(token) else None


def public_player_ref(api_key: str) -> str:
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12].upper()
    return f"PLAYER-{digest}"


def agent42_route_ref(event: Mapping[str, Any]) -> str:
    stored = str(event.get("route_ref") or "").strip().lower()
    if ROUTE_REF_RE.fullmatch(stored):
        return stored
    match = AGENT42_ROUTE_REF_RE.search(str(event.get("detail") or ""))
    return match.group(1).lower() if match else ""


def public_agent42_advice(advice: str) -> str:
    return AGENT42_PRIVATE_LINE_RE.sub("", advice).strip()


def authenticate(api_key: str, expected_slug: str | None = None) -> tuple[str, dict[str, Any]] | None:
    slug = parse_api_key(api_key)
    if slug is None or (expected_slug is not None and slug != expected_slug):
        return None
    player = storage.get_player(slug, api_key)
    return (slug, player) if player else None


def append_timeline_event(
    player: dict[str, Any],
    event_type: str,
    title: str,
    *,
    detail: str = "",
    mission_index: int | None = None,
    transport: str = "",
    route_ref: str = "",
) -> None:
    event: dict[str, Any] = {
        "type": event_type,
        "title": title,
        "detail": detail,
        "occurred_at": storage.utcnow_iso(),
    }
    if mission_index is not None:
        event["mission_index"] = mission_index
    if transport:
        event["transport"] = transport
    if ROUTE_REF_RE.fullmatch(route_ref):
        event["route_ref"] = route_ref
    events = list(player.get("timeline") or [])
    events.append(event)
    player["timeline"] = events[-MAX_TIMELINE_EVENTS:]


def register_player(slug: str, nickname: str) -> tuple[str, dict[str, Any]]:
    name = " ".join((nickname or "").split())
    if not name:
        raise ValueError("Enter a nickname to start the game.")
    if len(name) > MAX_NICKNAME_LENGTH:
        raise ValueError(f"Nickname must be {MAX_NICKNAME_LENGTH} characters or fewer.")

    game_version, document = storage.load_published(slug)
    quests = document.get("quests") or []
    if not quests:
        raise RuntimeError("No published quests are available for this game.")
    quest = _normalize_quest(random.choice(quests))
    missions = _quest_missions(quest)
    if not missions:
        raise RuntimeError("The selected quest has no missions.")

    api_key = f"litc.{slug}.{secrets.token_urlsafe(32)}"
    player = {
        "player_ref": public_player_ref(api_key),
        "name": name,
        "quest_id": quest["id"],
        "game_version": game_version,
        "status": "registered",
        "current_mission_index": 0,
        "started_at": None,
        "completed_at": None,
        "mission_results": [],
        "answer_attempts": 0,
        "score": None,
        "created_at": storage.utcnow_iso(),
        "timeline": [],
    }
    append_timeline_event(
        player,
        "registered",
        "Player ready",
        detail=f"{name} joined {quest['name']}.",
    )
    storage.save_player(slug, api_key, player)
    return api_key, player


def player_state(slug: str, api_key: str, player: dict[str, Any] | None = None) -> dict[str, Any]:
    player = player or storage.get_player(slug, api_key)
    if player is None:
        raise KeyError("Player not found")
    quest = storage.get_quest(slug, player["quest_id"], player["game_version"]) or {}
    quest = _normalize_quest(quest) if quest else {}
    missions = _quest_missions(quest) if quest else []
    current_index = _current_mission_index(player)
    question_index = next(
        (
            index for index, mission in enumerate(missions)
            if mission.get("type") == "question"
        ),
        None,
    )
    question_unlocked = (
        question_index is not None
        and player.get("status") in {"mission", "complete"}
        and current_index >= question_index
    )
    timeline = []
    for event_index, stored_event in enumerate(player.get("timeline") or []):
        event = {
            key: value for key, value in stored_event.items()
            if key != "route_ref"
        }
        if event.get("type") == "agent42":
            event["event_index"] = event_index
            event["has_details"] = True
            event["detail"] = public_agent42_advice(str(event.get("detail") or ""))
        timeline.append(event)
    return {
        "player_id": player.get("player_ref") or public_player_ref(api_key),
        "name": player.get("name"),
        "status": player.get("status"),
        "quest_name": quest.get("name"),
        "quest_question": (
            missions[question_index].get("mission")
            if question_unlocked and question_index is not None
            else None
        ),
        "game_version": player.get("game_version"),
        "current_mission_index": current_index,
        "mission_count": len(missions),
        "started_at": player.get("started_at"),
        "completed_at": player.get("completed_at"),
        "score": player.get("score"),
        "time_taken_minutes": player.get("time_taken_minutes"),
        "timeline": timeline,
    }
