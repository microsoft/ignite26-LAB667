"""Multi-game MCP server for the 'Lost in the City' workshop family.

Each game is exposed as an MCP endpoint at:

    http://<host>:<port>/<slug>/mcp

The dashboard runs as a **separate service** (see ``dashboard.py``) so it
can be scaled independently and never blocks the MCP event loop with
rendering or blob fetches. Games are configured in Azure Tables (see
storage.py). The server seeds the default game if needed, then builds and
caches MCP apps lazily per slug so games added through the admin UI become
routable without a restart.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import random
import re
import uuid
from pathlib import Path
from typing import Annotated, Any, AsyncGenerator

import anyio
from anyio.abc import TaskGroup, TaskStatus
import uvicorn
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from pydantic import Field
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, get_route_path
from starlette.types import Receive, Scope, Send

import storage
from game_schedule import game_availability
from quest_logic import (
    _answers_match,
    _as_text,
    _canonical_answer,
    _compute_score,
    _current_mission_index,
    _mission_type,
    _normalize_quest,
    _quest_missions,
)

load_dotenv(override=True)

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))
ROUTE_REF_RE = re.compile(r"^[a-z0-9]{15}$")

BASE_DIR = Path(__file__).resolve().parent
ACTIVE_PLAYER_STATUSES = {"mission"}


def _instructions_for(game: dict[str, Any]) -> str:
    name = game["display_name"]
    return f"""\
You are the narrator for the workshop game '{name}'. You talk directly to
the human player, like a friendly game host. Keep the experience moving.

NON-NEGOTIABLE PRIVACY RULES
- Never reveal, hint at, print, or summarize any hidden answer for a question
    mission. The player must supply the answer.
- Never mention private route metadata to the player. Do not say code,
    token, identifier, hidden value, or anything similar. If the route helper's
    response contains private route metadata, silently use it only for the
    submit_mission_answer tool call.
- Never show raw tool JSON, field names, tool arguments, or internal labels
    to the player.

PLAYER-FACING STYLE
- Speak in plain prose only. No markdown, no bullets, no tables, no JSON.
- If the narration contains a welcome banner, show that banner exactly before
    the scene text.
- Always read the full story text from 'narration' or 'scene' before asking
    for the next player action. Do not skip or summarize arrival_prompt or
    complete_prompt story beats.
- Do not say "the server says" or describe implementation details.

SESSION FLOW
Always call begin_session first.
- If you remember a player_id, pass it to begin_session(player_id=...).
- If you do not remember one, call begin_session() and ask the player whether
    they already have a player ID. If not, ask: "What name should I put on your
    badge?" Then call register_player(name).
Never invent a player_id, name, answer, or transport choice.

MISSION FLOW
- For a question mission: read the scene, ask the mission question, wait for
    the player's answer, then call submit_mission_answer(player_id, answer).
    If rejected, simply ask them to try again. Never hint at the correct answer.
- For a move mission: read the scene and route, then ask:
    "What transport will you take: car, walking, or bike? There are agents that can help lost travellers. Just ask for HELP."
    Do not choose for the player. When the player shares route advice,
    repeat that full advice back to the player in plain prose, then ask
    for their final transport choice if it is not clear. Silently extract any
    private route reference needed for submit_mission_answer; never mention it.

TOOL FLOW
- Follow 'next_action' for tool calls, but do not recite it to the player.
- Continue with start_quest and submit_mission_answer until the quest is
    complete. If the player wants to stop, call abandon_quest.
"""


PLACEHOLDER_PLAYER_NAMES = {"<your name>", "dummy", "test"}


def _game_play_prompt_for(game: dict[str, Any]) -> str:
    return """\
You are an agent that plays the game by using the available tools.
Show story text returned by game tools in full. Keep your own extra commentary short and plain.
Do not use markdown, bullet lists, tables, or code blocks. When a specialist tool returns advice
or an answer, show it plainly before continuing.
"""


def _err(message: str) -> dict[str, Any]:
    return {"status": "error", "message": message}


def _welcome_banner(display_name: str) -> str:
    title = display_name[:30]
    return f"""\
+--------------------------------+
| Welcome to:                    |
| {title:<30} |
+--------------------------------+"""


def _with_welcome_banner(display_name: str, text: str) -> str:
    return _as_text(_welcome_banner(display_name), text)


def _abandoned_msg() -> dict[str, Any]:
    return _err("You gave up on this quest. Register again for a fresh start.")


# Quest-shape helpers (_normalize_quest, _current_mission_index, etc.) live in
# ``quest_logic.py`` so the dashboard service can import them without pulling
# in the MCP server module.


def _mission_payload(player: dict[str, Any], quest: dict[str, Any]) -> dict[str, Any]:
    quest = _normalize_quest(quest)
    missions = quest.get("missions") or []
    index = _current_mission_index(player)
    if not missions or index >= len(missions):
        return {
            "narration": "This quest has no remaining missions. Ask the facilitator.",
            "next_action": "Call get_player_status(player_id) for details.",
        }

    mission = missions[index]
    mission_type = _mission_type(mission)
    ask_user = "Read the full scene to the user, then ask them to complete the current mission."
    if mission.get("mission"):
        ask_user = "Read the full scene to the user, then ask the mission question."
    next_action = "Ask the human for their answer (do NOT guess or hint), then call submit_mission_answer(player_id, answer)."
    if mission_type == "move":
        start_addr = mission.get("start_address", "")
        end_addr = mission.get("end_address", "")
        leg = (
            f"from {start_addr} to {end_addr}"
            if start_addr and end_addr
            else "for this leg"
        )
        ask_user = (
            f"Read the full scene to the user. Then tell the human: 'You need to get {leg}. What transport will you take - "
            "car, walking, or bike? There are agents that can help lost travellers. Just ask for HELP.' Then wait. DO NOT mention "
            "private route metadata to the human."
        )
        next_action = (
            "Do not choose transport yourself. Wait for the human to share route advice. "
            "Repeat the full route advice back to the human in plain prose. Silently "
            "extract any private routing metadata from the advice. Never mention "
            "that metadata to the human. Only when the human gives you their final "
            "transport choice, call submit_mission_answer with that choice and the "
            "private metadata value."
        )

    payload: dict[str, Any] = {
        "current_mission_index": index,
        "mission_number": index + 1,
        "mission_count": len(missions),
        "mission_id": mission.get("id", index + 1),
        "mission_type": mission_type,
        "start_address": mission.get("start_address", ""),
        "end_address": mission.get("end_address", ""),
        "movement_required": bool(mission.get("movement_required")),
        "mission": mission.get("mission", ""),
        "arrival_prompt": mission.get("arrival_prompt", ""),
        "scene": _as_text(mission.get("arrival_prompt", ""), mission.get("mission", "")),
        "narration": _as_text(mission.get("arrival_prompt", ""), mission.get("mission", "")),
        "ask_user": ask_user,
        "next_action": next_action,
    }
    # Only move missions expose their valid answers (public transport
    # categories). Question-mission answers are secret and must never leave
    # the server.
    if mission_type == "move":
        payload["transport_options"] = ["car", "walking", "bike"]
    return payload


def _resume_scene(player: dict[str, Any], quest: dict[str, Any], display_name: str) -> dict[str, Any]:
    status = player.get("status")
    if status == "registered":
        quest = _normalize_quest(quest)
        return {
            "narration": (
                f"Welcome back, {player.get('name')}. You registered for "
                f"'{quest.get('name')}' but never set off. The city is still waiting."
            ),
            "ask_user": "Ask the user: 'Ready to begin your quest? Say START.'",
            "next_action": "When the human says ready, call start_quest(player_id).",
        }
    if status in ACTIVE_PLAYER_STATUSES:
        payload = _mission_payload(player, quest)
        scene = _as_text(
            f"Welcome back, {player.get('name')}. Your quest is still in progress.",
            payload.get("narration", ""),
        )
        payload["scene"] = _with_welcome_banner(display_name, scene)
        payload["narration"] = _with_welcome_banner(display_name, scene)
        return {
            **payload,
        }
    if status == "complete":
        return {
            "narration": (
                f"{player.get('name')} already finished. Score: "
                f"{player.get('score')}, time: {player.get('time_taken_minutes')} min."
            ),
            "ask_user": "Ask the user if they want to see the leaderboard.",
            "next_action": "If yes, call get_leaderboard().",
        }
    if status == "abandoned":
        return {
            "narration": f"{player.get('name')} gave up earlier. That player_id is retired.",
            "ask_user": "Ask the user if they want to register again as a new player.",
            "next_action": "If yes, ask for a name and call register_player(name).",
        }
    return {
        "narration": "Your quest is in an unknown state. Ask the facilitator.",
        "next_action": "Call get_player_status(player_id) for details.",
    }


def build_mcp_for_game(game: dict[str, Any]) -> MCPServer:
    """Build an MCP server whose tools are bound to the given game slug."""
    slug = game["slug"]
    display_name = game["display_name"]

    def play_window_error() -> dict[str, Any] | None:
        current = storage.get_game(slug)
        if current is None:
            return _err("This game no longer exists.")
        availability = game_availability(current)
        if availability["state"] == "open":
            return None
        return {
            **_err(availability["message"]),
            "availability": availability["state"],
            "narration": availability["message"],
            "next_action": "Tell the player the game is not open. Do not attempt gameplay until the play window opens.",
        }

    mcp = MCPServer(
        f"game-{slug}",
        instructions=_instructions_for(game),
    )

    @mcp.prompt(
        name="game_play_prompt",
        description="Prompt instructions for the external game play agent.",
    )
    def game_play_prompt() -> str:
        """Return the prompt for the external game play agent."""
        return _game_play_prompt_for(game)

    @mcp.tool()
    def begin_session(
        player_id: Annotated[str, Field(default="", description="OPTIONAL. If the agent already remembers a player_id, pass it here.")] = "",
    ) -> dict[str, Any]:
        """Entry point for every new conversation. Always call this first."""
        if error := play_window_error():
            return error
        pid = (player_id or "").strip()
        if pid:
            player = storage.get_player(slug, pid)
            if player:
                status = player.get("status")
                pname = player.get("name")
                if status == "registered":
                    action = "START"
                    narration = f"We found a badge for {pname} (player_id {pid}). The quest is ready but hasn't begun yet."
                    next_action = "Ask the user if they want to START. If yes, call start_quest(player_id)."
                elif status in ACTIVE_PLAYER_STATUSES:
                    action = "CONTINUE"
                    narration = f"Welcome back, {pname}. We found your in-progress quest (player_id {pid})."
                    next_action = "Ask the user if they want to CONTINUE. If yes, call resume_player(player_id)."
                elif status == "complete":
                    action = "NEW"
                    narration = f"{pname} already finished. That player_id ({pid}) is retired."
                    next_action = "Ask the user for a name and call register_player(name)."
                else:
                    action = "NEW"
                    narration = f"That player_id ({pid}) was abandoned. Register again for a fresh start."
                    next_action = "Ask the user for a name and call register_player(name)."
                return {
                    "status": "known_player",
                    "game": display_name,
                    "player_id": pid,
                    "player_name": pname,
                    "current_status": status,
                    "action": action,
                    "narration": narration,
                    "ask_user": f"Tell the user we found player_id {pid} for {pname}. Ask if they want to {action}.",
                    "next_action": next_action,
                }
            return {
                "status": "unknown_player_id",
                "game": display_name,
                "player_id": pid,
                "action": "NEW",
                "narration": f"The player_id {pid} is not on file for '{display_name}'. It may be stale.",
                "ask_user": "Tell the user the stored player_id was not found. Ask for a name to register a new player.",
                "next_action": "Call register_player(name) with the name the user provides.",
            }

        return {
            "status": "awaiting_identity",
            "game": display_name,
            "narration": f"Welcome to '{display_name}'. Before we drop you into the city, we need to know who we're talking to.",
            "ask_user": (
                "Ask the human user, in order: 1) Do you already have a player_id from a previous session? "
                "If YES, ask them to paste it and call resume_player(player_id). If NO, ask what name to put "
                "on their badge and call register_player(name)."
            ),
            "options": [
                {"choice": "resume", "next_tool": "resume_player", "needs": ["player_id from the user"]},
                {"choice": "new", "next_tool": "register_player", "needs": ["name from the user"]},
            ],
            "next_action": "Do NOT call register_player or resume_player until the human user has answered.",
        }

    @mcp.tool()
    def resume_player(
        player_id: Annotated[str, Field(description="An existing player_id. REQUIRED. ASK the user for it.", min_length=1)],
    ) -> dict[str, Any]:
        """Resume an existing player's session for this game."""
        if error := play_window_error():
            return error
        player = storage.get_player(slug, player_id)
        if not player:
            return {
                "status": "unknown_player",
                "message": "We don't have a badge with that id. Double-check the player_id, or register as a new player.",
                "ask_user": "Ask the user to re-check their player_id, or to register a new one.",
                "next_action": "If the user cannot find their player_id, call register_player(name) with a name they provide.",
            }
        quest = storage.get_quest(slug, player.get("quest_id"), player["game_version"]) or {}
        scene = _resume_scene(player, quest, display_name)
        return {
            "status": "resumed",
            "game": display_name,
            "player_id": player_id,
            "player_name": player.get("name"),
            "quest_id": player.get("quest_id"),
            "quest_name": quest.get("name"),
            "current_status": player.get("status"),
            **scene,
        }

    @mcp.tool()
    def register_player(
        name: Annotated[str, Field(description="The human player's display name. REQUIRED. ASK the user.", min_length=1)],
    ) -> dict[str, Any]:
        """Register a new player and get the opening scene of their quest."""
        if error := play_window_error():
            return error
        pname = (name or "").strip()
        if not pname:
            return _err("We need a name to put on your badge. Ask the user what name to use, then try again.")
        if pname.casefold() in PLACEHOLDER_PLAYER_NAMES:
            return _err(f"Hi, please update {pname} to your realname and try again.")

        game_version, document = storage.load_published(slug)
        quests = document.get("quests", [])
        if not quests:
            return _err("No quests are configured for this game. Ask the facilitator.")

        quest = _normalize_quest(random.choice(quests))
        missions = _quest_missions(quest)
        if not missions:
            return _err("This quest has no missions configured. Ask the facilitator.")

        player_id = f"PLR-{uuid.uuid4().hex[:6].upper()}"
        storage.save_player(slug, player_id, {
            "name": pname,
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
        })

        begin = quest["begin"]
        scene = _as_text(begin.get("prompt", ""), begin.get("flavor", ""))
        return {
            "player_id": player_id,
            "game": display_name,
            "quest_id": quest["id"],
            "quest_name": quest["name"],
            "begin_location": begin.get("location", ""),
            "begin_prompt": begin.get("prompt", ""),
            "begin_flavor": begin.get("flavor", ""),
            "mission_count": len(missions),
            "scene": scene,
            "narration": (
                f"Welcome, {pname}. Your player ID is {player_id} - keep it safe. "
                f"Your quest is '{quest['name']}'. {scene}"
            ).strip(),
            "message": f"Your quest has begun. Your player_id is {player_id}. Say START when you are ready.",
            "ask_user": "Read the scene to the user. Then ask: 'Ready to begin? Say START when you want to go.'",
            "next_action": "Store player_id in memory, then when the human says they are ready, call start_quest(player_id).",
        }

    @mcp.tool()
    def start_quest(
        player_id: Annotated[str, Field(description="The player_id returned by register_player. REQUIRED.", min_length=1)],
    ) -> dict[str, Any]:
        """Begin the quest for a registered player."""
        if error := play_window_error():
            return error
        player = storage.get_player(slug, player_id)
        if not player:
            return _err("Your player badge doesn't seem to exist. Did you register?")
        if player["status"] == "complete":
            return _err("You've already finished. Enjoy the conference.")
        if player["status"] == "abandoned":
            return _abandoned_msg()
        quest = storage.get_quest(slug, player["quest_id"], player["game_version"])
        if not quest:
            return _err("Your quest appears to have vanished. Ask the facilitator.")
        quest = _normalize_quest(quest)
        if not _quest_missions(quest):
            return _err("This quest has no missions configured. Ask the facilitator.")

        first_start = not player.get("started_at")

        def mutate(p: dict[str, Any]):
            if not p.get("started_at"):
                p["started_at"] = storage.utcnow_iso()
            p["status"] = "mission"
            p["current_mission_index"] = _current_mission_index(p)
            return None
        storage.update_player(slug, player_id, mutate)
        player = storage.get_player(slug, player_id) or player

        payload = _mission_payload(player, quest)
        if first_start:
            begin = quest["begin"]
            opening_scene = _as_text(begin.get("prompt", ""), begin.get("flavor", ""))
            scene = _as_text(opening_scene, payload.get("scene", ""))
        else:
            scene = payload.get("scene", "")

        payload["scene"] = _with_welcome_banner(display_name, scene)
        payload["narration"] = _with_welcome_banner(display_name, scene)
        return {"status": "quest_started", **payload}

    @mcp.tool()
    def submit_mission_answer(
        player_id: Annotated[str, Field(description="The player_id. REQUIRED.", min_length=1)],
        answer: Annotated[str, Field(description="Answer for the current mission. For move missions, use the player's transport choice.", min_length=1)],
        route_ref: Annotated[str, Field(description="Private route reference. Never mention this value to the player.", default="")] = "",
    ) -> dict[str, Any]:
        """Submit the answer for the current mission and advance the quest."""
        if error := play_window_error():
            return error
        player = storage.get_player(slug, player_id)
        if not player:
            return _err("Your player badge doesn't seem to exist.")
        if player["status"] == "complete":
            return _err("You've already finished.")
        if player["status"] == "abandoned":
            return _abandoned_msg()
        if player["status"] == "registered":
            return _err("You need to start the quest first.")
        if player["status"] not in ACTIVE_PLAYER_STATUSES:
            return _err("You can't do that yet.")
        quest = storage.get_quest(slug, player["quest_id"], player["game_version"])
        if not quest:
            return _err("Your quest appears to have vanished.")
        quest = _normalize_quest(quest)
        missions = _quest_missions(quest)
        index = _current_mission_index(player)
        if index >= len(missions):
            return _err("This quest has no current mission. Ask the facilitator.")

        mission = missions[index]
        mission_type = _mission_type(mission)
        provided_answer = _canonical_answer(mission, answer)
        provided_route_ref = (route_ref or "").strip().lower()

        def bump(p: dict[str, Any]):
            p["answer_attempts"] = int(p.get("answer_attempts", p.get("code_attempts", 0))) + 1
            return None
        storage.update_player(slug, player_id, bump)

        code_error = ""
        if mission_type == "move":
            if not provided_route_ref:
                code_error = "The route advice was incomplete. Ask for help again."
            elif not ROUTE_REF_RE.match(provided_route_ref):
                code_error = "The route advice could not be verified. Ask for help again."

        if code_error or not _answers_match(mission, answer):
            rejected: dict[str, Any] = {
                "status": "mission_answer_rejected",
                "message": code_error or "That answer does not complete the mission.",
                "narration": "Not quite. Try again.",
                "mission_type": mission_type,
                "ask_user": "Ask the user to try the current mission again. Do not reveal or hint at hidden answers or internal values.",
                "next_action": "Call submit_mission_answer again with the user's corrected answer. For move missions, silently use the private metadata from the route advice.",
            }
            # Only expose transport categories for move missions; never echo back a
            # question mission's secret answers.
            if mission_type == "move":
                rejected["transport_options"] = ["car", "walking", "bike"]
            return rejected

        def record_success(p: dict[str, Any]):
            results = list(p.get("mission_results") or [])
            results.append({
                "mission_index": index,
                "mission_id": mission.get("id", index + 1),
                "mission_type": mission_type,
                "answer": provided_answer,
                "route_ref": provided_route_ref if mission_type == "move" else "",
                "completed_at": storage.utcnow_iso(),
            })
            p["mission_results"] = results
            return None
        storage.update_player(slug, player_id, record_success)

        complete_prompt = str(mission.get("complete_prompt", "")).strip()
        next_index = index + 1
        if next_index < len(missions):
            def advance(p: dict[str, Any]):
                p["status"] = "mission"
                p["current_mission_index"] = next_index
                return None
            storage.update_player(slug, player_id, advance)
            player = storage.get_player(slug, player_id) or player
            next_payload = _mission_payload(player, quest)
            return {
                "status": "mission_complete",
                "completed_mission_index": index,
                "completed_mission_id": mission.get("id", index + 1),
                "answer": provided_answer,
                "complete_prompt": complete_prompt,
                "scene": _as_text(complete_prompt, next_payload.get("scene", "")),
                "narration": _as_text(complete_prompt, next_payload.get("narration", "")),
                "next_mission": next_payload,
                "ask_user": (
                    "Read the full narration to the user, including the completed mission story "
                    "and the next scene. Then ask for the next player action."
                ),
                "next_action": next_payload.get("next_action", ""),
            }

        end_prompt = str((quest.get("end") or {}).get("prompt") or "Quest complete!").strip()

        def finish(p: dict[str, Any]):
            p["completed_at"] = storage.utcnow_iso()
            p["status"] = "complete"
            score, minutes = _compute_score(p)
            p["score"] = score
            p["time_taken_minutes"] = minutes
            return {"score": score, "minutes": minutes}
        result = storage.update_player(slug, player_id, finish)

        board = storage.get_leaderboard(slug, limit=1000)
        position = next((i + 1 for i, entry in enumerate(board) if entry["player_id"] == player_id), None)
        return {
            "status": "quest_complete",
            "completed_mission_index": index,
            "completed_mission_id": mission.get("id", index + 1),
            "answer": provided_answer,
            "complete_prompt": complete_prompt,
            "end_prompt": end_prompt,
            "arrival_message": end_prompt,
            "scene": _as_text(complete_prompt, end_prompt),
            "narration": (
                f"{_as_text(complete_prompt, end_prompt)} "
                f"Score: {result['score']} - Time: {result['minutes']} min - "
                f"Leaderboard position: #{position}."
            ).strip(),
            "score": result["score"],
            "time_taken_minutes": result["minutes"],
            "leaderboard_position": position,
            "ask_user": "Read the full final narration to the user, then read out their score and position.",
            "next_action": "The quest is done. You may call get_leaderboard() if the user wants to see the standings.",
        }

    @mcp.tool()
    def abandon_quest(
        player_id: Annotated[str, Field(description="The player_id. REQUIRED.", min_length=1)],
        reason: Annotated[str, Field(description="Optional reason.", default="")] = "",
    ) -> dict[str, Any]:
        """Give up and stop the current quest."""
        player = storage.get_player(slug, player_id)
        if not player:
            return _err("Your player badge doesn't seem to exist.")
        if player["status"] == "complete":
            return _err("You've already finished.")
        if player["status"] == "abandoned":
            return {"status": "already_abandoned", "message": "You already gave up on this one."}

        def mutate(p: dict[str, Any]):
            p["status"] = "abandoned"
            p["abandoned_at"] = storage.utcnow_iso()
            if reason:
                p["abandon_reason"] = reason
            return None
        storage.update_player(slug, player_id, mutate)
        return {
            "status": "quest_abandoned",
            "message": "You sit down on the curb and give up. The city wins this round.",
            "hint": "Call register_player again to start a new quest.",
        }

    @mcp.tool()
    def get_leaderboard() -> dict[str, Any]:
        """Return the top 10 players by score for this game."""
        top = storage.get_leaderboard(slug, limit=10)
        return {"game": display_name, "leaderboard": top, "count": len(top)}

    @mcp.tool()
    def get_player_status(
        player_id: Annotated[str, Field(description="The player_id to inspect.", min_length=1)],
    ) -> dict[str, Any]:
        """Return the current state of a player."""
        player = storage.get_player(slug, player_id)
        if not player:
            return _err("Your player badge doesn't seem to exist.")
        quest = storage.get_quest(slug, player["quest_id"], player["game_version"]) or {}
        quest = _normalize_quest(quest) if quest else {}
        attempts = int(player.get("answer_attempts", player.get("code_attempts", 0)))
        successes = len(player.get("mission_results") or [])
        # Scrub secrets out of mission_results: never echo back the private
        # route reference or the literal answer of a question mission.
        safe_results = [
            {
                "mission_index": int(result.get("mission_index", 0) or 0),
                "mission_id": result.get("mission_id"),
                "mission_type": result.get("mission_type"),
                "completed_at": result.get("completed_at"),
            }
            for result in (player.get("mission_results") or [])
        ]
        return {
            "game": display_name,
            "player_id": player_id,
            "name": player.get("name"),
            "quest_id": player.get("quest_id"),
            "quest_name": quest.get("name"),
            "status": player.get("status"),
            "current_mission_index": _current_mission_index(player),
            "current_mission": _mission_payload(player, quest) if player.get("status") in ACTIVE_PLAYER_STATUSES else None,
            "started_at": player.get("started_at"),
            "completed_at": player.get("completed_at"),
            "mission_results": safe_results,
            "answer_attempts": attempts,
            "failed_attempts": max(0, attempts - successes),
            "score": player.get("score"),
        }

    return mcp


class _CachedGameApp:
    def __init__(self, game: dict[str, Any], app: Starlette) -> None:
        self.game = dict(game)
        self.app = app
        self._stop = asyncio.Event()
        self._closed = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._requests = 0

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        # AnyIO cancellation scopes must open and close in the same owning task.
        try:
            async with self.app.router.lifespan_context(self.app):
                task_status.started()
                await self._stop.wait()
                await self._idle.wait()
        finally:
            self._closed.set()

    def acquire(self) -> None:
        self._requests += 1
        self._idle.clear()

    def release(self) -> None:
        self._requests -= 1
        if not self._requests:
            self._idle.set()

    async def close(self) -> None:
        self._stop.set()
        await self._closed.wait()


class DynamicGameMCPDispatcher:
    """ASGI dispatcher that resolves /<slug>/... against games in storage."""

    def __init__(self) -> None:
        self._cache: dict[str, _CachedGameApp] = {}
        self._lock = asyncio.Lock()
        self._tasks: TaskGroup | None = None

    async def startup(self, tasks: TaskGroup) -> None:
        self._tasks = tasks

    async def shutdown(self) -> None:
        self._tasks = None
        async with self._lock:
            cached_apps = list(self._cache.values())
            self._cache.clear()
        for cached in reversed(cached_apps):
            await cached.close()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await JSONResponse({"error": "Not found"}, status_code=404)(scope, receive, send)
            return

        slug, child_path = self._split_path(get_route_path(scope))
        if not slug:
            await JSONResponse({"error": "Not found"}, status_code=404)(scope, receive, send)
            return

        game = storage.get_game(slug)
        if not game:
            await self._forget_app(slug)
            await JSONResponse({"error": f"Game '{slug}' not found"}, status_code=404)(scope, receive, send)
            return

        async with self._app_for_game(game) as app:
            child_scope = dict(scope)
            child_scope["path"] = child_path
            child_scope["root_path"] = self._join_root_path(scope.get("root_path", ""), slug)
            if "raw_path" in child_scope:
                child_scope["raw_path"] = child_path.encode("ascii", errors="ignore")
            await app(child_scope, receive, send)

    @staticmethod
    def _split_path(path: str) -> tuple[str | None, str]:
        trimmed = path.lstrip("/")
        if not trimmed:
            return None, "/"
        slug, _, remainder = trimmed.partition("/")
        return slug, f"/{remainder}" if remainder else "/"

    @staticmethod
    def _join_root_path(root_path: str, slug: str) -> str:
        return f"{root_path.rstrip('/')}/{slug}"

    @staticmethod
    def _same_game(cached: _CachedGameApp, game: dict[str, Any]) -> bool:
        return (
            cached.game.get("display_name") == game.get("display_name")
            and cached.game.get("created_at") == game.get("created_at")
        )

    @contextlib.asynccontextmanager
    async def _app_for_game(self, game: dict[str, Any]) -> AsyncGenerator[Starlette, None]:
        slug = game["slug"]
        old_cached = None
        async with self._lock:
            cached = self._cache.get(slug)
            if cached is None or not self._same_game(cached, game):
                old_cached = cached
                cached = await self._build_cached_app(game)
                self._cache[slug] = cached
            cached.acquire()

        try:
            if old_cached is not None:
                await old_cached.close()
            yield cached.app
        finally:
            cached.release()

    async def _build_cached_app(self, game: dict[str, Any]) -> _CachedGameApp:
        app = build_mcp_for_game(game).streamable_http_app(
            host=MCP_HOST, stateless_http=True, json_response=False,
        )
        if self._tasks is None:
            raise RuntimeError("The MCP dispatcher lifespan is not running")
        cached = _CachedGameApp(game, app)
        await self._tasks.start(cached.run)
        return cached

    async def _forget_app(self, slug: str) -> None:
        async with self._lock:
            cached = self._cache.pop(slug, None)
        if cached is not None:
            await cached.close()


def build_app() -> Starlette:
    """Build a Starlette app that dispatches /<slug>/mcp and dashboards dynamically."""
    storage.init_storage()
    dispatcher = DynamicGameMCPDispatcher()

    async def index(_request):
        games = storage.list_games()
        return JSONResponse({
            "service": "lost-in-the-city game server",
            "games": [
                {
                    "slug": game["slug"],
                    "display_name": game["display_name"],
                    "mcp_url": f"/{game['slug']}/mcp",
                }
                for game in games
            ],
        })

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with anyio.create_task_group() as tasks:
            await dispatcher.startup(tasks)
            try:
                yield
            finally:
                await dispatcher.shutdown()

    return Starlette(
        routes=[
            Route("/", endpoint=index),
            Mount("/", app=dispatcher),
        ],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    app = build_app()
    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT)
