from __future__ import annotations

from pathlib import Path

from stzy_app.models import CrawlCombo
from stzy_app.storage.db import connect, record_schema_version


class CrawlState:
    """SQLite state for resumable crawling."""

    def __init__(self, path: Path, *, scope: str = "") -> None:
        self.path = path
        self.scope = scope
        self._init_db()

    def _init_db(self) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_combos (
                    combo_key TEXT PRIMARY KEY,
                    scope TEXT NOT NULL DEFAULT '',
                    subject_code TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(completed_combos)").fetchall()
            }
            if "scope" not in columns:
                connection.execute(
                    "ALTER TABLE completed_combos ADD COLUMN scope TEXT NOT NULL DEFAULT ''"
                )
            record_schema_version(connection, "crawl_state", 1)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resource_state (
                    resource_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(resource_state)").fetchall()
            }
            if "scope" not in columns:
                connection.execute(
                    "ALTER TABLE resource_state ADD COLUMN scope TEXT NOT NULL DEFAULT ''"
                )

    def combo_key(self, combo: CrawlCombo, subject_code: str = "") -> str:
        params = combo.params()
        return "|".join(
            [
                self.scope or "*",
                subject_code or "*",
                params.get("sceneCode", "*"),
                params.get("yearCode", "*"),
                params.get("rank", "*"),
                params.get("provinceCode", "*"),
                params.get("gradeCode", "*"),
                params.get("termCode", "*"),
            ]
        )

    def is_combo_completed(self, combo: CrawlCombo, subject_code: str = "") -> bool:
        key = self.combo_key(combo, subject_code)
        with connect(self.path) as connection:
            row = connection.execute(
                "SELECT 1 FROM completed_combos WHERE combo_key = ?",
                (key,),
            ).fetchone()
        return row is not None

    def mark_combo_completed(self, combo: CrawlCombo, subject_code: str = "") -> None:
        key = self.combo_key(combo, subject_code)
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO completed_combos (combo_key, scope, subject_code)
                VALUES (?, ?, ?)
                """,
                (key, self.scope, subject_code),
            )

    def mark_resource(self, resource_id: str, status: str, error: str = "") -> None:
        scoped_id = f"{self.scope}:{resource_id}" if self.scope else resource_id
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO resource_state (resource_id, scope, status, error, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(resource_id) DO UPDATE SET
                    scope = excluded.scope,
                    status = excluded.status,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (scoped_id, self.scope, status, error),
            )
