from __future__ import annotations

from dataclasses import asdict
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.crawler.tags import TagCatalog
from stzy_app.domain.store import DomainStore
from stzy_app.http import StzyHttpClient

STUDY_PHASES = {"200": "初中", "300": "高中"}


class CatalogService:
    def __init__(self, settings: AppSettings, store: DomainStore) -> None:
        self.settings = settings
        self.store = store

    def current(self) -> dict[str, Any]:
        cached = self.store.get_setting("catalog_cache", {})
        if cached:
            return cached
        return {"study_phases": STUDY_PHASES, "subjects": {}, "catalogs": {}}

    def refresh(self) -> dict[str, Any]:
        client = StzyHttpClient(self.settings)
        subjects = self._fetch_subjects(client)
        catalogs = {}
        for phase in STUDY_PHASES:
            phase_settings = self.settings.model_copy(update={"study_phase_code": phase})
            catalog = TagCatalog.fetch(client, phase_settings)
            catalogs[phase] = {
                field: [asdict(option) for option in options]
                for field, options in catalog.tags.items()
            }
        payload = {
            "study_phases": STUDY_PHASES,
            "subjects": subjects,
            "catalogs": catalogs,
        }
        self.store.set_setting("catalog_cache", payload)
        return payload

    def _fetch_subjects(self, client: StzyHttpClient) -> dict[str, dict[str, str]]:
        data = client.get_json("/zw-zzw/api/v1/zzw/tag/getStudyPhaseSubjectTagData")
        result = {phase: {} for phase in STUDY_PHASES}
        for item in data.get("data") or []:
            phase_code = str(item.get("dictCode") or "")
            if phase_code not in result:
                continue
            for child in item.get("childList") or []:
                code = str(child.get("dictCode") or "")
                name = str(child.get("dictName") or "")
                if code and name:
                    result[phase_code][code] = name
        return result
