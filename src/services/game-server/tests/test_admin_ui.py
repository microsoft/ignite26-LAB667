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
        self.games = [{"slug": "san-francisco", "display_name": "Lost in San Francisco", "created_at": "2026-01-01T12:00:00Z"}]
        self.quests = json.loads((ROOT / "quests.json").read_text())
        self.draft = copy.deepcopy(self.quests)
        self.revision = 1
        self.version = 1
        self.players = {
            "player-1": {"name": "<img src=x onerror=alert(1)>", "status": "complete", "score": 100, "quest_id": 1},
            "player-2": {"name": "Explorer", "status": "mission", "score": 0, "quest_id": 1},
        }
        self.requests: list[tuple[str, str, object]] = []
        self.fail_games = False
        self.create_error: tuple[int, str] | None = None
        self.created_slug: str | None = None
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
                            or payload["slug"] == "new" or not payload["display_name"].strip()):
                        route.fulfill(status=422, json={"detail": "Invalid game name or slug"})
                        return
                    game = {**payload, "slug": self.created_slug or payload["slug"]}
                    self.games.append(game)
                    route.fulfill(json={"ok": True, "game": game})
                else:
                    route.fulfill(json={"games": self.games})
            elif path == "/api/maps/config":
                route.fulfill(status=503, json={"detail": "Maps are not configured. Set AZURE_MAPS_KEY on the admin service."})
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
                self.revision += 1
                route.fulfill(json=self.draft_response())
            elif path.endswith("/activity"):
                players = [{
                    "player_id": pid, "name": p["name"], "game_version": 1,
                    "quest_id": 1, "quest_name": self.quests["quests"][0]["name"],
                    "status": p["status"], "current_mission_index": 0,
                    "current_mission_id": "mission-to-hayes-valley", "mission_count": 3,
                    "answer_attempts": 0, "score": p["score"], "location": None,
                } for pid, p in self.players.items()]
                route.fulfill(json={"players": players, "published_version": self.version,
                                    "versions": [{"version": self.version}], "documents": {str(self.version): self.quests}})
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
        match = re.fullmatch(r"/games/([^/]+)(/edit)?", path)
        if not template and match:
            game = next((game for game in self.games if game["slug"] == match[1]), None)
            if game:
                template = "admin_editor.html" if match[2] else "admin_game.html"
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

    def test_home_create_delete_and_mobile_layout(self) -> None:
        self.page.goto(ORIGIN)
        expect(self.page.locator(".game-card")).to_have_count(1)
        expect(self.page.locator("#new-game-form")).to_have_count(0)
        self.page.get_by_role("main").get_by_role("link", name="Create a game", exact=True).click()
        expect(self.page).to_have_url(f"{ORIGIN}/games/new")
        expect(self.page.get_by_role("heading", name="Start with a draft.")).to_be_visible()
        self.page.get_by_label("Game name", exact=True).fill("Evening adventure")
        self.page.get_by_label("URL slug").fill("evening")
        self.created_slug = "evening-created"
        self.page.get_by_role("button", name="Create game").click()
        expect(self.page).to_have_url(f"{ORIGIN}/games/evening-created/edit")
        expect(self.page.get_by_role("heading", name="Evening adventure", exact=True)).to_be_visible()
        self.assertIn(("POST", "/api/games", {"slug": "evening", "display_name": "Evening adventure"}), self.requests)
        self.page.get_by_role("main").get_by_role("link", name="All games").click()
        expect(self.page.locator(".game-card")).to_have_count(2)
        self.page.get_by_role("button", name="Delete Evening adventure").click()
        self.page.get_by_role("button", name="Cancel", exact=True).click()
        expect(self.page.locator(".game-card")).to_have_count(2)
        self.page.get_by_role("button", name="Delete Evening adventure").click()
        self.page.locator("#confirm-action").click()
        expect(self.page.locator(".game-card")).to_have_count(1)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        self.assertEqual(self.page.locator('a:has-text("Dashboard")').get_attribute("href"), "https://dashboard.example.test/san-francisco/dashboard")

    def test_empty_home_create_cancel_and_mobile_layout(self) -> None:
        self.games = []
        self.page.goto(ORIGIN)
        self.page.get_by_role("link", name="Create your first game", exact=True).click()
        expect(self.page).to_have_url(f"{ORIGIN}/games/new")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        expect(self.page.get_by_label("Game name", exact=True)).to_be_visible()
        expect(self.page.get_by_label("URL slug")).to_be_visible()
        self.page.get_by_label("Game name", exact=True).fill("Not created")
        self.page.get_by_role("link", name="Cancel", exact=True).click()
        expect(self.page).to_have_url(f"{ORIGIN}/")
        self.assertFalse(any(method == "POST" for method, _, _ in self.requests))
        self.page.get_by_role("main").get_by_role("link", name="Create a game", exact=True).click()
        self.page.get_by_role("main").get_by_role("link", name="All games").click()
        expect(self.page).to_have_url(f"{ORIGIN}/")

    def test_create_duplicate_preserves_fields_and_can_retry(self) -> None:
        self.page.goto(f"{ORIGIN}/games/new")
        self.page.get_by_label("Game name", exact=True).fill("My new adventure")
        self.page.get_by_label("URL slug").fill("san-francisco")
        self.page.get_by_role("button", name="Create game").click()
        expect(self.page.locator("#add-status")).to_have_text("A game with this slug already exists")
        expect(self.page.locator("#add-status")).to_be_visible()
        expect(self.page).to_have_url(f"{ORIGIN}/games/new")
        expect(self.page.get_by_label("Game name", exact=True)).to_have_value("My new adventure")
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
                self.page.get_by_label("Game name", exact=True).fill(name)
                self.page.get_by_label("URL slug").fill(slug)
                self.page.get_by_role("button", name="Create game").click()
                expect(self.page.locator("#add-status")).to_have_text(detail)
                expect(self.page.locator("#add-status")).to_be_visible()
                expect(self.page).to_have_url(f"{ORIGIN}/games/new")
                expect(self.page.get_by_label("Game name", exact=True)).to_have_value(name)
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

    def test_story_edit_save_publish_preview_and_mobile(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#draft-title")).to_have_text("Draft / live version 1")
        expect(self.page.locator(".mission-card")).to_have_count(3)
        expect(self.page.locator("#map-status")).to_contain_text("Maps are not configured")
        self.page.get_by_text("Quest settings", exact=True).click()
        self.page.get_by_label("Quest name", exact=True).fill("A new story")
        expect(self.page.locator("#draft-status")).to_contain_text("Unsaved edits")
        expect(self.page.get_by_role("button", name="Publish", exact=True)).to_be_disabled()
        self.page.get_by_role("button", name="Save draft", exact=True).click()
        expect(self.page.locator("#draft-status")).to_contain_text("Unpublished changes")
        self.assertEqual(self.quests["quests"][0]["name"], "The Mission Run")
        self.page.get_by_role("button", name="Publish", exact=True).click()
        self.page.locator("#confirm-action").click()
        expect(self.page.locator("#draft-title")).to_have_text("Draft / live version 2")
        self.assertEqual(self.quests["quests"][0]["name"], "A new story")
        self.page.get_by_label("Story preview", exact=True).check()
        expect(self.page.locator(".scene-edit:visible")).to_have_count(0)
        expect(self.page.locator(".scene-actions:visible")).to_have_count(0)
        self.page.get_by_role("button", name="Full map", exact=True).click()
        expect(self.page.locator("#story-pane")).not_to_be_visible()
        self.page.get_by_role("button", name="Story + map", exact=True).click()
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))

    def test_scrolled_map_does_not_overlap_quest_navigation(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#draft-title")).to_have_text("Draft / live version 1")
        for width in (1033, 768, 1150, 1151, 1440, 650, 390, 320):
            for view in ("Story + map", "Full map"):
                with self.subTest(width=width, view=view):
                    self.page.set_viewport_size({"width": width, "height": 635})
                    self.page.get_by_role("button", name=view, exact=True).click()
                    self.page.locator("#editor-map-panel").evaluate(
                        "(panel) => panel.scrollIntoView({block: 'start', behavior: 'instant'})"
                    )
                    overlap = self.page.evaluate("""() => {
                        const rail = document.querySelector('.quest-rail').getBoundingClientRect();
                        const map = document.getElementById('editor-map-panel').getBoundingClientRect();
                        return rail.left < map.right && rail.right > map.left
                            && rail.top < map.bottom && rail.bottom > map.top;
                    }""")
                    self.assertFalse(overlap, "Quest navigation covers the map panel")
                    self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    self.page.get_by_role("button", name="Fit all points", exact=True).click(trial=True)
                    self.page.get_by_label("Show on map", exact=True).select_option("all")

    def test_import_preview_validation_cancel_and_export(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator("#import-json")).to_be_enabled()
        imported = copy.deepcopy(self.quests)
        imported["quests"][0]["name"] = "<script>alert('unsafe')</script>"
        imported["custom_metadata"] = {"preserve": True}
        upload = {"name": "story.json", "mimeType": "application/json", "buffer": json.dumps(imported).encode()}
        self.page.locator("#json-file").set_input_files(upload)
        expect(self.page.locator("#import-summary")).to_contain_text("3 quests / 9 missions")
        self.assertEqual(self.draft["quests"][0]["name"], "The Mission Run")
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
        self.page.get_by_role("button", name="Move mission 2 up", exact=True).click()
        expect(self.page.locator(".mission-card").first).to_have_class(re.compile("question-card"))
        self.page.locator(".mission-card").first.get_by_role("button", name="Duplicate", exact=True).click()
        expect(self.page.locator(".mission-card")).to_have_count(4)
        travel = self.page.locator(".travel-card").first
        travel.get_by_text("Edit mission", exact=True).click()
        travel.get_by_role("button", name="Look up address").first.click()
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

    def test_switching_quests_cancels_pending_pin_placement(self) -> None:
        self.page.goto(f"{ORIGIN}/games/san-francisco/edit")
        expect(self.page.locator(".mission-card")).to_have_count(3)
        self.page.evaluate("map.pick = (target) => { map.pending = target; }")
        travel = self.page.locator(".travel-card").first
        travel.get_by_text("Edit mission", exact=True).click()
        travel.get_by_role("button", name="Pick on map").first.click()
        self.assertEqual(self.page.evaluate("map.pending"), {
            "questIndex": 0, "missionIndex": 0, "endpoint": "start",
        })
        self.page.locator('[data-quest="1"]').click()
        self.assertIsNone(self.page.evaluate("map.pending"))

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
