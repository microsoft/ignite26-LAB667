"""Role boundaries and account lifecycle against the real API with fake Tables."""
from __future__ import annotations

import socket
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from playwright.sync_api import expect, sync_playwright
import uvicorn

import test_admin_auth
from test_admin_auth import NEW_PASSWORD, ORIGIN
import admin
import admin_auth
import storage

TEMP_PASSWORD = "temporary-test-password"
EDITOR_PASSWORD = "editor-chosen-password"


class UserManagementTests(unittest.TestCase):
    setUp = test_admin_auth.AdminAuthTests.setUp
    tearDown = test_admin_auth.AdminAuthTests.tearDown
    login = test_admin_auth.AdminAuthTests.login
    csrf = test_admin_auth.AdminAuthTests.csrf
    activate = test_admin_auth.AdminAuthTests.activate

    def create(self, username: str = "editor", role: str = "editor") -> dict:
        response = self.client.post("/api/users", headers=self.csrf(), json={
            "username": username, "role": role, "temporary_password": TEMP_PASSWORD,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"]

    def update(self, user: dict, **changes):
        return self.client.patch(f"/api/users/{user['username']}", headers=self.csrf(), json={
            "role": user["role"], "enabled": user["enabled"], "revision": user["revision"], **changes,
        })

    def test_new_routes_require_login_and_completed_password_change(self) -> None:
        for path in ("/users", "/games/new"):
            self.assertEqual(self.client.get(path).headers["location"], "/login")
        create = {"username": "editor", "role": "editor", "temporary_password": TEMP_PASSWORD}
        change = {"role": "editor", "enabled": False, "revision": "old"}
        for method, path, payload in [
            ("GET", "/api/users", None), ("POST", "/api/users", create),
            ("PATCH", "/api/users/editor", change),
        ]:
            self.assertEqual(self.client.request(method, path, json=payload).status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/users").headers["location"], "/password")
        self.assertEqual(self.client.get("/games/new").headers["location"], "/password")
        self.assertEqual(self.client.get("/api/users").status_code, 403)
        self.assertEqual(self.client.post("/api/users", headers=self.csrf(), json=create).status_code, 403)

    def test_legacy_admin_keeps_access_without_password_or_session_reset(self) -> None:
        self.activate()
        user = self.tables[admin_auth.USERS_TABLE].entities[("users", "admin")]
        del user["role"]
        del user["enabled"]
        before = user["password_hash"], user["password_version"]
        response = self.client.get("/api/users")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["users"][0]["role"], "admin")
        admin.app.state.auth.initialize()
        self.assertEqual(before, (user["password_hash"], user["password_version"]))
        self.assertIn('href="/users"', self.client.get("/").text)

    def test_creation_validation_unique_names_and_safe_responses(self) -> None:
        self.activate()
        user = self.create("Alice")
        self.assertEqual(user["username"], "alice")
        self.assertTrue(user["must_change_password"])
        self.assertTrue(user["enabled"])
        stored = self.tables[admin_auth.USERS_TABLE].get_entity("users", "alice")
        self.assertTrue(admin_auth.verify_password(TEMP_PASSWORD, stored["password_hash"]))
        self.assertEqual(set(user), {"username", "role", "enabled", "must_change_password", "revision", "created_at"})
        self.assertNotIn(stored["password_hash"], self.client.get("/api/users").text)
        for changes, status in [
            ({"username": "ALICE"}, 409), ({"username": "../invalid"}, 422),
            ({"role": "owner"}, 422), ({"temporary_password": "short"}, 422),
            ({"temporary_password": " " * 12}, 422), ({"extra": "secret-extra"}, 422),
        ]:
            payload = {"username": "another", "role": "editor", "temporary_password": TEMP_PASSWORD, **changes}
            response = self.client.post("/api/users", headers=self.csrf(), json=payload)
            self.assertEqual(response.status_code, status, response.text)
            self.assertNotIn(payload["temporary_password"], response.text)
            self.assertNotIn("secret-extra", response.text)
        self.assertEqual(len(self.client.get("/api/users").json()["users"]), 2)
        for changes in ({"enabled": "false"}, {"role": "owner"}, {"temporary_password": "short"},
                        {"password_hash": "forged"}):
            self.assertEqual(self.update(user, **changes).status_code, 422)

    def test_editor_can_manage_games_but_not_users_or_promote_self(self) -> None:
        self.activate()
        user = self.create()
        self.login(TEMP_PASSWORD, "editor")
        self.assertEqual(self.client.get("/api/games").status_code, 403)
        response = self.client.post("/api/auth/password", headers=self.csrf(), json={
            "current_password": TEMP_PASSWORD, "new_password": EDITOR_PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.login(EDITOR_PASSWORD, "editor")
        self.assertEqual(self.client.get("/users").status_code, 403)
        self.assertNotIn('href="/users"', self.client.get("/").text)
        self.assertEqual(self.client.get("/api/users").status_code, 403)
        self.assertEqual(self.client.post("/api/users", headers=self.csrf(), json={
            "username": "intruder", "role": "admin", "temporary_password": TEMP_PASSWORD,
        }).status_code, 403)
        self.assertEqual(self.update(user, role="admin").status_code, 403)
        self.assertEqual(self.client.get("/games/new").status_code, 200)
        response = self.client.post("/api/games", headers=self.csrf(), json={"slug": "editor-game", "display_name": "Editor game"})
        self.assertEqual(response.status_code, 200, response.text)
        draft = self.client.get("/api/games/editor-game/draft").json()
        saved = self.client.put("/api/games/editor-game/draft", headers=self.csrf(), json={
            "revision": draft["revision"], "document": storage.load_seed_quests(),
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.post("/api/games/editor-game/publish", headers=self.csrf(),
                                         json={"revision": saved.json()["revision"]}).status_code, 200)

    def test_disable_enable_role_change_and_reset_revoke_sessions(self) -> None:
        self.activate()
        user = self.create()
        store = admin.app.state.auth
        first, _ = store.login("editor", TEMP_PASSWORD)
        result = self.update(user, enabled=False)
        self.assertEqual(result.status_code, 200)
        user = result.json()["user"]
        self.assertIsNone(store.get_session(first))
        with self.assertRaises(HTTPException) as invalid:
            store.login("editor", TEMP_PASSWORD)
        self.assertEqual(invalid.exception.status_code, 401)
        user = self.update(user, enabled=True).json()["user"]
        second, _ = store.login("editor", TEMP_PASSWORD)
        user = self.update(user, role="admin").json()["user"]
        self.assertIsNone(store.get_session(second))
        third, _ = store.login("editor", TEMP_PASSWORD)
        user = self.update(user, temporary_password="replacement-temporary-password").json()["user"]
        self.assertIsNone(store.get_session(third))
        self.assertTrue(user["must_change_password"])
        token, session = store.login("editor", "replacement-temporary-password")
        self.assertEqual(session.role, "admin")
        self.assertTrue(store.get_session(token).must_change_password)

    def test_stale_updates_csrf_and_protected_accounts(self) -> None:
        self.activate()
        user = self.create()
        self.assertEqual(self.client.patch("/api/users/editor", headers={"Origin": ORIGIN}, json={
            "role": "admin", "enabled": True, "revision": user["revision"],
        }).status_code, 403)
        headers = self.csrf()
        headers["Origin"] = "https://other.test"
        self.assertEqual(self.client.patch("/api/users/editor", headers=headers, json={
            "role": "admin", "enabled": True, "revision": user["revision"],
        }).status_code, 403)
        self.assertEqual(self.update(user, role="admin").status_code, 200)
        self.assertEqual(self.update(user, enabled=False).status_code, 409)
        current = next(u for u in self.client.get("/api/users").json()["users"] if u["username"] == "editor")
        self.tables[admin_auth.USERS_TABLE].conflicts = 1
        self.assertEqual(self.update(current, enabled=False).status_code, 409)
        self.assertTrue(self.tables[admin_auth.USERS_TABLE].get_entity("users", "editor")["enabled"])
        root = next(u for u in self.client.get("/api/users").json()["users"] if u["username"] == "admin")
        for change in ({"enabled": False}, {"role": "editor"}, {"temporary_password": TEMP_PASSWORD}):
            self.assertEqual(self.update(root, **change).status_code, 400)
        self.assertEqual(self.update({**current, "username": "missing"}).status_code, 404)

    def test_another_administrator_cannot_disable_or_demote_bootstrap_admin(self) -> None:
        self.activate()
        self.create("second-admin", "admin")
        store = admin.app.state.auth
        _, initial = store.login("second-admin", TEMP_PASSWORD)
        store.change_password(initial, TEMP_PASSWORD, EDITOR_PASSWORD)
        _, second = store.login("second-admin", EDITOR_PASSWORD)
        root = next(user for user in store.list_users(second) if user["username"] == "admin")
        for role, enabled in (("editor", True), ("admin", False)):
            with self.assertRaises(HTTPException) as invalid:
                store.update_user(second, "admin", role, enabled, root["revision"])
            self.assertEqual(invalid.exception.status_code, 400)

    def test_stale_administrator_cannot_use_store_after_demotion(self) -> None:
        self.activate()
        user = self.create("second-admin", "admin")
        store = admin.app.state.auth
        _, initial = store.login("second-admin", TEMP_PASSWORD)
        store.change_password(initial, TEMP_PASSWORD, EDITOR_PASSWORD)
        token, elevated = store.login("second-admin", EDITOR_PASSWORD)
        user = next(u for u in self.client.get("/api/users").json()["users"] if u["username"] == user["username"])
        self.assertEqual(self.update(user, role="editor").status_code, 200)
        self.assertIsNone(store.get_session(token))
        with self.assertRaises(HTTPException) as invalid:
            store.create_user(elevated, "intruder", "admin", TEMP_PASSWORD)
        self.assertEqual(invalid.exception.status_code, 401)
        _, demoted = store.login("second-admin", EDITOR_PASSWORD)
        self.assertEqual(demoted.role, "editor")
        with self.assertRaises(HTTPException) as forbidden:
            store.list_users(demoted)
        self.assertEqual(forbidden.exception.status_code, 403)

    def test_game_creation_has_explicit_errors_and_reserved_route(self) -> None:
        self.activate()
        self.assertEqual(self.client.get("/games/new").status_code, 200)
        for slug, name, status in (("new", "Reserved", 422), ("bad/slug", "Bad", 422),
                                   ("san-francisco", "Duplicate", 409), ("empty", "   ", 422)):
            result = self.client.post("/api/games", headers=self.csrf(), json={"slug": slug, "display_name": name})
            self.assertEqual(result.status_code, status)

    def test_browser_create_update_reset_and_editor_navigation(self) -> None:
        self.activate()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(admin.app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        with patch.dict("os.environ", {"ADMIN_COOKIE_SECURE": "false"}), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                thread.start()
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(server.started)
                page.goto(origin + "/login")
                page.get_by_label("Username", exact=True).fill("admin")
                page.get_by_label("Password", exact=True).fill(NEW_PASSWORD)
                page.get_by_role("button", name="Enter mission control").click()
                page.get_by_role("link", name="Users", exact=True).click()
                expect(page.locator("#users")).to_contain_text("Administrator")
                page.get_by_label("Username", exact=True).fill("workshop-editor")
                page.get_by_label("Temporary password", exact=True).fill(TEMP_PASSWORD)
                page.get_by_label("Confirm temporary password", exact=True).fill("does-not-match")
                page.get_by_role("button", name="Create user", exact=True).click()
                expect(page.locator("#create-user-error")).to_contain_text("do not match")
                page.get_by_label("Confirm temporary password", exact=True).fill(TEMP_PASSWORD)
                page.get_by_role("button", name="Create user", exact=True).click()
                expect(page.locator("#users")).to_contain_text("workshop-editor")
                expect(page.get_by_label("Temporary password", exact=True)).to_have_value("")
                page.get_by_role("button", name="Manage workshop-editor", exact=True).click()
                page.get_by_label("Account enabled", exact=True).uncheck()
                page.get_by_role("button", name="Save user", exact=True).click()
                page.get_by_role("button", name="Confirm account changes", exact=True).click()
                expect(page.locator("#edit-user-dialog")).not_to_be_visible()
                expect(page.locator("#users")).to_contain_text("Disabled")
                page.get_by_role("button", name="Manage workshop-editor", exact=True).click()
                page.get_by_label("Account enabled", exact=True).check()
                page.get_by_label("New temporary password", exact=True).fill("reset-browser-password")
                page.get_by_label("Confirm new temporary password", exact=True).fill("reset-browser-password")
                page.get_by_role("button", name="Save user", exact=True).click()
                page.get_by_role("button", name="Confirm account changes", exact=True).click()
                expect(page.locator("#edit-user-dialog")).not_to_be_visible()
                for width in (1440, 768, 390, 320):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                page.get_by_role("button", name="Sign out").click()
                expect(page).to_have_url(origin + "/login")
                page.get_by_label("Username", exact=True).fill("workshop-editor")
                page.get_by_label("Password", exact=True).fill("reset-browser-password")
                page.get_by_role("button", name="Enter mission control").click()
                expect(page).to_have_url(origin + "/password")
                page.get_by_label("Current password", exact=True).fill("reset-browser-password")
                page.get_by_label("New password", exact=True).fill(EDITOR_PASSWORD)
                page.get_by_label("Confirm new password", exact=True).fill(EDITOR_PASSWORD)
                page.get_by_role("button", name="Save password & sign out").click()
                expect(page).to_have_url(origin + "/login")
                page.get_by_label("Username", exact=True).fill("workshop-editor")
                page.get_by_label("Password", exact=True).fill(EDITOR_PASSWORD)
                page.get_by_role("button", name="Enter mission control").click()
                expect(page).to_have_url(origin + "/")
                expect(page.get_by_role("navigation", name="Admin navigation").get_by_role("link", name="Users")).to_have_count(0)
                page.get_by_role("navigation", name="Admin navigation").get_by_role("link", name="Create game", exact=True).click()
                expect(page).to_have_url(origin + "/games/new")
                self.assertEqual(errors, [])
            finally:
                browser.close()
                server.should_exit = True
                thread.join(timeout=5)
                listener.close()
                self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
