from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.crawler import CrawlRunner, CrawlStats
from stzy_app.domain.artifacts import ArtifactService
from stzy_app.domain.store import DomainStore, TASK_RESUMABLE
from stzy_app.http import StzyApiError
from stzy_app.models import CrawlFilters, ResourceRecord
from stzy_app.utils import ensure_directory


class TaskConflict(RuntimeError):
    pass


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    text = str(value)
    return [text] if text else []


def _catalog_phase_label(catalog_cache: dict[str, Any], phase: str) -> str:
    phases = catalog_cache.get("study_phases") if isinstance(catalog_cache, dict) else {}
    if isinstance(phases, dict) and phase:
        return str(phases.get(phase) or phase)
    return {"200": "初中", "300": "高中"}.get(phase, phase)


def _catalog_option_labels(catalog_cache: dict[str, Any], phase: str, field: str, values: list[str]) -> list[str]:
    catalogs = catalog_cache.get("catalogs") if isinstance(catalog_cache, dict) else {}
    phase_catalogs = catalogs.get(phase) if isinstance(catalogs, dict) else {}
    options = phase_catalogs.get(field) if isinstance(phase_catalogs, dict) else []
    by_code = {}
    if isinstance(options, list):
        for option in options:
            if not isinstance(option, dict):
                continue
            code = str(option.get("code") or "")
            name = str(option.get("name") or "")
            if code and name:
                by_code[code] = name
    labels = [by_code[value] for value in values if value in by_code]
    return labels if len(labels) == len(values) else []


class TaskService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        store: DomainStore,
        artifact_service: ArtifactService,
    ) -> None:
        self.settings = settings
        self.store = store
        self.artifact_service = artifact_service
        runtime_settings = self._runtime_settings()
        self.executor = ThreadPoolExecutor(max_workers=max(1, runtime_settings.max_active_tasks))
        self.download_semaphore = threading.Semaphore(max(1, runtime_settings.max_download_workers))
        self._handles: dict[str, Future] = {}
        self._runners: dict[str, CrawlRunner] = {}
        self._lock = threading.Lock()
        self.store.mark_interrupted_running_tasks()
        for task in self.store.queued_tasks():
            self._enqueue_existing(task)

    def apply_runtime_limits(self) -> None:
        """Refresh scheduler limits from persisted settings.

        Running tasks keep their existing runner and semaphore reference. Newly
        started runners use the refreshed download limit. The task executor can
        be resized immediately when no task is currently active; otherwise the
        persisted value remains authoritative for the next clean service start.
        """
        runtime_settings = self._runtime_settings()
        with self._lock:
            self.download_semaphore = threading.Semaphore(max(1, runtime_settings.max_download_workers))
            active = [future for future in self._handles.values() if not future.done()]
            if not active:
                self.executor.shutdown(wait=False, cancel_futures=False)
                self.executor = ThreadPoolExecutor(max_workers=max(1, runtime_settings.max_active_tasks))

    def create_task(
        self,
        *,
        mode: str,
        filters: dict[str, Any],
        filter_labels: dict[str, Any] | None = None,
        subjects: list[dict[str, str]] | None = None,
        settings_overrides: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        title: str = "",
    ) -> dict[str, Any]:
        runtime_settings = self._runtime_settings()
        runtime_settings = self._apply_runtime_overrides(runtime_settings, settings_overrides or {})
        normalized_subjects = self._normalize_subjects(subjects, runtime_settings)
        if len(normalized_subjects) == 1:
            runtime_settings = runtime_settings.model_copy(
                update={
                    "subject_code": normalized_subjects[0].get("code", ""),
                    "subject_name": normalized_subjects[0].get("name", ""),
                }
            )
        normalized_mode = "estimate" if mode == "estimate" else "crawl"
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        task_root = ensure_directory(runtime_settings.output_dir / "tasks" / task_id)
        spec = {
            "title": title,
            "mode": normalized_mode,
            "filters": filters,
            "filter_labels": filter_labels or {},
            "subjects": normalized_subjects,
            "settings": self._public_settings_snapshot(runtime_settings, settings_overrides or {}),
        }
        task = self.store.create_task(
            task_id=task_id,
            mode=normalized_mode,
            spec=spec,
            output_dir=task_root,
            idempotency_key=idempotency_key,
        )
        self._enqueue_existing(task)
        return task

    def estimate_preview(
        self,
        *,
        filters: dict[str, Any],
        filter_labels: dict[str, Any] | None = None,
        subjects: list[dict[str, str]] | None = None,
        settings_overrides: dict[str, Any] | None = None,
        title: str = "",
    ) -> dict[str, Any]:
        runtime_settings = self._runtime_settings()
        settings_overrides = settings_overrides or {}
        runtime_settings = self._apply_runtime_overrides(runtime_settings, settings_overrides)
        normalized_subjects = self._normalize_subjects(subjects, runtime_settings)
        if len(normalized_subjects) == 1:
            runtime_settings = runtime_settings.model_copy(
                update={
                    "subject_code": normalized_subjects[0].get("code", ""),
                    "subject_name": normalized_subjects[0].get("name", ""),
                }
            )
        spec = {
            "title": title,
            "mode": "estimate",
            "filters": filters,
            "filter_labels": filter_labels or {},
            "subjects": normalized_subjects,
            "settings": self._public_settings_snapshot(runtime_settings, settings_overrides),
        }
        logs: list[dict[str, Any]] = []
        aggregate = CrawlStats(task_mode="estimate", phase="running", running=True)
        for subject in spec["subjects"]:
            subject_code = str(subject.get("code") or "")
            subject_name = str(subject.get("name") or subject_code or "不限")
            task_settings = self._estimate_settings(
                f"estimate_preview_{uuid.uuid4().hex[:8]}",
                subject_code=subject_code,
                subject_name=subject_name,
                base_settings=runtime_settings,
            )
            runner = CrawlRunner(
                task_settings,
                CrawlFilters(**filters),
                on_log=lambda message: logs.append(
                    {
                        "id": len(logs) + 1,
                        "level": "info",
                        "message": message,
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                ),
                on_record=lambda _record: None,
                on_progress=lambda stats: None,
                on_proxy=lambda _proxy: None,
                completed_resource_ids=set(),
                download_semaphore=self.download_semaphore,
            )
            aggregate = self._merge_stats(aggregate, runner.estimate())
        aggregate.running = False
        aggregate.phase = "preview"
        aggregate.outcome = "estimated"
        return {
            "stats": asdict(aggregate),
            "logs": logs,
            "spec": spec,
        }

    def resume_task(self, task_id: str) -> dict[str, Any]:
        task = self.store.task(task_id)
        if not task:
            raise FileNotFoundError("Task not found")
        if task["status"] not in TASK_RESUMABLE:
            raise TaskConflict(f"当前状态 {task['status']} 不可恢复")
        self.store.set_task_status(task_id, "queued")
        refreshed = self.store.task(task_id)
        if refreshed:
            self._enqueue_existing(refreshed)
            return refreshed
        raise FileNotFoundError("Task not found")

    def pause_task(self, task_id: str) -> dict[str, Any]:
        task = self.store.task(task_id)
        if not task:
            raise FileNotFoundError("Task not found")
        if task["status"] == "queued":
            self.store.set_task_status(task_id, "paused")
            return self.store.task(task_id) or task
        if task["status"] != "running":
            raise TaskConflict(f"当前状态 {task['status']} 不可暂停")
        self.store.set_task_status(task_id, "pausing")
        runner = self._runners.get(task_id)
        if runner:
            runner.stop()
        return self.store.task(task_id) or task

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        task = self.store.task(task_id)
        if not task:
            raise FileNotFoundError("Task not found")
        runner = self._runners.get(task_id)
        if runner:
            runner.stop()
        self.store.set_task_status(task_id, "cancelled")
        return self.store.task(task_id) or task

    def archive_task(self, task_id: str) -> dict[str, Any]:
        if not self.store.archive_task(task_id, True):
            raise FileNotFoundError("Task not found")
        return self.store.task(task_id) or {"id": task_id, "archived": True}

    def list_tasks(self, *, archived: bool = False, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        tasks = self.store.list_tasks(archived=archived, limit=limit, offset=offset)
        for task in tasks:
            self._attach_task_display(task)
        return tasks

    def task(self, task_id: str) -> dict[str, Any]:
        task = self.store.task(task_id)
        if not task:
            raise FileNotFoundError("Task not found")
        self._attach_task_display(task)
        return task

    def resources(self, task_id: str, *, limit: int = 100, offset: int = 0, status: str = "") -> dict[str, Any]:
        return {
            "items": self.store.resources(task_id, limit=limit, offset=offset, status=status),
            "total": self.store.resource_count(task_id, status=status),
            "status_counts": self.store.resource_status_counts(task_id),
        }

    def logs(self, task_id: str, *, after: int = 0, limit: int = 300, tail: bool = False) -> list[dict[str, Any]]:
        return self.store.logs(task_id, after=after, limit=limit, tail=tail)

    def _enqueue_existing(self, task: dict[str, Any]) -> None:
        task_id = str(task["id"])
        with self._lock:
            future = self._handles.get(task_id)
            if future and not future.done():
                return
            self._handles[task_id] = self.executor.submit(self._run_task, task_id)

    def _run_task(self, task_id: str) -> None:
        task = self.store.task(task_id)
        if not task or task["status"] in {"cancelled", "completed"}:
            return
        self.store.set_task_status(task_id, "running")
        spec = task.get("spec") or {}
        mode = str(spec.get("mode") or task.get("mode") or "crawl")
        started_at = datetime.now()
        aggregate = CrawlStats(task_mode=mode, phase="running", running=True)
        try:
            filters = CrawlFilters(**(spec.get("filters") or {}))
            runtime_settings = self._runtime_settings()
            spec_settings = spec.get("settings") if isinstance(spec.get("settings"), dict) else {}
            runtime_settings = runtime_settings.model_copy(
                update={
                    key: value
                    for key, value in spec_settings.items()
                    if key
                    in {
                        "study_phase_code",
                        "subject_code",
                        "subject_name",
                        "file_type",
                        "max_pages_per_combo",
                        "list_delay_seconds",
                        "image_delay_seconds",
                        "list_max_retries",
                        "combo_failure_limit",
                        "concurrency",
                        "proxy_mode",
                        "proxy_provider",
                        "proxy_min_ttl_seconds",
                    }
                }
            )
            subjects = spec.get("subjects") or [{"code": runtime_settings.subject_code, "name": runtime_settings.subject_name}]
            for subject in subjects:
                latest = self.store.task(task_id)
                if latest and latest["status"] in {"cancelled", "pausing", "paused"}:
                    aggregate.paused = True
                    break
                subject_code = str(subject.get("code") or "")
                subject_name = str(subject.get("name") or subject_code or "不限")
                task_settings = self._task_settings(
                    task_id,
                    subject_code=subject_code,
                    subject_name=subject_name,
                    base_settings=runtime_settings,
                )
                runner = CrawlRunner(
                    task_settings,
                    filters,
                    on_log=lambda message, tid=task_id: self.store.append_log(tid, message),
                    on_record=lambda record, tid=task_id: self._record(tid, record),
                    on_progress=lambda stats, tid=task_id: self._progress(tid, stats),
                    on_proxy=lambda proxy, tid=task_id: self.store.update_task(tid, active_proxy=proxy or ""),
                    completed_resource_ids=self.store.completed_resource_ids(task_id),
                    download_semaphore=self.download_semaphore,
                )
                self._runners[task_id] = runner
                result = runner.estimate() if mode == "estimate" else runner.run()
                aggregate = self._merge_stats(aggregate, result)
                if result.aborted:
                    break
                if result.paused:
                    break
            stats_payload = self._final_stats(task_id, aggregate)
            status = self._final_status(task_id, aggregate, stats_payload)
            duration = int((datetime.now() - started_at).total_seconds())
            self.store.update_task(
                task_id,
                status=status,
                ended_at=datetime.now().isoformat(timespec="seconds"),
                error=aggregate.error if status == "failed" else "",
                stats_json={**stats_payload, "duration_seconds": duration},
            )
        except StzyApiError as exc:
            status = "auth_expired" if exc.requires_login else "failed"
            self.store.set_task_status(task_id, status, error=exc.message)
            self.store.append_log(task_id, exc.message, level="error")
        except Exception as exc:  # noqa: BLE001
            self.store.set_task_status(task_id, "failed", error=str(exc))
            self.store.append_log(task_id, f"任务失败：{exc}", level="error")
        finally:
            self._runners.pop(task_id, None)

    def _record(self, task_id: str, record: ResourceRecord) -> None:
        self.store.record_resource(task_id, record)
        if record.local_dir:
            try:
                self.artifact_service.register_resource_artifacts(task_id, record.resource_id, record.local_dir)
            except Exception as exc:  # noqa: BLE001
                self.store.append_log(task_id, f"产物登记失败：{record.resource_id} - {exc}", level="warning")

    def _progress(self, task_id: str, stats: CrawlStats) -> None:
        self.store.update_task(task_id, stats_json=asdict(stats))

    def _task_settings(
        self,
        task_id: str,
        *,
        subject_code: str,
        subject_name: str,
        base_settings: AppSettings | None = None,
    ) -> AppSettings:
        runtime_settings = base_settings or self._runtime_settings()
        task_root = ensure_directory(runtime_settings.output_dir / "tasks" / task_id)
        state_root = ensure_directory(task_root / ".state")
        return runtime_settings.model_copy(
            update={
                "output_dir": task_root,
                "state_file": state_root / "state.db",
                "csv_file": state_root / "index.db",
                "task_history_file": self.settings.task_history_file,
                "account_pool_file": self.settings.account_pool_file,
                "subject_code": subject_code,
                "subject_name": subject_name,
                "task_scope": task_id,
            }
        )

    def _estimate_settings(
        self,
        estimate_id: str,
        *,
        subject_code: str,
        subject_name: str,
        base_settings: AppSettings | None = None,
    ) -> AppSettings:
        runtime_settings = base_settings or self._runtime_settings()
        estimate_root = ensure_directory(self.settings.data_dir / ".tmp" / "estimates" / estimate_id)
        return runtime_settings.model_copy(
            update={
                "output_dir": estimate_root,
                "state_file": estimate_root / "state.db",
                "csv_file": estimate_root / "index.db",
                "task_history_file": self.settings.task_history_file,
                "account_pool_file": self.settings.account_pool_file,
                "subject_code": subject_code,
                "subject_name": subject_name,
                "task_scope": estimate_id,
            }
        )

    def _runtime_settings(self) -> AppSettings:
        persisted = self.store.get_setting("app_settings", {}) or {}
        allowed = {
            "output_dir",
            "study_phase_code",
            "subject_code",
            "subject_name",
            "file_type",
            "max_pages_per_combo",
            "list_delay_seconds",
            "image_delay_seconds",
            "list_max_retries",
            "combo_failure_limit",
            "concurrency",
            "max_retries",
            "connect_timeout",
            "read_timeout",
            "proxy_mode",
            "proxy_provider",
            "proxy_pool",
            "proxy_api_url",
            "proxy_max_failures",
            "proxy_cooldown_seconds",
            "proxy_min_ttl_seconds",
            "shenlong_whitelist_key",
            "shenlong_whitelist_sign",
            "max_active_tasks",
            "max_download_workers",
            "max_convert_workers",
            "max_export_workers",
        }
        updates = {key: value for key, value in persisted.items() if key in allowed}
        if "output_dir" in updates:
            updates["output_dir"] = Path(str(updates["output_dir"])).expanduser()
        return self.settings.model_copy(update=updates)

    def _normalize_subjects(
        self,
        subjects: list[dict[str, str]] | None,
        settings: AppSettings,
    ) -> list[dict[str, str]]:
        entries = subjects or [{"code": settings.subject_code, "name": settings.subject_name}]
        names = self._subject_names(settings.study_phase_code)
        normalized = []
        for subject in entries:
            code = str(subject.get("code") or "")
            name = str(subject.get("name") or names.get(code) or code or "不限")
            normalized.append({"code": code, "name": name})
        return normalized

    def _subject_names(self, study_phase_code: str) -> dict[str, str]:
        cached = self.store.get_setting("catalog_cache", {}) or {}
        subjects = cached.get("subjects") if isinstance(cached, dict) else {}
        if not isinstance(subjects, dict):
            return {}
        phase_subjects = subjects.get(str(study_phase_code)) or {}
        if not isinstance(phase_subjects, dict):
            return {}
        return {str(code): str(name) for code, name in phase_subjects.items()}

    def _apply_runtime_overrides(self, settings: AppSettings, overrides: dict[str, Any]) -> AppSettings:
        allowed = {
            "study_phase_code",
            "subject_code",
            "subject_name",
            "file_type",
            "max_pages_per_combo",
            "list_delay_seconds",
            "image_delay_seconds",
            "list_max_retries",
            "combo_failure_limit",
            "concurrency",
            "proxy_mode",
            "proxy_provider",
            "proxy_min_ttl_seconds",
        }
        updates = {key: value for key, value in overrides.items() if key in allowed}
        return settings.model_copy(update=updates) if updates else settings

    def _public_settings_snapshot(self, settings: AppSettings, overrides: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "study_phase_code",
            "subject_code",
            "subject_name",
            "file_type",
            "max_pages_per_combo",
            "list_delay_seconds",
            "image_delay_seconds",
            "list_max_retries",
            "combo_failure_limit",
            "concurrency",
            "proxy_mode",
            "proxy_provider",
            "proxy_min_ttl_seconds",
            "max_pages_per_combo",
        }
        snapshot = {key: getattr(settings, key) for key in allowed if hasattr(settings, key)}
        for key, value in overrides.items():
            if key in allowed:
                snapshot[key] = value
        return snapshot

    def _attach_task_display(self, task: dict[str, Any]) -> None:
        title = str(task.get("title") or (task.get("spec") or {}).get("title") or "").strip()
        task["task_title"] = title
        task["task_display_name"] = title or self._filter_display_name(task.get("spec") or "")
        self._attach_resource_status_summary(task)

    def _attach_resource_status_summary(self, task: dict[str, Any]) -> None:
        if task.get("mode") != "crawl":
            return
        counts = self.store.resource_status_counts(str(task.get("id") or ""))
        if not counts:
            return
        stats = dict(task.get("stats") or {})
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        paid = counts.get("paid_unavailable", 0) + counts.get("skipped_paid", 0)
        partial = counts.get("partial", 0)
        processed = completed + failed + paid + partial + int(stats.get("filtered_skipped") or 0)
        stats["resources_processed"] = max(int(stats.get("resources_processed") or 0), int(stats.get("resources_completed") or 0), processed)
        stats["resources_success"] = completed
        stats["resources_completed"] = completed
        stats["failed"] = max(int(stats.get("failed") or 0), failed)
        stats["paid_skipped"] = max(int(stats.get("paid_skipped") or 0), paid)
        stats["preview_limited"] = max(int(stats.get("preview_limited") or 0), partial)
        stats["resource_status_counts"] = counts
        task["stats"] = stats

    def _filter_display_name(self, spec: Any) -> str:
        if not isinstance(spec, dict):
            return ""
        settings = spec.get("settings") if isinstance(spec.get("settings"), dict) else {}
        filters = spec.get("filters") if isinstance(spec.get("filters"), dict) else {}
        filter_labels = spec.get("filter_labels") if isinstance(spec.get("filter_labels"), dict) else {}
        phase = str(settings.get("study_phase_code") or "")
        catalog_cache = self.store.get_setting("catalog_cache", {}) or {}
        parts: list[str] = []

        phase_label = _catalog_phase_label(catalog_cache, phase)
        if phase_label:
            parts.append(phase_label)

        subjects = spec.get("subjects") if isinstance(spec.get("subjects"), list) else []
        subject_names = self._subject_names(phase)
        subject_labels = []
        for subject in subjects:
            if not isinstance(subject, dict):
                continue
            code = str(subject.get("code") or "")
            name = str(subject.get("name") or subject_names.get(code) or "").strip()
            if name and name != "不限":
                subject_labels.append(name)
            elif code and not code.isdigit():
                subject_labels.append(code)
        if subject_labels:
            parts.append("、".join(subject_labels[:2]) + ("等" if len(subject_labels) > 2 else ""))

        for filter_key, catalog_field in [
            ("provinces", "provinceCode"),
            ("grades", "gradeCode"),
            ("terms", "termCode"),
            ("years", "yearCode"),
            ("scenes", "sceneCode"),
            ("ranks", "rank"),
        ]:
            values = _string_list(filters.get(filter_key))
            if not values:
                continue
            labels = _string_list(filter_labels.get(filter_key)) or _catalog_option_labels(catalog_cache, phase, catalog_field, values)
            if labels:
                parts.append("、".join(labels[:2]) + ("等" if len(labels) > 2 else ""))

        file_type = str(settings.get("file_type") or "").strip()
        if file_type:
            parts.append(file_type)

        return " / ".join(dict.fromkeys(part for part in parts if part))

    @staticmethod
    def _merge_stats(base: CrawlStats, result: CrawlStats) -> CrawlStats:
        base.total_combos += result.total_combos
        base.completed_combos += result.completed_combos
        base.resources_seen += result.resources_seen
        base.resources_total += result.resources_total
        base.resources_completed += result.resources_completed
        base.images_downloaded += result.images_downloaded
        base.paid_skipped += result.paid_skipped
        base.filtered_skipped += result.filtered_skipped
        base.preview_limited += result.preview_limited
        base.failed += result.failed
        base.paused = base.paused or result.paused
        base.aborted = base.aborted or result.aborted
        base.error = result.error or base.error
        base.outcome = result.outcome
        base.phase = result.phase
        base.running = False
        return base

    def _final_stats(self, task_id: str, stats: CrawlStats) -> dict[str, Any]:
        payload = asdict(stats)
        counts = self.store.resource_status_counts(task_id)
        if not counts:
            return payload
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        paid = counts.get("paid_unavailable", 0) + counts.get("skipped_paid", 0)
        partial = counts.get("partial", 0)
        processed = completed + failed + paid + partial + int(payload.get("filtered_skipped") or 0)
        payload["resources_processed"] = max(int(payload.get("resources_completed") or 0), processed)
        payload["resources_success"] = completed
        payload["resources_completed"] = completed
        payload["failed"] = max(int(payload.get("failed") or 0), failed)
        payload["paid_skipped"] = max(int(payload.get("paid_skipped") or 0), paid)
        payload["preview_limited"] = max(int(payload.get("preview_limited") or 0), partial)
        payload["resource_status_counts"] = counts
        return payload

    def _final_status(self, task_id: str, stats: CrawlStats, stats_payload: dict[str, Any] | None = None) -> str:
        task = self.store.task(task_id)
        if task and task["status"] == "cancelled":
            return "cancelled"
        if stats.aborted:
            return "failed"
        if stats.paused:
            return "paused"
        payload = stats_payload or asdict(stats)
        if payload.get("failed") or payload.get("paid_skipped") or payload.get("preview_limited"):
            return "partial_completed"
        return "completed"
