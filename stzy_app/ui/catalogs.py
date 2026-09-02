from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.crawler import TagCatalog
from stzy_app.http import StzyHttpClient
from stzy_app.models import TagOption
from stzy_app.storage import Preferences

ALL_VALUE = "__ALL__"
STUDY_PHASES = {"200": "初中", "300": "高中"}
DEFAULT_STUDY_PHASE_CODE = "200"
CATALOG_CACHE_KEY = "catalog_cache"


def empty_subject_options() -> dict[str, dict[str, str]]:
    return {study_phase_code: {} for study_phase_code in STUDY_PHASES}


def empty_catalogs() -> dict[str, TagCatalog]:
    return {study_phase_code: TagCatalog({}) for study_phase_code in STUDY_PHASES}


def catalog_settings(**overrides) -> AppSettings:
    return AppSettings(
        proxy_mode="off",
        proxy_pool="",
        proxy_api_url="",
        **overrides,
    )


def fetch_subject_options() -> dict[str, dict[str, str]]:
    local_settings = catalog_settings()
    client = StzyHttpClient(local_settings)
    response = client.get_json("/zw-zzw/api/v1/zzw/tag/getStudyPhaseSubjectTagData")
    subjects: dict[str, dict[str, str]] = {}
    for phase in response.get("data") or []:
        phase_code = str(phase.get("dictCode") or "")
        subjects[phase_code] = {
            str(item.get("dictCode")): str(item.get("dictName"))
            for item in phase.get("childList") or []
            if item.get("dictCode") and item.get("dictName")
        }
    return subjects


def fetch_tag_catalogs() -> dict[str, TagCatalog]:
    catalogs: dict[str, TagCatalog] = {}
    for study_phase_code in STUDY_PHASES:
        phase_settings = catalog_settings(study_phase_code=study_phase_code)
        catalogs[study_phase_code] = TagCatalog.fetch(StzyHttpClient(phase_settings), phase_settings)
    return catalogs


def load_catalog_cache(
    preferences: Preferences,
) -> tuple[dict[str, dict[str, str]], dict[str, TagCatalog], str]:
    cached = preferences.get(CATALOG_CACHE_KEY)
    subject_options = cached.get("subject_options")
    raw_catalogs = cached.get("catalogs")
    if not isinstance(subject_options, dict) or not isinstance(raw_catalogs, dict):
        return empty_subject_options(), empty_catalogs(), ""
    catalogs: dict[str, TagCatalog] = {}
    for study_phase_code in STUDY_PHASES:
        raw_tags = raw_catalogs.get(study_phase_code)
        catalogs[study_phase_code] = _catalog_from_cache(raw_tags if isinstance(raw_tags, dict) else {})
    normalized_subjects = {
        phase: {
            str(code): str(name)
            for code, name in options.items()
            if code and name
        }
        for phase, options in subject_options.items()
        if isinstance(options, dict)
    }
    return (
        {**empty_subject_options(), **normalized_subjects},
        catalogs,
        str(cached.get("updated_at") or ""),
    )


def save_catalog_cache(
    preferences: Preferences,
    subject_options: dict[str, dict[str, str]],
    catalogs: dict[str, TagCatalog],
) -> None:
    preferences.set(
        CATALOG_CACHE_KEY,
        {
            "subject_options": subject_options,
            "catalogs": {
                study_phase_code: _catalog_to_cache(catalogs.get(study_phase_code))
                for study_phase_code in STUDY_PHASES
            },
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def _catalog_to_cache(catalog: TagCatalog | None) -> dict[str, list[dict[str, str]]]:
    if catalog is None:
        return {}
    return {
        field: [asdict(option) for option in options]
        for field, options in catalog.tags.items()
    }


def _catalog_from_cache(raw_tags: dict[str, Any]) -> TagCatalog:
    tags: dict[str, list[TagOption]] = {}
    for field, items in raw_tags.items():
        if not isinstance(items, list):
            continue
        tags[str(field)] = [
            TagOption(
                field=str(item.get("field") or field),
                code=str(item.get("code") or ""),
                name=str(item.get("name") or ""),
            )
            for item in items
            if isinstance(item, dict) and item.get("code") and item.get("name")
        ]
    return TagCatalog(tags)
