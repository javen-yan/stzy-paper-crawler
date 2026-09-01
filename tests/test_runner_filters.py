from __future__ import annotations

import unittest
from dataclasses import dataclass

from stzy_app.crawler.runner import CrawlRunner
from stzy_app.models import CrawlCombo, ResourceRecord, ResourceStatus, TagOption


@dataclass
class FakeAccount:
    name: str
    user_type: int | None = None
    rank: int | None = None
    fail_count: int = 0


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

    def test_paid_resource_can_be_downloaded_when_later_account_succeeds(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.stats = type("Stats", (), {"paid_skipped": 0})()
        runner.client = FakeClient([FakeAccount("普通账号"), FakeAccount("VIP账号")])
        runner.api = FakeDownloadApi(
            {
                "普通账号": RuntimeError("额度不足"),
                "VIP账号": "https://cdn.stzy.com/stzy/pdf/vip.pdf",
            }
        )
        runner._log = lambda message: None
        record = ResourceRecord(
            resource_id="paid-1",
            resource_name="付费试卷",
            price=5,
        )

        url = CrawlRunner._download_pdf_url_with_accounts(runner, record)

        self.assertEqual(url, "https://cdn.stzy.com/stzy/pdf/vip.pdf")
        self.assertEqual(record.status, ResourceStatus.pending)
        self.assertEqual(runner.stats.paid_skipped, 0)

    def test_paid_resource_is_unavailable_only_after_all_accounts_fail(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.stats = type("Stats", (), {"paid_skipped": 0})()
        runner.client = FakeClient([FakeAccount("普通账号"), FakeAccount("VIP账号")])
        runner.api = FakeDownloadApi(
            {
                "普通账号": RuntimeError("额度不足"),
                "VIP账号": RuntimeError("无权限"),
            },
            {
                "普通账号": {"price": 3, "surplusNum": 0, "userType": 1},
                "VIP账号": {"price": 3, "surplusNum": 0, "userType": 1},
            },
        )
        runner._log = lambda message: None
        record = ResourceRecord(
            resource_id="paid-1",
            resource_name="付费试卷",
            price=5,
        )

        url = CrawlRunner._download_pdf_url_with_accounts(runner, record)

        self.assertEqual(url, "")
        self.assertEqual(record.status, ResourceStatus.paid_unavailable)
        self.assertEqual(runner.stats.paid_skipped, 1)

    def test_paid_resource_with_vip_zero_price_is_not_marked_paid_unavailable(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.stats = type("Stats", (), {"paid_skipped": 0})()
        runner.client = FakeClient([FakeAccount("VIP账号")])
        runner.api = FakeDownloadApi(
            {"VIP账号": RuntimeError("下载接口失败")},
            {"VIP账号": {"price": 0, "surplusNum": 92, "userType": 3, "rank": 3}},
        )
        runner._log = lambda message: None
        record = ResourceRecord(
            resource_id="paid-1",
            resource_name="付费试卷",
            price=3,
        )

        with self.assertRaisesRegex(RuntimeError, "实付 0"):
            CrawlRunner._download_pdf_url_with_accounts(runner, record)

        self.assertEqual(record.status, ResourceStatus.pending)
        self.assertEqual(runner.stats.paid_skipped, 0)

    def test_paid_resource_schedules_zero_price_vip_account_first(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.client = FakeClient([FakeAccount("普通账号"), FakeAccount("VIP账号")])
        runner.api = FakeDownloadApi(
            {},
            {
                "普通账号": {"price": 3, "surplusNum": 5, "userType": 1},
                "VIP账号": {"price": 0, "surplusNum": 92, "userType": 3, "rank": 3},
            },
        )
        runner._log = lambda message: None
        record = ResourceRecord(resource_id="paid-1", resource_name="付费试卷", price=3)

        attempts = CrawlRunner._scheduled_download_attempts(runner, record)

        self.assertEqual([attempt[0] for attempt in attempts], ["VIP账号", "普通账号"])

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


class FakeClient:
    def __init__(self, accounts: list[FakeAccount]) -> None:
        self.accounts = accounts
        self.account_pool = FakeAccountPool()

    def enabled_valid_accounts(self) -> list[FakeAccount]:
        return self.accounts

    def headers_for_account(self, account: FakeAccount) -> dict[str, str]:
        return {"x-test-account": account.name}


class FakeDownloadApi:
    def __init__(
        self,
        results: dict[str, str | Exception],
        download_info: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.results = results
        self.download_info = download_info or {}

    def download_resource_url(self, resource_id: str, *, headers: dict[str, str] | None = None) -> str:
        account = (headers or {}).get("x-test-account", "")
        result = self.results[account]
        if isinstance(result, Exception):
            raise result
        return result

    def check_download_info(
        self,
        resource_id: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        account = (headers or {}).get("x-test-account", "")
        return self.download_info.get(account, {})


class FakeAccountPool:
    def __init__(self) -> None:
        self.failures: list[tuple[str, str]] = []
        self.successes: list[str] = []
        self.profiles: list[tuple[str, dict[str, object]]] = []

    def update_download_profile(self, name: str, info: dict[str, object]) -> None:
        self.profiles.append((name, info))

    def mark_success(self, name: str) -> None:
        self.successes.append(name)

    def mark_failure(self, name: str, error: str) -> None:
        self.failures.append((name, error))


if __name__ == "__main__":
    unittest.main()
