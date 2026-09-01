from __future__ import annotations

from pathlib import Path

from stzy_app.config import AppSettings
from stzy_app.models import ResourceRecord
from stzy_app.utils import safe_filename


class ResourcePathBuilder:
    """Builds the stable on-disk layout for a downloaded resource."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def resource_dir(self, record: ResourceRecord) -> Path:
        return (
            self.settings.output_dir
            / safe_filename(record.subject, fallback=self.settings.subject_code)
            / safe_filename(record.grade)
            / safe_filename(self.term_dir_name(record.term))
            / safe_filename(self.province_dir_name(record.province))
            / safe_filename(record.scene)
            / safe_filename(record.resource_name, fallback=record.resource_id)
        )

    @staticmethod
    def term_dir_name(term: str) -> str:
        if term.endswith("上"):
            return "上学期"
        if term.endswith("下"):
            return "下学期"
        return term

    @staticmethod
    def province_dir_name(province: str) -> str:
        municipalities = {"北京", "天津", "上海", "重庆"}
        if province in municipalities:
            return f"{province}市"
        return province
