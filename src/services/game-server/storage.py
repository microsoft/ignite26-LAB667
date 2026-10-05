"""Azure Tables-backed storage for the multi-game 'Lost in the City' workshop.

Tables (auto-created on startup):
  games    PK="games"  RK=slug      {event_name, display_name, city, created_at}
  quests   PK=slug     RK="quests"  {payload, draft_payload, version, revision}
  quests   PK=slug     RK="vN"      {payload: immutable published story}
  players  PK=slug     RK=player_id {data: JSON-encoded player state}

The default game is seeded from quests.json on first start if no games exist.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableEntity, TableServiceClient, UpdateMode
from dotenv import load_dotenv
from quest_validation import validate_document
from game_schedule import GameSchedule

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
SEED_QUESTS_FILE = BASE_DIR / "quests.json"
DEFAULT_SLUG = os.environ.get("DEFAULT_GAME_SLUG", "san-francisco")
DEFAULT_DISPLAY = os.environ.get("DEFAULT_GAME_NAME", "Lost in San Francisco")
DEFAULT_EVENT_NAME = os.environ.get("DEFAULT_EVENT_NAME", "Open Hack")

GAMES_TABLE = "games"
QUESTS_TABLE = "quests"
PLAYERS_TABLE = "players"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,62}$")

_service: TableServiceClient | None = None


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _conn() -> str:
    cs = os.environ.get("AZURE_TABLES_CONNECTION_STRING")
    if not cs:
        raise RuntimeError(
            "AZURE_TABLES_CONNECTION_STRING is not set. Point it at your "
            "Azure Storage account (or 'UseDevelopmentStorage=true' for Azurite)."
        )
    return cs


def _svc() -> TableServiceClient:
    global _service
    if _service is None:
        _service = TableServiceClient.from_connection_string(_conn())
    return _service


def _validate_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError(
            "Slug must be lowercase alphanumeric (with optional - or _), 1-63 chars, starting alphanumeric."
        )
    return slug


def _default_city(display_name: str) -> str:
    prefix = "lost in "
    return display_name[len(prefix):].strip() if display_name.lower().startswith(prefix) else display_name


def init_storage() -> None:
    """Create tables if missing and seed the default game if none exist."""
    svc = _svc()
    for name in (GAMES_TABLE, QUESTS_TABLE, PLAYERS_TABLE):
        try:
            svc.create_table(name)
        except ResourceExistsError:
            pass
    if not list_games():
        try:
            create_game(
                DEFAULT_SLUG,
                DEFAULT_DISPLAY,
                quests=load_seed_quests(),
                event_name=DEFAULT_EVENT_NAME,
            )
        except ResourceExistsError:
            # Another service may seed the same game during coordinated startup.
            if get_game(DEFAULT_SLUG) is None:
                raise


def load_seed_quests() -> dict[str, Any]:
    """Load the local quests.json seed file."""
    if SEED_QUESTS_FILE.exists():
        return json.loads(SEED_QUESTS_FILE.read_text(encoding="utf-8"))
    return {"quests": []}


def import_seed_quests(slug: str) -> dict[str, Any]:
    """Import the local seed into the draft, without affecting live players."""
    slug = _validate_slug(slug)
    data = load_seed_quests()
    save_quests(slug, data)
    return data


# ---------- games ----------

def list_games() -> list[dict[str, Any]]:
    t = _svc().get_table_client(GAMES_TABLE)
    out: list[dict[str, Any]] = []
    for e in t.query_entities("PartitionKey eq 'games'"):
        out.append(_game_info(e))
    out.sort(key=lambda g: g["slug"])
    return out


def get_game(slug: str) -> dict[str, Any] | None:
    try:
        e = _svc().get_table_client(GAMES_TABLE).get_entity("games", slug)
    except ResourceNotFoundError:
        return None
    return _game_info(e)


def _game_info(e: TableEntity) -> dict[str, Any]:
    display_name = e.get("display_name", e["RowKey"])
    return {
        "slug": e["RowKey"],
        "event_name": e.get("event_name", ""),
        "display_name": display_name,
        "city": e.get("city") or _default_city(display_name),
        "created_at": e.get("created_at"),
        "starts_at": e.get("starts_at", ""),
        "ends_at": e.get("ends_at", ""),
        "timezone": e.get("timezone", "UTC"),
        "player_mode": e.get("player_mode", "guided"),
        "schedule_revision": int(e.get("schedule_revision", 0)),
    }


def create_game(
    slug: str, display_name: str, quests: dict[str, Any] | None = None,
    *, event_name: str = "", city: str | None = None, schedule: GameSchedule | None = None,
) -> dict[str, Any]:
    slug = _validate_slug(slug)
    display_name = (display_name or slug).strip() or slug
    event_name = (event_name or "").strip()
    city = (city or _default_city(display_name)).strip()
    if not city:
        raise ValueError("City is required.")
    document = quests if quests is not None else {"city": city, "quests": []}
    if quests is not None:
        errors = validate_document(quests, publish=True)["errors"]
        if errors:
            raise ValueError("\n".join(errors))
        document_city = quests.get("city")
        if isinstance(document_city, str) and document_city.strip():
            city = document_city.strip()
    entity = TableEntity({
        "PartitionKey": "games",
        "RowKey": slug,
        "event_name": event_name,
        "display_name": display_name,
        "city": city,
        "created_at": utcnow_iso(),
        **(schedule or GameSchedule()).storage_fields(),
        "schedule_revision": 1,
    })
    _svc().get_table_client(GAMES_TABLE).create_entity(entity)
    payload = json.dumps(document, ensure_ascii=False)
    _svc().get_table_client(QUESTS_TABLE).create_entity({
        "PartitionKey": slug, "RowKey": "quests",
        "payload": payload,
        "draft_payload": payload, "version": 0, "revision": 1,
        "updated_at": utcnow_iso(),
    })
    if quests is not None:
        publish_draft(slug, 1)
    return _game_info(entity)


def save_schedule(
    slug: str,
    schedule: GameSchedule,
    revision: int,
    *,
    display_name: str | None = None,
    event_name: str | None = None,
) -> dict[str, Any]:
    table = _svc().get_table_client(GAMES_TABLE)
    entity = table.get_entity("games", _validate_slug(slug))
    if int(entity.get("schedule_revision", 0)) != revision:
        raise ContentConflict("The schedule changed. Reload before saving.")
    entity.update(schedule.storage_fields())
    if display_name is not None:
        normalized_name = display_name.strip()
        if not normalized_name:
            raise ValueError("Challenge name is required.")
        entity["display_name"] = normalized_name
    if event_name is not None:
        normalized_event = event_name.strip()
        if not normalized_event:
            raise ValueError("Event name is required.")
        entity["event_name"] = normalized_event
    entity["schedule_revision"] = revision + 1
    try:
        table.update_entity(
            entity, mode=UpdateMode.REPLACE, etag=entity.metadata["etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    except HttpResponseError as exc:
        if exc.status_code != 412:
            raise
        raise ContentConflict("The schedule changed. Reload before saving.") from exc
    return _game_info(entity)


def delete_game(slug: str) -> None:
    slug = _validate_slug(slug)
    g = _svc().get_table_client(GAMES_TABLE)
    try:
        g.delete_entity("games", slug)
    except ResourceNotFoundError:
        pass
    q = _svc().get_table_client(QUESTS_TABLE)
    for entity in q.query_entities(f"PartitionKey eq '{slug}'"):
        q.delete_entity(slug, entity["RowKey"])
    delete_all_players(slug)


# ---------- quests ----------

class ContentConflict(ValueError):
    """Another operator modified the draft; never silently overwrite it."""


class VersionDeletionError(ValueError):
    """A published version cannot be safely deleted."""


def _content_state(slug: str) -> TableEntity:
    slug = _validate_slug(slug)
    table = _svc().get_table_client(QUESTS_TABLE)
    for _ in range(4):
        state = table.get_entity(slug, "quests")
        if "draft_payload" in state:
            return state
        # Preserve the exact pre-versioning story for every existing player.
        updated = dict(state)
        updated.update(draft_payload=state["payload"], version=1, revision=1, updated_at=utcnow_iso())
        try:
            table.submit_transaction([
                ("create", {
                    "PartitionKey": slug, "RowKey": "v1",
                    "payload": state["payload"], "version": 1,
                    "published_at": utcnow_iso(),
                }),
                ("update", updated, {"mode": UpdateMode.REPLACE, "etag": state.metadata["etag"],
                                     "match_condition": MatchConditions.IfNotModified}),
            ])
        except HttpResponseError as exc:
            if exc.status_code not in (409, 412):
                raise
        else:
            return table.get_entity(slug, "quests")
    raise ContentConflict("Game content changed during migration. Please reload.")


def load_published(slug: str) -> tuple[int, dict[str, Any]]:
    state = _content_state(slug)
    return int(state["version"]), json.loads(state["payload"])


def load_quests(slug: str, version: int | None = None) -> dict[str, Any]:
    if version is None:
        return load_published(slug)[1]
    _content_state(slug)
    entity = _svc().get_table_client(QUESTS_TABLE).get_entity(slug, f"v{version}")
    return json.loads(entity["payload"])


def list_versions(slug: str) -> list[dict[str, Any]]:
    _content_state(slug)
    entities = _svc().get_table_client(QUESTS_TABLE).query_entities(f"PartitionKey eq '{_validate_slug(slug)}'")
    return sorted([
        {"version": int(e["version"]), "published_at": e["published_at"]}
        for e in entities if str(e["RowKey"]).startswith("v")
    ], key=lambda item: item["version"], reverse=True)


def delete_version(slug: str, version: int) -> None:
    state = _content_state(slug)
    if int(state["version"]) == version:
        raise VersionDeletionError("The current published version cannot be deleted.")
    players = [
        player for player in list_players(slug).values()
        if int(player.get("game_version", 1)) == version
    ]
    if players:
        noun = "player is" if len(players) == 1 else "players are"
        raise VersionDeletionError(
            f"Version {version} cannot be deleted because {len(players)} {noun} still assigned to it. "
            "Reset those players first."
        )
    try:
        _svc().get_table_client(QUESTS_TABLE).delete_entity(_validate_slug(slug), f"v{version}")
    except ResourceNotFoundError as exc:
        raise KeyError(f"Version {version} does not exist.") from exc


def load_draft(slug: str) -> dict[str, Any]:
    state = _content_state(slug)
    document = json.loads(state["draft_payload"])
    return {
        "document": document, "revision": int(state["revision"]),
        "published_version": int(state["version"]),
        "dirty": json.loads(state["payload"]) != document or not state["version"],
        "updated_at": state.get("updated_at"),
        "versions": list_versions(slug),
        **validate_document(document, publish=True),
    }


def save_draft(slug: str, document: dict[str, Any], revision: int) -> dict[str, Any]:
    errors = validate_document(document)["errors"]
    if errors:
        raise ValueError("\n".join(errors))
    state = _content_state(slug)
    if int(state["revision"]) != revision:
        raise ContentConflict("Someone else changed this draft. Export your edits, then reload.")
    state["draft_payload"] = json.dumps(document, ensure_ascii=False, allow_nan=False)
    state["revision"] = revision + 1
    state["updated_at"] = utcnow_iso()
    try:
        _svc().get_table_client(QUESTS_TABLE).update_entity(
            state, mode=UpdateMode.REPLACE, etag=state.metadata["etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    except HttpResponseError as exc:
        if exc.status_code != 412:
            raise
        raise ContentConflict("Someone else changed this draft. Export your edits, then reload.") from exc
    return load_draft(slug)


def publish_draft(slug: str, revision: int) -> dict[str, Any]:
    state = _content_state(slug)
    if int(state["revision"]) != revision:
        raise ContentConflict("The draft changed. Reload before publishing.")
    document = json.loads(state["draft_payload"])
    errors = validate_document(document, publish=True)["errors"]
    if errors:
        raise ValueError("\n".join(errors))
    if state["version"] and json.loads(state["payload"]) == document:
        raise ValueError("There are no changes to publish.")
    version = int(state["version"]) + 1
    published_at = utcnow_iso()
    state.update(payload=state["draft_payload"], version=version, revision=revision + 1, updated_at=published_at)
    try:
        _svc().get_table_client(QUESTS_TABLE).submit_transaction([
            ("create", {"PartitionKey": slug, "RowKey": f"v{version}", "payload": state["payload"],
                        "version": version, "published_at": published_at}),
            ("update", state, {"mode": UpdateMode.REPLACE, "etag": state.metadata["etag"],
                              "match_condition": MatchConditions.IfNotModified}),
        ])
    except HttpResponseError as exc:
        if exc.status_code not in (409, 412):
            raise
        raise ContentConflict("The draft changed during publication. Reload before publishing.") from exc
    return load_draft(slug)


def save_quests(slug: str, data: dict[str, Any]) -> None:
    save_draft(slug, data, load_draft(slug)["revision"])


def get_quest(slug: str, quest_id: int, version: int | None = None) -> dict[str, Any] | None:
    for q in load_quests(slug, version).get("quests", []):
        try:
            if int(q.get("id")) == int(quest_id):
                return q
        except (TypeError, ValueError):
            continue
    return None


# ---------- players ----------

def get_player(slug: str, player_id: str) -> dict[str, Any] | None:
    try:
        e = _svc().get_table_client(PLAYERS_TABLE).get_entity(slug, player_id)
    except ResourceNotFoundError:
        return None
    player = json.loads(e.get("data") or "{}")
    player.setdefault("game_version", 1)
    return player


def save_player(slug: str, player_id: str, data: dict[str, Any]) -> None:
    _svc().get_table_client(PLAYERS_TABLE).upsert_entity({
        "PartitionKey": slug,
        "RowKey": player_id,
        "data": json.dumps(data, ensure_ascii=False),
    })


def update_player(slug: str, player_id: str, mutator: Callable[[dict[str, Any]], Any]) -> Any:
    """Load the player record, run mutator(player), persist, return mutator result."""
    player = get_player(slug, player_id) or {}
    result = mutator(player)
    save_player(slug, player_id, player)
    return result


def list_players(slug: str) -> dict[str, dict[str, Any]]:
    t = _svc().get_table_client(PLAYERS_TABLE)
    out: dict[str, dict[str, Any]] = {}
    for e in t.query_entities(f"PartitionKey eq '{slug}'"):
        out[e["RowKey"]] = json.loads(e.get("data") or "{}")
        out[e["RowKey"]].setdefault("game_version", 1)
    return out


def delete_player(slug: str, player_id: str) -> None:
    try:
        _svc().get_table_client(PLAYERS_TABLE).delete_entity(slug, player_id)
    except ResourceNotFoundError:
        pass


def delete_player_by_ref(slug: str, player_ref: str) -> bool:
    for player_id, player in list_players(slug).items():
        if (player.get("player_ref") or player_id) == player_ref:
            delete_player(slug, player_id)
            return True
    return False


def delete_all_players(slug: str) -> None:
    t = _svc().get_table_client(PLAYERS_TABLE)
    for e in t.query_entities(f"PartitionKey eq '{slug}'"):
        try:
            t.delete_entity(e["PartitionKey"], e["RowKey"])
        except ResourceNotFoundError:
            pass


def get_leaderboard(slug: str, limit: int = 10) -> list[dict[str, Any]]:
    quests_by_version: dict[int, dict[int, Any]] = {}
    entries: list[dict[str, Any]] = []
    for pid, p in list_players(slug).items():
        if p.get("status") == "complete" and p.get("score") is not None:
            version = int(p.get("game_version", 1))
            if version not in quests_by_version:
                quests_by_version[version] = {int(q["id"]): q for q in load_quests(slug, version)["quests"]}
            quest = quests_by_version[version].get(int(p.get("quest_id") or 0), {})
            entries.append({
                "player_id": p.get("player_ref") or pid,
                "game_version": version,
                "name": p.get("name"),
                "quest_name": quest.get("name", f"Quest {p.get('quest_id')}"),
                "score": p.get("score"),
                "time_taken_minutes": p.get("time_taken_minutes"),
                "answer_attempts": p.get("answer_attempts", p.get("code_attempts", 0)),
                "failed_attempts": max(
                    0,
                    int(p.get("answer_attempts", p.get("code_attempts", 0)))
                    - len(p.get("mission_results") or []),
                ),
                "completed_at": p.get("completed_at"),
            })
    entries.sort(key=lambda e: (-(e.get("score") or 0), e.get("time_taken_minutes") or 0))
    return entries[:limit]


if __name__ == "__main__":
    init_storage()
    if not get_game(DEFAULT_SLUG):
        create_game(DEFAULT_SLUG, DEFAULT_DISPLAY)
    imported = import_seed_quests(DEFAULT_SLUG)
    print(f"Imported {len(imported.get('quests', []))} quests into the '{DEFAULT_SLUG}' draft. Publish from the admin editor when ready.")
