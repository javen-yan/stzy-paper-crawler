from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stzy_app.storage.db import connect, record_schema_version


class Preferences:
    """Small key-value store for project-level UI preferences."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._init_db()

    def _init_db(self) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            record_schema_version(connection, "preferences", 1)

    def get(self, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT value_json FROM preferences WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return default or {}
        try:
            value = json.loads(str(row["value_json"]))
        except json.JSONDecodeError:
            return default or {}
        return value if isinstance(value, dict) else default or {}

    def set(self, key: str, value: dict[str, Any]) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO preferences (key, value_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False, default=str)),
            )
