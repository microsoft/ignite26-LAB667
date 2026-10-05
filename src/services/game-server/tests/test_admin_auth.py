"""Exercise real admin routes and storage logic without contacting Azure."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError, ResourceModifiedError, ResourceNotFoundError,
    ServiceRequestError,
)
from azure.data.tables import TableEntity, TableServiceClient, UpdateMode
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin
import admin_auth
import storage

ORIGIN = "https://testserver"
NEW_PASSWORD = "only-for-tests-strong-password"


class FakeTable:
    def __init__(self) -> None:
        self.entities: dict[tuple[str, str], TableEntity] = {}
        self.version = 0
        self.conflicts = 0

    def create_entity(self, entity: dict) -> None:
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.entities:
            error = ResourceExistsError("Already exists")
            error.status_code = 409
            raise error
        self.upsert_entity(entity)

    def upsert_entity(self, entity: dict) -> None:
        self.version += 1
        saved = TableEntity(copy.deepcopy(entity))
        saved._metadata = {"etag": str(self.version), "timestamp": None}
        self.entities[(entity["PartitionKey"], entity["RowKey"])] = saved

    def get_entity(self, partition_key: str, row_key: str) -> TableEntity:
        try:
            return copy.deepcopy(self.entities[(partition_key, row_key)])
        except KeyError as exc:
            raise ResourceNotFoundError("Not found") from exc

    def update_entity(self, entity: dict, mode: UpdateMode, etag: str, match_condition: MatchConditions) -> None:
        current = self.get_entity(entity["PartitionKey"], entity["RowKey"])
        if self.conflicts:
            self.conflicts -= 1
            error = ResourceModifiedError("Simulated conflict")
            error.status_code = 412
            raise error
        if etag != current.metadata["etag"]:
            error = ResourceModifiedError("Stale ETag")
            error.status_code = 412
            raise error
        if match_condition != MatchConditions.IfNotModified or mode != UpdateMode.REPLACE:
            raise AssertionError("Expected optimistic replacement")
        self.upsert_entity(entity)

    def submit_transaction(self, operations: list) -> list:
        before = copy.deepcopy(self.entities)
        try:
            for operation in operations:
                kind, entity = operation[:2]
                if kind == "create":
                    self.create_entity(entity)
                elif kind == "update":
                    self.update_entity(entity, **operation[2])
                else:
                    raise AssertionError(f"Unsupported transaction operation: {kind}")
        except (ResourceExistsError, ResourceModifiedError, ResourceNotFoundError):
            self.entities = before
            raise
        return []

    def delete_entity(self, partition_key: str, row_key: str) -> None:
        try:
            del self.entities[(partition_key, row_key)]
        except KeyError as exc:
            raise ResourceNotFoundError("Not found") from exc

    def query_entities(self, query_filter: str) -> list[TableEntity]:
        match = re.fullmatch(r"PartitionKey eq '([^']+)'", query_filter)
        if match is None:
            raise AssertionError(f"Unsupported test query: {query_filter}")
        return [copy.deepcopy(entity) for (partition, _), entity in self.entities.items() if partition == match[1]]

    def list_entities(self) -> list[TableEntity]:
        return copy.deepcopy(list(self.entities.values()))


def fake_service() -> tuple[Mock, dict[str, FakeTable]]:
    tables: dict[str, FakeTable] = {}
    service = Mock(spec=TableServiceClient)

    def get_table(name: str) -> FakeTable:
        return tables.setdefault(name, FakeTable())

    service.get_table_client.side_effect = get_table
    service.create_table.side_effect = get_table
    service.create_table_if_not_exists.side_effect = get_table
    return service, tables


class AdminAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service, self.tables = fake_service()
        self.storage_patch = patch.object(storage, "_service", self.service)
        self.storage_patch.start()
        self.env_patch = patch.dict("os.environ", {"ADMIN_COOKIE_SECURE": "true"})
        self.env_patch.start()
        self.client = TestClient(admin.app, base_url=ORIGIN, follow_redirects=False)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.storage_patch.stop()

    def login(self, password: str = "admin", username: str = "admin"):
        return self.client.post(
            "/api/auth/login", json={"username": username, "password": password},
            headers={"Origin": ORIGIN},
        )

    def csrf(self) -> dict[str, str]:
        response = self.client.get("/password")
        token = re.search(r'name="csrf-token" content="([^"]+)"', response.text)
        self.assertIsNotNone(token)
        return {"Origin": ORIGIN, "X-CSRF-Token": token.group(1)}

    def activate(self) -> None:
        self.assertEqual(self.login().status_code, 200)
        response = self.client.post("/api/auth/password", headers=self.csrf(), json={
            "current_password": "admin", "new_password": NEW_PASSWORD,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.login(NEW_PASSWORD).status_code, 200)

    def test_bootstrap_hash_is_salted_and_does_not_reset(self) -> None:
        user = self.tables[admin_auth.USERS_TABLE].get_entity("users", "admin")
        self.assertNotEqual(user["password_hash"], "admin")
        self.assertTrue(admin_auth.verify_password("admin", user["password_hash"]))
        self.assertNotEqual(admin_auth.hash_password("admin"), user["password_hash"])
        self.activate()
        admin.app.state.auth.initialize()
        user = self.tables[admin_auth.USERS_TABLE].get_entity("users", "admin")
        self.assertFalse(user["must_change_password"])
        self.assertTrue(admin_auth.verify_password(NEW_PASSWORD, user["password_hash"]))
        self.assertFalse(admin_auth.verify_password("admin", user["password_hash"]))

    def test_all_game_routes_require_login(self) -> None:
        routes = [
            ("GET", "/api/games", None), ("POST", "/api/games", {"slug": "demo", "display_name": "Demo"}),
            ("DELETE", "/api/games/san-francisco", None),
            ("GET", "/api/games/san-francisco/quests", None),
            ("PUT", "/api/games/san-francisco/quests", {"quests": []}),
            ("POST", "/api/games/san-francisco/quests/import-seed", {"revision": 1}),
            ("GET", "/api/games/san-francisco/leaderboard", None),
            ("GET", "/api/games/san-francisco/players", None),
            ("DELETE", "/api/games/san-francisco/players/player", None),
            ("DELETE", "/api/games/san-francisco/players", None),
            ("GET", "/api/games/san-francisco/draft", None),
            ("PUT", "/api/games/san-francisco/draft", {"revision": 1, "document": {"quests": []}}),
            ("POST", "/api/games/san-francisco/publish", {"revision": 1}),
            ("POST", "/api/games/san-francisco/validate", {"document": {}}),
            ("GET", "/api/games/san-francisco/activity", None),
            ("GET", "/api/games/san-francisco/versions", None),
            ("DELETE", "/api/games/san-francisco/versions/1", None),
            ("GET", "/api/maps/config", None),
            ("GET", "/api/maps/geocode?query=San+Francisco", None),
        ]
        for method, path, payload in routes:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.client.request(method, path, json=payload).status_code, 401)
        for path in ("/", "/games/san-francisco", "/games/san-francisco/edit", "/password"):
            self.assertEqual(self.client.get(path).headers["location"], "/login")
        self.assertEqual(self.client.get("/openapi.json").status_code, 404)

    def test_login_cookie_and_forced_password_change(self) -> None:
        response = self.login()
        self.assertEqual(response.json()["redirect"], "/password")
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertEqual(self.client.get("/").headers["location"], "/password")
        self.assertEqual(self.client.get("/games/san-francisco").headers["location"], "/password")
        self.assertEqual(self.client.get("/api/games").status_code, 403)
        self.assertEqual(self.client.delete("/api/games/san-francisco", headers=self.csrf()).status_code, 403)
        token = self.client.cookies.get(admin_auth.COOKIE_NAME)
        stored = self.tables[admin_auth.SESSIONS_TABLE].entities
        self.assertIn(("sessions", hashlib.sha256(token.encode()).hexdigest()), stored)
        self.assertNotIn(token, repr(stored))

    def test_invalid_credentials_have_generic_error(self) -> None:
        wrong_password = self.login("wrong")
        wrong_user = self.login("admin", "unknown")
        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(wrong_password.json(), wrong_user.json())
        self.assertFalse(self.tables[admin_auth.SESSIONS_TABLE].entities)

    def test_login_rejects_cross_site_and_missing_origin(self) -> None:
        for origin in ("https://evil.test", "null", "https://[bad"):
            response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers={"Origin": origin})
            self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        self.assertEqual(response.status_code, 403)

    def test_https_origin_works_behind_tls_termination(self) -> None:
        with TestClient(admin.app, base_url="http://testserver") as proxy:
            response = proxy.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers={"Origin": ORIGIN})
            self.assertEqual(response.status_code, 200)
            self.assertIn("Secure", response.headers["set-cookie"])

    def test_mutations_require_csrf_and_same_origin(self) -> None:
        self.activate()
        path = "/api/games/san-francisco/players"
        self.assertEqual(self.client.delete(path, headers={"Origin": ORIGIN}).status_code, 403)
        headers = self.csrf()
        headers["Origin"] = "https://evil.test"
        self.assertEqual(self.client.delete(path, headers=headers).status_code, 403)
        self.assertEqual(self.client.delete(path, headers=self.csrf()).status_code, 200)

    def test_password_policy_and_old_sessions_revoked(self) -> None:
        self.login()
        first_token = self.client.cookies.get(admin_auth.COOKIE_NAME)
        self.login()
        headers = self.csrf()
        for current, new, status in [("wrong", NEW_PASSWORD, 400), ("admin", "short", 422)]:
            response = self.client.post("/api/auth/password", headers=headers, json={"current_password": current, "new_password": new})
            self.assertEqual(response.status_code, status)
        response = self.client.post("/api/auth/password", headers=headers, json={"current_password": "admin", "new_password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(admin.app.state.auth.get_session(first_token))
        self.assertEqual(self.client.get("/api/games").status_code, 401)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(NEW_PASSWORD).status_code, 200)
        response = self.client.post("/api/auth/password", headers=self.csrf(), json={"current_password": NEW_PASSWORD, "new_password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 400)

    def test_logout_and_expiration(self) -> None:
        self.login()
        token = self.client.cookies.get(admin_auth.COOKIE_NAME)
        self.assertEqual(self.client.post("/api/auth/logout", headers=self.csrf()).status_code, 200)
        self.assertIsNone(admin.app.state.auth.get_session(token))
        self.login()
        token = self.client.cookies.get(admin_auth.COOKIE_NAME)
        key = ("sessions", hashlib.sha256(token.encode()).hexdigest())
        self.tables[admin_auth.SESSIONS_TABLE].entities[key]["expires_at"] = 0
        self.assertEqual(self.client.get("/api/games").status_code, 401)
        self.assertNotIn(key, self.tables[admin_auth.SESSIONS_TABLE].entities)

    def test_table_backed_throttle_and_etag_retry(self) -> None:
        self.login("wrong")
        self.tables[admin_auth.ATTEMPTS_TABLE].conflicts = 1
        for _ in range(admin_auth.ATTEMPT_LIMIT - 1):
            self.assertEqual(self.login("wrong", "unknown").status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertIn("retry-after", response.headers)
        self.tables[admin_auth.ATTEMPTS_TABLE].entities[("login", "admin")]["window_end"] = 0
        self.assertEqual(self.login().status_code, 200)

    def test_authenticated_game_operations_are_preserved(self) -> None:
        self.activate()
        headers = self.csrf()
        response = self.client.post("/api/games", json={"slug": "demo", "display_name": "Demo"}, headers=headers)
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(self.client.put("/api/games/demo/quests", json={"quests": []}, headers=headers).status_code, 409)
        self.assertEqual(self.client.get("/api/games/demo/quests").json(), {"city": "Demo", "quests": []})
        draft = self.client.get("/api/games/demo/draft").json()
        saved = self.client.put("/api/games/demo/draft", json={"revision": draft["revision"], "document": storage.load_seed_quests()}, headers=headers)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.post("/api/games/demo/publish", json={"revision": saved.json()["revision"]}, headers=headers).status_code, 200)
        storage.save_player("demo", "p1", {"name": "Player", "status": "registered"})
        self.assertIn("p1", self.client.get("/api/games/demo/players").json()["players"])
        versions = self.client.get("/api/games/demo/versions").json()
        self.assertEqual(versions["published_version"], 1)
        self.assertEqual(versions["versions"][0]["player_count"], 1)
        self.assertEqual(self.client.delete("/api/games/demo/versions/1", headers=headers).status_code, 409)
        self.assertEqual(self.client.delete("/api/games/demo/players/p1", headers=headers).status_code, 200)
        self.assertEqual(self.client.delete("/api/games/demo", headers=headers).status_code, 200)
        self.assertIsNone(storage.get_game("demo"))

    def test_storage_failure_is_explicit_and_security_headers_present(self) -> None:
        self.service.get_table_client.side_effect = ServiceRequestError("unavailable")
        with patch.object(admin.app.state.auth.users, "get_entity", side_effect=ServiceRequestError("unavailable")):
            self.assertEqual(self.login().status_code, 503)
        response = self.client.get("/login")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_local_http_cookie_setting_and_input_limits(self) -> None:
        with patch.dict("os.environ", {"ADMIN_COOKIE_SECURE": "false"}):
            with TestClient(admin.app, base_url="http://localhost") as local:
                response = local.post("/api/auth/login", json={"username": "admin", "password": "admin"}, headers={"Origin": "http://localhost"})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Secure", response.headers["set-cookie"])
        self.assertEqual(self.login("a" * 129).status_code, 422)
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin", "padding": "x" * 5000}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 413)

    def test_browser_login_password_change_and_game_management(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(admin.app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        with patch.dict("os.environ", {"ADMIN_COOKIE_SECURE": "false"}), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context()
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                thread.start()
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(server.started, "Test server failed to start")
                page.goto(origin)
                expect(page).to_have_url(f"{origin}/login")
                page.get_by_label("Username", exact=True).fill("admin")
                page.get_by_label("Password", exact=True).fill("admin")
                page.get_by_role("button", name="Enter mission control").click()
                expect(page).to_have_url(f"{origin}/password")
                page.get_by_label("Current password", exact=True).fill("admin")
                page.get_by_label("New password", exact=True).fill(NEW_PASSWORD)
                page.get_by_label("Confirm new password", exact=True).fill(NEW_PASSWORD)
                page.get_by_role("button", name="Save password & sign out").click()
                expect(page).to_have_url(f"{origin}/login")
                page.get_by_label("Username", exact=True).fill("admin")
                page.get_by_label("Password", exact=True).fill(NEW_PASSWORD)
                page.get_by_role("button", name="Enter mission control").click()
                expect(page).to_have_url(f"{origin}/")
                expect(page.locator(".game-card")).to_have_count(1)
                page.locator("main").get_by_role("link", name="Create a game").click()
                expect(page).to_have_url(f"{origin}/games/new")
                page.get_by_label("Event name", exact=True).fill("Open Hack")
                page.get_by_label("Challenge name", exact=True).fill("Browser adventure")
                page.get_by_label("City", exact=True).fill("Amsterdam")
                page.get_by_label("URL slug").fill("browser-adventure")
                page.get_by_role("button", name="Create game").click()
                expect(page).to_have_url(f"{origin}/games/browser-adventure/edit")
                created_game = storage.get_game("browser-adventure")
                self.assertEqual(created_game["event_name"], "Open Hack")
                self.assertEqual(created_game["display_name"], "Browser adventure")
                page.goto(f"{origin}/games/browser-adventure/edit")
                expect(page.locator("#draft-title")).to_have_text("Draft / not published yet")
                page.locator("#json-file").set_input_files({
                    "name": "quests.json", "mimeType": "application/json",
                    "buffer": json.dumps(storage.load_seed_quests()).encode(),
                })
                page.get_by_role("button", name="Replace editor draft").click()
                expect(page.locator(".mission-card")).to_have_count(3)
                page.get_by_role("button", name="Save draft", exact=True).click()
                expect(page.locator("#draft-status")).to_contain_text("Unpublished changes")
                self.assertEqual(storage.load_published("browser-adventure")[0], 0)
                page.get_by_role("button", name="Publish", exact=True).click()
                page.locator("#confirm-action").click()
                expect(page.locator("#draft-title")).to_have_text("Draft / live version 1")
                self.assertEqual(storage.load_published("browser-adventure")[0], 1)
                page.get_by_role("link", name="Dashboard", exact=True).click()
                expect(page.locator("#player-count")).to_have_text("0")
                expect(page.get_by_role("region", name="Player summary")).to_be_visible()
                page.get_by_role("button", name="Sign out").click()
                expect(page).to_have_url(f"{origin}/login")
                page.goto(origin)
                expect(page).to_have_url(f"{origin}/login")
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
                server.should_exit = True
                thread.join(timeout=5)
                listener.close()
                self.assertFalse(thread.is_alive(), "Test server failed to stop")


if __name__ == "__main__":
    unittest.main()
