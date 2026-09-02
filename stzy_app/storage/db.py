from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from stzy_app.utils import ensure_directory


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    ensure_directory(path.parent)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def record_schema_version(connection: sqlite3.Connection, component: str, version: int) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
            component TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO schema_versions (component, version, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(component) DO UPDATE SET
            version = excluded.version,
            updated_at = excluded.updated_at
        """,
        (component, version),
    )
