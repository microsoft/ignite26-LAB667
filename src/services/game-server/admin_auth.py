"""Table-backed operator credentials, opaque sessions, and login throttling."""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.data.tables import TableClient, TableEntity, TableServiceClient, UpdateMode
from fastapi import HTTPException

USERS_TABLE = "adminusers"
SESSIONS_TABLE = "adminsessions"
ATTEMPTS_TABLE = "adminloginattempts"
COOKIE_NAME = "admin_session"
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_ITERATIONS = 600_000
ATTEMPT_LIMIT = 10
ATTEMPT_WINDOW_SECONDS = 5 * 60
Role = Literal["admin", "editor"]
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    algorithm, iterations, salt, expected = encoded.split("$")
    if algorithm != "pbkdf2_sha256" or int(iterations) != PASSWORD_ITERATIONS:
        raise ValueError("Unsupported admin password hash format")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(actual, bytes.fromhex(expected))


@dataclass(frozen=True)
class Session:
    username: str
    token_hash: str
    csrf_token: str
    must_change_password: bool
    password_version: str
    role: Role


class AuthStore:
    def __init__(self, service: TableServiceClient, development_mode: bool = False) -> None:
        self.service = service
        self.development_mode = development_mode
        self.users = service.get_table_client(USERS_TABLE)
        self.sessions = service.get_table_client(SESSIONS_TABLE)
        self.attempts = service.get_table_client(ATTEMPTS_TABLE)

    def initialize(self) -> None:
        for name in (USERS_TABLE, SESSIONS_TABLE, ATTEMPTS_TABLE):
            self.service.create_table_if_not_exists(name)
        admin = self._get(self.users, "users", "admin")
        if admin is None:
            try:
                self.users.create_entity({
                    "PartitionKey": "users",
                    "RowKey": "admin",
                    "password_hash": hash_password("admin"),
                    "password_version": secrets.token_hex(16),
                    "must_change_password": not self.development_mode,
                    "role": "admin",
                    "enabled": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                return
            except ResourceExistsError:
                admin = self._get(self.users, "users", "admin")
        if self.development_mode and admin is not None and admin["must_change_password"]:
            admin["must_change_password"] = False
            self.users.update_entity(
                admin, mode=UpdateMode.REPLACE, etag=admin.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )

    @staticmethod
    def _get(table: TableClient, partition: str, key: str) -> TableEntity | None:
        try:
            return table.get_entity(partition_key=partition, row_key=key)
        except ResourceNotFoundError:
            return None

    def consume_attempt(self) -> None:
        # Keep a shared throttle, including unknown usernames, across replicas.
        for _ in range(8):
            now = int(time.time())
            entity = self._get(self.attempts, "login", "admin")
            if entity is None:
                try:
                    self.attempts.create_entity({
                        "PartitionKey": "login", "RowKey": "admin",
                        "count": 1, "window_end": now + ATTEMPT_WINDOW_SECONDS,
                    })
                    return
                except ResourceExistsError:
                    continue
            if int(entity["window_end"]) <= now:
                entity["count"] = 1
                entity["window_end"] = now + ATTEMPT_WINDOW_SECONDS
            elif int(entity["count"]) >= ATTEMPT_LIMIT:
                raise HTTPException(
                    429, "Too many sign-in attempts. Please try again later.",
                    headers={"Retry-After": str(int(entity["window_end"]) - now)},
                )
            else:
                entity["count"] = int(entity["count"]) + 1
            try:
                self.attempts.update_entity(
                    entity, mode=UpdateMode.REPLACE,
                    etag=entity.metadata["etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
                return
            except ResourceModifiedError:
                continue
        raise HTTPException(429, "Sign-in is busy. Please try again shortly.", headers={"Retry-After": "5"})

    def login(self, username: str, password: str) -> tuple[str, Session]:
        self.consume_attempt()
        username = username.strip().lower()
        user = self._get(self.users, "users", username) if USERNAME_RE.fullmatch(username) else None
        # Unknown accounts still perform the same password verification work.
        verifier = user if user is not None else self._get(self.users, "users", "admin")
        if verifier is None:
            raise RuntimeError("Admin account is missing; restart the admin service to initialize it")
        valid_password = verify_password(password, str(verifier["password_hash"]))
        if user is None or not valid_password or not user.get("enabled", True):
            raise HTTPException(401, "Invalid username or password")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        csrf = secrets.token_urlsafe(32)
        self.sessions.create_entity({
            "PartitionKey": "sessions",
            "RowKey": token_hash,
            "username": username,
            "csrf_token": csrf,
            "expires_at": int(time.time()) + SESSION_SECONDS,
            "password_version": user["password_version"],
        })
        return token, Session(
            username, token_hash, csrf, bool(user["must_change_password"]),
            str(user["password_version"]), self._role(user),
        )

    def get_session(self, token: str | None) -> Session | None:
        if not token or len(token) != 43:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        entity = self._get(self.sessions, "sessions", token_hash)
        if entity is None:
            return None
        user = self._get(self.users, "users", str(entity["username"]))
        if (
            int(entity["expires_at"]) <= int(time.time())
            or user is None
            or not user.get("enabled", True)
            or entity["password_version"] != user["password_version"]
        ):
            self._delete_session(token_hash)
            return None
        return Session(
            str(entity["username"]), token_hash, str(entity["csrf_token"]),
            bool(user["must_change_password"]), str(user["password_version"]),
            self._role(user),
        )

    def _delete_session(self, token_hash: str) -> None:
        try:
            self.sessions.delete_entity(partition_key="sessions", row_key=token_hash)
        except ResourceNotFoundError:
            pass  # Expiration and logout may race with another request.

    def logout(self, session: Session) -> None:
        self._delete_session(session.token_hash)

    def change_password(self, session: Session, current: str, new: str) -> None:
        self.consume_attempt()
        user = self._get(self.users, "users", session.username)
        if user is None or not user.get("enabled", True) or user["password_version"] != session.password_version:
            raise HTTPException(401, "Session expired. Please sign in again.")
        if not verify_password(current, str(user["password_hash"])):
            raise HTTPException(400, "Current password is incorrect")
        if not 12 <= len(new) <= 128 or not new.strip() or new == current or new == "admin":
            raise HTTPException(400, "Choose a different password of 12-128 characters")
        user["password_hash"] = hash_password(new)
        user["must_change_password"] = False
        # A version change invalidates every session, including concurrently created ones.
        user["password_version"] = secrets.token_hex(16)
        try:
            self.users.update_entity(
                user, mode=UpdateMode.REPLACE, etag=user.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except ResourceModifiedError as exc:
            raise HTTPException(409, "Credentials changed. Please sign in again.") from exc
        self._delete_session(session.token_hash)

    @staticmethod
    def _role(user: TableEntity) -> Role:
        # Only the original bootstrap account inherits administrator privileges.
        role = user.get("role", "admin" if user["RowKey"] == "admin" else "editor")
        if role == "admin":
            return "admin"
        if role == "editor":
            return "editor"
        raise RuntimeError("Invalid stored account role")

    @staticmethod
    def _username(username: str) -> str:
        username = username.strip().lower()
        if not USERNAME_RE.fullmatch(username):
            raise HTTPException(422, "Use 1-64 lowercase letters, numbers, dashes or underscores; start with a letter or number.")
        return username

    @staticmethod
    def _temporary_password(password: str) -> None:
        if not 12 <= len(password) <= 128 or not password.strip():
            raise HTTPException(422, "Temporary passwords must contain 12-128 characters and cannot be blank.")

    def _administrator(self, session: Session) -> None:
        user = self._get(self.users, "users", session.username)
        if user is None or not user.get("enabled", True) or user["password_version"] != session.password_version:
            raise HTTPException(401, "Session expired. Please sign in again.")
        if self._role(user) != "admin" or user["must_change_password"]:
            raise HTTPException(403, "Administrator access required")

    def _public_user(self, user: TableEntity) -> dict[str, Any]:
        return {
            "username": str(user["RowKey"]),
            "role": self._role(user),
            "enabled": bool(user.get("enabled", True)),
            "must_change_password": bool(user["must_change_password"]),
            "revision": str(user["password_version"]),
            "created_at": user.get("created_at"),
        }

    def list_users(self, actor: Session) -> list[dict[str, Any]]:
        self._administrator(actor)
        return sorted(
            [self._public_user(user) for user in self.users.query_entities("PartitionKey eq 'users'")],
            key=lambda user: user["username"],
        )

    def create_user(self, actor: Session, username: str, role: Role, password: str) -> dict[str, Any]:
        self._administrator(actor)
        username = self._username(username)
        self._temporary_password(password)
        if role not in ("admin", "editor"):
            raise HTTPException(422, "Choose administrator or editor.")
        user = TableEntity({
            "PartitionKey": "users", "RowKey": username,
            "role": role, "enabled": True,
            "password_hash": hash_password(password),
            "password_version": secrets.token_hex(16),
            "must_change_password": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            self.users.create_entity(user)
        except ResourceExistsError as exc:
            raise HTTPException(409, "That username already exists. Choose another username.") from exc
        logger.info("Operator %s created account %s with role %s", actor.username, username, role)
        return self._public_user(user)

    def update_user(
        self, actor: Session, username: str, role: Role, enabled: bool,
        revision: str, temporary_password: str | None = None,
    ) -> dict[str, Any]:
        self._administrator(actor)
        username = self._username(username)
        if role not in ("admin", "editor"):
            raise HTTPException(422, "Choose administrator or editor.")
        user = self._get(self.users, "users", username)
        if user is None:
            raise HTTPException(404, "User not found")
        if user["password_version"] != revision:
            raise HTTPException(409, "This account changed. Close this dialog and refresh users before trying again.")
        if username == "admin" and (role != "admin" or not enabled):
            raise HTTPException(400, "The built-in admin must remain an enabled administrator.")
        if username == actor.username:
            raise HTTPException(400, "You cannot change your own access here. Use Password to change your password.")
        changed = self._role(user) != role or bool(user.get("enabled", True)) != enabled
        if temporary_password is not None:
            self._temporary_password(temporary_password)
            if verify_password(temporary_password, str(user["password_hash"])):
                raise HTTPException(400, "Choose a temporary password different from the current password.")
            user["password_hash"] = hash_password(temporary_password)
            user["must_change_password"] = True
            changed = True
        if not changed:
            return self._public_user(user)
        user["role"], user["enabled"] = role, enabled
        user["password_version"] = secrets.token_hex(16)
        try:
            self.users.update_entity(
                user, mode=UpdateMode.REPLACE, etag=user.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except ResourceModifiedError as exc:
            raise HTTPException(409, "This account changed. Close this dialog and refresh users before trying again.") from exc
        logger.info("Operator %s updated account %s (role=%s, enabled=%s, password_reset=%s)",
                    actor.username, username, role, enabled, temporary_password is not None)
        return self._public_user(user)

    @staticmethod
    def context(session: Session) -> dict[str, Any]:
        return {
            "username": session.username,
            "csrf_token": session.csrf_token,
            "must_change_password": session.must_change_password,
            "role": session.role,
        }
