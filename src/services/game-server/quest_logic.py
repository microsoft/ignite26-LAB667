"""Pure quest-shape helpers shared by the MCP, admin, and dashboard services.

These functions have no I/O and no framework dependencies. They normalize
quest/mission/player shapes so every service interprets stored data the
same way. Keeping them in their own module avoids circular imports between
``server.py`` (MCP) and ``dashboard.py`` (read-only HTTP).
"""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _as_text(*parts: Any) -> str:
    return "\n\n".join(str(part).strip() for part in parts if str(part or "").strip())


def _elapsed_minutes(player: dict[str, Any]) -> int:
    started = _parse_iso(player["started_at"])
    completed = _parse_iso(player["completed_at"])
    return max(0, int((completed - started).total_seconds() // 60))


def _compute_score(player: dict[str, Any]) -> tuple[int, int]:
    minutes = _elapsed_minutes(player)
    attempts = int(player.get("answer_attempts", player.get("code_attempts", 0)))
    successes = len(player.get("mission_results") or [])
    failed = max(0, attempts - successes)
    score = 1000 - 50 * failed - 10 * minutes
    return max(0, score), minutes


def _normalize_answer(answer: str) -> str:
    return (answer or "").strip().lower()


def _normalize_transport_answer(answer: str) -> str:
    value = _normalize_answer(answer)
    if value in {"taxi", "driving", "rideshare", "uber", "lyft", "waymo"}:
        return "car"
    if value in {"bicycle", "cycling"}:
        return "bike"
    if value in {"walk", "pedestrian"}:
        return "walking"
    return value


def _mission_type(mission: dict[str, Any]) -> str:
    raw = str(mission.get("type") or mission.get("challenge_type") or "question").strip().lower()
    if raw == "transport":
        return "move"
    if raw in {"rag", "code", "secret_code"}:
        return "question"
    return raw


def _valid_answers(mission: dict[str, Any]) -> list[str]:
    answers = list(mission.get("valid_answers") or mission.get("valid_transports") or [])
    for key in ("answer", "secret_code"):
        value = mission.get(key)
        if value:
            answers.append(value)
    cleaned: list[str] = []
    for answer in answers:
        value = str(answer).strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _answers_match(mission: dict[str, Any], answer: str) -> bool:
    valid = _valid_answers(mission)
    if not valid:
        return bool(answer.strip())
    if _mission_type(mission) == "move":
        provided = _normalize_transport_answer(answer)
        accepted = {_normalize_transport_answer(value) for value in valid}
        return provided in accepted
    provided = _normalize_answer(answer)
    accepted = {_normalize_answer(value) for value in valid}
    return provided in accepted


def _canonical_answer(mission: dict[str, Any], answer: str) -> str:
    if _mission_type(mission) == "move":
        return _normalize_transport_answer(answer)
    return answer.strip()


def _section(value: Any, prompt_key: str = "prompt") -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {prompt_key: value}
    return {}


def _mission_address(mission: dict[str, Any], key: str) -> str:
    value = mission.get(f"{key}_address")
    if value is None:
        value = mission.get(key)
    if isinstance(value, dict):
        value = value.get("address") or value.get("location") or value.get("neighborhood")
    return str(value or "").strip()


def _normalize_mission(mission: dict[str, Any], index: int) -> dict[str, Any]:
    mission_type = _mission_type(mission)
    valid_answers = _valid_answers(mission)
    if mission_type == "move" and not valid_answers:
        valid_answers = ["car", "walking", "bike"]
    mission_text = mission.get("mission") or mission.get("question") or mission.get("prompt") or ""
    if mission_type == "move" and not mission_text:
        mission_text = "What transport will you take: car, walking, or bike?"

    normalized = {
        **mission,
        "id": mission.get("id", index + 1),
        "type": mission_type,
        "start_address": _mission_address(mission, "start"),
        "end_address": _mission_address(mission, "end"),
        "mission": mission_text,
        "arrival_prompt": mission.get("arrival_prompt") or mission.get("setup_description") or "",
        "complete_prompt": mission.get("complete_prompt") or mission.get("arrival_description") or "",
        "valid_answers": valid_answers,
    }
    normalized["movement_required"] = bool(normalized["start_address"] and normalized["end_address"])
    return normalized


def _quest_begin_location(begin: dict[str, Any], missions: list[dict[str, Any]]) -> str:
    if missions:
        first_start = missions[0].get("start_address", "")
        if first_start:
            return first_start
    return begin.get("location") or begin.get("neighborhood", "")


def _quest_end_location(end: dict[str, Any], missions: list[dict[str, Any]]) -> str:
    if missions:
        last_end = missions[-1].get("end_address", "")
        if last_end:
            return last_end
    return end.get("location") or end.get("neighborhood", "")


def _normalize_quest(quest: dict[str, Any]) -> dict[str, Any]:
    """Return the current mission-based quest shape used by quests.json."""
    begin = _section(quest.get("begin") or {})
    end = _section(quest.get("end") or {})
    missions = [_normalize_mission(mission, index) for index, mission in enumerate(quest.get("missions") or [])]
    return {
        **quest,
        "begin": {
            "location": _quest_begin_location(begin, missions),
            "prompt": begin.get("prompt") or begin.get("description", ""),
            "flavor": begin.get("flavor", ""),
        },
        "end": {
            "location": _quest_end_location(end, missions),
            "prompt": end.get("prompt") or end.get("arrival_message", "Quest complete!"),
        },
        "missions": missions,
    }


def _quest_missions(quest: dict[str, Any]) -> list[dict[str, Any]]:
    return _normalize_quest(quest).get("missions") or []


def _current_mission_index(player: dict[str, Any]) -> int:
    if "current_mission_index" in player:
        try:
            return max(0, int(player.get("current_mission_index") or 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _player_location(player: dict[str, Any], quest: dict[str, Any]) -> dict[str, Any] | None:
    """Last known story location, never an inferred live/GPS position."""
    missions = _quest_missions(quest)
    if not missions:
        return None
    current = _current_mission_index(player)
    completed = player.get("status") == "complete"
    candidates: list[tuple[dict[str, Any], str]] = []
    if not completed and current < len(missions):
        candidates.append((missions[current], "start"))
    stop = len(missions) if completed else min(current, len(missions))
    candidates.extend((mission, "end") for mission in reversed(missions[:stop]))
    for mission, endpoint in candidates:
        lat, lng = mission.get(f"{endpoint}_lat"), mission.get(f"{endpoint}_lng")
        if (
            type(lat) in (int, float) and type(lng) in (int, float)
            and math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180
        ):
            return {"lat": lat, "lng": lng, "address": mission.get(f"{endpoint}_address", "")}
    return None
