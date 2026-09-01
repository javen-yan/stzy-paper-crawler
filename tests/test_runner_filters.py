from __future__ import annotations

import unittest

from stzy_app.crawler.runner import CrawlRunner
from stzy_app.models import CrawlCombo, TagOption


class RunnerFilterTest(unittest.TestCase):
    def test_selected_province_rejects_national_result(self) -> None:
        combo = self._combo(TagOption("provinceCode", "340000", "安徽"))

        matched = CrawlRunner._matches_selected_province(
            {"provinceName": "全国", "resourceName": "高一数学期末卷"},
            combo,
        )

        self.assertFalse(matched)

    def test_selected_province_accepts_same_province_result(self) -> None:
        combo = self._combo(TagOption("provinceCode", "340000", "安徽"))

        matched = CrawlRunner._matches_selected_province(
            {"provinceName": "安徽", "resourceName": "安徽高一数学期末卷"},
            combo,
        )

        self.assertTrue(matched)

    def test_unlimited_province_keeps_api_results(self) -> None:
        combo = self._combo(TagOption("provinceCode", "", "不限"))

        matched = CrawlRunner._matches_selected_province(
            {"provinceName": "全国", "resourceName": "高一数学期末卷"},
            combo,
        )

        self.assertTrue(matched)

    @staticmethod
    def _combo(province: TagOption) -> CrawlCombo:
        return CrawlCombo(
            scene=TagOption("sceneCode", "9", "期末"),
            year=TagOption("yearCode", "", "不限"),
            rank=TagOption("rank", "", "不限"),
            province=province,
            grade=TagOption("gradeCode", "10", "高一"),
            term=TagOption("termCode", "30", "高一上"),
        )


if __name__ == "__main__":
    unittest.main()
