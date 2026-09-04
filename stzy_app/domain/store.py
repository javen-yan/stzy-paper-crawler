from __future__ import annotations

import json
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from stzy_app.models import ResourceRecord, ResourceStatus
from stzy_app.storage.db import connect, record_schema_version

TASK_ACTIVE = {"queued", "running", "pausing", "paused"}
TASK_TERMINAL = {"completed", "partial_completed", "failed", "auth_expired", "cancelled", "interrupted"}
TASK_RESUMABLE = {"paused", "partial_completed", "failed", "auth_expired", "interrupted", "cancelled"}


class DomainStore:
    """SQLite storage for the new API/domain layer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._backup_legacy_db()
        self._init_db()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with connect(self.path) as connection:
            yield connection

    def _backup_legacy_db(self) -> None:
        if not self.path.exists():
            return
        backup_marker = self.path.with_suffix(self.path.suffix + ".domain-v1")
        if backup_marker.exists():
            return
        backup_path = self.path.with_suffix(self.path.suffix + f".backup-{int(time.time())}")
        shutil.copy2(self.path, backup_path)
        backup_marker.write_text(str(backup_path), encoding="utf-8")

    def _init_db(self) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_tasks (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    idempotency_key TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    spec_json TEXT NOT NULL DEFAULT '{}',
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    output_dir TEXT NOT NULL DEFAULT '',
                    active_proxy TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_tasks_idempotency "
                "ON domain_tasks(idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain_tasks_status ON domain_tasks(status, archived)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(task_id) REFERENCES domain_tasks(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain_task_logs_task_id "
                "ON domain_task_logs(task_id, id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_task_resources (
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
                    error TEXT NOT NULL DEFAULT '',
                    local_dir TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, resource_id),
                    FOREIGN KEY(task_id) REFERENCES domain_tasks(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain_resources_task_id "
                "ON domain_task_resources(task_id, id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_artifacts (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    media_type TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    page_index INTEGER,
                    parent_artifact_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(task_id, path),
                    FOREIGN KEY(task_id) REFERENCES domain_tasks(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_domain_artifacts_task_resource "
                "ON domain_artifacts(task_id, resource_id, kind)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_exports (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    spec_json TEXT NOT NULL DEFAULT '{}',
                    file_path TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    manifest_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_sessions (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    csrf_token TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            record_schema_version(connection, "domain", 1)

    def create_task(
        self,
        *,
        task_id: str,
        mode: str,
        spec: dict[str, Any],
        output_dir: Path,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().isoformat(timespec="seconds")
        with self.transaction() as connection:
            if idempotency_key:
                existing = connection.execute(
                    "SELECT * FROM domain_tasks WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return self._task_from_row(existing)
            connection.execute(
                """
                INSERT INTO domain_tasks (
                    id, mode, status, idempotency_key, title, spec_json, stats_json,
                    output_dir, created_at, updated_at
                )
                VALUES (?, ?, 'queued', ?, ?, ?, '{}', ?, ?, ?)
                """,
                (
                    task_id,
                    mode,
                    idempotency_key,
                    str(spec.get("title") or ""),
                    _json(spec),
                    str(output_dir),
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT * FROM domain_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row)

    def update_task(self, task_id: str, **updates: Any) -> None:
        if not updates:
            return
        updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
        assignments = []
        values: list[Any] = []
        for key, value in updates.items():
            if key == "manifest":
                continue
            column = {"spec": "spec_json", "stats": "stats_json"}.get(key, key)
            assignments.append(f"{column} = ?")
            values.append(_json(value) if column in {"spec_json", "stats_json"} else value)
        values.append(task_id)
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE domain_tasks SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def set_task_status(self, task_id: str, status: str, *, error: str = "") -> None:
        fields: dict[str, Any] = {"status": status}
        if status == "running":
            fields["started_at"] = datetime.now().isoformat(timespec="seconds")
            fields["error"] = ""
        if status in TASK_TERMINAL or status == "paused":
            fields["ended_at"] = datetime.now().isoformat(timespec="seconds")
        if error:
            fields["error"] = error[:1000]
        self.update_task(task_id, **fields)

    def mark_interrupted_running_tasks(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE domain_tasks
                SET status = 'interrupted', ended_at = ?, updated_at = ?
                WHERE status IN ('running', 'pausing')
                """,
                (now, now),
            )

    def archive_task(self, task_id: str, archived: bool = True) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE domain_tasks SET archived = ?, updated_at = ? WHERE id = ?",
                (1 if archived else 0, datetime.now().isoformat(timespec="seconds"), task_id),
            )
        return cursor.rowcount > 0

    def task(self, task_id: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM domain_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, *, archived: bool = False, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM domain_tasks
                WHERE archived = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (1 if archived else 0, limit, offset),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def queued_tasks(self) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM domain_tasks
                WHERE status = 'queued' AND archived = 0
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def append_log(self, task_id: str, message: str, *, level: str = "info") -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO domain_task_logs (task_id, level, message) VALUES (?, ?, ?)",
                (task_id, level, message),
            )

    def logs(self, task_id: str, *, after: int = 0, limit: int = 100, tail: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit or 100)))
        with self.transaction() as connection:
            if tail and after <= 0:
                rows = connection.execute(
                    """
                    SELECT id, level, message, created_at
                    FROM domain_task_logs
                    WHERE task_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (task_id, limit),
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = connection.execute(
                    """
                    SELECT id, level, message, created_at
                    FROM domain_task_logs
                    WHERE task_id = ? AND id > ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (task_id, after, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def record_resource(self, task_id: str, record: ResourceRecord) -> None:
        row = asdict(record)
        row["status"] = record.status.value
        row["raw_json"] = _json(row.pop("raw", {}) or {})
        row["task_id"] = task_id
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO domain_task_resources (
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
                """
                ,
                row,
            )

    def resources(self, task_id: str, *, limit: int = 100, offset: int = 0, status: str = "") -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit or 100)))
        offset = max(0, int(offset or 0))
        where = "WHERE task_id = ?"
        params: list[Any] = [task_id]
        if status:
            where += " AND status = ?"
            params.append(status)
        params.extend([limit, offset])
        with self.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM domain_task_resources
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        resources = []
        for row in rows:
            resource = dict(row)
            resource["raw"] = _loads(resource.pop("raw_json", ""))
            resources.append(resource)
        return resources

    def resource_count(self, task_id: str, *, status: str = "") -> int:
        where = "WHERE task_id = ?"
        params: list[Any] = [task_id]
        if status:
            where += " AND status = ?"
            params.append(status)
        with self.transaction() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM domain_task_resources {where}",
                params,
            ).fetchone()
        return int(row["count"] or 0) if row else 0

    def completed_resource_ids(self, task_id: str) -> set[str]:
        with self.transaction() as connection:
            rows = connection.execute(
                """
                SELECT resource_id FROM domain_task_resources
                WHERE task_id = ? AND status = 'completed'
                """,
                (task_id,),
            ).fetchall()
        return {str(row["resource_id"]) for row in rows}

    def incomplete_resource_records(self, task_id: str) -> list[ResourceRecord]:
        retry_statuses = [
            ResourceStatus.pending.value,
            ResourceStatus.downloading.value,
            ResourceStatus.partial.value,
            ResourceStatus.paid_unavailable.value,
            ResourceStatus.failed.value,
        ]
        placeholders = ",".join("?" for _ in retry_statuses)
        with self.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM domain_task_resources
                WHERE task_id = ? AND status IN ({placeholders})
                ORDER BY updated_at ASC, id ASC
                """,
                [task_id, *retry_statuses],
            ).fetchall()
        return [self._resource_record_from_row(row) for row in rows]

    def resource_status_counts(self, task_id: str) -> dict[str, int]:
        with self.transaction() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM domain_task_resources
                WHERE task_id = ?
                GROUP BY status
                """,
                (task_id,),
            ).fetchall()
        return {str(row["status"]): int(row["count"] or 0) for row in rows}

    def _resource_record_from_row(self, row: sqlite3.Row) -> ResourceRecord:
        status_value = str(row["status"] or ResourceStatus.pending.value)
        try:
            status = ResourceStatus(status_value)
        except ValueError:
            status = ResourceStatus.pending
        return ResourceRecord(
            resource_id=str(row["resource_id"] or ""),
            resource_name=str(row["resource_name"] or row["resource_id"] or ""),
            subject=str(row["subject"] or ""),
            year=str(row["year"] or ""),
            scene=str(row["scene"] or ""),
            rank=str(row["rank"] or ""),
            province=str(row["province"] or ""),
            grade=str(row["grade"] or ""),
            term=str(row["term"] or ""),
            price=float(row["price"] or 0),
            page_count=int(row["page_count"] or 0),
            image_count=int(row["image_count"] or 0),
            status=status,
            error=str(row["error"] or ""),
            local_dir=str(row["local_dir"] or ""),
            raw=_loads(row["raw_json"] or ""),
        )

    def upsert_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO domain_artifacts (
                    id, task_id, resource_id, kind, path, display_name, media_type,
                    size_bytes, page_index, parent_artifact_id
                )
                VALUES (
                    :id, :task_id, :resource_id, :kind, :path, :display_name, :media_type,
                    :size_bytes, :page_index, :parent_artifact_id
                )
                ON CONFLICT(task_id, path) DO UPDATE SET
                    kind = excluded.kind,
                    resource_id = excluded.resource_id,
                    display_name = excluded.display_name,
                    media_type = excluded.media_type,
                    size_bytes = excluded.size_bytes,
                    page_index = excluded.page_index,
                    parent_artifact_id = excluded.parent_artifact_id
                """,
                artifact,
            )
            row = connection.execute(
                "SELECT * FROM domain_artifacts WHERE task_id = ? AND path = ?",
                (artifact["task_id"], artifact["path"]),
            ).fetchone()
        return dict(row)

    def artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM domain_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        return dict(row) if row else None

    def artifacts(
        self,
        *,
        task_id: str | None = None,
        resource_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if resource_id:
            clauses.append("resource_id = ?")
            params.append(resource_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM domain_artifacts
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_export(self, export: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO domain_exports (
                    id, task_id, status, spec_json, display_name, created_at, expires_at, updated_at
                )
                VALUES (:id, :task_id, :status, :spec_json, :display_name, :created_at, :expires_at, :updated_at)
                """,
                export,
            )
        return self.export(export["id"]) or export

    def update_export(self, export_id: str, **updates: Any) -> None:
        updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
        assignments = []
        values: list[Any] = []
        for key, value in updates.items():
            assignments.append(f"{key} = ?")
            values.append(_json(value) if key in {"spec_json", "manifest_json"} else value)
        values.append(export_id)
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE domain_exports SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def export(self, export_id: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM domain_exports WHERE id = ?", (export_id,)).fetchone()
        return self._export_from_row(row) if row else None

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.transaction() as connection:
            row = connection.execute("SELECT value_json FROM domain_settings WHERE key = ?", (key,)).fetchone()
        return _loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO domain_settings (key, value_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, _json(value)),
            )

    def _task_from_row(self, row: Any) -> dict[str, Any]:
        task = dict(row)
        task["archived"] = bool(task["archived"])
        task["spec"] = _loads(task.pop("spec_json", ""))
        task["stats"] = _loads(task.pop("stats_json", ""))
        return task

    def _export_from_row(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["spec"] = _loads(item.pop("spec_json", ""))
        item["manifest"] = _loads(item.pop("manifest_json", ""))
        return item


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}
