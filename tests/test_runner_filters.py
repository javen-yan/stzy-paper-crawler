from __future__ import annotations

import unittest
import threading
from dataclasses import dataclass

from stzy_app.config import AppSettings
from stzy_app.crawler.account_scheduler import AccountScheduler
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

    def test_selected_province_rejects_missing_province_result(self) -> None:
        combo = self._combo(TagOption("provinceCode", "340000", "安徽"))

        matched = CrawlRunner._matches_selected_province(
            {"resourceName": "高一数学期末卷"},
            combo,
        )

        self.assertFalse(matched)

    def test_selected_national_province_only_accepts_national_result(self) -> None:
        combo = self._combo(TagOption("provinceCode", "000000", "全国"))

        self.assertTrue(
            CrawlRunner._matches_selected_province(
                {"provinceName": "全国", "resourceName": "全国高一数学期末卷"},
                combo,
            )
        )
        self.assertFalse(
            CrawlRunner._matches_selected_province(
                {"provinceName": "安徽", "resourceName": "安徽高一数学期末卷"},
                combo,
            )
        )

    def test_unlimited_province_keeps_api_results(self) -> None:
        combo = self._combo(TagOption("provinceCode", "", "不限"))

        matched = CrawlRunner._matches_selected_province(
            {"provinceName": "全国", "resourceName": "高一数学期末卷"},
            combo,
        )

        self.assertTrue(matched)

    def test_paid_resource_can_be_downloaded_when_later_account_succeeds(self) -> None:
        client = FakeClient([FakeAccount("普通账号"), FakeAccount("VIP账号")])
        api = FakeDownloadApi(
            {
                "普通账号": RuntimeError("额度不足"),
                "VIP账号": "https://cdn.stzy.com/stzy/pdf/vip.pdf",
            }
        )
        record = ResourceRecord(
            resource_id="paid-1",
            resource_name="付费试卷",
            price=5,
        )

        result = AccountScheduler(client, api).download_pdf_url(record)

        self.assertEqual(result.url, "https://cdn.stzy.com/stzy/pdf/vip.pdf")
        self.assertEqual(result.paid_unavailable, 0)

    def test_paid_resource_is_unavailable_only_after_all_accounts_fail(self) -> None:
        client = FakeClient([FakeAccount("普通账号"), FakeAccount("VIP账号")])
        api = FakeDownloadApi(
            {
                "普通账号": RuntimeError("额度不足"),
                "VIP账号": RuntimeError("无权限"),
            },
            {
                "普通账号": {"price": 3, "surplusNum": 0, "userType": 1},
                "VIP账号": {"price": 3, "surplusNum": 0, "userType": 1},
            },
        )
        record = ResourceRecord(
            resource_id="paid-1",
            resource_name="付费试卷",
            price=5,
        )

        result = AccountScheduler(client, api).download_pdf_url(record)

        self.assertEqual(result.url, "")
        self.assertEqual(result.status, ResourceStatus.paid_unavailable)
        self.assertEqual(result.paid_unavailable, 1)

    def test_paid_resource_auth_error_is_compact(self) -> None:
        client = FakeClient([FakeAccount("过期账号")])
        api = FakeDownloadApi(
            {"过期账号": RuntimeError("STZY API error -1: 暂未登录或token已经过期")},
            {"过期账号": {"check_error": "STZY API error -1: 暂未登录或token已经过期"}},
        )
        record = ResourceRecord(resource_id="paid-1", resource_name="付费试卷", price=5)

        result = AccountScheduler(client, api).download_pdf_url(record)

        self.assertEqual(result.url, "")
        self.assertEqual(result.error, "登录态已失效，请重新登录或换一个可用账号")
        self.assertNotIn("STZY API error", result.error)

    def test_paid_resource_with_vip_zero_price_is_not_marked_paid_unavailable(self) -> None:
        client = FakeClient([FakeAccount("VIP账号")])
        api = FakeDownloadApi(
            {"VIP账号": RuntimeError("下载接口失败")},
            {"VIP账号": {"price": 0, "surplusNum": 92, "userType": 3, "rank": 3}},
        )
        record = ResourceRecord(
            resource_id="paid-1",
            resource_name="付费试卷",
            price=3,
        )

        result = AccountScheduler(client, api).download_pdf_url(record)

        self.assertEqual(result.url, "")
        self.assertIn("实付 0", result.error)
        self.assertIsNone(result.status)
        self.assertEqual(result.paid_unavailable, 0)

    def test_paid_resource_schedules_zero_price_vip_account_first(self) -> None:
        client = FakeClient([FakeAccount("普通账号"), FakeAccount("VIP账号")])
        api = FakeDownloadApi(
            {},
            {
                "普通账号": {"price": 3, "surplusNum": 5, "userType": 1},
                "VIP账号": {"price": 0, "surplusNum": 92, "userType": 3, "rank": 3},
            },
        )
        record = ResourceRecord(resource_id="paid-1", resource_name="付费试卷", price=3)

        attempts = AccountScheduler(client, api).scheduled_attempts(record)

        self.assertEqual([attempt.name for attempt in attempts], ["VIP账号", "普通账号"])

    def test_download_workers_are_clamped_for_paper_concurrency(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)

        runner.settings = AppSettings(concurrency=0)
        self.assertEqual(CrawlRunner.download_workers.fget(runner), 1)

        runner.settings = AppSettings(concurrency=20)
        self.assertEqual(CrawlRunner.download_workers.fget(runner), 8)

    def test_paper_concurrency_handles_multiple_records(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(concurrency=3)
        runner._stop = threading.Event()
        handled: list[str] = []
        lock = threading.Lock()

        def handle(record: ResourceRecord) -> None:
            with lock:
                handled.append(record.resource_id)

        runner._handle_resource = handle
        records = [
            ResourceRecord(resource_id="paper-1", resource_name="试卷1"),
            ResourceRecord(resource_id="paper-2", resource_name="试卷2"),
            ResourceRecord(resource_id="paper-3", resource_name="试卷3"),
        ]

        CrawlRunner._handle_resources(runner, records)

        self.assertCountEqual(handled, ["paper-1", "paper-2", "paper-3"])

    def test_resume_skips_completed_resources_and_retries_remaining(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(subject_name="数学")
        runner.filters = type("Filters", (), {"max_pages_per_combo": None})()
        runner.stats = type(
            "Stats",
            (),
            {
                "resources_total": 0,
                "resources_seen": 0,
                "resources_completed": 0,
                "current_resource_name": "",
            },
        )()
        runner._stats_lock = threading.RLock()
        runner._stop = threading.Event()
        runner.completed_resource_ids = {"done-1"}
        runner.api = FakeListApi(
            [
                {"resourceId": "done-1", "resourceName": "已完成", "provinceName": "安徽"},
                {"resourceId": "todo-1", "resourceName": "待继续", "provinceName": "安徽"},
            ]
        )
        runner._log = lambda message: None
        runner._emit_progress = lambda: None
        handled: list[str] = []
        runner._handle_resources = lambda records: handled.extend(
            record.resource_id for record in records
        )

        CrawlRunner._crawl_combo(runner, self._combo(TagOption("provinceCode", "340000", "安徽")))

        self.assertEqual(handled, ["todo-1"])
        self.assertEqual(runner.stats.resources_seen, 1)
        self.assertEqual(runner.stats.resources_completed, 1)

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


class FakeListApi:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self.items = items

    def list_resources(self, combo: object, filters: object, page_num: int) -> dict[str, object]:
        return {"total": len(self.items), "totalPage": 1, "list": self.items}


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
