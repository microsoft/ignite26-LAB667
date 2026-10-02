"""Reset Azure Tables state and recreate the first game from quests.json."""
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


def reset_storage(slug: str, display_name: str) -> dict[str, Any]:
    _ensure_tables()
    deleted = {table_name: _clear_table(table_name) for table_name in TABLES}
    quests = storage.load_seed_quests()
    game = storage.create_game(slug, display_name, quests=quests)
    return {
        "deleted": deleted,
        "game": game,
        "quest_count": len(quests.get("quests", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete all game-server Azure Tables data and recreate the first game from quests.json."
    )
    parser.add_argument("--yes", action="store_true", help="Actually perform the destructive reset.")
    parser.add_argument("--slug", default=storage.DEFAULT_SLUG, help="Slug for the recreated first game.")
    parser.add_argument("--name", default=storage.DEFAULT_DISPLAY, help="Display name for the recreated first game.")
    args = parser.parse_args()

    if not args.yes:
        print("Refusing to wipe storage without --yes.")
        print(f"Would recreate '{args.slug}' from {storage.SEED_QUESTS_FILE}.")
        return 2

    result = reset_storage(args.slug, args.name)
    print("Storage reset complete.")
    for table_name, count in result["deleted"].items():
        print(f"Deleted {count} entities from '{table_name}'.")
    print(
        f"Created game '{result['game']['slug']}' "
        f"({result['game']['display_name']}) with {result['quest_count']} quests."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())