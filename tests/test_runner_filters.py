from __future__ import annotations

import unittest
import threading
from dataclasses import dataclass
from unittest.mock import patch

from stzy_app.config import AppSettings
from stzy_app.crawler.account_scheduler import AccountScheduler
from stzy_app.crawler.runner import CrawlRunner, CrawlStats
from stzy_app.http import ProxyPool, RequestStopped, StzyApiError
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
        self.assertIn("无账号支持，请补充 VIP 账号", result.error)

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

        runner.settings = AppSettings(max_download_workers=0)
        self.assertEqual(CrawlRunner.download_workers.fget(runner), 1)

        runner.settings = AppSettings(max_download_workers=64)
        self.assertEqual(CrawlRunner.download_workers.fget(runner), 32)

    def test_proxy_capacity_caps_effective_download_workers(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(
            proxy_mode="fixed",
            proxy_pool="proxy-a.test:7000\nproxy-b.test:7001",
            max_download_workers=8,
        )
        runner.proxy_pool = ProxyPool(runner.settings)

        self.assertEqual(CrawlRunner.download_workers.fget(runner), 2)

    def test_paper_concurrency_handles_multiple_records(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(max_download_workers=3)
        runner._stop = threading.Event()
        logs: list[str] = []
        runner.on_log = logs.append
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
        self.assertIn("本页待下载 3 份，启动 3 个下载线程", logs)

    def test_stopped_resource_is_not_marked_failed(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(max_download_workers=1)
        runner._stop = threading.Event()
        runner.stats = type(
            "Stats",
            (),
            {
                "resources_seen": 0,
                "resources_completed": 0,
                "current_resource_name": "",
                "images_downloaded": 0,
                "paid_skipped": 0,
                "preview_limited": 0,
                "failed": 0,
                "paused": False,
            },
        )()
        runner._stats_lock = threading.RLock()
        runner._emit_progress = lambda: None
        runner._store_record = lambda record: None
        runner._log = lambda message: None
        runner.on_record = lambda record: None

        class StoppedDownloader:
            def handle_resource(self, record: ResourceRecord):
                raise RequestStopped("任务已停止")

        runner.downloader = StoppedDownloader()
        record = ResourceRecord(resource_id="paper-1", resource_name="试卷1")

        CrawlRunner._handle_resource(runner, record)

        self.assertTrue(runner.stats.paused)
        self.assertEqual(runner.stats.failed, 0)
        self.assertEqual(record.status, ResourceStatus.pending)

    def test_resource_is_reported_as_downloading_before_completion(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(max_download_workers=1)
        runner._stop = threading.Event()
        runner.stats = type(
            "Stats",
            (),
            {
                "resources_seen": 0,
                "resources_completed": 0,
                "current_resource_name": "",
                "images_downloaded": 0,
                "paid_skipped": 0,
                "preview_limited": 0,
                "failed": 0,
                "paused": False,
            },
        )()
        runner._stats_lock = threading.RLock()
        runner._emit_progress = lambda: None
        runner._store_record = lambda record: None
        runner._log = lambda message: None
        seen_statuses: list[ResourceStatus] = []
        runner.on_record = lambda record: seen_statuses.append(record.status)

        class DoneDownloader:
            def handle_resource(self, record: ResourceRecord):
                return type(
                    "Result",
                    (),
                    {
                        "local_dir": "/tmp/paper",
                        "saved_pages": 3,
                        "status": ResourceStatus.completed,
                        "error": "",
                        "images_added": 3,
                        "paid_unavailable": 0,
                    },
                )()

        runner.downloader = DoneDownloader()
        record = ResourceRecord(resource_id="paper-1", resource_name="试卷1", error="旧失败")

        CrawlRunner._handle_resource(runner, record)

        self.assertEqual(seen_statuses, [ResourceStatus.downloading, ResourceStatus.completed])
        self.assertEqual(record.error, "")

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
        runner.retry_resource_ids = None
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

    def test_resume_with_retry_set_only_handles_incomplete_resources(self) -> None:
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
        runner.retry_resource_ids = {"failed-1", "partial-1"}
        runner.api = FakeListApi(
            [
                {"resourceId": "done-1", "resourceName": "已完成", "provinceName": "安徽"},
                {"resourceId": "failed-1", "resourceName": "失败", "provinceName": "安徽"},
                {"resourceId": "partial-1", "resourceName": "未完成", "provinceName": "安徽"},
                {"resourceId": "new-1", "resourceName": "新资源", "provinceName": "安徽"},
            ]
        )
        runner._log = lambda message: None
        runner._emit_progress = lambda: None
        handled: list[str] = []
        runner._handle_resources = lambda records: handled.extend(
            record.resource_id for record in records
        )

        CrawlRunner._crawl_combo(runner, self._combo(TagOption("provinceCode", "340000", "安徽")))

        self.assertEqual(handled, ["failed-1", "partial-1"])
        self.assertEqual(runner.stats.resources_seen, 0)
        self.assertEqual(runner.stats.resources_completed, 0)

    def test_run_records_retries_local_records_without_listing(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(max_download_workers=1)
        runner._stop = threading.Event()
        runner._stats_lock = threading.RLock()
        runner.proxy_pool = type("ProxyPool", (), {"proxy_mode": "off"})()
        runner._emit_progress = lambda: None
        logs: list[str] = []
        runner._log = logs.append
        handled: list[str] = []
        runner._handle_resources = lambda records: handled.extend(record.resource_id for record in records)
        runner.api = None
        records = [
            ResourceRecord(resource_id="failed-1", resource_name="失败"),
            ResourceRecord(resource_id="partial-1", resource_name="部分完成"),
        ]

        stats = CrawlRunner.run_records(runner, records)

        self.assertEqual(handled, ["failed-1", "partial-1"])
        self.assertEqual(stats.resources_total, 2)
        self.assertEqual(stats.outcome, "completed")
        self.assertTrue(any("不重新扫描已完成资源" in line for line in logs))

    def test_selected_region_filters_national_results_but_counts_them_processed(self) -> None:
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
                "filtered_skipped": 0,
                "current_resource_name": "",
            },
        )()
        runner._stats_lock = threading.RLock()
        runner._stop = threading.Event()
        runner.completed_resource_ids = set()
        runner.retry_resource_ids = None
        runner.api = FakeListApi(
            [
                {"resourceId": "national-1", "resourceName": "全国卷", "provinceName": "全国"},
                {"resourceId": "anhui-1", "resourceName": "安徽卷", "provinceName": "安徽"},
            ]
        )
        logs: list[str] = []
        runner._log = logs.append
        runner._emit_progress = lambda: None
        handled: list[str] = []
        runner._handle_resources = lambda records: handled.extend(
            record.resource_id for record in records
        )

        CrawlRunner._crawl_combo(runner, self._combo(TagOption("provinceCode", "340000", "安徽")))

        self.assertEqual(handled, ["anhui-1"])
        self.assertEqual(runner.stats.resources_total, 2)
        self.assertEqual(runner.stats.resources_seen, 1)
        self.assertEqual(runner.stats.resources_completed, 1)
        self.assertEqual(runner.stats.filtered_skipped, 1)
        self.assertTrue(any("接口返回非目标地区，已过滤" in line for line in logs))

    def test_combo_list_request_retries_before_handling_resources(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(subject_name="数学", list_max_retries=3, list_delay_seconds=0)
        runner.filters = type("Filters", (), {"max_pages_per_combo": None})()
        runner.stats = type(
            "Stats",
            (),
            {
                "resources_total": 0,
                "resources_seen": 0,
                "resources_completed": 0,
                "failed": 0,
                "current_resource_name": "",
            },
        )()
        runner._stats_lock = threading.RLock()
        runner._stop = threading.Event()
        runner.completed_resource_ids = set()
        runner.retry_resource_ids = None
        runner.api = FlakyListApi(
            RuntimeError("代理抖动"),
            RuntimeError("接口超时"),
            [{"resourceId": "paper-1", "resourceName": "试卷", "provinceName": "安徽"}],
        )
        runner._sleep = lambda seconds: None
        runner._emit_progress = lambda: None
        logs: list[str] = []
        runner._log = logs.append
        handled: list[str] = []
        runner._handle_resources = lambda records: handled.extend(record.resource_id for record in records)

        result = CrawlRunner._crawl_combo(runner, self._combo(TagOption("provinceCode", "340000", "安徽")))

        self.assertTrue(result)
        self.assertEqual(handled, ["paper-1"])
        self.assertEqual(runner.stats.failed, 0)
        self.assertEqual(runner.api.calls, 3)
        self.assertTrue(any("列表请求失败" in line for line in logs))

    def test_combo_list_request_skips_combo_after_retry_limit(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(subject_name="数学", list_max_retries=2, list_delay_seconds=0)
        runner.filters = type("Filters", (), {"max_pages_per_combo": None})()
        runner.stats = type(
            "Stats",
            (),
            {
                "resources_total": 0,
                "resources_seen": 0,
                "resources_completed": 0,
                "failed": 0,
                "current_resource_name": "",
            },
        )()
        runner._stats_lock = threading.RLock()
        runner._stop = threading.Event()
        runner.completed_resource_ids = set()
        runner.retry_resource_ids = None
        runner.api = FlakyListApi(RuntimeError("代理不可用"), RuntimeError("仍然不可用"))
        runner._sleep = lambda seconds: None
        runner._emit_progress = lambda: None
        logs: list[str] = []
        runner._log = logs.append
        runner._handle_resources = lambda records: self.fail("列表失败时不应进入资源下载")

        result = CrawlRunner._crawl_combo(runner, self._combo(TagOption("provinceCode", "340000", "安徽")))

        self.assertIsNone(result)
        self.assertEqual(runner.stats.failed, 1)
        self.assertEqual(runner.api.calls, 2)
        self.assertTrue(any("组合列表连续失败，跳过当前组合" in line for line in logs))

    def test_auth_expired_list_request_is_not_skipped_as_combo_failure(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(subject_name="数学", list_max_retries=3, list_delay_seconds=0)
        runner.filters = type("Filters", (), {"max_pages_per_combo": None})()
        runner.stats = CrawlStats()
        runner._stats_lock = threading.RLock()
        runner._stop = threading.Event()
        runner.api = FlakyListApi(StzyApiError("-1", "暂未登录或token已经过期"))
        runner._emit_progress = lambda: None
        runner._log = lambda message: None

        with self.assertRaises(StzyApiError):
            CrawlRunner._crawl_combo(runner, self._combo(TagOption("provinceCode", "340000", "安徽")))

        self.assertEqual(runner.stats.failed, 0)
        self.assertEqual(runner.api.calls, 1)

    def test_run_aborts_after_consecutive_combo_failure_limit(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.settings = AppSettings(combo_failure_limit=2)
        runner.filters = object()
        runner.stats = CrawlStats()
        runner._stop = threading.Event()
        runner._emit_progress = lambda: None
        logs: list[str] = []
        runner._log = logs.append
        runner.proxy_pool = type("ProxyPool", (), {"proxy_mode": "off"})()
        runner.client = type("Client", (), {"enabled_account_names": lambda self: []})()
        runner.state = FakeState()
        combos = [
            self._combo(TagOption("provinceCode", "340000", "安徽")),
            self._combo(TagOption("provinceCode", "110000", "北京")),
            self._combo(TagOption("provinceCode", "310000", "上海")),
        ]

        def fail_combo(combo: CrawlCombo) -> None:
            runner.stats.failed += 1
            return None

        runner._crawl_combo = fail_combo

        with patch("stzy_app.crawler.runner.TagCatalog.fetch", return_value=FakeCatalog(combos)):
            stats = CrawlRunner.run(runner)

        self.assertTrue(stats.aborted)
        self.assertEqual(stats.outcome, "failed")
        self.assertEqual(stats.failed, 2)
        self.assertIn("连续 2 个筛选组合失败，已停止任务", stats.error)
        self.assertEqual(runner.state.completed, 0)
        self.assertTrue(any("连续 2 个筛选组合失败" in line for line in logs))

    def test_estimate_filters_by_selected_region_across_pages(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.filters = type("Filters", (), {"max_pages_per_combo": None})()
        runner._stop = threading.Event()
        runner.settings = AppSettings(list_delay_seconds=0)
        runner._sleep = lambda seconds: None
        logs: list[str] = []
        runner._log = logs.append
        runner.api = FakeListApi(
            [
                {"resourceId": "national-1", "resourceName": "全国卷", "provinceName": "全国"},
                {"resourceId": "anhui-1", "resourceName": "安徽卷1", "provinceName": "安徽"},
            ],
            [
                {"resourceId": "unknown-1", "resourceName": "未知卷", "provinceName": ""},
                {"resourceId": "anhui-2", "resourceName": "安徽卷2", "provinceName": "安徽"},
            ],
        )

        matched, filtered = CrawlRunner._estimate_combo_resources(
            runner,
            self._combo(TagOption("provinceCode", "340000", "安徽")),
        )

        self.assertEqual(matched, 2)
        self.assertEqual(filtered, 2)
        self.assertTrue(any("预估地区过滤：已选 安徽，过滤 2/4 份" in line for line in logs))

    def test_estimate_without_region_uses_remote_total(self) -> None:
        runner = CrawlRunner.__new__(CrawlRunner)
        runner.filters = type("Filters", (), {"max_pages_per_combo": None})()
        runner._stop = threading.Event()
        runner.settings = AppSettings()
        runner.api = FakeListApi(
            [
                {"resourceId": "national-1", "resourceName": "全国卷", "provinceName": "全国"},
                {"resourceId": "anhui-1", "resourceName": "安徽卷1", "provinceName": "安徽"},
            ],
            [{"resourceId": "other-1", "resourceName": "其他卷", "provinceName": "北京"}],
        )

        matched, filtered = CrawlRunner._estimate_combo_resources(
            runner,
            self._combo(TagOption("provinceCode", "", "不限")),
        )

        self.assertEqual(matched, 3)
        self.assertEqual(filtered, 0)

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
    def __init__(self, *pages: list[dict[str, object]]) -> None:
        self.pages = list(pages)
        self.items = pages[0] if pages else []

    def list_resources(self, combo: object, filters: object, page_num: int) -> dict[str, object]:
        pages = self.pages or [self.items]
        items = pages[page_num - 1] if 0 <= page_num - 1 < len(pages) else []
        return {"total": sum(len(page) for page in pages), "totalPage": len(pages), "list": items}


class FakeCatalog:
    def __init__(self, combos: list[CrawlCombo]) -> None:
        self._combos = combos

    def combos(self, filters: object) -> list[CrawlCombo]:
        return self._combos


class FakeState:
    def __init__(self) -> None:
        self.completed = 0

    def is_combo_completed(self, combo: CrawlCombo, subject_code: str = "") -> bool:
        return False

    def mark_combo_completed(self, combo: CrawlCombo, subject_code: str = "") -> None:
        self.completed += 1


class FlakyListApi:
    def __init__(self, *results: list[dict[str, object]] | Exception) -> None:
        self.results = list(results)
        self.calls = 0

    def list_resources(self, combo: object, filters: object, page_num: int) -> dict[str, object]:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return {"total": len(result), "totalPage": 1, "list": result}


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
