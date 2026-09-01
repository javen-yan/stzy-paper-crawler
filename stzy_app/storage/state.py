from __future__ import annotations

from pathlib import Path

from stzy_app.models import CrawlCombo
from stzy_app.storage.db import connect


class CrawlState:
    """SQLite state for resumable crawling."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._init_db()

    def _init_db(self) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_combos (
                    combo_key TEXT PRIMARY KEY,
                    subject_code TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resource_state (
                    resource_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def combo_key(self, combo: CrawlCombo, subject_code: str = "") -> str:
        params = combo.params()
        return "|".join(
            [
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
                INSERT OR IGNORE INTO completed_combos (combo_key, subject_code)
                VALUES (?, ?)
                """,
                (key, subject_code),
            )

    def mark_resource(self, resource_id: str, status: str, error: str = "") -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO resource_state (resource_id, status, error, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(resource_id) DO UPDATE SET
                    status = excluded.status,
                    error = excluded.error,
                    updated_at = excluded.updated_at
                """,
                (resource_id, status, error),
            )
