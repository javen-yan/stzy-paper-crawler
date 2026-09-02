from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from stzy_app.models import ResourceRecord
from stzy_app.storage.db import connect, record_schema_version

ARCHIVED_TASK_STATUS = "del"
TERMINAL_TASK_STATUSES = {"completed", "partial", "failed", "auth_expired"}
RESUMABLE_TASK_STATUSES = {"running", "paused", "partial", "failed", "auth_expired"}
ACTIVE_TASK_STATUSES = {"running", "paused"}


class TaskHistory:
    """Task and per-task resource history persisted in SQLite."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._init_db()

    def _init_db(self) -> None:
        with connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration_seconds INTEGER,
                    filters_json TEXT NOT NULL DEFAULT '{}',
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
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
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, resource_id),
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_started_at ON tasks(started_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_resources_task_id ON task_resources(task_id)"
            )
            record_schema_version(connection, "tasks", 1)

    def start(self, record: dict[str, Any]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        payload = {
            "id": str(record["id"]),
            "mode": str(record["mode"]),
            "status": str(record.get("status") or "running"),
            "started_at": str(record.get("started_at") or now),
            "ended_at": record.get("ended_at"),
            "duration_seconds": record.get("duration_seconds"),
            "filters_json": self._json(record.get("filters") or {}),
            "stats_json": self._json(record.get("stats") or {}),
            "created_at": str(record.get("created_at") or now),
            "updated_at": now,
        }
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, mode, status, started_at, ended_at, duration_seconds,
                    filters_json, stats_json, created_at, updated_at
                )
                VALUES (
                    :id, :mode, :status, :started_at, :ended_at, :duration_seconds,
                    :filters_json, :stats_json, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    mode = excluded.mode,
                    status = excluded.status,
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    duration_seconds = excluded.duration_seconds,
                    filters_json = excluded.filters_json,
                    stats_json = excluded.stats_json,
                    updated_at = excluded.updated_at
                """,
                payload,
            )

    def finish(self, task_id: str, updates: dict[str, Any]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with connect(self.path) as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    ended_at = ?,
                    duration_seconds = ?,
                    stats_json = ?,
                    updated_at = ?
                WHERE id = ?
                    AND status != ?
                """,
                (
                    str(updates.get("status") or "failed"),
                    str(updates.get("ended_at") or now),
                    updates.get("duration_seconds"),
                    self._json(updates.get("stats") or {}),
                    now,
                    task_id,
                    ARCHIVED_TASK_STATUS,
                ),
            )

    def resume(self, task_id: str, stats: dict[str, Any] | None = None) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        placeholders = ", ".join("?" for _ in RESUMABLE_TASK_STATUSES)
        with connect(self.path) as connection:
            cursor = connection.execute(
                f"""
                UPDATE tasks
                SET status = 'running',
                    stats_json = ?,
                    updated_at = ?
                WHERE id = ?
                    AND status IN ({placeholders})
                """,
                (self._json(stats or {}), now, task_id, *RESUMABLE_TASK_STATUSES),
            )
        return cursor.rowcount > 0

    def cancel(self, task_id: str) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        placeholders = ", ".join("?" for _ in ACTIVE_TASK_STATUSES)
        with connect(self.path) as connection:
            cursor = connection.execute(
                f"""
                UPDATE tasks
                SET status = ?,
                    ended_at = COALESCE(ended_at, ?),
                    updated_at = ?
                WHERE id = ?
                    AND status IN ({placeholders})
                """,
                (ARCHIVED_TASK_STATUS, now, now, task_id, *ACTIVE_TASK_STATUSES),
            )
        return cursor.rowcount > 0

    def archive(self, task_id: str) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        placeholders = ", ".join("?" for _ in TERMINAL_TASK_STATUSES)
        with connect(self.path) as connection:
            cursor = connection.execute(
                f"""
                UPDATE tasks
                SET status = ?,
                    updated_at = ?
                WHERE id = ?
                    AND status IN ({placeholders})
                """,
                (ARCHIVED_TASK_STATUS, now, task_id, *TERMINAL_TASK_STATUSES),
            )
        return cursor.rowcount > 0

    def record_resource(self, task_id: str, record: ResourceRecord) -> None:
        row = asdict(record)
        row["status"] = record.status.value
        row["raw_json"] = self._json(row.pop("raw", {}) or {})
        row["task_id"] = task_id
        with connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO task_resources (
                    task_id, resource_id, resource_name, subject, year, scene, rank,
                    province, grade, term, price, page_count, image_count, status,
                    error, local_dir, raw_json, updated_at
                )
                VALUES (
                    :task_id, :resource_id, :resource_name, :subject, :year, :scene, :rank,
                    :province, :grade, :term, :price, :page_count, :image_count, :status,
                    :error, :local_dir, :raw_json, CURRENT_TIMESTAMP
                )
                ON CONFLICT(task_id, resource_id) DO UPDATE SET
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
                    raw_json = excluded.raw_json,
                    updated_at = excluded.updated_at
                """,
                row,
            )

    def recent(self, limit: int = 20, *, mode: str | None = None) -> list[dict[str, Any]]:
        where_clauses = ["tasks.status != ?"]
        params: list[Any] = [ARCHIVED_TASK_STATUS]
        if mode:
            where_clauses.append("tasks.mode = ?")
            params.append(mode)
        where_sql = "WHERE " + " AND ".join(where_clauses)
        params.append(limit)
        with connect(self.path) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    tasks.*,
                    COUNT(task_resources.id) AS resource_record_count,
                    (
                        SELECT local_dir
                        FROM task_resources AS first_resource
                        WHERE first_resource.task_id = tasks.id
                            AND first_resource.local_dir IS NOT NULL
                            AND first_resource.local_dir != ''
                        ORDER BY first_resource.created_at ASC
                        LIMIT 1
                    ) AS first_local_dir
                FROM tasks
                LEFT JOIN task_resources ON task_resources.task_id = tasks.id
                {where_sql}
                GROUP BY tasks.id
                ORDER BY tasks.started_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def resources(self, task_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_resources
                WHERE task_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        resources = []
        for row in rows:
            resource = dict(row)
            resource["raw"] = self._loads(resource.pop("raw_json", ""))
            resources.append(resource)
        return resources

    def completed_resource_ids(self, task_id: str) -> set[str]:
        with connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT resource_id
                FROM task_resources
                WHERE task_id = ?
                    AND status = 'completed'
                """,
                (task_id,),
            ).fetchall()
        return {str(row["resource_id"]) for row in rows}

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _loads(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _task_from_row(self, row: Any) -> dict[str, Any]:
        task = dict(row)
        task["filters"] = self._loads(task.pop("filters_json", ""))
        task["stats"] = self._loads(task.pop("stats_json", ""))
        return task
