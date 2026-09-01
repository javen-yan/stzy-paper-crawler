from __future__ import annotations

from itertools import product
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.http import StzyHttpClient
from stzy_app.models import CrawlCombo, CrawlFilters, TagOption


class TagCatalog:
    """Fetches and normalizes STZY filter dimensions."""

    def __init__(self, tags: dict[str, list[TagOption]]) -> None:
        self.tags = tags

    @classmethod
    def fetch(cls, client: StzyHttpClient, settings: AppSettings) -> "TagCatalog":
        payload = {
            "studyPhaseCode": settings.study_phase_code,
            "dictType": "",
            "tagCategory": "1",
        }
        response = client.post_json(
            "/zw-resource/api/v1/resource/tag/queryQuestionFixedTag", payload
        )
        return cls.from_api(response.get("data", []))

    @classmethod
    def from_api(cls, data: list[dict[str, Any]]) -> "TagCatalog":
        tags: dict[str, list[TagOption]] = {
            "sceneCode": [],
            "yearCode": [],
            "rank": [],
            "provinceCode": [],
            "gradeCode": [],
            "termCode": [],
        }
        for group in data:
            rel_field = group.get("relField")
            children = group.get("children") or []
            if rel_field == "area":
                tags["provinceCode"] = cls._province_options(children)
            elif rel_field in tags:
                tags[rel_field] = cls._options(rel_field, children)
        return cls(tags)

    @staticmethod
    def _options(field: str, children: list[dict[str, Any]]) -> list[TagOption]:
        options = []
        for item in children:
            code = item.get("tagCode") or item.get("dictCode") or item.get("code")
            name = item.get("dictName") or item.get("tagName") or item.get("name")
            if code not in (None, "", "0") and name:
                options.append(TagOption(field=field, code=str(code), name=str(name)))
        return options

    @staticmethod
    def _province_options(children: list[dict[str, Any]]) -> list[TagOption]:
        options = []
        for item in children:
            code = item.get("tagCode") or item.get("code")
            name = item.get("dictName") or item.get("name")
            if code not in (None, "", "0") and name:
                options.append(TagOption(field="provinceCode", code=str(code), name=str(name)))
        return options

    def selected(self, field: str, codes: list[str]) -> list[TagOption]:
        options = self.tags.get(field, [])
        if not codes:
            return [TagOption(field=field, code="", name="不限")]
        wanted = set(codes)
        return [option for option in options if option.code in wanted]

    def combos(self, filters: CrawlFilters) -> list[CrawlCombo]:
        dimensions = [
            self.selected("sceneCode", filters.scenes),
            self.selected("yearCode", filters.years),
            self.selected("rank", filters.ranks),
            self.selected("provinceCode", filters.provinces),
            self.selected("gradeCode", filters.grades),
            self.selected("termCode", filters.terms),
        ]
        if any(not items for items in dimensions):
            return []
        return [
            CrawlCombo(scene=s, year=y, rank=r, province=p, grade=g, term=t)
            for s, y, r, p, g, t in product(*dimensions)
        ]

    def as_select_options(self, field: str) -> dict[str, str]:
        return {item.code: item.name for item in self.tags.get(field, [])}
