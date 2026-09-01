from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from stzy_app.storage.db import connect


@dataclass
class AccountCredential:
    name: str
    cookie: str = ""
    access_token: str = ""
    enabled: bool = True

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.cookie or self.access_token)


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
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _load_db(self) -> list[AccountCredential]:
        with connect(self.path) as connection:
            rows = connection.execute(
                "SELECT name, cookie, access_token, enabled FROM accounts ORDER BY created_at, name"
            ).fetchall()
        return [
            AccountCredential(
                name=str(row["name"]),
                cookie=str(row["cookie"] or ""),
                access_token=str(row["access_token"] or ""),
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def save(self) -> None:
        with connect(self.path) as connection:
            connection.execute("DELETE FROM accounts")
            for account in self.accounts:
                connection.execute(
                    """
                    INSERT INTO accounts (name, cookie, access_token, enabled, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        account.name,
                        account.cookie,
                        account.access_token,
                        1 if account.enabled else 0,
                    ),
                )

    def upsert(self, account: AccountCredential) -> None:
        with self._lock:
            for index, current in enumerate(self.accounts):
                if current.name == account.name:
                    self.accounts[index] = account
                    self.save()
                    return
            self.accounts.append(account)
            self.save()

    def remove(self, name: str) -> None:
        with self._lock:
            self.accounts = [account for account in self.accounts if account.name != name]
            self.save()

    def enabled_accounts(self) -> list[AccountCredential]:
        return [account for account in self.accounts if account.usable]

    def next(self) -> AccountCredential | None:
        return self.next_matching(lambda account: True)

    def next_matching(self, predicate: Callable[[AccountCredential], bool]) -> AccountCredential | None:
        enabled = self.enabled_accounts()
        enabled = [account for account in enabled if predicate(account)]
        if not enabled:
            return None
        with self._lock:
            account = enabled[self._next_index % len(enabled)]
            self._next_index += 1
            return account
