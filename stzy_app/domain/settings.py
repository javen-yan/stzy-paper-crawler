from __future__ import annotations

from pathlib import Path
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.domain.store import DomainStore
from stzy_app.utils import ensure_directory

PUBLIC_SETTING_KEYS = {
    "output_dir",
    "max_active_tasks",
    "max_download_workers",
    "max_convert_workers",
    "max_export_workers",
    "preview_max_pages",
    "preview_max_pixels",
    "preview_timeout_seconds",
    "proxy_mode",
    "proxy_provider",
    "proxy_pool",
    "proxy_api_url",
    "proxy_max_failures",
    "proxy_cooldown_seconds",
    "shenlong_whitelist_key",
    "shenlong_whitelist_sign",
    "study_phase_code",
    "subject_code",
    "subject_name",
    "file_type",
    "max_pages_per_combo",
    "list_delay_seconds",
    "image_delay_seconds",
    "concurrency",
    "max_retries",
    "connect_timeout",
    "read_timeout",
}

SECRET_KEYS = {
    "proxy_pool",
    "proxy_api_url",
    "shenlong_whitelist_key",
    "shenlong_whitelist_sign",
}


class SettingsService:
    def __init__(self, settings: AppSettings, store: DomainStore) -> None:
        self.settings = settings
        self.store = store

    def get_public_settings(self) -> dict[str, Any]:
        persisted = self.store.get_setting("app_settings", {}) or {}
        values = {
            key: str(getattr(self.settings, key)) if isinstance(getattr(self.settings, key, None), Path) else getattr(self.settings, key, None)
            for key in PUBLIC_SETTING_KEYS
            if hasattr(self.settings, key)
        }
        values.update(persisted)
        redacted = dict(values)
        for key in SECRET_KEYS:
            if redacted.get(key):
                redacted[key] = "***"
        return redacted

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.store.get_setting("app_settings", {}) or {}
        for key, value in payload.items():
            if key not in PUBLIC_SETTING_KEYS:
                continue
            if key == "output_dir":
                value = str(ensure_directory(Path(str(value)).expanduser()))
            current[key] = value
        self.store.set_setting("app_settings", current)
        return self.get_public_settings()

    def effective_settings(self) -> AppSettings:
        persisted = self.store.get_setting("app_settings", {}) or {}
        updates = {key: value for key, value in persisted.items() if key in PUBLIC_SETTING_KEYS}
        if "output_dir" in updates:
            updates["output_dir"] = Path(str(updates["output_dir"])).expanduser()
        return self.settings.model_copy(update=updates)
