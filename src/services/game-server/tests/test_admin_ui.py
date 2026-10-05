"""Browser regressions for the admin UI using deterministic API fixtures."""
from __future__ import annotations

import json
import copy
import re
import sys
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import Browser, Page, Playwright, Route, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quest_validation import validate_document
from game_schedule import GameSchedule, game_availability, local_fields
ORIGIN = "https://admin.test"


class AdminUITests(unittest.TestCase):
    playwright: Playwright
    browser: Browser
    page: Page

    @classmethod
    def setUpClass(cls) -> None:
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.page = self.context.new_page()
        self.errors: list[str] = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.templates = Environment(
            loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape()
        )
        self.games = [{"slug": "san-francisco", "event_name": "Open Hack",
                       "display_name": "Lost in San Francisco",
                       "city": "San Francisco", "created_at": "2026-01-01T12:00:00Z"}]
        self.quests = json.loads((ROOT / "quests.json").read_text())
        self.draft = copy.deepcopy(self.quests)
        self.revision = 1
        self.version = 1
        self.versions = [1]
        self.players = {
            "player-1": {"name": "<img src=x onerror=alert(1)>", "status": "complete", "score": 100, "quest_id": 1},
            "player-2": {"name": "Explorer", "status": "mission", "score": 0, "quest_id": 1},
        }
        self.requests: list[tuple[str, str, object]] = []
        self.fail_games = False
        self.create_error: tuple[int, str] | None = None
        self.created_slug: str | None = None
        self.schedule_conflict = False
        self.page.route(f"{ORIGIN}/**", self.serve)

    def tearDown(self) -> None:
        self.context.close()
        self.assertEqual(self.errors, [])

    def serve(self, route: Route) -> None:
        path = route.request.url.removeprefix(ORIGIN)
        method = route.request.method
        if path.startswith("/static/"):
            file = ROOT / path.lstrip("/")
            content_type = "text/css" if file.suffix == ".css" else "application/javascript"
            route.fulfill(body=file.read_text(), content_type=content_type)
            return
        if path.startswith("/api/"):
            payload = route.request.post_data_json if route.request.post_data else None
            self.requests.append((method, path, payload))
            if method != "GET" and path != "/api/auth/login":
                self.assertEqual(route.request.headers.get("x-csrf-token"), "test-csrf")
            if path == "/api/games":
                if self.fail_games:
                    route.fulfill(status=503, json={"detail": "Storage unavailable"})
                    return
                if method == "POST":
                    if self.create_error:
                        status, detail = self.create_error
                        route.fulfill(status=status, json={"detail": detail})
                        return
                    if any(game["slug"] == payload["slug"] for game in self.games):
                        route.fulfill(status=409, json={"detail": "A game with this slug already exists"})
                        return
                    if (not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", payload["slug"])
                            or payload["slug"] == "new" or not payload["display_name"].strip()
                            or not payload["city"].strip()):
                        route.fulfill(status=422, json={"detail": "Invalid game name or slug"})
                        return
                    game = {**payload, "slug": self.created_slug or payload["slug"]}
                    self.games.append(game)
                    route.fulfill(json={"ok": True, "game": game})
                else:
                    route.fulfill(json={"games": self.games})
            elif path == "/api/maps/config":
                route.fulfill(status=503, json={"detail": "Maps are not configured. Set AZURE_MAPS_KEY on the admin service."})
            elif path.endswith("/schedule"):
                if self.schedule_conflict:
                    route.fulfill(status=409, json={"detail": "The schedule changed. Reload before saving."})
                    return
                game = next(game for game in self.games if game["slug"] == path.split("/")[3])
                game["event_name"] = payload.get("event_name", game.get("event_name", ""))
                game["display_name"] = payload.get("display_name", game["display_name"])
                schedule = GameSchedule.model_validate({
                    key: value for key, value in payload.items()
                    if key not in {"revision", "event_name", "display_name"}
                })
                game.update(schedule.storage_fields(), schedule_revision=payload["revision"] + 1)
                route.fulfill(json={"ok": True, "game": game, "availability": game_availability(game)})
            elif path.startswith("/api/maps/geocode"):
                route.fulfill(json={"candidates": [{"label": "Verified address", "lat": 37.8, "lng": -122.4, "confidence": "High"}]})
            elif path.endswith("/draft"):
                if method == "PUT":
                    if payload["revision"] != self.revision:
                        route.fulfill(status=409, json={"detail": "Someone else changed this draft. Export your edits, then reload."})
                        return
                    self.draft = payload["document"]
                    self.revision += 1
                route.fulfill(json=self.draft_response())
            elif path.endswith("/validate"):
                route.fulfill(json=validate_document(payload["document"], publish=payload.get("publish", False)))
            elif path.endswith("/publish"):
                self.quests = copy.deepcopy(self.draft)
                self.version += 1
                self.versions.insert(0, self.version)
                self.revision += 1
                route.fulfill(json=self.draft_response())
            elif path.endswith("/activity"):
                players = [{
                    "player_id": pid, "name": p["name"], "game_version": p.get("game_version", 1),
                    "quest_id": 1, "quest_name": self.quests["quests"][0]["name"],
                    "status": p["status"], "current_mission_index": 0,
                    "current_mission_id": "mission-to-hayes-valley", "mission_count": 3,
                    "answer_attempts": 0, "score": p["score"], "location": None,
                } for pid, p in self.players.items()]
                route.fulfill(json={"players": players, "published_version": self.version,
                                    "versions": [{"version": version} for version in self.versions],
                                    "documents": {str(version): self.quests for version in self.versions}})
            elif path.endswith("/versions") and method == "GET":
                route.fulfill(json={
                    "published_version": self.version,
                    "versions": [{
                        "version": version,
                        "player_count": len(self.players) if version == 1 else 0,
                    } for version in self.versions],
                })
            elif "/versions/" in path and method == "DELETE":
                version = int(path.rsplit("/", 1)[-1])
                if version == self.version:
                    route.fulfill(status=409, json={"detail": "The current published version cannot be deleted."})
                elif version == 1 and self.players:
                    route.fulfill(status=409, json={"detail": "Reset those players first."})
                elif version not in self.versions:
                    route.fulfill(status=404, json={"detail": f"Version {version} does not exist."})
                else:
                    self.versions.remove(version)
                    route.fulfill(json={"ok": True})
            elif path.endswith("/quests"):
                if method == "PUT":
                    self.quests = payload
                    route.fulfill(json={"ok": True})
                else:
                    route.fulfill(json=self.quests)
            elif path.endswith("/quests/import-seed"):
                self.quests = {"quests": [{"id": 2, "name": "Seed quest", "missions": []}]}
                route.fulfill(json={"ok": True, "quests": self.quests})
            elif path.endswith("/leaderboard"):
                route.fulfill(json={"leaderboard": []})
            elif "/players" in path:
                if method == "DELETE":
                    if path.endswith("/players"):
                        self.players.clear()
                    else:
                        self.players.pop(path.rsplit("/", 1)[-1])
                    route.fulfill(json={"ok": True})
                else:
                    route.fulfill(json={"players": self.players})
            elif path == "/api/auth/login":
                route.fulfill(json={"ok": True, "redirect": "/password"})
            elif path in ("/api/auth/password", "/api/auth/logout"):
                route.fulfill(json={"ok": True, "redirect": "/login"})
            elif path.startswith("/api/games/") and method == "DELETE":
                self.games = [game for game in self.games if game["slug"] != path.rsplit("/", 1)[-1]]
                route.fulfill(json={"ok": True})
            else:
                route.fulfill(status=404, json={"detail": "Unknown fixture endpoint"})
            return
        template = {
            "/": "admin_home.html",
            "/login": "admin_login.html",
            "/password": "admin_password.html",
            "/games/new": "admin_create_game.html",
        }.get(path)
        game = None
        match = re.fullmatch(r"/games/([^/]+)(/(?:edit|settings))?", path)
        if not template and match:
            game = next((game for game in self.games if game["slug"] == match[1]), None)
            if game:
                if match[2] == "/settings":
                    route.fulfill(status=303, headers={"Location": f"/games/{game['slug']}/edit"})
                    return
                template = {"/edit": "admin_editor.html", None: "admin_game.html"}[match[2]]
        if not template:
            route.fulfill(status=404, body="Not found")
            return
        context = {
            "csrf_token": "test-csrf",
            "must_change_password": True,
            "game": game,
            "game_server_url": "https://mcp.example.test",
            "dashboard_url": "https://dashboard.example.test",
            "game_page": "edit" if path.endswith("/edit") else "dashboard",
            "schedule": local_fields(game or {}),
            "availability": game_availability(game or {}),
            "timezones": ["UTC", "Europe/Amsterdam", "America/Los_Angeles"],
        }
        if path != "/login":
            context["username"] = "admin"
        route.fulfill(
            body=self.templates.get_template(template).render(**context),
            content_type="text/html",
        )

    def draft_response(self) -> dict:
        return {
            "document": self.draft, "revision": self.revision, "published_version": self.version,
            "dirty": self.draft != self.quests, "versions": [{"version": self.version}],
            **validate_document(self.draft, publish=True),
        }

    def test_home_create_and_compact_mobile_layout(self) -> None:
        self.page.goto(ORIGIN)
        expect(self.page.locator(".game-card")).to_have_count(1)
        card = self.page.locator(".game-card").first
        expect(card.locator(".mode-pill")).to_have_text("Guided mode")
        expect(card.locator("button, .game-icon, .card-endpoint, .card-created")).to_have_count(0)
        expect(card).not_to_contain_text("MCP ENDPOINT")
        expect(card).not_to_contain_text("Created")
        self.assertEqual(card.get_by_role("link", name="Manage").get_attribute("href"), "/games/san-francisco")
        self.assertEqual(card.get_by_role("link", name="Player").get_attribute(
            "href"
        ), "https://dashboard.example.test/san-francisco/player")
        self.assertEqual(card.get_by_role("link", name="Dashboard").get_attribute("href"), "https://dashboard.example.test/san-francisco/dashboard")
        self.assertTrue(self.page.locator("#games").evaluate("""grid => {
            const gap = parseFloat(getComputedStyle(grid).columnGap);
            return Math.abs(grid.firstElementChild.getBoundingClientRect().width * 2
                + gap - grid.getBoundingClientRect().width) < 1;
        }"""))
        expect(self.page.locator("#new-game-form")).to_have_count(0)
        self.page.get_by_role("main").get_by_role("link", name="Create a game", exact=True).click()
        expect(self.page).to_have_url(f"{ORIGIN}/games/new")
        expect(self.page.get_by_role("heading", name="Start with a draft.")).to_be_visible()
        self.page.get_by_label("Event name", exact=True).fill("Open Hack")
        self.page.get_by_label("Challenge name", exact=True).fill("Evening adventure")
        self.page.get_by_label("City", exact=True).fill("Amsterdam")
        self.page.get_by_label("URL slug").fill("evening")
        self.created_slug = "evening-created"
        self.page.get_by_role("button", name="Create game").click()
        expect(self.page).to_have_url(f"{ORIGIN}/games/evening-created/edit")
        expect(self.page.get_by_role("heading", name="Evening adventure", exact=True)).to_be_visible()
        self.assertIn(("POST", "/api/games", {
            "slug": "evening", "event_name": "Open Hack",
            "display_name": "Evening adventure", "city": "Amsterdam",
            "starts_at": None, "ends_at": None, "timezone": "UTC", "player_mode": "guided",
        }), self.requests)
        self.page.goto(ORIGIN)
        expect(self.page.locator(".game-card")).to_have_count(2)
        boxes = self.page.locator(".game-card").evaluate_all(
            "cards => cards.map(card => { const r = card.getBoundingClientRect(); return {top: r.top, width: r.width}; })"
        )
        self.assertAlmostEqual(boxes[0]["top"], boxes[1]["top"], delta=1)
        self.assertAlmostEqual(boxes[0]["width"], boxes[1]["width"], delta=1)
        expect(self.page.locator(".game-card button")).to_have_count(0)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        self.assertTrue(self.page.locator("#games").evaluate("""grid => {
            const cards = [...grid.children].map(card => card.getBoundingClientRect());
            return Math.abs(cards[0].width - grid.getBoundingClientRect().width) < 1
                && cards[1].top >= cards[0].bottom;
        }"""))
        self.assertFalse(any(method == "DELETE" for method, _, _ in self.requests))

    def test_empty_home_create_cancel_and_mobile_layout(self) -> None:
        self.games = []
        self.page.goto(ORIGIN)
        self.page.get_by_role("link", name="Create your first game", exact=True).click()
        expect(self.page).to_have_url(f"{ORIGIN}/games/new")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        expect(self.page.get_by_label("Event name", exact=True)).to_be_visible()
        expect(self.page.get_by_label("Challenge name", exact=True)).to_be_visible()
        expect(self.page.get_by_label("City", exact=True)).to_be_visible()
        expect(self.page.get_by_label("URL slug")).to_be_visible()
        self.page.get_by_label("Event name", exact=True).fill("Open Hack")
        self.page.get_by_label("Challenge name", exact=True).fill("Not created")
        self.page.get_by_role("link", name="Cancel", exact=True).click()
        expect(self.page).to_have_url(f"{ORIGIN}/")
        self.assertFalse(any(method == "POST" for method, _, _ in self.requests))
        self.page.get_by_role("main").get_by_role("link", name="Create a game", exact=True).click()
        self.page.get_by_role("main").get_by_role("link", name="All games").click()
        expect(self.page).to_have_url(f"{ORIGIN}/")

    def test_schedule_settings_save_and_conflict_preserve_fields(self) -> None:
        self.games[0]["schedule_revision"] = 0
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.get_by_role("navigation", name="Game pages").get_by_role("link")).to_have_count(2)
        expect(self.page.get_by_label("City used in attendee instructions")).to_have_count(0)
        expect(self.page.get_by_label("Event name", exact=True)).to_have_value("Open Hack")
        expect(self.page.get_by_label("Challenge name", exact=True)).to_have_value("Lost in San Francisco")
        self.page.get_by_label("Event name", exact=True).fill("Ignite Open Hack")
        self.page.get_by_label("Challenge name", exact=True).fill("Lost across San Francisco")
        self.page.get_by_label("Start date and time").fill("2026-10-06T09:00")
        self.page.get_by_label("End date and time").fill("2026-10-06T17:00")
        self.page.get_by_label("Timezone", exact=True).fill("Europe/Amsterdam")
        self.page.get_by_label("Player mode").select_option("challenge")
        self.page.get_by_role("button", name="Save settings").click()
        expect(self.page.locator("#notice")).to_contain_text("Game settings saved")
        self.assertEqual(self.games[0]["city"], "San Francisco")
        self.assertEqual(self.games[0]["event_name"], "Ignite Open Hack")
        self.assertEqual(self.games[0]["display_name"], "Lost across San Francisco")
        self.assertEqual(self.games[0]["starts_at"], "2026-10-06T07:00:00+00:00")
        self.assertEqual(self.games[0]["player_mode"], "challenge")
        self.assertEqual(self.games[0]["schedule_revision"], 1)
        expect(self.page.locator("[data-player-mode]").first).to_have_text("Challenge mode")
        self.assertEqual(self.page.get_by_role("link", name="Open player").get_attribute("href"),
                         "https://dashboard.example.test/san-francisco/player")
        self.schedule_conflict = True
        self.page.get_by_label("End date and time").fill("2026-10-06T18:00")
        self.page.get_by_role("button", name="Save settings").click()
        expect(self.page.locator("#schedule-error")).to_contain_text("Reload")
        expect(self.page.get_by_label("End date and time")).to_have_value("2026-10-06T18:00")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))

    def test_create_duplicate_preserves_fields_and_can_retry(self) -> None:
        self.page.goto(f"{ORIGIN}/games/new")
        self.page.get_by_label("Event name", exact=True).fill("Open Hack")
        self.page.get_by_label("Challenge name", exact=True).fill("My new adventure")
        self.page.get_by_label("City", exact=True).fill("Amsterdam")
        self.page.get_by_label("URL slug").fill("san-francisco")
        self.page.get_by_role("button", name="Create game").click()
        expect(self.page.locator("#add-status")).to_have_text("A game with this slug already exists")
        expect(self.page.locator("#add-status")).to_be_visible()
        expect(self.page).to_have_url(f"{ORIGIN}/games/new")
        expect(self.page.get_by_label("Event name", exact=True)).to_have_value("Open Hack")
        expect(self.page.get_by_label("Challenge name", exact=True)).to_have_value("My new adventure")
        expect(self.page.get_by_label("City", exact=True)).to_have_value("Amsterdam")
        expect(self.page.get_by_label("URL slug")).to_have_value("san-francisco")
        expect(self.page.get_by_role("button", name="Create game")).to_be_enabled()
        self.assertEqual(len(self.games), 1)
        self.page.get_by_label("URL slug").fill("my-adventure")
        self.page.get_by_role("button", name="Create game").click()
        expect(self.page).to_have_url(f"{ORIGIN}/games/my-adventure/edit")

    def test_create_errors_preserve_fields_and_can_retry(self) -> None:
        for status, detail in ((422, "Invalid game name or slug"), (503, "Storage unavailable")):
            with self.subTest(status=status):
                self.create_error = (status, detail)
                self.page.goto(f"{ORIGIN}/games/new")
                name, slug = f"Adventure {status}", f"adventure-{status}"
                self.page.get_by_label("Event name", exact=True).fill("Open Hack")
                self.page.get_by_label("Challenge name", exact=True).fill(name)
                self.page.get_by_label("City", exact=True).fill("Amsterdam")
                self.page.get_by_label("URL slug").fill(slug)
                self.page.get_by_role("button", name="Create game").click()
                expect(self.page.locator("#add-status")).to_have_text(detail)
                expect(self.page.locator("#add-status")).to_be_visible()
                expect(self.page).to_have_url(f"{ORIGIN}/games/new")
                expect(self.page.get_by_label("Challenge name", exact=True)).to_have_value(name)
                expect(self.page.get_by_label("URL slug")).to_have_value(slug)
                expect(self.page.get_by_role("button", name="Create game")).to_be_enabled()
                self.create_error = None
                self.page.get_by_role("button", name="Create game").click()
                expect(self.page).to_have_url(f"{ORIGIN}/games/{slug}/edit")

    def test_errors_are_visible_and_refresh_recovers(self) -> None:
        self.fail_games = True
        self.page.goto(ORIGIN)
        expect(self.page.locator("#games")).to_contain_text("Storage unavailable")
        self.fail_games = False
        self.page.get_by_role("button", name="Refresh", exact=True).click()
        expect(self.page.locator(".game-card")).to_have_count(1)

    def test_light_theme_palette_has_readable_text_contrast(self) -> None:
        self.page.goto(ORIGIN)
        expect(self.page.locator(".game-card")).to_have_count(1)
        palette = self.page.evaluate("""() => {
            const style = getComputedStyle(document.documentElement);
            return Object.fromEntries(
                ['bg', 'panel', 'ink', 'muted', 'accent', 'cyan', 'danger',
                 'action', 'action-hover', 'soft', 'warm', 'success', 'error']
                .map(name => [name, style.getPropertyValue('--' + name).trim()])
            );
        }""")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.documentElement).colorScheme"), "light")

        def luminance(color: str) -> float:
            channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
            return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))

        pairs = [(text, surface) for text in ("ink", "muted", "accent", "cyan")
                 for surface in ("bg", "panel", "soft", "warm", "success")]
        pairs += [("ink", "action"), ("ink", "action-hover"), ("muted", "action"), ("danger", "error")]
        for text, surface in pairs:
            with self.subTest(text=text, surface=surface):
                light, dark = sorted((luminance(palette[text]), luminance(palette[surface])), reverse=True)
                self.assertGreaterEqual((light + .05) / (dark + .05), 4.5)

    def test_dashboard_player_resets_and_escaped_names(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco")
        expect(self.page.get_by_role("main").get_by_role("link", name="All games")).to_have_count(0)
        expect(self.page.get_by_text("Follow the players. Run the room.")).to_have_count(0)
        expect(self.page.locator("#dashboard-version")).to_have_text("Live · Version 1")
        self.page.get_by_role("button", name="Game assets").click()
        expect(self.page.locator("#game-assets-dialog")).to_be_visible()
        expect(self.page.locator(".game-asset")).to_have_count(3)
        expect(self.page.get_by_role("heading", name="MCP", exact=True)).to_be_visible()
        expect(self.page.get_by_role("link", name="Open player")).to_have_attribute(
            "href", "https://dashboard.example.test/san-francisco/player"
        )
        expect(self.page.get_by_role("link", name="Open display")).to_have_attribute(
            "href", "https://dashboard.example.test/san-francisco/dashboard"
        )
        self.page.get_by_role("button", name="Close", exact=True).click()
        expect(self.page.locator("#game-assets-dialog")).not_to_be_visible()
        expect(self.page.locator("#player-count")).to_have_text("2")
        expect(self.page.locator("#completed-count")).to_have_text("1")
        expect(self.page.locator("#players img")).to_have_count(0)
        expect(self.page.locator("#players")).to_contain_text("<img src=x onerror=alert(1)>")
        self.page.get_by_role("button", name="Explorer", exact=True).click()
        expect(self.page.locator("#player-detail")).to_contain_text("Version 1")
        self.page.get_by_role("button", name="Close", exact=True).click()
        self.page.get_by_role("button", name="Reset player Explorer", exact=True).click()
        self.page.locator("#confirm-action").click()
        expect(self.page.locator("#player-count")).to_have_text("1")
        self.page.get_by_text("Game controls & destructive actions", exact=True).click()
        self.page.get_by_role("button", name="Reset all players", exact=True).click()
        self.page.locator("#confirm-action").click()
        expect(self.page.locator("#player-count")).to_have_text("0")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))

    def test_dashboard_only_shows_latest_published_version(self) -> None:
        self.version = 2
        self.versions = [2, 1]
        self.players["player-1"]["game_version"] = 1
        self.players["player-2"]["game_version"] = 2

        self.page.goto(f"{ORIGIN}/games/san-francisco")

        expect(self.page.locator("#dashboard-version")).to_have_text("Live · Version 2")
        expect(self.page.locator("#player-count")).to_have_text("1")
        expect(self.page.locator("#players")).to_contain_text("Explorer")
        expect(self.page.locator("#players")).not_to_contain_text("<img src=x onerror=alert(1)>")
        expect(self.page.locator("#players")).to_contain_text("Version 2")

    def test_historical_version_can_only_be_deleted_without_assigned_players(self) -> None:
        self.version = 2
        self.versions = [2, 1]
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#version-management")).to_have_value("2")
        expect(self.page.locator("#delete-version")).to_be_disabled()
        expect(self.page.locator("#version-delete-status")).to_contain_text("Current version")
        self.page.locator("#version-management").select_option("1")
        expect(self.page.locator("#delete-version")).to_be_disabled()
        expect(self.page.locator("#version-delete-status")).to_contain_text("2 players are assigned")
        self.players.clear()
        self.page.reload()
        expect(self.page.locator("#version-management")).to_have_value("2")
        self.page.locator("#version-management").select_option("1")
        expect(self.page.locator("#delete-version")).to_be_enabled()
        self.page.locator("#delete-version").click()
        self.page.locator("#confirm-action").click()
        expect(self.page.locator("#notice")).to_contain_text("Version 1 deleted")
        expect(self.page.locator("#version-management").locator('option[value="1"]')).to_have_count(0)
        expect(self.page.locator("#version-management")).to_have_value("2")

    def test_story_edit_save_publish_preview_and_mobile(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#draft-title")).to_have_text("Draft / live version 1")
        expect(self.page.locator(".mission-card")).to_have_count(3)
        expect(self.page.locator(".travel-card .route-map-preview")).to_have_count(2)
        expect(self.page.locator(".mission-progress")).to_have_count(3)
        expect(self.page.locator(".phase-start")).to_have_count(3)
        expect(self.page.locator(".phase-answer")).to_have_count(3)
        expect(self.page.locator(".phase-complete")).to_have_count(3)
        expect(self.page.locator(".completion-scene")).to_have_count(0)
        expect(self.page.locator(".question-card .answer-panel")).to_contain_text("Ritual Coffee Roasters")
        expect(self.page.locator(".route-map-state").first).to_contain_text("Maps are not configured")
        expect(self.page.get_by_role("group", name="Editor view")).to_have_count(0)
        expect(self.page.locator("#editor-map-panel")).to_have_count(0)
        self.page.locator(".quest-action-menu summary").click()
        self.page.locator(".quest-action-menu").get_by_role("button", name="Edit", exact=True).click()
        expect(self.page.locator("#scene-dialog")).to_be_visible()
        self.page.get_by_label("Quest name", exact=True).fill("A new story")
        self.page.get_by_role("button", name="Done", exact=True).click()
        expect(self.page.locator("#draft-status")).to_contain_text("Unsaved edits")
        expect(self.page.get_by_role("button", name="Publish", exact=True)).to_be_disabled()
        self.page.get_by_role("button", name="Save draft", exact=True).click()
        expect(self.page.locator("#draft-status")).to_contain_text("Unpublished changes")
        self.assertEqual(self.quests["quests"][0]["name"], "Mission to Moscone")
        self.page.get_by_role("button", name="Publish", exact=True).click()
        self.page.locator("#confirm-action").click()
        expect(self.page.locator("#draft-title")).to_have_text("Draft / live version 2")
        self.assertEqual(self.quests["quests"][0]["name"], "A new story")
        self.page.get_by_label("Story preview", exact=True).check()
        expect(self.page.locator(".card-actions:visible")).to_have_count(0)
        expect(self.page.locator(".answer-panel:visible")).to_have_count(0)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))

    def test_story_layout_is_responsive(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#draft-title")).to_have_text("Draft / live version 1")
        for width in (1033, 768, 1150, 1151, 1440, 650, 390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 635})
                expect(self.page.locator("#story-pane")).to_be_visible()
                self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))

    def test_import_preview_validation_cancel_and_export(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#import-json")).to_be_enabled()
        imported = copy.deepcopy(self.quests)
        imported["quests"][0]["name"] = "<script>alert('unsafe')</script>"
        imported["custom_metadata"] = {"preserve": True}
        upload = {"name": "story.json", "mimeType": "application/json", "buffer": json.dumps(imported).encode()}
        self.page.locator("#json-file").set_input_files(upload)
        expect(self.page.locator("#import-summary")).to_contain_text("3 quests / 9 missions")
        self.assertEqual(self.draft["quests"][0]["name"], "Mission to Moscone")
        self.page.locator("#import-dialog").get_by_role("button", name="Cancel").click()
        expect(self.page.locator("#import-json")).to_be_enabled()
        expect(self.page.locator("#save-draft")).to_be_disabled()
        self.page.locator("#json-file").set_input_files(upload)
        self.page.get_by_role("button", name="Replace editor draft").click()
        expect(self.page.locator(".quest-heading h2")).to_have_text(imported["quests"][0]["name"])
        expect(self.page.locator("#story-pane script")).to_have_count(0)
        with self.page.expect_download() as info:
            self.page.get_by_role("button", name="Export JSON").click()
        self.assertEqual(json.loads(Path(info.value.path()).read_text()), imported)
        self.page.locator("#json-file").set_input_files({"name": "bad.json", "mimeType": "application/json", "buffer": b'{"quests": [{"id": 1, "missions": "bad"}]}'})
        expect(self.page.locator("#validation-summary")).to_contain_text("missions must be an array")
        expect(self.page.locator("#import-dialog")).not_to_be_visible()

    def test_reorder_duplicate_geocode_and_conflict(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator(".mission-card")).to_have_count(3)
        second = self.page.locator(".mission-card").nth(1)
        second.locator(".action-menu summary").click()
        second.get_by_role("button", name="Move up", exact=True).click()
        expect(self.page.locator(".mission-card").first).to_have_class(re.compile("question-card"))
        first = self.page.locator(".mission-card").first
        first.locator(".action-menu summary").click()
        first.get_by_role("button", name="Duplicate", exact=True).click()
        expect(self.page.locator(".mission-card")).to_have_count(4)
        travel = self.page.locator(".travel-card").first
        travel.locator(".action-menu summary").click()
        travel.get_by_role("button", name="Edit", exact=True).click()
        expect(self.page.locator("#scene-dialog")).to_be_visible()
        self.page.locator("#scene-dialog").get_by_role("button", name="Look up address").first.click()
        expect(self.page.locator(".geocode-choice")).to_contain_text("Verified address")
        self.page.locator(".geocode-choice").click()
        document = json.loads(self.page.locator("#raw-quests").input_value())
        self.assertEqual(document["quests"][0]["missions"][2]["start_lat"], 37.8)
        self.revision += 1
        self.page.get_by_role("button", name="Save draft", exact=True).click()
        expect(self.page.locator("#notice")).to_contain_text("Someone else changed this draft")
        expect(self.page.locator("#draft-status")).to_contain_text("Unsaved edits")

    def test_map_points_deduplicate_and_never_guess_missing_coordinates(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#draft-title")).to_contain_text("Draft")
        document = copy.deepcopy(self.quests)
        del document["quests"][0]["missions"][0]["start_lat"]
        graph = self.page.evaluate("(doc) => GameMap.pointsFor(doc)", document)
        self.assertEqual(len(graph["missing"]), 1)
        self.assertTrue(any(len(point["members"]) > 1 for point in graph["points"]))
        filtered = self.page.evaluate("(doc) => GameMap.pointsFor(doc, '0')", document)
        self.assertEqual(len(filtered["legend"]), 1)
        self.assertEqual(len(filtered["lines"]), 1)

    def test_public_map_updates_versions_without_removing_player_markers(self) -> None:
        version = 1

        def serve_public(route: Route) -> None:
            if route.request.url.endswith("/data"):
                route.fulfill(json={"players": [], "leaderboard": [], "quest_versions": [version]})
            else:
                route.fulfill(json={"versions": [version], "quests": [{
                    "name": f"Story v{version}",
                    "points": [{"lat": 37.7, "lng": -122.4, "kind": "start",
                                "label": f"Version {version}", "address": "San Francisco"}],
                }]})

        self.page.goto(f"{ORIGIN}/login")
        self.page.route(f"{ORIGIN}/city/dashboard/*", serve_public)
        self.page.set_content(
            '<body data-slug="city" data-azure-maps-key="test-key">'
            '<div id="players"></div><div id="map"></div><div id="map-status"></div></body>'
        )
        self.page.evaluate("""() => {
            window.pins = [];
            window.atlas = {
                Map: class {
                    constructor() {
                        this.markers = {
                            add: marker => window.pins.push(marker),
                            remove: marker => { window.pins = window.pins.filter(pin => pin !== marker); }
                        };
                        this.events = {
                            add: (type, callback) => { if (type === 'ready') queueMicrotask(callback); },
                            remove: () => {}
                        };
                    }
                    setCamera() {}
                },
                HtmlMarker: class { constructor(options) { this.options = options; } },
                Popup: class { close() {} },
                data: { BoundingBox: { fromPositions: positions => positions } }
            };
        }""")
        self.page.add_script_tag(content=(ROOT / "static/js/dashboard.js").read_text())
        self.page.wait_for_function("window.pins.length === 1")
        self.assertIn("Version 1", self.page.evaluate("window.pins[0].options.htmlContent"))
        self.page.evaluate("window.pins.push({player: true})")
        version = 2
        self.page.evaluate("refreshDashboard()")
        self.assertEqual(self.page.evaluate("window.pins.length"), 2)
        self.assertIn("Version 2", self.page.evaluate("window.pins.find(pin => !pin.player).options.htmlContent"))
        self.assertTrue(self.page.evaluate("window.pins.some(pin => pin.player)"))

    def test_login_and_password_change_forms(self) -> None:
        self.page.goto(f"{ORIGIN}/login")
        self.page.get_by_label("Username", exact=True).fill("admin")
        self.page.get_by_label("Password", exact=True).fill("admin")
        self.page.get_by_role("button", name="Enter mission control").click()
        expect(self.page).to_have_url(f"{ORIGIN}/password")
        self.page.get_by_label("Current password", exact=True).fill("admin")
        self.page.get_by_label("New password", exact=True).fill("test-passphrase-123")
        self.page.get_by_label("Confirm new password", exact=True).fill("different-passphrase")
        self.page.get_by_role("button", name="Save password & sign out").click()
        self.assertFalse(any(path == "/api/auth/password" for _, path, _ in self.requests))
        self.page.get_by_label("Confirm new password", exact=True).fill("test-passphrase-123")
        self.page.get_by_role("button", name="Save password & sign out").click()
        expect(self.page).to_have_url(f"{ORIGIN}/login")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))


if __name__ == "__main__":
    unittest.main()
