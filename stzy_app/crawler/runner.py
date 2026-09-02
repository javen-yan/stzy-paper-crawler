from __future__ import annotations

import random
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from dataclasses import dataclass
from typing import Callable

from stzy_app.config import AppSettings
from stzy_app.crawler.api import StzyCrawlerApi, build_record
from stzy_app.crawler.download_service import DownloadService
from stzy_app.crawler.tags import TagCatalog
from stzy_app.http import StzyHttpClient
from stzy_app.models import CrawlCombo, CrawlFilters, ResourceRecord, ResourceStatus
from stzy_app.storage import CrawlState, CsvIndex

LogCallback = Callable[[str], None]
RecordCallback = Callable[[ResourceRecord], None]
ProgressCallback = Callable[["CrawlStats"], None]
ProxyCallback = Callable[[str], None]


@dataclass
class CrawlStats:
    task_mode: str = "idle"
    phase: str = "preview"
    outcome: str = ""
    total_combos: int = 0
    completed_combos: int = 0
    resources_seen: int = 0
    resources_total: int = 0
    resources_completed: int = 0
    current_resource_name: str = ""
    images_downloaded: int = 0
    paid_skipped: int = 0
    preview_limited: int = 0
    failed: int = 0
    running: bool = False
    paused: bool = False


class CrawlRunner:
    """Coordinates combinations, pagination, downloads and resumable state."""

    def __init__(
        self,
        settings: AppSettings,
        filters: CrawlFilters,
        *,
        on_log: LogCallback | None = None,
        on_record: RecordCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_proxy: ProxyCallback | None = None,
        completed_resource_ids: set[str] | None = None,
    ) -> None:
        self.settings = settings
        self.filters = filters
        self.on_proxy = on_proxy or (lambda _proxy: None)
        self.client = StzyHttpClient(settings, on_proxy=self.on_proxy)
        self.api = StzyCrawlerApi(self.client, settings)
        self.index = CsvIndex(settings.csv_file)
        self.state = CrawlState(settings.state_file)
        self.downloader = DownloadService(
            settings,
            self.client,
            self.api,
            on_log=self._log,
            sleep=self._sleep,
        )
        self.on_log = on_log or (lambda message: None)
        self.on_record = on_record or (lambda record: None)
        self.on_progress = on_progress or (lambda stats: None)
        self.stats = CrawlStats()
        self._stats_lock = threading.RLock()
        self._storage_lock = threading.Lock()
        self._stop = threading.Event()
        self.completed_resource_ids = completed_resource_ids or set()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> CrawlStats:
        self.stats.task_mode = "crawl"
        self.stats.phase = "running"
        self.stats.outcome = ""
        self.stats.running = True
        self._emit_progress()
        try:
            catalog = TagCatalog.fetch(self.client, self.settings)
            combos = catalog.combos(self.filters)
            self.stats.total_combos = len(combos)
            self._log(f"已生成 {len(combos)} 个筛选组合")
            if self.download_workers > 1:
                self._log(f"试卷并发数：{self.download_workers}，单个试卷内部按页串行处理")
            account_names = self.client.enabled_account_names()
            if account_names:
                self._log(f"账号轮询顺序：{' -> '.join(account_names)}")
            for combo in combos:
                if self._stop.is_set():
                    self.stats.paused = True
                    self._log("任务已暂停")
                    break
                if self.state.is_combo_completed(combo, self.settings.subject_code):
                    self._log("组合曾经跑过，本次继续检查新增或缺失资源")
                combo_completed = self._crawl_combo(combo)
                if not combo_completed:
                    self.stats.paused = True
                    self._log("任务已暂停")
                    break
                self.state.mark_combo_completed(combo, self.settings.subject_code)
                self.stats.completed_combos += 1
                self._emit_progress()
        finally:
            self.stats.running = False
            self.stats.phase = "finished"
            if self.stats.paused:
                self.stats.outcome = "paused"
            elif self.stats.failed or self.stats.paid_skipped:
                self.stats.outcome = "partial"
            elif self.stats.preview_limited:
                self.stats.outcome = "partial"
            else:
                self.stats.outcome = "completed"
            self._emit_progress()
        return self.stats

    def estimate(self) -> CrawlStats:
        catalog = TagCatalog.fetch(self.client, self.settings)
        combos = catalog.combos(self.filters)
        stats = CrawlStats(
            task_mode="estimate",
            phase="running",
            total_combos=len(combos),
            running=True,
        )
        self._log(f"开始预估 {len(combos)} 个组合")
        for combo in combos:
            if self._stop.is_set():
                stats.paused = True
                break
            try:
                data = self.api.list_resources(combo, self.filters, 1)
                stats.resources_seen += int(data.get("total") or 0)
            except Exception as exc:  # noqa: BLE001
                stats.failed += 1
                self._log(f"预估失败：{combo.names()} - {exc}")
            stats.completed_combos += 1
            self.on_progress(stats)
            self._sleep(self.settings.list_delay_seconds)
        stats.running = False
        stats.phase = "finished" if stats.paused else "preview"
        stats.outcome = "paused" if stats.paused else "estimated"
        self.on_progress(stats)
        return stats

    def _crawl_combo(self, combo: CrawlCombo) -> bool:
        page_num = 1
        names = combo.names()
        self._log(
            "抓取组合："
            f"{names['year']} / {names['scene']} / {names['rank']} / "
            f"{names['province']} / {names['grade']} / {names['term']}"
        )
        while not self._stop.is_set():
            if self.filters.max_pages_per_combo and page_num > self.filters.max_pages_per_combo:
                return True
            data = self.api.list_resources(combo, self.filters, page_num)
            if page_num == 1:
                self.stats.resources_total += int(data.get("total") or 0)
                self._emit_progress()
            items = data.get("list") or []
            if not items:
                return True
            records = []
            for item in items:
                if self._stop.is_set():
                    return False
                if not self._matches_selected_province(item, combo):
                    actual_province = str(item.get("provinceName") or "未知地区")
                    resource_name = str(item.get("resourceName") or item.get("resourceId") or "")
                    self._log(
                        "接口返回非目标地区，已过滤："
                        f"已选 {names['province']}，返回 {actual_province} - {resource_name}"
                    )
                    continue
                record = build_record(item, combo)
                record.subject = self.settings.subject_name
                if record.resource_id in self.completed_resource_ids:
                    self._skip_completed_resource(record)
                    continue
                records.append(record)
            self._handle_resources(records)
            if self._stop.is_set():
                return False
            total_page = int(data.get("totalPage") or 0)
            if page_num >= total_page:
                return True
            page_num += 1
            self._sleep(self.settings.list_delay_seconds)
        return False

    @property
    def download_workers(self) -> int:
        return max(1, min(8, int(self.settings.concurrency or 1)))

    def _handle_resources(self, records: list[ResourceRecord]) -> None:
        if self.download_workers == 1 or len(records) <= 1:
            for record in records:
                if self._stop.is_set():
                    return
                self._handle_resource(record)
            return
        with ThreadPoolExecutor(max_workers=self.download_workers) as executor:
            futures = [executor.submit(self._handle_resource, record) for record in records]
            for future in as_completed(futures):
                if self._stop.is_set():
                    return
                future.result()

    def _skip_completed_resource(self, record: ResourceRecord) -> None:
        with self._stats_lock:
            self.stats.resources_seen += 1
            self.stats.resources_completed += 1
            self.stats.current_resource_name = record.resource_name
            self._emit_progress()
        self._log(f"续跑跳过已完成资源：{record.resource_id} - {record.resource_name}")

    def _handle_resource(self, record: ResourceRecord) -> None:
        with self._stats_lock:
            self.stats.resources_seen += 1
            self.stats.current_resource_name = record.resource_name
            self._emit_progress()
        try:
            downloader = self.downloader if self.download_workers == 1 else self._build_downloader()
            result = downloader.handle_resource(record)
            record.local_dir = result.local_dir
            record.image_count = result.saved_pages
            record.status = result.status
            record.error = result.error
            with self._stats_lock:
                self.stats.images_downloaded += result.images_added
                self.stats.paid_skipped += result.paid_unavailable
            if result.status == ResourceStatus.completed:
                self._store_record(record)
            elif result.status == ResourceStatus.paid_unavailable:
                self._store_record(record)
            else:
                with self._stats_lock:
                    self.stats.preview_limited += 1
                self._store_record(record)
        except Exception as exc:  # noqa: BLE001
            record.status = ResourceStatus.failed
            record.error = str(exc)
            with self._stats_lock:
                self.stats.failed += 1
            self._store_record(record)
            self._log(f"资源失败：{record.resource_id} - {exc}")
        finally:
            with self._stats_lock:
                self.stats.resources_completed += 1
        self.on_record(record)
        self._emit_progress()

    def _build_downloader(self) -> DownloadService:
        client = StzyHttpClient(self.settings, on_proxy=self.on_proxy)
        api = StzyCrawlerApi(client, self.settings)
        return DownloadService(
            self.settings,
            client,
            api,
            on_log=self._log,
            sleep=self._sleep,
        )

    def _store_record(self, record: ResourceRecord) -> None:
        with self._storage_lock:
            self.index.append(record)
            self.state.mark_resource(record.resource_id, record.status.value, record.error)

    @staticmethod
    def _matches_selected_province(item: dict[str, object], combo: CrawlCombo) -> bool:
        if not combo.province.code:
            return True
        actual_province = str(item.get("provinceName") or "").strip()
        return actual_province == combo.province.name

    def _sleep(self, base_seconds: float) -> None:
        delay = max(0.0, base_seconds) + random.uniform(0, 0.2)
        self._stop.wait(delay)

    def _log(self, message: str) -> None:
        self.on_log(message)

    def _emit_progress(self) -> None:
        with self._stats_lock:
            self.on_progress(self.stats)
