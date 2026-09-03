from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from stzy_app.domain.store import DomainStore


@dataclass(frozen=True)
class Session:
    id: str
    kind: str
    csrf_token: str
    expires_at: str


class IdentityService:
    def __init__(self, store: DomainStore, *, admin_password_hash: str = "", bootstrap_token: str = "") -> None:
        self.store = store
        self.admin_password_hash = admin_password_hash
        self.bootstrap_token = bootstrap_token
        self._bootstrap_used = False
        self._failures: dict[str, list[float]] = {}

    def login_admin(self, password: str, *, remote: str = "") -> Session:
        self._check_rate_limit(remote)
        if not self.admin_password_hash:
            raise PermissionError("Server mode requires STZY_ADMIN_PASSWORD_HASH")
        if not verify_password(password, self.admin_password_hash):
            self._record_failure(remote)
            raise PermissionError("管理员密码错误")
        return self.create_session("admin", hours=12)

    def login_bootstrap(self, token: str) -> Session:
        if not self.bootstrap_token or self._bootstrap_used or not secrets.compare_digest(token, self.bootstrap_token):
            raise PermissionError("启动凭证无效")
        self._bootstrap_used = True
        return self.create_session("gui", hours=24)

    def create_session(self, kind: str, *, hours: int) -> Session:
        session = Session(
            id=secrets.token_urlsafe(32),
            kind=kind,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=(datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds"),
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO domain_sessions (id, kind, csrf_token, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session.id, session.kind, session.csrf_token, now, session.expires_at),
            )
        return session

    def revoke(self, session_id: str) -> None:
        with self.store.transaction() as connection:
            connection.execute("UPDATE domain_sessions SET revoked = 1 WHERE id = ?", (session_id,))

    def session(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        with self.store.transaction() as connection:
            row = connection.execute(
                """
                SELECT id, kind, csrf_token, expires_at
                FROM domain_sessions
                WHERE id = ? AND revoked = 0 AND expires_at > ?
                """,
                (session_id, datetime.now().isoformat(timespec="seconds")),
            ).fetchone()
        if not row:
            return None
        return Session(
            id=str(row["id"]),
            kind=str(row["kind"]),
            csrf_token=str(row["csrf_token"]),
            expires_at=str(row["expires_at"]),
        )

    def _check_rate_limit(self, remote: str) -> None:
        key = remote or "local"
        now = time.time()
        self._failures[key] = [value for value in self._failures.get(key, []) if now - value < 60]
        if len(self._failures[key]) >= 8:
            raise PermissionError("登录尝试过于频繁，请稍后再试")

    def _record_failure(self, remote: str) -> None:
        key = remote or "local"
        self._failures.setdefault(key, []).append(time.time())


def hash_password(password: str, *, salt: str | None = None) -> str:
    actual_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), actual_salt.encode("utf-8"), 240_000)
    return f"pbkdf2_sha256${actual_salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hash_password(password, salt=salt)
    return hmac.compare_digest(actual, encoded)
