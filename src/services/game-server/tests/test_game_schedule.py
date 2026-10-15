"""Offline schedule validation, authenticated editing, and live MCP enforcement."""
from __future__ import annotations

import asyncio
import copy
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from test_admin_auth import NEW_PASSWORD, ORIGIN, fake_service
from test_game_versions import story
import admin
import game_schedule
import server
import storage
import player_identity
from game_schedule import GameSchedule


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        service, self.tables = fake_service()
        self.patch = patch.object(storage, "_service", service)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        storage.create_game("timed", "Timed", quests=story())

    def test_timezone_validation_and_daylight_saving_boundaries(self) -> None:
        schedule = GameSchedule(starts_at="2026-10-05T09:00", ends_at="2026-10-06T01:00", timezone="Europe/Amsterdam")
        self.assertEqual(schedule.starts_at.isoformat(), "2026-10-05T07:00:00+00:00")
        self.assertEqual(schedule.ends_at.isoformat(), "2026-10-05T23:00:00+00:00")
        for values in (
            {"timezone": "Not/AZone"},
            {"starts_at": "2026-10-05T09:00"},
            {"starts_at": "2026-10-05T09:00", "ends_at": "2026-10-05T08:00"},
            {"starts_at": "2026-10-05T09:00", "ends_at": "2026-10-05T09:00"},
            {"starts_at": "2026-03-29T02:30", "ends_at": "2026-03-29T04:00", "timezone": "Europe/Amsterdam"},
            {"starts_at": "2026-10-25T02:30", "ends_at": "2026-10-25T04:00", "timezone": "Europe/Amsterdam"},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                GameSchedule(**values)
        explicit = GameSchedule(starts_at="2026-10-25T02:30+02:00", ends_at="2026-10-25T02:30+01:00", timezone="Europe/Amsterdam")
        self.assertEqual((explicit.ends_at - explicit.starts_at).total_seconds(), 3600)

    def test_persistence_legacy_clear_and_conflicts(self) -> None:
        table = self.tables[storage.GAMES_TABLE]
        old = table.entities[("games", "timed")]
        for field in (
            "event_name", "starts_at", "ends_at", "timezone", "player_mode",
            "competitive_mode", "schedule_revision",
        ):
            del old[field]
        legacy = storage.get_game("timed")
        self.assertEqual(legacy["event_name"], "")
        self.assertEqual(legacy["player_mode"], "guided")
        self.assertFalse(legacy["competitive_mode"])
        self.assertEqual(game_schedule.game_availability(legacy)["state"], "open")
        schedule = GameSchedule(starts_at="2026-10-05T09:00Z", ends_at="2026-10-05T10:00Z")
        saved = storage.save_schedule("timed", schedule, 0)
        self.assertEqual(storage.list_games()[0], saved)
        with self.assertRaises(storage.ContentConflict):
            storage.save_schedule("timed", GameSchedule(), 0)
        table.conflicts = 1
        with self.assertRaises(storage.ContentConflict):
            storage.save_schedule("timed", GameSchedule(), 1)
        self.assertEqual(storage.get_game("timed")["starts_at"], saved["starts_at"])
        cleared = storage.save_schedule("timed", GameSchedule(timezone="Europe/Amsterdam"), 1)
        self.assertEqual(cleared["starts_at"], "")
        self.assertEqual(cleared["player_mode"], "guided")
        self.assertFalse(cleared["competitive_mode"])
        self.assertEqual(game_schedule.game_availability(cleared)["state"], "open")

    def test_player_mode_is_validated_and_persisted(self) -> None:
        with self.assertRaises(ValidationError):
            GameSchedule(player_mode="unsupported")
        saved = storage.save_schedule("timed", GameSchedule(player_mode="challenge"), 1)
        self.assertEqual(saved["player_mode"], "challenge")
        self.assertEqual(storage.list_games()[0]["player_mode"], "challenge")

    def test_scheduled_availability_includes_countdown_metadata(self) -> None:
        game = {
            **storage.get_game("timed"),
            **GameSchedule(
                starts_at="2026-10-05T09:00Z",
                ends_at="2026-10-05T17:00Z",
            ).storage_fields(),
        }
        with patch.object(
            game_schedule,
            "utcnow",
            return_value=datetime(2026, 10, 5, 8, 59, 59, 500000, tzinfo=timezone.utc),
        ):
            availability = game_schedule.game_availability(game)
        self.assertEqual(availability["state"], "scheduled")
        self.assertEqual(availability["starts_at"], "2026-10-05T09:00:00+00:00")
        self.assertEqual(availability["seconds_until_start"], 1)

    def test_competitive_mode_defaults_off_and_is_persisted(self) -> None:
        self.assertFalse(storage.get_game("timed")["competitive_mode"])
        saved = storage.save_schedule("timed", GameSchedule(competitive_mode=True), 1)
        self.assertTrue(saved["competitive_mode"])
        self.assertTrue(storage.list_games()[0]["competitive_mode"])

    def test_cached_mcp_enforces_fresh_schedule_without_mutating_players(self) -> None:
        mcp = server.build_mcp_for_game(storage.get_game("timed"))
        api_key, _ = player_identity.register_player("timed", "Alice")

        def call(name: str, arguments: dict) -> dict:
            context_token = server.PLAYER_API_KEY.set(api_key)
            try:
                result = asyncio.run(mcp.call_tool(name, arguments))
            finally:
                server.PLAYER_API_KEY.reset(context_token)
            self.assertFalse(result.is_error)
            return result.structured_content

        storage.save_schedule("timed", GameSchedule(
            starts_at="2026-10-05T09:00Z", ends_at="2026-10-05T10:00Z",
        ), 1)
        before = copy.deepcopy(storage.list_players("timed"))
        for instant, state in (("2026-10-05T08:59:59+00:00", "scheduled"), ("2026-10-05T10:00:00+00:00", "ended")):
            with patch.object(game_schedule, "utcnow", return_value=datetime.fromisoformat(instant)):
                for name, arguments in (
                    ("begin_session", {}), ("resume_player", {}),
                    ("start_quest", {}),
                    ("submit_mission_answer", {"answer": "OLD"}),
                ):
                    with self.subTest(instant=instant, tool=name):
                        result = call(name, arguments)
                        self.assertEqual(result["status"], "error")
                        self.assertEqual(result["availability"], state)
                self.assertIn("leaderboard", call("get_leaderboard", {}))
                self.assertEqual(call("get_player_status", {})["status"], "registered")
                self.assertEqual(storage.list_players("timed"), before)
        with patch.object(game_schedule, "utcnow", return_value=datetime(2026, 10, 5, 9, tzinfo=timezone.utc)):
            self.assertEqual(call("start_quest", {})["status"], "quest_started")
        active = copy.deepcopy(storage.list_players("timed"))
        with patch.object(game_schedule, "utcnow", return_value=datetime(2026, 10, 5, 10, tzinfo=timezone.utc)):
            self.assertEqual(call("submit_mission_answer", {"answer": "OLD"})["availability"], "ended")
            self.assertEqual(storage.list_players("timed"), active)
            self.assertEqual(call("abandon_quest", {})["status"], "quest_abandoned")
        storage.save_schedule("timed", GameSchedule(), 2)
        new_api_key, _ = player_identity.register_player("timed", "Beatrice")
        self.assertTrue(new_api_key.startswith("litc.timed."))

    def test_admin_schedule_requires_auth_csrf_and_valid_input(self) -> None:
        with patch.dict("os.environ", {"ADMIN_COOKIE_SECURE": "true"}), TestClient(admin.app, base_url=ORIGIN) as client:
            payload = {
                "event_name": "Open Hack",
                "display_name": "Timed challenge",
                "starts_at": "2026-10-05T09:00",
                "ends_at": "2026-10-05T10:00",
                "timezone": "Europe/Amsterdam",
                "revision": 1,
            }
            self.assertEqual(client.put("/api/games/timed/schedule", json=payload).status_code, 401)
            self.assertEqual(client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers={"Origin": ORIGIN}).status_code, 200)

            def headers() -> dict:
                token = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/password").text)
                return {"Origin": ORIGIN, "X-CSRF-Token": token[1]}

            self.assertEqual(client.put("/api/games/timed/schedule", json=payload, headers=headers()).status_code, 403)
            client.post("/api/auth/password", json={"current_password": "admin", "new_password": NEW_PASSWORD}, headers=headers())
            client.post("/api/auth/login", json={"username": "admin", "password": NEW_PASSWORD}, headers={"Origin": ORIGIN})
            auth = headers()
            self.assertEqual(client.put("/api/games/timed/schedule", json=payload).status_code, 403)
            invalid = client.put("/api/games/timed/schedule", json={**payload, "ends_at": None}, headers=auth)
            self.assertEqual(invalid.status_code, 422)
            self.assertIn("both", invalid.json()["detail"])
            for field in ("event_name", "display_name"):
                blank = client.put(
                    "/api/games/timed/schedule",
                    json={**payload, field: "   "},
                    headers=auth,
                )
                self.assertEqual(blank.status_code, 422)
            result = client.put("/api/games/timed/schedule", json=payload, headers=auth)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["game"]["event_name"], "Open Hack")
            self.assertEqual(result.json()["game"]["display_name"], "Timed challenge")
            self.assertEqual(result.json()["game"]["starts_at"], "2026-10-05T07:00:00+00:00")
            self.assertFalse(result.json()["game"]["competitive_mode"])
            self.assertEqual(client.put("/api/games/timed/schedule", json=payload, headers=auth).status_code, 409)
            self.assertEqual(client.put("/api/games/missing/schedule", json=payload, headers=auth).status_code, 404)
            new = client.post("/api/games", json={
                **{key: value for key, value in payload.items() if key != "revision"},
                "slug": "new-timed", "event_name": "Open Hack", "display_name": "New timed",
            }, headers=auth)
            self.assertEqual(new.status_code, 200, new.text)
            self.assertEqual(storage.get_game("new-timed")["timezone"], "Europe/Amsterdam")
            self.assertFalse(storage.get_game("new-timed")["competitive_mode"])
            self.assertEqual(storage.load_draft("new-timed")["document"]["city"], "New timed")
            settings = client.get("/games/new-timed/settings", follow_redirects=False)
            self.assertEqual(settings.status_code, 303)
            self.assertEqual(settings.headers["location"], "/games/new-timed/edit")
            self.assertEqual(client.get("/games/new-timed/edit").status_code, 200)
