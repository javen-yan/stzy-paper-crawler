from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Any

from stzy_app.storage.db import connect, record_schema_version


@dataclass
class AccountCredential:
    name: str
    cookie: str = ""
    access_token: str = ""
    user_agent: str = ""
    request_headers_json: str = ""
    import_method: str = ""
    login_phone: str = ""
    login_password: str = ""
    enabled: bool = True
    user_type: int | None = None
    rank: int | None = None
    last_price: float | None = None
    surplus_num: int | None = None
    fail_count: int = 0
    last_error: str = ""
    cooldown_until: str = ""
    last_checked_at: str = ""

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.cookie or self.access_token or self.login_phone)

    @property
    def request_headers(self) -> dict[str, str]:
        try:
            data = json.loads(self.request_headers_json or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        headers = {}
        for key, value in data.items():
            if value is None:
                continue
            headers[str(key).lower()] = str(value)
        return headers

    @property
    def in_cooldown(self) -> bool:
        if not self.cooldown_until:
            return False
        try:
            return datetime.fromisoformat(self.cooldown_until) > datetime.now()
        except ValueError:
            return False

    @property
    def account_type_label(self) -> str:
        if self.user_type == 3 or self.rank == 3 or self.last_price == 0:
            return "VIP/高端"
        if self.user_type:
            return f"类型{self.user_type}"
        return "未知"

    @property
    def health_label(self) -> str:
        if not self.enabled:
            return "停用"
        if self.in_cooldown:
            return "冷却中"
        if self.fail_count:
            return f"失败{self.fail_count}次"
        return "正常"


class AccountPool:
    """Persists crawler accounts and returns enabled credentials round-robin."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._next_index = 0
        self._init_db()
        self.accounts = self._load()

    def _load(self) -> list[AccountCredential]:
        return self._load_db()

    def _init_db(self) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    name TEXT PRIMARY KEY,
                    cookie TEXT NOT NULL DEFAULT '',
                    access_token TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    request_headers_json TEXT NOT NULL DEFAULT '',
                    import_method TEXT NOT NULL DEFAULT '',
                    login_phone TEXT NOT NULL DEFAULT '',
                    login_password TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    user_type INTEGER,
                    rank INTEGER,
                    last_price REAL,
                    surplus_num INTEGER,
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    cooldown_until TEXT NOT NULL DEFAULT '',
                    last_checked_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(accounts)").fetchall()
            }
            migrations = {
                "user_type": "ALTER TABLE accounts ADD COLUMN user_type INTEGER",
                "user_agent": "ALTER TABLE accounts ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''",
                "request_headers_json": "ALTER TABLE accounts ADD COLUMN request_headers_json TEXT NOT NULL DEFAULT ''",
                "import_method": "ALTER TABLE accounts ADD COLUMN import_method TEXT NOT NULL DEFAULT ''",
                "login_phone": "ALTER TABLE accounts ADD COLUMN login_phone TEXT NOT NULL DEFAULT ''",
                "login_password": "ALTER TABLE accounts ADD COLUMN login_password TEXT NOT NULL DEFAULT ''",
                "rank": "ALTER TABLE accounts ADD COLUMN rank INTEGER",
                "last_price": "ALTER TABLE accounts ADD COLUMN last_price REAL",
                "surplus_num": "ALTER TABLE accounts ADD COLUMN surplus_num INTEGER",
                "fail_count": "ALTER TABLE accounts ADD COLUMN fail_count INTEGER NOT NULL DEFAULT 0",
                "last_error": "ALTER TABLE accounts ADD COLUMN last_error TEXT NOT NULL DEFAULT ''",
                "cooldown_until": "ALTER TABLE accounts ADD COLUMN cooldown_until TEXT NOT NULL DEFAULT ''",
                "last_checked_at": "ALTER TABLE accounts ADD COLUMN last_checked_at TEXT NOT NULL DEFAULT ''",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            record_schema_version(connection, "accounts", 4)

    def _load_db(self) -> list[AccountCredential]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT
                    name, cookie, access_token, user_agent, request_headers_json, import_method,
                    login_phone, login_password, enabled, user_type, rank, last_price,
                    surplus_num, fail_count, last_error, cooldown_until, last_checked_at
                FROM accounts
                ORDER BY created_at, name
                """
            ).fetchall()
        return [
            AccountCredential(
                name=str(row["name"]),
                cookie=str(row["cookie"] or ""),
                access_token=str(row["access_token"] or ""),
                user_agent=str(row["user_agent"] or ""),
                request_headers_json=str(row["request_headers_json"] or ""),
                import_method=str(row["import_method"] or ""),
                login_phone=str(row["login_phone"] or ""),
                login_password=str(row["login_password"] or ""),
                enabled=bool(row["enabled"]),
                user_type=row["user_type"],
                rank=row["rank"],
                last_price=row["last_price"],
                surplus_num=row["surplus_num"],
                fail_count=int(row["fail_count"] or 0),
                last_error=str(row["last_error"] or ""),
                cooldown_until=str(row["cooldown_until"] or ""),
                last_checked_at=str(row["last_checked_at"] or ""),
            )
            for row in rows
        ]

    def save(self) -> None:
        with connect(self.path) as connection:
            for account in self.accounts:
                connection.execute(
                    """
                    INSERT INTO accounts (
                        name, cookie, access_token, user_agent, request_headers_json, import_method,
                        login_phone, login_password, enabled, user_type, rank, last_price,
                        surplus_num, fail_count, last_error, cooldown_until, last_checked_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(name) DO UPDATE SET
                        cookie = excluded.cookie,
                        access_token = excluded.access_token,
                        user_agent = excluded.user_agent,
                        request_headers_json = excluded.request_headers_json,
                        import_method = excluded.import_method,
                        login_phone = excluded.login_phone,
                        login_password = excluded.login_password,
                        enabled = excluded.enabled,
                        user_type = excluded.user_type,
                        rank = excluded.rank,
                        last_price = excluded.last_price,
                        surplus_num = excluded.surplus_num,
                        fail_count = excluded.fail_count,
                        last_error = excluded.last_error,
                        cooldown_until = excluded.cooldown_until,
                        last_checked_at = excluded.last_checked_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        account.name,
                        account.cookie,
                        account.access_token,
                        account.user_agent,
                        account.request_headers_json,
                        account.import_method,
                        account.login_phone,
                        account.login_password,
                        1 if account.enabled else 0,
                        account.user_type,
                        account.rank,
                        account.last_price,
                        account.surplus_num,
                        account.fail_count,
                        account.last_error,
                        account.cooldown_until,
                        account.last_checked_at,
                    ),
                )

    def upsert(self, account: AccountCredential) -> None:
        with self._lock:
            for index, current in enumerate(self.accounts):
                if current.name == account.name:
                    self.accounts[index] = self._merge_account(current, account)
                    self.save()
                    return
            self.accounts.append(account)
            self.save()

    def remove(self, name: str) -> None:
        with self._lock:
            self.accounts = [account for account in self.accounts if account.name != name]
            with connect(self.path) as connection:
                connection.execute("DELETE FROM accounts WHERE name = ?", (name,))

    def enabled_accounts(self) -> list[AccountCredential]:
        return [account for account in self.accounts if account.usable]

    def schedulable_accounts(self) -> list[AccountCredential]:
        return [
            account
            for account in self.enabled_accounts()
            if not account.in_cooldown
        ]

    def next(self) -> AccountCredential | None:
        return self.next_matching(lambda account: True)

    def next_matching(self, predicate: Callable[[AccountCredential], bool]) -> AccountCredential | None:
        enabled = self.schedulable_accounts()
        enabled = [account for account in enabled if predicate(account)]
        if not enabled:
            return None
        with self._lock:
            account = enabled[self._next_index % len(enabled)]
            self._next_index += 1
            return account

    def update_download_profile(self, name: str, info: dict[str, object]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            for account in self.accounts:
                if account.name != name:
                    continue
                account.user_type = self._int_or_none(info.get("userType"))
                account.rank = self._int_or_none(info.get("rank"))
                account.last_price = self._float_or_none(info.get("price"))
                account.surplus_num = self._int_or_none(info.get("surplusNum"))
                account.last_checked_at = now
                self.save()
                return

    def mark_success(self, name: str) -> None:
        with self._lock:
            for account in self.accounts:
                if account.name == name:
                    account.fail_count = 0
                    account.last_error = ""
                    account.cooldown_until = ""
                    self.save()
                    return

    def mark_failure(self, name: str, error: str) -> None:
        with self._lock:
            for account in self.accounts:
                if account.name != name:
                    continue
                account.fail_count += 1
                account.last_error = error[:300]
                seconds = min(300, 20 * account.fail_count)
                account.cooldown_until = (datetime.now() + timedelta(seconds=seconds)).isoformat(
                    timespec="seconds"
                )
                self.save()
                return

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _merge_account(current: AccountCredential, incoming: AccountCredential) -> AccountCredential:
        credentials_changed = (
            incoming.cookie != current.cookie
            or incoming.access_token != current.access_token
            or (bool(incoming.user_agent) and incoming.user_agent != current.user_agent)
            or (bool(incoming.request_headers_json) and incoming.request_headers_json != current.request_headers_json)
            or incoming.login_phone != current.login_phone
            or incoming.login_password != current.login_password
        )
        return AccountCredential(
            name=incoming.name,
            cookie=incoming.cookie,
            access_token=incoming.access_token,
            user_agent=incoming.user_agent or current.user_agent,
            request_headers_json=incoming.request_headers_json or current.request_headers_json,
            import_method=incoming.import_method or current.import_method,
            login_phone=incoming.login_phone or current.login_phone,
            login_password=incoming.login_password or current.login_password,
            enabled=incoming.enabled,
            user_type=incoming.user_type if incoming.user_type is not None else current.user_type,
            rank=incoming.rank if incoming.rank is not None else current.rank,
            last_price=incoming.last_price if incoming.last_price is not None else current.last_price,
            surplus_num=incoming.surplus_num if incoming.surplus_num is not None else current.surplus_num,
            fail_count=0 if credentials_changed else incoming.fail_count or current.fail_count,
            last_error="" if credentials_changed else incoming.last_error or current.last_error,
            cooldown_until="" if credentials_changed else incoming.cooldown_until or current.cooldown_until,
            last_checked_at=incoming.last_checked_at or current.last_checked_at,
        )
