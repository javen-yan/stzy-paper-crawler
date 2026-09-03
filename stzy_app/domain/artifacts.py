from __future__ import annotations

import hashlib
import mimetypes
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.domain.store import DomainStore
from stzy_app.utils import ensure_directory, safe_filename

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
BLOCKED_INLINE_SUFFIXES = {".svg", ".html", ".htm"}


class ArtifactService:
    def __init__(self, store: DomainStore, *, data_root: Path, settings: AppSettings | None = None) -> None:
        self.store = store
        self.data_root = data_root.resolve()
        self.settings = settings or AppSettings(data_dir=data_root, output_dir=data_root)

    def register_resource_artifacts(self, task_id: str, resource_id: str, directory: str | Path) -> None:
        root = Path(directory)
        candidates = []
        if root.exists():
            candidates.extend(path for path in root.glob("练习*.png") if path.is_file())
            candidates.extend(path for path in root.iterdir() if path.is_file())
            pdf = root.parent / f"{root.name}.pdf"
            if pdf.exists():
                candidates.append(pdf)
        for path in sorted(set(candidates)):
            self.register_file(task_id=task_id, resource_id=resource_id, path=path)

    def register_file(self, *, task_id: str, resource_id: str, path: Path, page_index: int | None = None) -> dict[str, Any]:
        safe_path = self.safe_path(path)
        suffix = safe_path.suffix.lower()
        media_type = mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream"
        if suffix in IMAGE_SUFFIXES:
            kind = "image"
        elif suffix == ".pdf":
            kind = "pdf"
        elif suffix in BLOCKED_INLINE_SUFFIXES:
            kind = "attachment"
            media_type = "application/octet-stream"
        else:
            kind = "attachment"
        artifact = {
            "id": artifact_id(task_id, safe_path),
            "task_id": task_id,
            "resource_id": resource_id,
            "kind": kind,
            "path": str(safe_path),
            "display_name": safe_path.name,
            "media_type": media_type,
            "size_bytes": safe_path.stat().st_size,
            "page_index": page_index,
            "parent_artifact_id": "",
        }
        return self.store.upsert_artifact(artifact)

    def list_artifacts(
        self,
        *,
        task_id: str | None = None,
        resource_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        items = self.store.artifacts(task_id=task_id, resource_id=resource_id, kind=kind, limit=limit, offset=offset)
        task_cache: dict[str, dict[str, Any] | None] = {}
        for item in items:
            current_task_id = str(item.get("task_id") or "")
            if current_task_id not in task_cache:
                task_cache[current_task_id] = self.store.task(current_task_id) if current_task_id else None
            self._attach_task_display(item, task_cache[current_task_id])
            self._attach_path_display(item)
        return items

    def browser_list(self, *, task_id: str | None = None, path: str | None = None) -> dict[str, Any]:
        root = self.browser_root(task_id=task_id)
        current_dir = self.browser_file_path(path=path, task_id=task_id, allow_dir=True)
        if not current_dir.exists():
            children: list[dict[str, Any]] = []
        elif not current_dir.is_dir():
            raise ValueError("Path is not a directory")
        else:
            children = [self._browser_file_system_entry(child, root) for child in current_dir.iterdir() if _visible_path(child, root)]
        return {
            "current_path": _relative_posix(current_dir, root),
            "items": sorted(children, key=_file_browser_sort_key),
        }

    def browser_search(
        self,
        *,
        task_id: str | None = None,
        path: str | None = None,
        filter_text: str = "",
        deep: bool = True,
    ) -> dict[str, Any]:
        root = self.browser_root(task_id=task_id)
        current_dir = self.browser_file_path(path=path, task_id=task_id, allow_dir=True)
        if not current_dir.exists():
            return {"items": []}
        if not current_dir.is_dir():
            raise ValueError("Path is not a directory")
        needle = filter_text.strip().lower()
        candidates = current_dir.rglob("*") if deep else current_dir.iterdir()
        matched = []
        for candidate in candidates:
            if not candidate.is_file() or not _visible_path(candidate, root):
                continue
            entry = self._browser_file_system_entry(candidate, root)
            haystack = f"{entry.get('name', '')} {entry.get('relative_path', '')}".lower()
            if not needle or needle in haystack:
                matched.append(entry)
        return {"items": sorted(matched, key=_file_browser_sort_key)}

    def browser_file(self, *, path: str, task_id: str | None = None) -> tuple[dict[str, Any], Path]:
        file_path = self.browser_file_path(path=path, task_id=task_id)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError("File not found")
        root = self.browser_root(task_id=task_id)
        entry = self._browser_file_system_entry(file_path, root)
        entry["kind"] = _file_kind(file_path)
        entry["display_name"] = file_path.name
        return entry, file_path

    def browser_root(self, *, task_id: str | None = None) -> Path:
        if task_id:
            task = self.store.task(task_id)
            if not task:
                raise FileNotFoundError("Task not found")
            configured = Path(str(task.get("output_dir") or ""))
            root = configured if configured.is_absolute() else self.data_root / configured
        else:
            root = self.data_root / "tasks"
        return self.safe_browser_path(root.resolve(), root=self.data_root, allow_missing=True)

    def browser_file_path(self, *, path: str | None, task_id: str | None = None, allow_dir: bool = False) -> Path:
        root = self.browser_root(task_id=task_id)
        relative = _normalize_relative_browser_path(path)
        target = root / relative if relative else root
        safe_target = self.safe_browser_path(target, root=root, allow_missing=True)
        if not allow_dir and safe_target.exists() and not safe_target.is_file():
            raise FileNotFoundError("File not found")
        return safe_target

    def safe_browser_path(self, path: Path, *, root: Path, allow_missing: bool = False) -> Path:
        resolved_root = root.resolve()
        candidate = path.expanduser()
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        try:
            raw_relative_parts = candidate.relative_to(resolved_root).parts
        except ValueError:
            raise PermissionError("Path escapes the file browser root") from None
        if any(part.startswith(".") and part not in {".", ".."} for part in raw_relative_parts):
            raise PermissionError("Hidden files are not browsable")
        current = resolved_root
        for part in raw_relative_parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise PermissionError("Symbolic links are not browsable")
        resolved = candidate.resolve(strict=False)
        if not _is_relative_to(resolved, resolved_root):
            raise PermissionError("Path escapes the file browser root")
        if not allow_missing and not resolved.exists():
            raise FileNotFoundError("File not found")
        return resolved

    def get_artifact_path(self, artifact_id_value: str) -> tuple[dict[str, Any], Path]:
        artifact = self.store.artifact(artifact_id_value)
        if not artifact:
            raise FileNotFoundError("Artifact not found")
        self._attach_task_display(artifact, self.store.task(str(artifact.get("task_id") or "")))
        self._attach_path_display(artifact)
        return artifact, self.safe_path(Path(str(artifact["path"])))

    def safe_path(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if not _is_relative_to(resolved, self.data_root):
            raise PermissionError("Path escapes the configured data root")
        if any(part.startswith(".") and part not in {".", ".."} for part in resolved.relative_to(self.data_root).parts):
            raise PermissionError("Hidden application files are not downloadable")
        if resolved.is_symlink():
            raise PermissionError("Symbolic links are not downloadable")
        return resolved

    def task_display_name(self, task_id: str) -> str:
        item = {"task_id": task_id}
        self._attach_task_display(item, self.store.task(task_id))
        return str(item.get("task_display_name") or _short_task_label(task_id))

    def _attach_task_display(self, item: dict[str, Any], task: dict[str, Any] | None) -> None:
        task_id = str(item.get("task_id") or "")
        title = ""
        if task:
            spec = task.get("spec") if isinstance(task.get("spec"), dict) else {}
            title = str(task.get("title") or spec.get("title") or "").strip()
        item["task_title"] = title
        item["task_display_name"] = title or self._task_filter_name(task) or _short_task_label(task_id)

    def _attach_path_display(self, item: dict[str, Any]) -> None:
        task_id = str(item.get("task_id") or "")
        try:
            path = self.safe_path(Path(str(item.get("path") or "")))
            relative_parts = list(path.relative_to(self.data_root).parts)
        except Exception:
            relative_parts = []
        task_marker = ["tasks", task_id]
        if task_id and len(relative_parts) >= 2 and relative_parts[:2] == task_marker:
            inside_task = relative_parts[2:]
        else:
            inside_task = relative_parts
        directory_parts = inside_task[:-1]
        resource_dir_name = directory_parts[-1] if len(directory_parts) >= 6 else ""
        hierarchy_parts = directory_parts[:-1] if resource_dir_name else directory_parts
        item["relative_path"] = "/".join(inside_task)
        item["directory_path"] = "/".join(directory_parts)
        item["hierarchy_parts"] = hierarchy_parts
        item["hierarchy_path"] = "/".join(hierarchy_parts) if hierarchy_parts else "未分类"
        item["resource_dir_name"] = resource_dir_name
        item["kind_label"] = _kind_label(str(item.get("kind") or ""))

    def _browser_file_system_entry(self, path: Path, root: Path) -> dict[str, Any]:
        relative_path = _relative_posix(path, root)
        is_dir = path.is_dir()
        media_type = None if is_dir else mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        stat = path.stat()
        return {
            "name": path.name,
            "extension": "" if is_dir else _extension_without_dot(path.name),
            "relative_path": relative_path,
            "parent_path": _relative_posix(path.parent, root),
            "item_type": "folder" if is_dir else "file",
            "size_bytes": None if is_dir else stat.st_size,
            "modified_at": int(stat.st_mtime * 1000),
            "media_type": media_type,
        }

    def _task_filter_name(self, task: dict[str, Any] | None) -> str:
        if not task:
            return ""
        spec = task.get("spec") if isinstance(task.get("spec"), dict) else {}
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
        subject_labels = []
        subject_names = _catalog_subjects(catalog_cache, phase)
        for subject in subjects:
            if not isinstance(subject, dict):
                continue
            code = str(subject.get("code") or "")
            name = str(subject.get("name") or subject_names.get(code) or "").strip()
            if name and name != "不限":
                subject_labels.append(name)
            elif code:
                subject_labels.append(code)
        if subject_labels:
            parts.append("、".join(subject_labels[:2]) + ("等" if len(subject_labels) > 2 else ""))

        field_order = [
            ("provinces", "provinceCode"),
            ("grades", "gradeCode"),
            ("terms", "termCode"),
            ("years", "yearCode"),
            ("scenes", "sceneCode"),
            ("ranks", "rank"),
        ]
        for filter_key, catalog_field in field_order:
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

class ExportService:
    def __init__(
        self,
        store: DomainStore,
        artifact_service: ArtifactService,
        *,
        data_root: Path,
        max_workers: int = 1,
    ) -> None:
        self.store = store
        self.artifact_service = artifact_service
        self.data_root = data_root.resolve()
        self.export_root = ensure_directory(self.data_root / "exports")
        self.max_workers = max(1, int(max_workers or 1))
        self.pending_max_workers = self.max_workers
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._futures: dict[str, Future] = {}

    def apply_max_workers(self, max_workers: int) -> None:
        self.pending_max_workers = max(1, int(max_workers or 1))
        self._apply_pending_max_workers_if_idle()

    def _apply_pending_max_workers_if_idle(self) -> None:
        active = [future for future in self._futures.values() if not future.done()]
        if active or self.pending_max_workers == self.max_workers:
            return
        self.executor.shutdown(wait=False, cancel_futures=False)
        self.max_workers = self.pending_max_workers
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

    def create_zip_export(
        self,
        *,
        export_id: str,
        task_id: str,
        file_paths: list[str] | None = None,
        ttl_hours: int = 24,
    ) -> dict[str, Any]:
        now = datetime.now()
        self._apply_pending_max_workers_if_idle()
        display_name = f"{safe_filename(self.artifact_service.task_display_name(task_id), fallback=task_id or 'task')}.zip"
        export = self.store.create_export(
            {
                "id": export_id,
                "task_id": task_id,
                "status": "queued",
                "spec_json": _jsonable({"file_paths": file_paths or []}),
                "display_name": display_name,
                "created_at": now.isoformat(timespec="seconds"),
                "expires_at": (now + timedelta(hours=max(1, ttl_hours))).isoformat(timespec="seconds"),
                "updated_at": now.isoformat(timespec="seconds"),
            }
        )
        self._futures[export_id] = self.executor.submit(self.build_zip, export_id)
        return self.store.export(export_id) or export

    def build_zip(self, export_id: str) -> None:
        export = self.store.export(export_id)
        if not export:
            raise FileNotFoundError("Export not found")
        self.store.update_export(export_id, status="processing")
        spec = export.get("spec") or {}
        task_id = str(export["task_id"])
        selected_paths = [str(item) for item in spec.get("file_paths") or [] if str(item)]
        root = self.artifact_service.browser_root(task_id=task_id)
        files = []
        if selected_paths:
            for selected_path in selected_paths:
                try:
                    files.append(self.artifact_service.browser_file_path(path=selected_path, task_id=task_id))
                except Exception:
                    continue
        elif root.exists():
            files = [path for path in root.rglob("*") if path.is_file() and _visible_path(path, root)]
        if not files:
            self.store.update_export(export_id, status="failed", error="没有可打包的文件")
            return
        target = self.export_root / f"{export_id}.zip"
        manifest = {"included": [], "missing": []}
        try:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    relative_path = _relative_posix(path, root)
                    try:
                        path = self.artifact_service.safe_browser_path(path, root=root)
                    except Exception as exc:  # noqa: BLE001
                        manifest["missing"].append({"path": relative_path, "reason": str(exc)})
                        continue
                    if not path.exists():
                        manifest["missing"].append({"path": relative_path, "reason": "文件不存在"})
                        continue
                    arcname = _zip_path(tuple(Path(relative_path).parts))
                    archive.write(path, arcname)
                    manifest["included"].append({"path": relative_path, "name": arcname})
                archive.writestr("manifest.json", _jsonable(manifest))
            if not manifest["included"]:
                target.unlink(missing_ok=True)
                self.store.update_export(export_id, status="failed", error="没有可用文件", manifest_json=manifest)
                return
            self.store.update_export(
                export_id,
                status="completed",
                file_path=str(target),
                size_bytes=target.stat().st_size,
                manifest_json=manifest,
            )
        except Exception as exc:  # noqa: BLE001
            target.unlink(missing_ok=True)
            self.store.update_export(export_id, status="failed", error=str(exc), manifest_json=manifest)

    def export_path(self, export_id: str) -> tuple[dict[str, Any], Path]:
        export = self.store.export(export_id)
        if not export:
            raise FileNotFoundError("Export not found")
        if export.get("status") != "completed":
            raise FileNotFoundError("Export is not ready")
        path = self.artifact_service.safe_path(Path(str(export.get("file_path") or "")))
        return export, path

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)


def artifact_id(task_id: str, path: Path) -> str:
    digest = hashlib.sha256(f"{task_id}:{path}".encode("utf-8")).hexdigest()[:24]
    return f"art_{digest}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _short_task_label(task_id: str) -> str:
    if not task_id:
        return "未关联任务"
    suffix = task_id[-8:] if len(task_id) > 8 else task_id
    return f"筛选任务 {suffix}"


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


def _catalog_subjects(catalog_cache: dict[str, Any], phase: str) -> dict[str, str]:
    subjects = catalog_cache.get("subjects") if isinstance(catalog_cache, dict) else {}
    phase_subjects = subjects.get(phase) if isinstance(subjects, dict) else {}
    if not isinstance(phase_subjects, dict):
        return {}
    return {str(code): str(name) for code, name in phase_subjects.items()}


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


def _kind_label(kind: str) -> str:
    return {
        "image": "图片",
        "pdf": "PDF",
        "attachment": "附件",
    }.get(kind, kind or "文件")


def _extension_without_dot(filename: str) -> str:
    index = filename.rfind(".")
    return filename[index + 1 :].lower() if index > 0 else ""


def _file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    return "attachment"


def _file_browser_sort_key(entry: dict[str, Any]) -> tuple[int, str]:
    return (0 if entry.get("item_type") == "folder" else 1, str(entry.get("name") or "").lower())


def _normalize_relative_browser_path(path: str | None) -> Path:
    value = str(path or "").strip().replace("\\", "/")
    if not value:
        return Path()
    candidate = Path(value)
    if candidate.is_absolute():
        raise PermissionError("Absolute paths are not browsable")
    parts = [part for part in value.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise PermissionError("Parent path traversal is not allowed")
    return Path(*parts)


def _relative_posix(path: Path, root: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve())
    except ValueError:
        return ""
    return "" if str(relative) == "." else relative.as_posix()


def _visible_path(path: Path, root: Path) -> bool:
    resolved_root = root.resolve()
    try:
        raw_relative = path.relative_to(resolved_root)
    except ValueError:
        return False
    if any(part.startswith(".") for part in raw_relative.parts):
        return False
    current = resolved_root
    for part in raw_relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            return False
    try:
        path.resolve(strict=False).relative_to(resolved_root)
    except ValueError:
        return False
    return True


def _zip_path(parts: tuple[str, ...]) -> str:
    safe_parts = [safe_filename(str(part), fallback="未命名") for part in parts if str(part)]
    return "/".join(safe_parts) or "未命名"


def _jsonable(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
