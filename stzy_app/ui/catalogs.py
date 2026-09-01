from __future__ import annotations

from stzy_app.config import AppSettings
from stzy_app.crawler import TagCatalog
from stzy_app.http import StzyHttpClient

ALL_VALUE = "__ALL__"
STUDY_PHASES = {"200": "初中", "300": "高中"}
DEFAULT_STUDY_PHASE_CODE = "200"


def fetch_subject_options() -> dict[str, dict[str, str]]:
    local_settings = AppSettings()
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
        phase_settings = AppSettings(study_phase_code=study_phase_code)
        catalogs[study_phase_code] = TagCatalog.fetch(StzyHttpClient(phase_settings), phase_settings)
    return catalogs
