"""Reset Azure Tables state and recreate the built-in games."""
from __future__ import annotations

import argparse
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

import storage


TABLES = (storage.GAMES_TABLE, storage.QUESTS_TABLE, storage.PLAYERS_TABLE)


def _ensure_tables() -> None:
    service = storage._svc()
    for table_name in TABLES:
        try:
            service.create_table(table_name)
        except ResourceExistsError:
            pass


def _clear_table(table_name: str) -> int:
    table = storage._svc().get_table_client(table_name)
    deleted = 0
    for entity in table.list_entities():
        try:
            table.delete_entity(entity["PartitionKey"], entity["RowKey"])
            deleted += 1
        except ResourceNotFoundError:
            pass
    return deleted


def reset_storage(
    slug: str,
    display_name: str,
    event_name: str = storage.DEFAULT_EVENT_NAME,
) -> dict[str, Any]:
    _ensure_tables()
    deleted = {table_name: _clear_table(table_name) for table_name in TABLES}
    games: list[dict[str, Any]] = []
    quest_count = 0
    for index, seed in enumerate(storage.SEED_GAMES):
        game_slug = slug if index == 0 else seed.slug
        game_name = display_name if index == 0 else seed.display_name
        game_event = event_name if index == 0 else seed.event_name
        quests = storage.load_seed_quests(seed.slug)
        games.append(
            storage.create_game(
                game_slug,
                game_name,
                quests=quests,
                event_name=game_event,
                schedule=storage.GameSchedule(player_mode=seed.player_mode),
            )
        )
        quest_count += len(quests.get("quests", []))
    return {
        "deleted": deleted,
        "game": games[0],
        "games": games,
        "quest_count": quest_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete all game-server Azure Tables data and recreate the built-in games."
    )
    parser.add_argument("--yes", action="store_true", help="Actually perform the destructive reset.")
    parser.add_argument("--slug", default=storage.DEFAULT_SLUG, help="Slug for the recreated first game.")
    parser.add_argument("--name", default=storage.DEFAULT_DISPLAY, help="Display name for the recreated first game.")
    parser.add_argument(
        "--event-name",
        default=storage.DEFAULT_EVENT_NAME,
        help="Event name for the recreated first game.",
    )
    args = parser.parse_args()

    if not args.yes:
        print("Refusing to wipe storage without --yes.")
        print(f"Would recreate '{args.slug}' from {storage.SEED_QUESTS_FILE}.")
        return 2

    result = reset_storage(args.slug, args.name, args.event_name)
    print("Storage reset complete.")
    for table_name, count in result["deleted"].items():
        print(f"Deleted {count} entities from '{table_name}'.")
    for game in result["games"]:
        print(f"Created game '{game['slug']}' ({game['display_name']}).")
    print(f"Published {result['quest_count']} quests across {len(result['games'])} games.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())