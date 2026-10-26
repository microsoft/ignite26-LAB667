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
import player_identity
from dashboard import Dashboard
from game_schedule import GameSchedule
from quest_validation import validate_document


def story(answer: str = "OLD", name: str = "Original story") -> dict:
    return {"quests": [{
        "id": 1, "name": name, "city_guide": "# Test city guide\n\nThe code is documented here.",
        "begin": {"prompt": "The beginning"}, "end": {"prompt": "The ending"},
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
        storage.create_game(
            "test-city", "Test city", quests=story(),
            schedule=GameSchedule(competitive_mode=True),
        )

    def call(self, mcp: MCPServer, tool: str, arguments: dict, api_key: str) -> dict:
        context_token = server.PLAYER_API_KEY.set(api_key)
        try:
            result = asyncio.run(mcp.call_tool(tool, arguments))
        finally:
            server.PLAYER_API_KEY.reset(context_token)
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

    def test_question_mission_exposes_versioned_city_guide_resource(self) -> None:
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        api_key, _ = player_identity.register_player("test-city", "Guide reader")
        result = self.call(mcp, "start_quest", {}, api_key)

        self.assertEqual(result["mission_type"], "question")
        self.assertEqual(result["resources"], [{
            "name": "Original story city guide",
            "description": "Download this guide and add it to Foundry IQ to answer the mission question.",
            "url": "http://localhost:8090/test-city/guides/1/1.md",
            "media_type": "text/markdown",
        }])
        self.assertNotIn("valid_answers", result)

    def test_question_mission_can_opt_out_of_city_guide(self) -> None:
        document = story()
        document["quests"][0]["missions"][0]["uses_city_guide"] = False
        self.publish_new(document)
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        api_key, _ = player_identity.register_player("test-city", "Note reader")
        result = self.call(mcp, "start_quest", {}, api_key)

        self.assertEqual(result["mission_type"], "question")
        self.assertNotIn("resources", result)
        self.assertNotIn("city guide", result["ask_user"])
        self.assertIsNone(player_identity.player_state("test-city", api_key)["quest_question"])
        del document["quests"][0]["city_guide"]
        self.assertEqual(validate_document(document, publish=True)["errors"], [])
        document["quests"][0]["missions"][0]["uses_city_guide"] = "no"
        self.assertTrue(validate_document(document)["errors"])

    def test_image_question_offers_note_image_not_answer(self) -> None:
        document = story("SECRET")
        mission = document["quests"][0]["missions"][0]
        mission.update(uses_city_guide=False, image_url="https://notes.example.test/door.jpg")
        self.publish_new(document)
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        api_key, _ = player_identity.register_player("test-city", "Door guest")
        result = self.call(mcp, "start_quest", {}, api_key)

        self.assertEqual(result["resources"], [{
            "name": "Note image",
            "description": "A picture of the note the player carries. A note-reading tool can read it.",
            "url": "https://notes.example.test/door.jpg",
            "media_type": "image/jpeg",
        }])
        self.assertIn("HELP", result["ask_user"])
        self.assertIn("note-reading tool", result["next_action"])
        self.assertNotIn("SECRET", str(result))
        for invalid in ("http://notes.example.test/door.jpg", 42):
            mission["image_url"] = invalid
            with self.subTest(image_url=invalid):
                self.assertTrue(validate_document(document)["errors"])

    def test_browser_registration_pins_story_and_all_mcp_actions(self) -> None:
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        old_id, _ = player_identity.register_player("test-city", "Alice")
        self.publish_new(story("NEW", "New story"))
        new_id, _ = player_identity.register_player("test-city", "Beatrice")
        self.assertEqual(storage.get_player("test-city", old_id)["game_version"], 1)
        self.assertEqual(storage.get_player("test-city", new_id)["game_version"], 2)
        self.assertEqual(self.call(mcp, "resume_player", {}, old_id)["quest_name"], "Original story")
        self.call(mcp, "start_quest", {}, old_id)
        self.call(mcp, "start_quest", {}, new_id)
        old_result = self.call(mcp, "submit_mission_answer", {"answer": "OLD"}, old_id)
        new_result = self.call(mcp, "submit_mission_answer", {"answer": "NEW"}, new_id)
        self.assertEqual(old_result["status"], "quest_complete")
        self.assertEqual(new_result["status"], "quest_complete")
        self.assertEqual(self.call(mcp, "get_player_status", {}, old_id)["quest_name"], "Original story")
        board = storage.get_leaderboard("test-city")
        self.assertEqual({entry["game_version"] for entry in board}, {1, 2})
        data = Dashboard().build_data(storage.get_game("test-city"), limit=None)
        names = {p["game_version"]: p["quest_name"] for p in data["players"]}
        self.assertEqual(names, {1: "Original story", 2: "New story"})
        self.assertEqual(data["quest_versions"], [1, 2])
        locations = Dashboard().build_quest_locations(storage.get_game("test-city"))
        self.assertEqual(locations["versions"], [1, 2])
        self.assertEqual(len(locations["quests"]), 2)

    def test_move_completion_records_transport_on_timeline(self) -> None:
        document = story("bike")
        mission = document["quests"][0]["missions"][0]
        mission.update({
            "type": "move",
            "end_address": "Destination",
            "end_lat": 37.78,
            "end_lng": -122.41,
        })
        storage.save_draft(
            "test-city",
            document,
            storage.load_draft("test-city")["revision"],
        )
        draft = storage.load_draft("test-city")
        storage.publish_draft("test-city", draft["revision"])
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        api_key, _ = player_identity.register_player("test-city", "Cyclist")
        self.call(mcp, "start_quest", {}, api_key)
        result = self.call(
            mcp,
            "submit_mission_answer",
            {"answer": "bike", "route_ref": "abc123def456ghi"},
            api_key,
        )
        self.assertEqual(result["status"], "quest_complete")
        timeline = player_identity.player_state("test-city", api_key)["timeline"]
        self.assertEqual(timeline[-2]["type"], "mission_complete")
        self.assertEqual(timeline[-2]["transport"], "bike")

    def test_noncompetitive_game_completes_without_points_or_ranking(self) -> None:
        storage.save_schedule("test-city", GameSchedule(), 1)
        mcp = server.build_mcp_for_game(storage.get_game("test-city"))
        api_key, _ = player_identity.register_player("test-city", "Explorer")
        self.call(mcp, "start_quest", {}, api_key)
        result = self.call(mcp, "submit_mission_answer", {"answer": "OLD"}, api_key)
        self.assertFalse(result["competitive_mode"])
        self.assertNotIn("score", result)
        self.assertNotIn("leaderboard_position", result)
        self.assertNotIn("Score:", result["narration"])
        player = storage.get_player("test-city", api_key)
        self.assertNotIn("score", player)
        self.assertEqual(storage.get_leaderboard("test-city"), [])
        board = self.call(mcp, "get_leaderboard", {}, api_key)
        self.assertFalse(board["competitive_mode"])
        self.assertEqual(board["leaderboard"], [])
        self.assertIn("not enabled", board["message"])
        status = self.call(mcp, "get_player_status", {}, api_key)
        self.assertFalse(status["competitive_mode"])
        self.assertNotIn("score", status)

    def test_invalid_or_duplicate_creation_does_not_overwrite_a_game(self) -> None:
        with self.assertRaises(ValueError):
            storage.create_game("invalid", "Invalid", quests={"quests": []})
        self.assertIsNone(storage.get_game("invalid"))
        with self.assertRaises(ResourceExistsError):
            storage.create_game("test-city", "Replacement", quests=story("NEW"))
        self.assertEqual(storage.get_game("test-city")["display_name"], "Test city")
        self.assertEqual(storage.get_game("test-city")["city"], "Test city")
        self.assertEqual(storage.get_quest("test-city", 1)["name"], "Original story")

    def test_init_storage_adds_missing_seed_games_without_overwriting_existing_games(self) -> None:
        storage.init_storage()
        games = {game["slug"]: game for game in storage.list_games()}
        self.assertEqual(
            set(games),
            {"test-city", "san-francisco", "philadelphia"},
        )
        self.assertEqual(games["san-francisco"]["event_name"], "Microsoft Ignite")
        self.assertEqual(games["san-francisco"]["display_name"], "Lost in San Francisco")
        self.assertEqual(games["philadelphia"]["event_name"], "Open Hack Philadelphia")
        self.assertEqual(games["philadelphia"]["display_name"], "Lost in Philadelphia")
        self.assertEqual(games["philadelphia"]["player_mode"], "challenge")
        self.assertEqual(storage.load_published("san-francisco")[1]["city"], "San Francisco")
        self.assertEqual(storage.load_published("philadelphia")[1]["city"], "Philadelphia")

        revision = games["san-francisco"]["schedule_revision"]
        storage.save_schedule(
            "san-francisco",
            GameSchedule(),
            revision,
            event_name="Customized event",
        )
        storage.init_storage()
        self.assertEqual(storage.get_game("san-francisco")["event_name"], "Customized event")

    def test_built_in_seed_documents_are_publishable(self) -> None:
        for seed in storage.SEED_GAMES:
            with self.subTest(slug=seed.slug):
                result = validate_document(storage.load_seed_quests(seed.slug), publish=True)
                self.assertEqual(result["errors"], [])

    def test_reset_removes_all_versions_but_preserves_admin_tables(self) -> None:
        self.publish_new(story("NEW"))
        auth = self.service.get_table_client("adminusers")
        auth.create_entity({"PartitionKey": "admin", "RowKey": "admin", "hash": "test-hash"})
        result = init.reset_storage("fresh", "Fresh game")
        self.assertEqual(result["deleted"][storage.QUESTS_TABLE], 3)
        self.assertIsNone(storage.get_game("test-city"))
        self.assertEqual(storage.load_published("fresh")[0], 1)
        self.assertEqual(storage.load_published("philadelphia")[0], 1)
        self.assertEqual(len(storage.list_versions("fresh")), 1)
        self.assertEqual(len(result["games"]), 2)
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
        player_id, _ = player_identity.register_player("test-city", "Alice")
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
        with self.assertRaises(RuntimeError):
            player_identity.register_player("empty", "Alice")
        draft = storage.save_draft("empty", story(), storage.load_draft("empty")["revision"])
        storage.publish_draft("empty", draft["revision"])
        api_key, player = player_identity.register_player("empty", "Alice")
        self.assertTrue(api_key.startswith("litc.empty."))
        self.assertEqual(player["name"], "Alice")

    def test_reset_re_registers_on_latest_and_delete_removes_versions(self) -> None:
        pid, _ = player_identity.register_player("test-city", "Alice")
        self.publish_new(story("NEW"))
        storage.delete_player("test-city", pid)
        new_pid, _ = player_identity.register_player("test-city", "Alice")
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
