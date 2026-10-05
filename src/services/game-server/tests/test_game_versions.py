"""Draft/publication isolation, legacy migration, and MCP version pinning."""
from __future__ import annotations

import asyncio
import copy
import unittest
from unittest.mock import patch

from azure.core.exceptions import ResourceExistsError
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from test_admin_auth import fake_service
import init
import storage
import server
from dashboard import Dashboard
from quest_validation import validate_document


def story(answer: str = "OLD", name: str = "Original story") -> dict:
    return {"quests": [{
        "id": 1, "name": name, "begin": {"prompt": "The beginning"}, "end": {"prompt": "The ending"},
        "missions": [{"id": "question-one", "type": "question", "mission": "What is the code?",
                      "arrival_prompt": "Read the guide.", "complete_prompt": "Well done.", "valid_answers": [answer],
                      "start_address": "Test location", "start_lat": 37.77, "start_lng": -122.42}],
    }]}


class GameVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service, self.tables = fake_service()
        self.patch = patch.object(storage, "_service", self.service)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        storage.create_game("test-city", "Test city", quests=story())

    def call(self, mcp: MCPServer, tool: str, arguments: dict) -> dict:
        result = asyncio.run(mcp.call_tool(tool, arguments))
        self.assertIsInstance(result, CallToolResult)
        assert isinstance(result, CallToolResult)
        self.assertFalse(result.is_error)
        self.assertIsInstance(result.structured_content, dict)
        assert isinstance(result.structured_content, dict)
        return result.structured_content

    def publish_new(self, document: dict) -> None:
        draft = storage.load_draft("test-city")
        saved = storage.save_draft("test-city", document, draft["revision"])
        storage.publish_draft("test-city", saved["revision"])

    def test_draft_does_not_affect_live_story(self) -> None:
        before = storage.load_draft("test-city")
        result = storage.save_draft("test-city", story("NEW", "New story"), before["revision"])
        self.assertTrue(result["dirty"])
        self.assertEqual(storage.get_quest("test-city", 1)["name"], "Original story")
        self.assertEqual(storage.load_published("test-city")[0], 1)
        published = storage.publish_draft("test-city", result["revision"])
        self.assertEqual(published["published_version"], 2)
        self.assertFalse(published["dirty"])
        self.assertEqual(storage.get_quest("test-city", 1)["name"], "New story")
        self.assertEqual(storage.get_quest("test-city", 1, 1)["name"], "Original story")

    def test_mcp_registration_pins_story_and_all_subsequent_actions(self) -> None:
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        old = self.call(mcp, "register_player", {"name": "Alice"})
        old_id = old["player_id"]
        self.publish_new(story("NEW", "New story"))
        new_id = self.call(mcp, "register_player", {"name": "Beatrice"})["player_id"]
        self.assertEqual(storage.get_player("test-city", old_id)["game_version"], 1)
        self.assertEqual(storage.get_player("test-city", new_id)["game_version"], 2)
        self.assertEqual(self.call(mcp, "resume_player", {"player_id": old_id})["quest_name"], "Original story")
        self.call(mcp, "start_quest", {"player_id": old_id})
        self.call(mcp, "start_quest", {"player_id": new_id})
        old_result = self.call(mcp, "submit_mission_answer", {"player_id": old_id, "answer": "OLD"})
        new_result = self.call(mcp, "submit_mission_answer", {"player_id": new_id, "answer": "NEW"})
        self.assertEqual(old_result["status"], "quest_complete")
        self.assertEqual(new_result["status"], "quest_complete")
        self.assertEqual(self.call(mcp, "get_player_status", {"player_id": old_id})["quest_name"], "Original story")
        board = storage.get_leaderboard("test-city")
        self.assertEqual({entry["game_version"] for entry in board}, {1, 2})
        data = Dashboard().build_data(storage.get_game("test-city"), limit=None)
        names = {p["game_version"]: p["quest_name"] for p in data["players"]}
        self.assertEqual(names, {1: "Original story", 2: "New story"})
        self.assertEqual(data["quest_versions"], [1, 2])
        locations = Dashboard().build_quest_locations(storage.get_game("test-city"))
        self.assertEqual(locations["versions"], [1, 2])
        self.assertEqual(len(locations["quests"]), 2)

    def test_invalid_or_duplicate_creation_does_not_overwrite_a_game(self) -> None:
        with self.assertRaises(ValueError):
            storage.create_game("invalid", "Invalid", quests={"quests": []})
        self.assertIsNone(storage.get_game("invalid"))
        with self.assertRaises(ResourceExistsError):
            storage.create_game("test-city", "Replacement", quests=story("NEW"))
        self.assertEqual(storage.get_game("test-city")["display_name"], "Test city")
        self.assertEqual(storage.get_game("test-city")["city"], "Test city")
        self.assertEqual(storage.get_quest("test-city", 1)["name"], "Original story")

    def test_reset_removes_all_versions_but_preserves_admin_tables(self) -> None:
        self.publish_new(story("NEW"))
        auth = self.service.get_table_client("adminusers")
        auth.create_entity({"PartitionKey": "admin", "RowKey": "admin", "hash": "test-hash"})
        result = init.reset_storage("fresh", "Fresh game")
        self.assertEqual(result["deleted"][storage.QUESTS_TABLE], 3)
        self.assertIsNone(storage.get_game("test-city"))
        self.assertEqual(storage.load_published("fresh")[0], 1)
        self.assertEqual(len(storage.list_versions("fresh")), 1)
        self.assertEqual(auth.get_entity("admin", "admin")["hash"], "test-hash")

    def test_legacy_migration_preserves_unversioned_players(self) -> None:
        quests = self.tables[storage.QUESTS_TABLE]
        quests.entities = {("test-city", "quests"): quests.entities[("test-city", "quests")]}
        state = quests.entities[("test-city", "quests")]
        for key in ("draft_payload", "version", "revision"):
            del state[key]
        storage.save_player("test-city", "legacy", {"name": "Legacy", "quest_id": 1, "status": "registered"})
        self.publish_new(story("NEW", "Replacement"))
        player = storage.get_player("test-city", "legacy")
        self.assertEqual(player["game_version"], 1)
        self.assertEqual(storage.get_quest("test-city", 1, player["game_version"])["name"], "Original story")
        storage.load_draft("test-city")
        self.assertEqual(len(storage.list_versions("test-city")), 2)

    def test_stale_save_and_publish_conflict_without_losing_content(self) -> None:
        original = storage.load_draft("test-city")
        saved = storage.save_draft("test-city", story("NEW"), original["revision"])
        with self.assertRaises(storage.ContentConflict):
            storage.save_draft("test-city", story("OVERWRITE"), original["revision"])
        with self.assertRaises(storage.ContentConflict):
            storage.publish_draft("test-city", original["revision"])
        self.tables[storage.QUESTS_TABLE].conflicts = 1
        with self.assertRaises(storage.ContentConflict):
            storage.publish_draft("test-city", saved["revision"])
        self.assertEqual(storage.load_published("test-city")[0], 1)
        self.assertEqual(len(storage.list_versions("test-city")), 1)

    def test_version_deletion_protects_current_and_assigned_versions(self) -> None:
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        player_id = self.call(mcp, "register_player", {"name": "Alice"})["player_id"]
        self.publish_new(story("NEW", "New story"))
        with self.assertRaisesRegex(storage.VersionDeletionError, "current published"):
            storage.delete_version("test-city", 2)
        with self.assertRaisesRegex(storage.VersionDeletionError, "1 player is still assigned"):
            storage.delete_version("test-city", 1)
        storage.delete_player("test-city", player_id)
        storage.delete_version("test-city", 1)
        self.assertEqual([item["version"] for item in storage.list_versions("test-city")], [2])
        with self.assertRaises(KeyError):
            storage.delete_version("test-city", 1)

    def test_unpublished_game_cannot_register_until_publish(self) -> None:
        storage.create_game("empty", "Empty")
        mcp = server.build_mcp_for_game(storage.get_game("empty"))
        self.assertEqual(self.call(mcp, "register_player", {"name": "Alice"})["status"], "error")
        draft = storage.save_draft("empty", story(), storage.load_draft("empty")["revision"])
        storage.publish_draft("empty", draft["revision"])
        self.assertIn("player_id", self.call(mcp, "register_player", {"name": "Alice"}))

    def test_reset_re_registers_on_latest_and_delete_removes_versions(self) -> None:
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        pid = self.call(mcp, "register_player", {"name": "Alice"})["player_id"]
        self.publish_new(story("NEW"))
        storage.delete_player("test-city", pid)
        new_pid = self.call(mcp, "register_player", {"name": "Alice"})["player_id"]
        self.assertEqual(storage.get_player("test-city", new_pid)["game_version"], 2)
        storage.delete_game("test-city")
        self.assertFalse(list(self.tables[storage.QUESTS_TABLE].query_entities("PartitionKey eq 'test-city'")))

    def test_validation_preserves_unknown_fields_and_rejects_invalid_content(self) -> None:
        document = story()
        document["metadata"] = {"author": "Test author"}
        self.assertEqual(validate_document(document, publish=True)["errors"], [])
        draft = storage.save_draft("test-city", document, storage.load_draft("test-city")["revision"])
        self.assertEqual(draft["document"]["metadata"], document["metadata"])
        for mutation in ("ids", "coordinates", "answers", "missions", "city", "story", "size"):
            invalid = copy.deepcopy(document)
            if mutation == "ids":
                invalid["quests"].append(copy.deepcopy(invalid["quests"][0]))
            elif mutation == "coordinates":
                invalid["quests"][0]["missions"][0]["start_lat"] = 91
            elif mutation == "answers":
                invalid["quests"][0]["missions"][0]["valid_answers"] = []
            elif mutation == "missions":
                invalid["quests"][0]["missions"] = []
            elif mutation == "city":
                invalid["city"] = ["Not plain text"]
            elif mutation == "story":
                invalid["story"] = {"text": "Not plain text"}
            else:
                invalid["metadata"]["large"] = "x" * 33000
            with self.subTest(mutation=mutation):
                self.assertTrue(validate_document(invalid, publish=True)["errors"])
        incomplete = story()
        incomplete["quests"][0]["missions"][0].pop("start_lat")
        incomplete["quests"][0]["missions"][0].pop("start_lng")
        self.assertTrue(validate_document(incomplete)["warnings"])


if __name__ == "__main__":
    unittest.main()
