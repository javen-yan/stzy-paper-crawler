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
from stzy_app.http import ProxyPool, RequestStopped, StzyApiError, StzyHttpClient
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
    filtered_skipped: int = 0
    preview_limited: int = 0
    failed: int = 0
    running: bool = False
    paused: bool = False
    aborted: bool = False
    error: str = ""


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
        retry_resource_ids: set[str] | None = None,
        download_semaphore: threading.Semaphore | None = None,
    ) -> None:
        self.settings = settings
        self.filters = filters
        self.on_log = on_log or (lambda message: None)
        self.on_record = on_record or (lambda record: None)
        self.on_progress = on_progress or (lambda stats: None)
        self.on_proxy = on_proxy or (lambda _proxy: None)
        self._stop = threading.Event()
        self.proxy_pool = ProxyPool(settings, on_event=self._log)
        self.client = StzyHttpClient(
            settings,
            on_proxy=self.on_proxy,
            proxy_pool=self.proxy_pool,
            should_stop=self._stop.is_set,
        )
        self.api = StzyCrawlerApi(self.client, settings)
        self.index = CsvIndex(settings.csv_file)
        self.state = CrawlState(settings.state_file, scope=getattr(settings, "task_scope", "") or "")
        self.downloader = DownloadService(
            settings,
            self.client,
            self.api,
            on_log=self._log,
            sleep=self._sleep,
        )
        self.stats = CrawlStats()
        self._stats_lock = threading.RLock()
        self._storage_lock = threading.Lock()
        self.completed_resource_ids = completed_resource_ids or set()
        self.retry_resource_ids = retry_resource_ids
        self.download_semaphore = download_semaphore

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
            if self.proxy_pool.proxy_mode != "off":
                self._log(
                    f"代理严格租约：一个 IP 同时只处理一条下载链路；"
                    f"代理可用 {self.proxy_pool.available_capacity()} 个，本轮下载并发上限 {self.download_workers}"
                )
            account_names = self.client.enabled_account_names()
            if account_names:
                self._log(f"账号轮询顺序：{' -> '.join(account_names)}")
            consecutive_combo_failures = 0
            combo_failure_limit = max(0, int(getattr(self.settings, "combo_failure_limit", 10) or 0))
            for combo in combos:
                if self._stop.is_set():
                    self.stats.paused = True
                    self._log("任务已暂停")
                    break
                if self.state.is_combo_completed(combo, self.settings.subject_code):
                    self._log("组合曾经跑过，本次继续检查新增或缺失资源")
                combo_completed = self._crawl_combo(combo)
                if combo_completed is False:
                    self.stats.paused = True
                    self._log("任务已暂停")
                    break
                if combo_completed is True:
                    consecutive_combo_failures = 0
                    self.state.mark_combo_completed(combo, self.settings.subject_code)
                    self.stats.completed_combos += 1
                    self._emit_progress()
                elif combo_completed is None:
                    consecutive_combo_failures += 1
                    if combo_failure_limit and consecutive_combo_failures >= combo_failure_limit:
                        self.stats.aborted = True
                        self.stats.error = f"连续 {consecutive_combo_failures} 个筛选组合失败，已停止任务"
                        self._log(self.stats.error)
                        break
        finally:
            self.stats.running = False
            self.stats.phase = "finished"
            if self.stats.paused:
                self.stats.outcome = "paused"
            elif self.stats.aborted:
                self.stats.outcome = "failed"
            elif self.stats.failed or self.stats.paid_skipped:
                self.stats.outcome = "partial"
            elif self.stats.preview_limited:
                self.stats.outcome = "partial"
            else:
                self.stats.outcome = "completed"
            self._emit_progress()
        return self.stats

    def run_records(self, records: list[ResourceRecord]) -> CrawlStats:
        self.stats = CrawlStats(
            task_mode="crawl",
            phase="running",
            resources_total=len(records),
            running=True,
        )
        self._emit_progress()
        try:
            self._log(f"继续下载：仅处理未完成资源 {len(records)} 份，不重新扫描已完成资源")
            if self.download_workers > 1:
                self._log(f"试卷并发数：{self.download_workers}，单个试卷内部按页串行处理")
            self._handle_resources(records)
            if self._stop.is_set():
                self.stats.paused = True
                self._log("任务已暂停")
        finally:
            self.stats.running = False
            self.stats.phase = "finished"
            if self.stats.paused:
                self.stats.outcome = "paused"
            elif self.stats.failed or self.stats.paid_skipped or self.stats.preview_limited:
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
                total, filtered = self._estimate_combo_resources(combo)
                stats.resources_seen += total
                stats.resources_total += total
                stats.filtered_skipped += filtered
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

    def _estimate_combo_resources(self, combo: CrawlCombo) -> tuple[int, int]:
        page_num = 1
        matched = 0
        filtered = 0
        total_reported = 0
        while not self._stop.is_set():
            if self.filters.max_pages_per_combo and page_num > self.filters.max_pages_per_combo:
                break
            data = self._list_resources_with_retry(combo, page_num)
            if page_num == 1:
                total_reported = int(data.get("total") or 0)
                if not combo.province.code:
                    return total_reported, 0
            items = data.get("list") or []
            if not items:
                break
            for item in items:
                if self._matches_selected_province(item, combo):
                    matched += 1
                else:
                    filtered += 1
            total_page = int(data.get("totalPage") or 0)
            if page_num >= total_page:
                break
            page_num += 1
            self._sleep(self.settings.list_delay_seconds)
        if filtered:
            names = combo.names()
            self._log(f"预估地区过滤：已选 {names['province']}，过滤 {filtered}/{total_reported} 份")
        return matched, filtered

    def _crawl_combo(self, combo: CrawlCombo) -> bool | None:
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
            try:
                data = self._list_resources_with_retry(combo, page_num)
            except RequestStopped:
                return False
            except StzyApiError:
                raise
            except Exception as exc:  # noqa: BLE001
                with self._stats_lock:
                    self.stats.failed += 1
                    self._emit_progress()
                self._log(f"组合列表连续失败，跳过当前组合：{names['province']} / 第 {page_num} 页 - {exc}")
                return None
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
                    self._skip_filtered_resource(resource_name)
                    continue
                record = build_record(item, combo)
                record.subject = self.settings.subject_name
                if self.retry_resource_ids is not None:
                    if record.resource_id not in self.retry_resource_ids:
                        continue
                    records.append(record)
                    continue
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

    def _list_resources_with_retry(self, combo: CrawlCombo, page_num: int) -> dict[str, object]:
        attempts = max(1, int(getattr(self.settings, "list_max_retries", getattr(self.settings, "max_retries", 3)) or 3))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            if self._stop.is_set():
                raise RequestStopped("任务已停止")
            try:
                return self.api.list_resources(combo, self.filters, page_num)
            except RequestStopped:
                raise
            except StzyApiError as exc:
                if exc.requires_login:
                    raise
                last_error = exc
                names = combo.names()
                self._log(
                    "列表请求失败："
                    f"{names['province']} / 第 {page_num} 页（{attempt}/{attempts}）- {exc.message}"
                )
                if attempt < attempts:
                    self._sleep(self.settings.list_delay_seconds)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                names = combo.names()
                self._log(
                    "列表请求失败："
                    f"{names['province']} / 第 {page_num} 页（{attempt}/{attempts}）- {exc}"
                )
                if attempt < attempts:
                    self._sleep(self.settings.list_delay_seconds)
        raise last_error or RuntimeError("列表请求失败")

    @property
    def download_workers(self) -> int:
        configured = max(1, min(32, int(getattr(self.settings, "max_download_workers", 1) or 1)))
        proxy_pool = getattr(self, "proxy_pool", None)
        if not proxy_pool or proxy_pool.proxy_mode == "off":
            return configured
        capacity = proxy_pool.available_capacity()
        return max(1, min(configured, capacity or proxy_pool.target_size() or 1))

    def _handle_resources(self, records: list[ResourceRecord]) -> None:
        if not records:
            return
        if self.download_workers == 1 or len(records) <= 1:
            self._log(f"本页待下载 {len(records)} 份，按顺序处理")
            for record in records:
                if self._stop.is_set():
                    return
                self._handle_resource(record)
            return
        workers = min(self.download_workers, len(records))
        self._log(f"本页待下载 {len(records)} 份，启动 {workers} 个下载线程")
        executor = ThreadPoolExecutor(max_workers=workers)
        futures = [executor.submit(self._handle_resource, record) for record in records]
        try:
            for future in as_completed(futures):
                future.result()
                if self._stop.is_set():
                    for pending in futures:
                        pending.cancel()
                    return
        finally:
            executor.shutdown(wait=True, cancel_futures=self._stop.is_set())

    def _skip_completed_resource(self, record: ResourceRecord) -> None:
        with self._stats_lock:
            self.stats.resources_seen += 1
            self.stats.resources_completed += 1
            self.stats.current_resource_name = record.resource_name
            self._emit_progress()
        self._log(f"续跑跳过已完成资源：{record.resource_id} - {record.resource_name}")

    def _skip_filtered_resource(self, resource_name: str) -> None:
        with self._stats_lock:
            self.stats.resources_seen += 1
            self.stats.resources_completed += 1
            self.stats.filtered_skipped = getattr(self.stats, "filtered_skipped", 0) + 1
            self.stats.current_resource_name = resource_name
            self._emit_progress()

    def _handle_resource(self, record: ResourceRecord) -> None:
        if self._stop.is_set():
            return
        with self._stats_lock:
            self.stats.resources_seen += 1
            self.stats.current_resource_name = record.resource_name
            self._emit_progress()
        record.status = ResourceStatus.downloading
        self.on_record(record)
        self._log(f"开始下载：{record.resource_id} - {record.resource_name}")
        proxy_pool = getattr(self, "proxy_pool", None)
        try:
            downloader = self.downloader if self.download_workers == 1 else self._build_downloader()
            if proxy_pool:
                proxy_pool.set_lease_context(
                    task_id=str(getattr(self.settings, "task_scope", "") or ""),
                    resource_name=record.resource_name,
                )
            download_semaphore = getattr(self, "download_semaphore", None)
            if download_semaphore:
                with download_semaphore:
                    if self._stop.is_set():
                        raise RequestStopped("任务已停止")
                    result = downloader.handle_resource(record)
            else:
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
        except RequestStopped:
            record.status = ResourceStatus.pending
            with self._stats_lock:
                self.stats.paused = True
        except Exception as exc:  # noqa: BLE001
            record.status = ResourceStatus.failed
            record.error = str(exc)
            with self._stats_lock:
                self.stats.failed += 1
            self._store_record(record)
            self._log(f"资源失败：{record.resource_id} - {exc}")
        finally:
            if proxy_pool:
                proxy_pool.set_lease_context()
            with self._stats_lock:
                self.stats.resources_completed += 1
        self.on_record(record)
        if record.status == ResourceStatus.completed:
            self._log(f"下载完成：{record.resource_id} - {record.resource_name}")
        self._emit_progress()

    def _build_downloader(self) -> DownloadService:
        client = StzyHttpClient(
            self.settings,
            on_proxy=self.on_proxy,
            proxy_pool=self.proxy_pool,
            should_stop=self._stop.is_set,
        )
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
        on_log = getattr(self, "on_log", None)
        if on_log:
            on_log(message)

    def _emit_progress(self) -> None:
        with self._stats_lock:
            self.on_progress(self.stats)
