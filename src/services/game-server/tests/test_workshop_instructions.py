"""Public instruction rendering never needs credentials or live services."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from starlette.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from test_admin_auth import fake_service
import admin
import dashboard
import storage
import workshop_instructions
from game_schedule import GameSchedule


def quest_document(story: str, city: str = "Amsterdam") -> dict:
    return {
        "city": city,
        "story": story,
        "quests": [{
            "id": 1,
            "name": "Test route",
            "begin": {"prompt": "Begin"},
            "end": {"prompt": "End"},
            "missions": [{
                "id": "question",
                "type": "question",
                "mission": "What is the answer?",
                "arrival_prompt": "Find it.",
                "complete_prompt": "Done.",
                "valid_answers": ["ANSWER"],
            }],
        }],
    }


class InstructionsTests(unittest.TestCase):
    def setUp(self) -> None:
        service, _ = fake_service()
        self.patch = patch.object(storage, "_service", service)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.env = patch.dict("os.environ", {
            "GAME_SERVER_URL": "https://mcp.example.test",
            "AGENT42_URL": "https://transport.example.test",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        storage.create_game(
            "amsterdam", '<script>alert("game")</script> Amsterdam',
            city="Legacy city", schedule=GameSchedule(
                starts_at="2026-10-05T09:00", ends_at="2026-10-05T17:00", timezone="Europe/Amsterdam",
            ),
        )
        draft = storage.load_draft("amsterdam")
        saved = storage.save_draft(
            "amsterdam", quest_document("A published Amsterdam story from the quest document."), draft["revision"],
        )
        storage.publish_draft("amsterdam", saved["revision"])
        storage.create_game("london", "London")

    def test_all_lessons_render_with_game_values_assets_and_navigation(self) -> None:
        with TestClient(dashboard.build_app()) as client:
            for lesson in workshop_instructions.GUIDED_DIR.glob("[0-9][0-9]_*.md"):
                response = client.get(f"/amsterdam/player/{lesson.stem}")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn("{{", response.text)
                self.assertNotIn("@lab.", response.text)
                self.assertNotIn('<script>alert("game")</script>', response.text)
                self.assertIn("Europe/Amsterdam", response.text)
                self.assertIn("09:00:00", response.text)
                self.assertIn('/amsterdam/player/', response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")
            connection = client.get("/amsterdam/player/03_connect_to_the_gaming_mcp_server").text
            self.assertIn("GAME_MCP_URL=https://mcp.example.test/amsterdam/mcp", connection)
            self.assertNotIn("/san-francisco/mcp", connection)
            other = client.get("/london/player/03_connect_to_the_gaming_mcp_server").text
            self.assertIn("GAME_MCP_URL=https://mcp.example.test/london/mcp", other)
            self.assertNotIn("https://mcp.example.test/amsterdam/mcp", other)
            story = client.get("/amsterdam/player/00_step_into_your_workspace").text
            self.assertIn("A published Amsterdam story from the quest document.", story)
            self.assertIn("Amsterdam city guide", story)
            self.assertNotIn("arrived in San Francisco", story)
            self.assertEqual(workshop_instructions.instruction_city({}, "London"), "London")
            transport = client.get("/amsterdam/player/06_test_agent42_transport_specialist").text
            self.assertIn("AGENT42_URL=https://transport.example.test/", transport)
            foundry = client.get("/amsterdam/player/01_get_azure_openai_details_from_foundry").text
            self.assertIn('src="/player-assets/sign-in-foundry.png"', foundry)
            self.assertEqual(client.get("/player-assets/sign-in-foundry.png").status_code, 200)
            self.assertEqual(client.get("/static/css/player.css").status_code, 200)
            self.assertEqual(client.get("/missing/player").status_code, 404)
            self.assertEqual(client.get("/amsterdam/player/README").status_code, 404)
            self.assertEqual(client.get("/amsterdam/player/").status_code, 200)
            legacy = client.get("/amsterdam/instructions", follow_redirects=False)
            self.assertEqual(legacy.status_code, 308)
            self.assertEqual(legacy.headers["location"], "/amsterdam/player")

    def test_admin_preview_is_public_but_settings_are_not(self) -> None:
        with TestClient(admin.app) as client:
            self.assertEqual(client.get("/amsterdam/player").status_code, 200)
            self.assertEqual(client.get("/games/amsterdam/settings", follow_redirects=False).status_code, 303)

    def test_challenge_mode_shows_brief_without_guided_lessons(self) -> None:
        storage.save_schedule("amsterdam", GameSchedule(
            starts_at="2026-10-05T09:00", ends_at="2026-10-05T17:00",
            timezone="Europe/Amsterdam", player_mode="challenge",
        ), 1)
        with TestClient(dashboard.build_app()) as client:
            guided = sorted(path.name for path in workshop_instructions.GUIDED_DIR.glob("[0-9][0-9]_*.md"))
            challenge = sorted(path.name for path in workshop_instructions.CHALLENGE_DIR.glob("[0-9][0-9]_*.md"))
            self.assertEqual(challenge, guided)
            self.assertEqual(len(challenge), 10)
            for chapter in workshop_instructions.CHALLENGE_DIR.glob("[0-9][0-9]_*.md"):
                chapter_response = client.get(f"/amsterdam/player/{chapter.stem}")
                self.assertEqual(chapter_response.status_code, 200, chapter_response.text)
                self.assertIn("Challenge mode", chapter_response.text)
                self.assertIn("Expected outcome", chapter_response.text)
                self.assertNotIn("{{", chapter_response.text)
            response = client.get("/amsterdam/player")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Challenge mode", response.text)
            self.assertIn("Prepare Your Workspace", response.text)
            self.assertIn("A published Amsterdam story from the quest document.", response.text)
            self.assertIn("Expected outcome", response.text)
            self.assertIn("Next lesson", response.text)
            self.assertEqual(response.text.count('/amsterdam/player/'), 11)
            connection = client.get("/amsterdam/player/03_connect_to_the_gaming_mcp_server")
            self.assertIn("GAME_MCP_URL=https://mcp.example.test/amsterdam/mcp", connection.text)
            self.assertNotIn("Connect the MCP tool", connection.text)

    def test_variable_values_are_text_not_markdown_html_or_templates(self) -> None:
        rendered = workshop_instructions.render_lesson(
            "# {{ game_name }}\n\n{{ game_story }}\n\n```env\nGAME_MCP_URL={{ game_mcp_url }}\n```",
            {"game_name": '[click](javascript:alert(1)) <img src=x onerror=alert(1)> {{ secret }}',
             "game_story": '<script>alert("story")</script> [click](javascript:alert(2))',
             "game_mcp_url": 'https://mcp.example.test/a/mcp'},
        )
        self.assertNotIn("<img", rendered)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<a ", rendered)
        self.assertIn("&lt;img", rendered)
        self.assertIn("{{ secret }}", rendered)
        with self.assertRaisesRegex(ValueError, "Unknown workshop"):
            workshop_instructions.render_lesson("{{ unknown }}", {})
        with patch.dict("os.environ", {"GAME_SERVER_URL": "https://user:secret@example.test"}):
            with self.assertRaises(ValueError):
                workshop_instructions.public_url("GAME_SERVER_URL", "")

    def test_public_lessons_are_responsive_and_navigation_preserves_game(self) -> None:
        with TestClient(dashboard.build_app()) as client, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                response = client.get(route.request.url.removeprefix("https://instructions.test"))
                route.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get("content-type", "text/plain"))

            page.route("**/*", serve)
            page.goto("https://instructions.test/amsterdam/player/03_connect_to_the_gaming_mcp_server")
            expect(page.locator(".lesson-content")).to_contain_text("GAME_MCP_URL=https://mcp.example.test/amsterdam/mcp")
            for width in (1440, 900, 650, 390, 320):
                with self.subTest(width=width):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    expect(page.get_by_role("link", name="Next lesson")).to_be_visible()
            page.get_by_role("link", name="Next lesson").click()
            expect(page).to_have_url("https://instructions.test/amsterdam/player/04_add_memory_for_the_player_id")
            page.get_by_role("link", name="Previous lesson").click()
            expect(page).to_have_url("https://instructions.test/amsterdam/player/03_connect_to_the_gaming_mcp_server")
            self.assertEqual(errors, [])
            browser.close()
