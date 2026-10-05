"""Public instruction rendering never needs credentials or live services."""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

from test_admin_auth import fake_service
import admin
import dashboard
import game_schedule
import player_identity
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
            event_name="Open Hack",
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
                self.assertNotIn("No play window is set", response.text)
                self.assertNotIn('class="workshop-details"', response.text)
                self.assertIn("Open Hack", response.text)
                self.assertIn('/amsterdam/player/', response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertIn("img-src 'self' blob:", response.headers["content-security-policy"])
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
            player_script = client.get("/static/js/player.js")
            self.assertEqual(player_script.status_code, 200)
            self.assertIn("Authorization: 'Bearer ' + apiKey", player_script.text)
            self.assertNotIn("******", player_script.text)
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

    def test_player_registration_issues_bearer_key_and_returns_safe_timeline(self) -> None:
        with patch.object(
            game_schedule, "utcnow",
            return_value=datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
        ), TestClient(dashboard.build_app()) as client:
            response = client.post(
                "/api/games/amsterdam/players",
                json={"nickname": "  City   Fox  "},
            )
            self.assertEqual(response.status_code, 201, response.text)
            payload = response.json()
            api_key = payload["api_key"]
            self.assertTrue(api_key.startswith("litc.amsterdam."))
            self.assertEqual(payload["player"]["name"], "City Fox")
            self.assertNotEqual(payload["player"]["player_id"], api_key)
            self.assertEqual(payload["player"]["timeline"][0]["type"], "registered")
            self.assertEqual(client.get("/api/games/amsterdam/player").status_code, 401)
            state = client.get(
                "/api/games/amsterdam/player",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            self.assertEqual(state.status_code, 200)
            self.assertNotIn(api_key, state.text)
            self.assertEqual(state.json()["player"]["mission_count"], 1)
            self.assertEqual(
                client.get(
                    "/api/games/london/player",
                    headers={"Authorization": "Bearer " + api_key},
                ).status_code,
                401,
            )
            for nickname in ("   ", "x" * 41):
                invalid = client.post(
                    "/api/games/amsterdam/players",
                    json={"nickname": nickname},
                )
                self.assertEqual(invalid.status_code, 422, invalid.text)
                self.assertNotIn("api_key", invalid.text)

    def test_agent42_details_proxy_map_without_exposing_route_reference(self) -> None:
        route_ref = "abc123def456ghi"
        advice = (
            "Weather: 14 C, light rain\n\n"
            "Options:\nCar: 1.8 miles, 14 minutes\nBike: 1.7 miles, 11 minutes\n"
            "Walking: 1.6 miles, 31 minutes\n\n"
            "Reasoning: Light rain still makes biking practical.\n\n"
            "map: https://routes.blob.core.windows.net/agent42-routes/abc123def456ghi.png\n"
            "directions: https://routes.blob.core.windows.net/agent42-routes/abc123def456ghi.json\n"
            "recommendation: bike\n"
            f"recommendation code: {route_ref}"
        )
        route = {
            "mode": "bike",
            "origin": {"query": "Chinatown"},
            "destination": {"query": "North Beach"},
            "distance_km": 2.7,
            "travel_time_seconds": 660,
            "traffic_delay_seconds": 0,
        }
        with patch.object(
            game_schedule, "utcnow",
            return_value=datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
        ), patch.object(
            dashboard.dashboard, "fetch_route", new=AsyncMock(return_value=route),
        ), patch.object(
            dashboard.dashboard, "fetch_route_asset", new=AsyncMock(return_value=b"\x89PNG\r\n"),
        ), TestClient(dashboard.build_app()) as client:
            registration = client.post(
                "/api/games/amsterdam/players",
                json={"nickname": "Route Fox"},
            ).json()
            api_key = registration["api_key"]

            def add_advice(player: dict) -> None:
                player_identity.append_timeline_event(
                    player,
                    "agent42",
                    "Agent42 route advice",
                    detail=advice,
                    route_ref=route_ref,
                )

            storage.update_player("amsterdam", api_key, add_advice)
            headers = {"Authorization": "Bearer " + api_key}
            state = client.get("/api/games/amsterdam/player", headers=headers)
            self.assertEqual(state.status_code, 200, state.text)
            self.assertNotIn(route_ref, state.text)
            self.assertNotIn("routes.example.test", state.text)
            event = state.json()["player"]["timeline"][-1]
            self.assertTrue(event["has_details"])
            event_index = event["event_index"]

            details = client.get(
                f"/api/games/amsterdam/player/timeline/{event_index}/agent42",
                headers=headers,
            )
            self.assertEqual(details.status_code, 200, details.text)
            payload = details.json()
            self.assertEqual(payload["weather"], "14 C, light rain")
            self.assertEqual(payload["recommendation"], "bike")
            self.assertEqual(payload["route"]["travel_time_minutes"], 11)
            self.assertTrue(payload["map_available"])
            self.assertNotIn(route_ref, details.text)
            self.assertNotIn("routes.blob.core.windows.net", details.text)
            dashboard.dashboard.fetch_route.assert_awaited_once_with(
                route_ref,
                f"https://routes.blob.core.windows.net/agent42-routes/{route_ref}.json",
            )

            route_map = client.get(
                f"/api/games/amsterdam/player/timeline/{event_index}/agent42/map",
                headers=headers,
            )
            self.assertEqual(route_map.status_code, 200, route_map.text)
            self.assertEqual(route_map.headers["content-type"], "image/png")
            self.assertEqual(route_map.content, b"\x89PNG\r\n")
            dashboard.dashboard.fetch_route_asset.assert_awaited_once_with(
                route_ref,
                "png",
                f"https://routes.blob.core.windows.net/agent42-routes/{route_ref}.png",
            )
            self.assertEqual(
                client.get(
                    f"/api/games/amsterdam/player/timeline/{event_index}/agent42"
                ).status_code,
                401,
            )
            self.assertEqual(
                client.get(
                    "/api/games/amsterdam/player/timeline/999/agent42",
                    headers=headers,
                ).status_code,
                404,
            )

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
                self.assertNotIn("Challenge mode", chapter_response.text)
                self.assertIn("Expected outcome", chapter_response.text)
                self.assertNotIn("{{", chapter_response.text)
            response = client.get("/amsterdam/player")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Challenge mode", response.text)
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
        with patch.object(
            game_schedule, "utcnow",
            return_value=datetime(2026, 10, 5, 12, tzinfo=timezone.utc),
        ), TestClient(dashboard.build_app()) as client, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def serve(route):
                url = route.request.url.removeprefix("https://instructions.test")
                headers = dict(route.request.headers)
                if route.request.method == "POST":
                    response = client.post(url, headers=headers, content=route.request.post_data or "")
                else:
                    response = client.get(url, headers=headers)
                route.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get("content-type", "text/plain"))

            page.route("**/*", serve)
            page.goto("https://instructions.test/amsterdam/player/03_connect_to_the_gaming_mcp_server")
            page.get_by_label("Nickname").fill("Browser Fox")
            page.get_by_role("button", name="Start game").click()
            expect(page.get_by_text("Player: Browser Fox", exact=True)).to_be_visible()
            expect(page.get_by_text("LIVE PROGRESS", exact=True)).to_be_visible()
            expect(page.get_by_text("missions completed")).to_have_count(0)
            expect(page.get_by_text("Your game timeline")).to_have_count(0)
            self.assertEqual(
                page.locator("#player-timeline").evaluate(
                    "(element) => getComputedStyle(element).display"
                ),
                "flex",
            )
            expect(page.locator(".player-timeline-pending")).to_have_count(1)
            expect(page.locator(".player-timeline-pending")).to_contain_text("Mission 1")
            expect(page.locator("#player-timeline time")).to_have_count(0)
            pending_colors = page.locator(".player-timeline-pending").evaluate(
                "(element) => { const style = getComputedStyle(element.querySelector('div')); "
                "return [style.color, style.backgroundColor]; }"
            )
            self.assertNotEqual(pending_colors[0], pending_colors[1])
            page.get_by_role("button", name="API key").click()
            expect(page.get_by_role("dialog", name="Private API key")).to_be_visible()
            key_colors = page.locator("#player-api-key").evaluate(
                "(element) => { const style = getComputedStyle(element); "
                "return [style.color, style.backgroundColor]; }"
            )
            self.assertNotEqual(key_colors[0], key_colors[1])
            self.assertTrue(page.evaluate(
                "Boolean(localStorage.getItem('lost-in-the-city:amsterdam:api-key'))"
            ))
            page.reload()
            expect(page.get_by_text("Player: Browser Fox", exact=True)).to_be_visible()
            page.get_by_role("button", name="API key").click()
            page.get_by_role("button", name="Forget this player").click()
            expect(page.get_by_role("heading", name="Enter the city")).to_be_visible()
            self.assertFalse(page.evaluate(
                "Boolean(localStorage.getItem('lost-in-the-city:amsterdam:api-key'))"
            ))
            page.get_by_label("Nickname").fill("Browser Fox")
            page.get_by_role("button", name="Start game").click()
            page.wait_for_function(
                "Boolean(localStorage.getItem('lost-in-the-city:amsterdam:api-key'))"
            )
            expect(page.get_by_text("Player: Browser Fox", exact=True)).to_be_visible()
            expect(page.locator(".lesson-content")).to_contain_text("GAME_MCP_URL=https://mcp.example.test/amsterdam/mcp")
            browser_api_key = page.evaluate(
                "localStorage.getItem('lost-in-the-city:amsterdam:api-key')"
            )

            def add_browser_advice(player: dict) -> None:
                player_identity.append_timeline_event(
                    player,
                    "agent42",
                    "Agent42 route advice",
                    detail=(
                        "Weather: 14 C, light rain\n"
                        "Reasoning: The bike route is quickest.\n"
                        "recommendation: bike\n"
                        "recommendation code: abc123def456ghi"
                    ),
                    route_ref="abc123def456ghi",
                )

            storage.update_player("amsterdam", browser_api_key, add_browser_advice)
            route = {
                "mode": "bike",
                "origin": {"query": "Central Station"},
                "destination": {"query": "Museum Square"},
                "distance_km": 2.7,
                "travel_time_seconds": 660,
                "traffic_delay_seconds": 0,
            }
            with patch.object(
                dashboard.dashboard, "fetch_route", new=AsyncMock(return_value=route),
            ), patch.object(
                dashboard.dashboard,
                "fetch_route_asset",
                new=AsyncMock(return_value=b"\x89PNG\r\n"),
            ):
                page.reload()
                expect(page.locator("[data-agent42-event]")).to_be_visible()
                page.locator("[data-agent42-event]").click()
                agent42_dialog = page.get_by_role("dialog", name="Agent42 route advice")
                expect(agent42_dialog).to_be_visible()
                expect(agent42_dialog).to_contain_text("14 C, light rain")
                expect(agent42_dialog).to_contain_text("Central Station")
                expect(agent42_dialog).to_contain_text("The bike route is quickest.")
                expect(page.locator("#player-agent42-map")).to_have_attribute(
                    "src", re.compile(r"^blob:")
                )
                page.get_by_role("button", name="Close Agent42 details").click()
                expect(agent42_dialog).not_to_be_visible()
            for width in (1440, 900, 650, 390, 320):
                with self.subTest(width=width):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    expect(page.get_by_role("link", name="Next lesson")).to_be_visible()
            timeline_previous = page.get_by_role("button", name="Scroll timeline left")
            timeline_next = page.get_by_role("button", name="Scroll timeline right")
            expect(timeline_previous).to_be_visible()
            expect(timeline_previous).to_be_disabled()
            expect(timeline_next).to_be_visible()
            expect(timeline_next).to_be_enabled()
            timeline_next.click()
            expect(page.locator("#player-timeline")).not_to_have_js_property("scrollLeft", 0)
            page.get_by_role("link", name="Next lesson").click()
            expect(page).to_have_url(
                "https://instructions.test/amsterdam/player/04_use_the_player_api_key"
            )
            page.get_by_role("link", name="Previous lesson").click()
            expect(page).to_have_url("https://instructions.test/amsterdam/player/03_connect_to_the_gaming_mcp_server")
            self.assertEqual(errors, [])
            browser.close()
