from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from stzy_app.models import ResourceRecord
from stzy_app.storage.db import connect, record_schema_version


class CsvIndex:
    """Resource index persisted in the shared SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._init_db()
        self.seen = self._load_seen()

    def _init_db(self) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resources (
                    resource_id TEXT PRIMARY KEY,
                    resource_name TEXT NOT NULL,
                    subject TEXT,
                    year TEXT,
                    scene TEXT,
                    rank TEXT,
                    province TEXT,
                    grade TEXT,
                    term TEXT,
                    price REAL,
                    page_count INTEGER,
                    image_count INTEGER,
                    status TEXT NOT NULL,
                    error TEXT,
                    local_dir TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            record_schema_version(connection, "resource_index", 1)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_resources_updated_at ON resources(updated_at DESC)"
            )

    def _load_seen(self) -> set[str]:
        with connect(self.path) as connection:
            rows = connection.execute("SELECT resource_id FROM resources").fetchall()
        return {str(row["resource_id"]) for row in rows}

    def append(self, record: ResourceRecord) -> bool:
        row = asdict(record)
        row["status"] = record.status.value
        row.pop("raw", None)
        inserted = record.resource_id not in self.seen
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO resources (
                    resource_id, resource_name, subject, year, scene, rank, province,
                    grade, term, price, page_count, image_count, status, error,
                    local_dir, updated_at
                )
                VALUES (
                    :resource_id, :resource_name, :subject, :year, :scene, :rank, :province,
                    :grade, :term, :price, :page_count, :image_count, :status, :error,
                    :local_dir, CURRENT_TIMESTAMP
                )
                ON CONFLICT(resource_id) DO UPDATE SET
                    resource_name = excluded.resource_name,
                    subject = excluded.subject,
                    year = excluded.year,
                    scene = excluded.scene,
                    rank = excluded.rank,
                    province = excluded.province,
                    grade = excluded.grade,
                    term = excluded.term,
                    price = excluded.price,
                    page_count = excluded.page_count,
                    image_count = excluded.image_count,
                    status = excluded.status,
                    error = excluded.error,
                    local_dir = excluded.local_dir,
                    updated_at = excluded.updated_at
                """,
                row,
            )
        self.seen.add(record.resource_id)
        return inserted
