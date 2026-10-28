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
            "city_guide": "# Amsterdam route guide\n\nThe trusted guide says the answer is ANSWER.",
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
        self.clock = patch.object(
            game_schedule,
            "utcnow",
            return_value=datetime(2026, 10, 5, 10, tzinfo=timezone.utc),
        )
        self.clock.start()
        self.addCleanup(self.clock.stop)
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
                self.assertIn("style-src 'self' 'unsafe-inline'", response.headers["content-security-policy"])
                self.assertNotIn("script-src", response.headers["content-security-policy"])
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
            self.assertIn('src="/player-assets/illustration-foundry-sign-in.webp"', foundry)
            self.assertEqual(client.get("/player-assets/illustration-foundry-sign-in.webp").status_code, 200)
            self.assertEqual(client.get("/static/css/player.css").status_code, 200)
            player_script = client.get("/static/js/player.js")
            self.assertEqual(player_script.status_code, 200)
            self.assertIn("Authorization: 'Bearer ' + apiKey", player_script.text)
            self.assertNotIn("******", player_script.text)
            self.assertEqual(client.get("/missing/player").status_code, 404)
            self.assertEqual(client.get("/amsterdam/player/README").status_code, 404)
            self.assertEqual(client.get("/amsterdam/player/").status_code, 200)
            guide = client.get("/amsterdam/guides/1/1.md")
            self.assertEqual(guide.status_code, 200)
            self.assertEqual(guide.text, "# Amsterdam route guide\n\nThe trusted guide says the answer is ANSWER.\n")
            self.assertEqual(guide.headers["content-type"], "text/markdown; charset=utf-8")
            self.assertIn('filename="test-route.md"', guide.headers["content-disposition"])
            self.assertEqual(client.get("/amsterdam/guides/1/missing.md").status_code, 404)
            legacy = client.get("/amsterdam/instructions", follow_redirects=False)
            self.assertEqual(legacy.status_code, 308)
            self.assertEqual(legacy.headers["location"], "/amsterdam/player")

    def test_player_instructions_are_not_sent_outside_play_window(self) -> None:
        with TestClient(dashboard.build_app()) as client:
            with patch.object(
                game_schedule,
                "utcnow",
                return_value=datetime(2026, 10, 4, 6, tzinfo=timezone.utc),
            ):
                scheduled = client.get(
                    "/amsterdam/player/00_step_into_your_workspace"
                )
                guide = client.get("/amsterdam/guides/1/1.md")
            self.assertEqual(scheduled.status_code, 200)
            self.assertIn("Player window is closed", scheduled.text)
            self.assertNotIn('class="lesson-content"', scheduled.text)
            self.assertNotIn('class="workshop-nav"', scheduled.text)
            self.assertNotIn('id="player-registration-form"', scheduled.text)
            self.assertNotIn('id="player-window-countdown"', scheduled.text)
            self.assertNotIn("/static/js/player.js", scheduled.text)
            self.assertEqual(guide.status_code, 403)
            self.assertIn("Player window is closed", guide.text)

            with patch.object(
                game_schedule,
                "utcnow",
                return_value=datetime(2026, 10, 4, 8, tzinfo=timezone.utc),
            ):
                countdown = client.get("/amsterdam/player")
            self.assertIn("Player window is closed", countdown.text)
            self.assertIn("Enter the city in", countdown.text)
            self.assertIn('data-seconds-until-start="82800"', countdown.text)
            self.assertIn("/static/js/player_window.js", countdown.text)
            self.assertNotIn('class="lesson-content"', countdown.text)

            with patch.object(
                game_schedule,
                "utcnow",
                return_value=datetime(2026, 10, 5, 17, tzinfo=timezone.utc),
            ):
                ended = client.get("/amsterdam/player")
            self.assertIn("Player window is closed", ended.text)
            self.assertNotIn("Enter the city in", ended.text)
            self.assertNotIn('class="lesson-content"', ended.text)

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
            self.assertEqual(payload["player"]["quest_name"], "Test route")
            self.assertEqual(payload["player"]["quest_question"], "What is the answer?")
            self.assertNotEqual(payload["player"]["player_id"], api_key)
            self.assertEqual(payload["player"]["timeline"][0]["type"], "registered")
            self.assertEqual(client.get("/api/games/amsterdam/player").status_code, 401)
            state = client.get(
                "/api/games/amsterdam/player",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            self.assertEqual(state.status_code, 200)
            self.assertNotIn(api_key, state.text)
            self.assertNotIn("valid_answers", state.text)
            self.assertEqual(state.json()["player"]["mission_count"], 1)

            self.assertEqual(state.json()["player"]["quest_question"], "What is the answer?")
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
            challenge = sorted(path.name for path in workshop_instructions.CHALLENGE_DIR.glob("[0-9][0-9]_*.md"))
            self.assertEqual(challenge, [
                "00_mission_1_get_ready_and_start_the_game.md",
                "01_mission_2_use_agent42_to_travel.md",
                "02_mission_3_solve_the_quest_with_foundry_iq.md",
                "03_arrived_complete_the_game.md",
            ])
            for chapter in workshop_instructions.CHALLENGE_DIR.glob("[0-9][0-9]_*.md"):
                chapter_response = client.get(f"/amsterdam/player/{chapter.stem}")
                self.assertEqual(chapter_response.status_code, 200, chapter_response.text)
                self.assertNotIn("Challenge mode", chapter_response.text)
                self.assertIn("Objectives", chapter_response.text)
                self.assertIn("Completion check", chapter_response.text)
                self.assertNotIn("{{", chapter_response.text)
            response = client.get("/amsterdam/player")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Challenge mode", response.text)
            self.assertIn("Chapter 1: Get Ready and Start the Game", response.text)
            self.assertIn("A published Amsterdam story from the quest document.", response.text)
            self.assertIn("Load the <code>game_play_prompt</code> instructions", response.text)
            self.assertIn("Next lesson", response.text)
            self.assertEqual(response.text.count('/amsterdam/player/'), 5)
            self.assertIn("GAME_MCP_URL=https://mcp.example.test/amsterdam/mcp", response.text)
            agent42 = client.get("/amsterdam/player/01_mission_2_use_agent42_to_travel")
            self.assertIn("AGENT42_URL=https://transport.example.test/", agent42.text)
            foundry_iq = client.get("/amsterdam/player/02_mission_3_solve_the_quest_with_foundry_iq")
            self.assertIn("Foundry IQ", foundry_iq.text)

    def test_guided_lessons_are_grouped_into_named_chapters(self) -> None:
        lessons = [
            {
                "slug": path.stem,
                "title": path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# "),
            }
            for path in sorted(workshop_instructions.GUIDED_DIR.glob("[0-9][0-9]_*.md"))
        ]
        missions = workshop_instructions.guided_mission_navigation(lessons)
        self.assertEqual(
            [(mission["label"], mission["name"], len(mission["lessons"])) for mission in missions],
            [
                ("Chapter 1", "Get Ready and Start the Game", 5),
                ("Chapter 2", "Travel with Agent42", 2),
                ("Chapter 3", "Build the City Guide", 3),
                ("Chapter 4", "Read the Secret Note", 2),
                ("Chapter 5", "Lab Recap", 1),
            ],
        )

        with TestClient(dashboard.build_app()) as client:
            response = client.get(
                "/amsterdam/player/06_test_agent42_transport_specialist"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count('class="workshop-nav-mission"'), 5)
        self.assertRegex(
            response.text,
            r'class="lesson-mission-heading">\s*<span>Chapter 2</span>\s*'
            r'<strong>Travel with Agent42</strong>',
        )
        self.assertEqual(response.text.count('aria-current="page"'), 1)

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
        self.assertEqual(
            workshop_instructions.render_lesson("Hi {{ player_name }}", {}),
            "<p>Hi <span data-player-name>player</span></p>\n",
        )
        self.assertEqual(
            workshop_instructions.render_lesson("{{ player_quest }}", {}),
            "<p><span data-player-quest>your quest</span></p>\n",
        )
        self.assertEqual(
            workshop_instructions.render_lesson("{{ player_quest_question }}", {}),
            "<p><span data-player-question>the question from your quest</span></p>\n",
        )
        self.assertEqual(
            workshop_instructions.render_lesson("{{ player_api_key }}", {}),
            "<p><span data-player-api-key>&lt;copy-from-this-player-page&gt;</span></p>\n",
        )
        panels = workshop_instructions.more_info_panels(
            '<a href="#more-mcp">a</a> <a href="#more-mcp">b</a> <a href="#more-foundry-iq">c</a>',
            {"game_name": "Lost in Testville", "game_city": "Testville"},
        )
        self.assertEqual([panel["slug"] for panel in panels], ["mcp", "foundry-iq"])
        self.assertEqual(panels[0]["title"], "MCP: Model Context Protocol")
        self.assertIn("<strong>Lost in Testville</strong>", panels[0]["content"])
        self.assertIn("Testville city guide", panels[1]["content"])
        with self.assertRaisesRegex(ValueError, "Unknown player read-more panel"):
            workshop_instructions.more_info_panels('<a href="#more-missing">x</a>', {})

    def test_game_prompt_panel_quotes_the_prompt_the_server_returns(self) -> None:
        import server

        panel = workshop_instructions.more_info_panels(
            '<a href="#more-game-prompt">prompt</a>', {"game_name": "Test City"},
        )[0]
        shown = re.search(r"<pre><code[^>]*>(.*?)</code></pre>", panel["content"], re.S).group(1)
        shown = shown.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
        self.assertEqual(shown, server._game_play_prompt_for({"display_name": "Test City"}).rstrip("\n") + "\n")
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
            expect(page.locator(".player-game-story")).to_have_text(
                "A published Amsterdam story from the quest document."
            )
            registration_layout = page.locator("#player-registration").evaluate(
                "(element) => { const style = getComputedStyle(element); "
                "return { textAlign: style.textAlign, width: element.getBoundingClientRect().width }; }"
            )
            self.assertEqual(registration_layout["textAlign"], "center")
            self.assertLessEqual(registration_layout["width"], 760)
            start_button = page.get_by_role("button", name="Start game")
            self.assertGreaterEqual(start_button.bounding_box()["height"], 64)
            page.get_by_label("Choose your nickname").fill("Browser Fox")
            start_button.click()
            expect(page.get_by_text("Player: Browser Fox", exact=True)).to_be_visible()
            expect(page.get_by_text("LIVE PROGRESS", exact=True)).to_have_count(0)
            progress_rail = page.get_by_role("complementary", name="Your Quest")
            timeline_shell = page.locator("#player-timeline-shell")
            expect(progress_rail).to_be_visible()
            expect(progress_rail.get_by_role("heading", name="Your Quest")).to_be_visible()
            expect(progress_rail.get_by_text("Click on the steps for more info.", exact=True)).to_be_visible()
            expect(page.locator("#player-progress-toggle")).to_have_count(0)
            expect(timeline_shell).to_be_visible()
            self.assertEqual(progress_rail.evaluate(
                "(element) => getComputedStyle(element).backgroundColor"
            ), "rgb(255, 255, 255)")
            self.assertEqual(progress_rail.bounding_box()["width"], 192)
            expect(page.locator(".workshop-header #player-progress")).to_have_count(0)
            self.assertLess(page.locator(".workshop-header").bounding_box()["height"], 120)
            nav_toggle = page.locator("#workshop-nav-toggle")
            chapter_nav = page.locator("#workshop-nav")
            nav_icon = nav_toggle.locator(".workshop-nav-toggle-icon")
            def toggle_with_animation(dimension: str) -> None:
                measurements = page.evaluate(
                    """(dimension) => {
                        const layout = document.getElementById('player-content');
                        const sidebar = layout.querySelector('.workshop-sidebar');
                        const size = () => sidebar.getBoundingClientRect()[dimension];
                        const before = size();
                        document.getElementById('workshop-nav-toggle').click();
                        const animations = layout.getAnimations({subtree: true});
                        const durations = animations.map(animation =>
                            animation.effect.getTiming().duration);
                        for (const animation of animations) {
                            animation.pause();
                            animation.currentTime = animation.effect.getTiming().duration / 2;
                        }
                        const middle = size();
                        for (const animation of animations) animation.finish();
                        return {before, middle, after: size(), durations};
                    }""",
                    dimension,
                )
                self.assertIn(240, measurements["durations"])
                self.assertGreater(
                    measurements["middle"], min(measurements["before"], measurements["after"])
                )
                self.assertLess(
                    measurements["middle"], max(measurements["before"], measurements["after"])
                )

            expect(nav_toggle).to_have_attribute("aria-expanded", "false")
            expect(chapter_nav).to_have_js_property("inert", True)
            expect(nav_toggle).to_have_attribute("aria-label", "Show chapters")
            expect(nav_toggle).to_have_attribute("title", "Show chapters")
            expect(nav_toggle).to_have_text("")
            expect(chapter_nav).to_be_hidden()
            self.assertEqual(
                nav_icon.evaluate("(element) => getComputedStyle(element, '::before').content"),
                '"\u203a"',
            )
            toggle_with_animation("width")
            expect(chapter_nav).to_be_visible()
            expect(chapter_nav).to_have_js_property("inert", False)
            expect(nav_toggle).to_have_attribute("aria-expanded", "true")
            expect(nav_toggle).to_have_attribute("aria-label", "Hide chapters")
            expect(nav_toggle).to_have_attribute("title", "Hide chapters")
            self.assertEqual(
                nav_icon.evaluate("(element) => getComputedStyle(element, '::before').content"),
                '"\u2039"',
            )
            page.reload()
            expect(chapter_nav).to_be_visible()
            expect(nav_toggle).to_have_attribute("aria-expanded", "true")
            nav_toggle.focus()
            page.keyboard.press("Enter")
            expect(chapter_nav).to_be_hidden()
            page.reload()
            expect(chapter_nav).to_be_hidden()
            expect(nav_toggle).to_have_attribute("aria-expanded", "false")
            expect(nav_toggle).to_have_attribute("title", "Show chapters")
            page.evaluate("localStorage.setItem('lost-in-the-city:progress-collapsed', 'true')")
            page.reload()
            expect(page.get_by_text("Player: Browser Fox", exact=True)).to_be_visible()
            expect(chapter_nav).to_be_hidden()
            expect(timeline_shell).to_be_visible()
            expect(timeline_shell).to_have_js_property("inert", False)
            page.emulate_media(reduced_motion="reduce")
            nav_toggle.click()
            expect(chapter_nav).to_be_visible()
            self.assertEqual(page.locator("#player-content").evaluate(
                "(element) => element.getAnimations({subtree: true}).length"
            ), 0)
            nav_toggle.click()
            expect(chapter_nav).to_be_hidden()
            expect(timeline_shell).to_be_visible()
            page.emulate_media(reduced_motion="no-preference")
            expect(page.get_by_text("missions completed")).to_have_count(0)
            expect(page.get_by_text("Your game timeline")).to_have_count(0)
            expect(page.locator(".player-timeline-label")).to_have_text(["Start", "Quest step 1", "End"])
            expect(page.locator(".player-timeline-pending-end")).to_have_count(1)
            path_style = page.locator(".player-timeline-connector").first.evaluate(
                "(element) => { const style = getComputedStyle(element); "
                "return {dash: style.strokeDasharray, cap: style.strokeLinecap}; }"
            )
            self.assertEqual(path_style, {"dash": "1px, 6px", "cap": "round"})
            marker_alignment = page.locator(".player-timeline-event").first.evaluate(
                """(element) => {
                    const marker = element.querySelector('.player-timeline-marker').getBoundingClientRect();
                    const next = element.nextElementSibling.querySelector('.player-timeline-marker').getBoundingClientRect();
                    const path = element.querySelector('path');
                    const start = path.getPointAtLength(0).matrixTransform(path.getScreenCTM());
                    const end = path.getPointAtLength(path.getTotalLength()).matrixTransform(path.getScreenCTM());
                    return {
                        startX: Math.abs(marker.left + marker.width / 2 - start.x),
                        startY: Math.abs(marker.top + marker.height / 2 - start.y),
                        endX: Math.abs(next.left + next.width / 2 - end.x),
                        endY: Math.abs(next.top + next.height / 2 - end.y),
                        verticalDistance: next.top - marker.top,
                    };
                }"""
            )
            for coordinate in ("startX", "startY", "endX", "endY"):
                self.assertLessEqual(marker_alignment[coordinate], .5)
            self.assertEqual(marker_alignment["verticalDistance"], 64)
            expect(page.locator(".player-timeline-pending")).to_have_count(1)
            expect(page.locator(".player-timeline-pending .player-timeline-dot")).to_have_attribute(
                "aria-label", "Quest step 1. Not completed yet."
            )
            expect(page.locator(".player-timeline-pending .player-timeline-dot")).to_have_attribute(
                "title", "Quest step 1. Not completed yet."
            )
            expect(page.locator("#player-timeline time")).to_have_count(0)
            expect(page.locator("#player-timeline button[aria-haspopup='dialog']")).to_have_count(3)
            milestone_dialog = page.locator("#player-milestone-dialog")
            for title, detail in (
                ("Start", "Your adventure begins here."),
                ("Quest step 1", "Not completed yet."),
                ("End", "Your final destination."),
            ):
                trigger = page.locator(".player-timeline-dot").filter(has_text=title)
                trigger.locator(".player-timeline-label").click()
                expect(milestone_dialog).to_be_visible()
                expect(milestone_dialog.get_by_role("heading", name=title, exact=True)).to_be_visible()
                expect(milestone_dialog).to_contain_text(detail)
                page.keyboard.press("Escape")
                expect(milestone_dialog).not_to_be_visible()
                expect(trigger).to_be_focused()
            page.keyboard.press("Enter")
            expect(milestone_dialog).to_be_visible()
            page.get_by_role("button", name="Close milestone details").click()
            expect(milestone_dialog).not_to_be_visible()
            page.keyboard.press("Tab")
            page.locator(".player-timeline-dot").first.focus()
            page.keyboard.press("Space")
            expect(milestone_dialog).to_be_visible()
            page.mouse.click(1, 1)
            expect(milestone_dialog).not_to_be_visible()
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
            page.get_by_label("Choose your nickname").fill("Browser Fox")
            page.get_by_role("button", name="Start game").click()
            page.wait_for_function(
                "Boolean(localStorage.getItem('lost-in-the-city:amsterdam:api-key'))"
            )
            expect(page.get_by_text("Player: Browser Fox", exact=True)).to_be_visible()
            expect(page.locator(".lesson-content")).to_contain_text("GAME_MCP_URL=https://mcp.example.test/amsterdam/mcp")
            browser_api_key = page.evaluate(
                "localStorage.getItem('lost-in-the-city:amsterdam:api-key')"
            )
            expect(page.locator(".workshop-nav-mission-heading strong", has_text="Lab Recap")).to_have_count(1)
            expect(page.locator("[data-player-quest-question]")).to_have_count(0)

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
                page.locator("[data-agent42-event] .player-timeline-label").click()
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
                    toggle_with_animation("height" if width <= 900 else "width")
                    expect(chapter_nav).to_be_visible()
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    toggle_with_animation("height" if width <= 900 else "width")
                    expect(chapter_nav).to_be_hidden()
                    rail_box = progress_rail.bounding_box()
                    lesson_box = page.locator("#player").bounding_box()
                    self.assertGreaterEqual(rail_box["x"], lesson_box["x"] + lesson_box["width"] - 1)
                    self.assertLessEqual(rail_box["x"] + rail_box["width"], width)
                    for endpoint in (
                        page.locator(".player-timeline-label").first,
                        page.locator(".player-timeline-label").last,
                    ):
                        expect(endpoint).to_be_visible()
                        self.assertFalse(endpoint.evaluate(
                            "(element) => element.scrollWidth > element.clientWidth"
                        ))
                    label_style = page.locator(".player-timeline-label").nth(1).evaluate(
                        "(element) => { const style = getComputedStyle(element); "
                        "return {whitespace: style.whiteSpace, overflow: style.textOverflow}; }"
                    )
                    self.assertEqual(label_style, {"whitespace": "nowrap", "overflow": "ellipsis"})
                    expect(timeline_shell).to_be_visible()
                    expect(progress_rail.get_by_role("heading", name="Your Quest")).to_be_visible()
                    page.locator(".player-timeline-label").first.click()
                    expect(milestone_dialog).to_be_visible()
                    self.assertLessEqual(milestone_dialog.bounding_box()["width"], width)
                    page.get_by_role("button", name="Close milestone details").click()

            def add_long_timeline(player: dict) -> None:
                for index in range(20):
                    player_identity.append_timeline_event(
                        player, "mission_complete", f"Completed stage {index + 1}",
                        detail="Read <b>the sign</b> & continue.",
                    )

            storage.update_player("amsterdam", browser_api_key, add_long_timeline)
            page.reload()
            expect(page.locator(".player-timeline-dot")).to_have_count(24)
            page.locator(".player-timeline-dot").filter(has_text="Completed stage 1").first.click()
            expect(page.locator("#player-milestone-detail")).to_have_text("Read <b>the sign</b> & continue.")
            expect(milestone_dialog.locator("b")).to_have_count(0)
            page.get_by_role("button", name="Close milestone details").click()
            self.assertTrue(timeline_shell.evaluate(
                "(element) => element.scrollHeight > element.clientHeight"
            ))
            page.locator(".player-timeline-dot").last.focus()
            expect(timeline_shell).not_to_have_js_property("scrollTop", 0)
            with page.expect_response(re.compile(r"/api/games/amsterdam/player$")):
                pass
            expect(page.locator(".player-timeline-dot").last).to_be_focused()
            def complete_adventure(player: dict) -> None:
                player_identity.append_timeline_event(
                    player, "mission_complete", "Mission 1 complete", mission_index=0,
                )
                player["status"] = "complete"

            storage.update_player("amsterdam", browser_api_key, complete_adventure)
            expect(page.locator(".player-timeline-pending")).to_have_count(0)
            expect(page.locator(".player-timeline-dot").nth(-2)).to_have_attribute(
                "aria-label", "Quest step 1 complete"
            )
            expect(page.locator(".player-timeline-dot").last).to_have_attribute(
                "aria-label", "End. Adventure completed."
            )
            expect(page.locator(".player-timeline-end")).to_have_count(1)
            expect(page.locator(".player-timeline-label").first).to_have_text("Start")
            expect(page.locator(".player-timeline-label").last).to_have_text("End")
            expect(page.get_by_role("button", name="Scroll timeline left")).to_have_count(0)
            page.get_by_role("link", name="Next lesson").click()
            expect(page).to_have_url(
                "https://instructions.test/amsterdam/player/05_add_session_logging"
            )
            page.get_by_role("link", name="Previous lesson").click()
            expect(page).to_have_url("https://instructions.test/amsterdam/player/03_connect_to_the_gaming_mcp_server")
            self.assertEqual(errors, [])
            browser.close()
