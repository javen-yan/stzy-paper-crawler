from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResourceStatus(str, Enum):
    pending = "pending"
    downloading = "downloading"
    completed = "completed"
    partial = "partial"
    skipped_paid = "skipped_paid"
    paid_unavailable = "paid_unavailable"
    failed = "failed"


@dataclass(frozen=True)
class TagOption:
    field: str
    code: str
    name: str


@dataclass(frozen=True)
class CrawlCombo:
    scene: TagOption
    year: TagOption
    rank: TagOption
    province: TagOption
    grade: TagOption
    term: TagOption

    def params(self) -> dict[str, str]:
        pairs = {
            "sceneCode": self.scene.code,
            "yearCode": self.year.code,
            "rank": self.rank.code,
            "provinceCode": self.province.code,
            "gradeCode": self.grade.code,
            "termCode": self.term.code,
        }
        return {key: value for key, value in pairs.items() if value}

    def names(self) -> dict[str, str]:
        return {
            "scene": self.scene.name,
            "year": self.year.name,
            "rank": self.rank.name,
            "province": self.province.name,
            "grade": self.grade.name,
            "term": self.term.name,
        }


@dataclass
class CrawlFilters:
    scenes: list[str] = field(default_factory=list)
    years: list[str] = field(default_factory=list)
    ranks: list[str] = field(default_factory=list)
    provinces: list[str] = field(default_factory=list)
    grades: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    file_type: str = "PDF"
    max_pages_per_combo: int | None = None
    download_paid: bool = False


@dataclass
class ResourceRecord:
    resource_id: str
    resource_name: str
    subject: str = ""
    year: str = ""
    scene: str = ""
    rank: str = ""
    province: str = ""
    grade: str = ""
    term: str = ""
    price: float = 0.0
    page_count: int = 0
    image_count: int = 0
    status: ResourceStatus = ResourceStatus.pending
    error: str = ""
    local_dir: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadResult:
    status: ResourceStatus
    saved_pages: int = 0
    expected_pages: int = 0
    source: str = ""
    local_dir: str = ""
    error: str = ""
    images_added: int = 0
    paid_unavailable: int = 0
