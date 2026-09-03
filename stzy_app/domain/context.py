from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stzy_app.config import AppSettings
from stzy_app.crawler.conversion_pool import configure_conversion_pool
from stzy_app.domain.accounts import AccountService
from stzy_app.domain.artifacts import ArtifactService, ExportService
from stzy_app.domain.catalogs import CatalogService
from stzy_app.domain.settings import SettingsService
from stzy_app.domain.store import DomainStore
from stzy_app.domain.tasks import TaskService
from stzy_app.runtime import RuntimeAdapter
from stzy_app.utils import ensure_directory


@dataclass
class AppContext:
    settings: AppSettings
    runtime: RuntimeAdapter
    store: DomainStore
    accounts: AccountService
    artifacts: ArtifactService
    catalogs: CatalogService
    exports: ExportService
    settings_service: SettingsService
    tasks: TaskService


def create_context(settings: AppSettings, runtime: RuntimeAdapter) -> AppContext:
    data_root = ensure_directory((settings.data_dir if settings.data_dir != Path(".") else settings.output_dir).resolve())
    app_db = data_root / "stzy.db"
    runtime_settings = settings.model_copy(
        update={
            "runtime_mode": runtime.mode,
            "host": runtime.host,
            "port": runtime.port,
            "data_dir": data_root,
            "output_dir": data_root,
            "state_file": app_db,
            "csv_file": app_db,
            "task_history_file": app_db,
            "account_pool_file": app_db,
        }
    )
    configure_conversion_pool(runtime_settings.max_convert_workers)
    store = DomainStore(app_db)
    artifacts = ArtifactService(store, data_root=data_root, settings=runtime_settings)
    exports = ExportService(
        store,
        artifacts,
        data_root=data_root,
        max_workers=runtime_settings.max_export_workers,
    )
    tasks = TaskService(settings=runtime_settings, store=store, artifact_service=artifacts)
    return AppContext(
        settings=runtime_settings,
        runtime=runtime,
        store=store,
        accounts=AccountService(runtime_settings),
        artifacts=artifacts,
        catalogs=CatalogService(runtime_settings, store),
        exports=exports,
        settings_service=SettingsService(runtime_settings, store),
        tasks=tasks,
    )
