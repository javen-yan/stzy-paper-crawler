from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from stzy_app.config import AppSettings
from stzy_app.crawler.account_scheduler import AccountScheduler
from stzy_app.crawler.api import StzyCrawlerApi, build_record
from stzy_app.crawler.converters import DocumentConverter
from stzy_app.crawler.download_service import DownloadService
from stzy_app.crawler.paths import ResourcePathBuilder
from stzy_app.crawler.tags import TagCatalog
from stzy_app.http import StzyHttpClient
from stzy_app.models import CrawlCombo, CrawlFilters, ResourceRecord, ResourceStatus
from stzy_app.storage import CrawlState, CsvIndex

LogCallback = Callable[[str], None]
RecordCallback = Callable[[ResourceRecord], None]
ProgressCallback = Callable[["CrawlStats"], None]


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
    ) -> None:
        self.settings = settings
        self.filters = filters
        self.client = StzyHttpClient(settings)
        self.api = StzyCrawlerApi(self.client, settings)
        self.index = CsvIndex(settings.csv_file)
        self.state = CrawlState(settings.state_file)
        self.paths = ResourcePathBuilder(settings)
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
        self._stop = threading.Event()

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
                self._crawl_combo(combo)
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

    def _crawl_combo(self, combo: CrawlCombo) -> None:
        page_num = 1
        names = combo.names()
        self._log(
            "抓取组合："
            f"{names['year']} / {names['scene']} / {names['rank']} / "
            f"{names['province']} / {names['grade']} / {names['term']}"
        )
        while not self._stop.is_set():
            if self.filters.max_pages_per_combo and page_num > self.filters.max_pages_per_combo:
                return
            data = self.api.list_resources(combo, self.filters, page_num)
            if page_num == 1:
                self.stats.resources_total += int(data.get("total") or 0)
                self._emit_progress()
            items = data.get("list") or []
            if not items:
                return
            for item in items:
                if self._stop.is_set():
                    return
                if not self._matches_selected_province(item, combo):
                    actual_province = str(item.get("provinceName") or "未知地区")
                    resource_name = str(item.get("resourceName") or item.get("resourceId") or "")
                    self._log(
                        "跳过地区不匹配资源："
                        f"已选 {names['province']}，返回 {actual_province} - {resource_name}"
                    )
                    continue
                record = build_record(item, combo)
                record.subject = self.settings.subject_name
                self._handle_resource(record)
            total_page = int(data.get("totalPage") or 0)
            if page_num >= total_page:
                return
            page_num += 1
            self._sleep(self.settings.list_delay_seconds)

    def _handle_resource(self, record: ResourceRecord) -> None:
        self.stats.resources_seen += 1
        self.stats.current_resource_name = record.resource_name
        self._emit_progress()
        try:
            result = self.downloader.handle_resource(record)
            record.local_dir = result.local_dir
            record.image_count = result.saved_pages
            record.status = result.status
            record.error = result.error
            self.stats.images_downloaded += result.images_added
            self.stats.paid_skipped += result.paid_unavailable
            if result.status == ResourceStatus.completed:
                self._store_record(record)
            elif result.status == ResourceStatus.paid_unavailable:
                self._store_record(record)
            else:
                self.stats.preview_limited += 1
                self._store_record(record)
        except Exception as exc:  # noqa: BLE001
            record.status = ResourceStatus.failed
            record.error = str(exc)
            self.stats.failed += 1
            self._store_record(record)
            self._log(f"资源失败：{record.resource_id} - {exc}")
        finally:
            self.stats.resources_completed += 1
        self.on_record(record)
        self._emit_progress()

    def _store_record(self, record: ResourceRecord) -> None:
        self.index.append(record)
        self.state.mark_resource(record.resource_id, record.status.value, record.error)

    def _download_preview_images(self, record: ResourceRecord, pictures: list[str]) -> None:
        converter = DocumentConverter(self.settings, self.client, on_log=self._log, sleep=self._sleep)
        images_added = converter.download_preview_images(record, pictures, self._resource_dir(record))
        self.stats.images_downloaded += images_added

    def _download_full_pdf_with_accounts(self, record: ResourceRecord) -> int:
        result = DownloadService(
            self.settings,
            self.client,
            self.api,
            on_log=self._log,
            sleep=self._sleep,
        ).download_full_pdf(record)
        self.stats.images_downloaded += result.images_added
        self.stats.paid_skipped += result.paid_unavailable
        if result.status == ResourceStatus.paid_unavailable:
            record.status = result.status
            record.error = result.error
        return result.saved_pages

    def _download_pdf_url_with_accounts(self, record: ResourceRecord) -> str:
        result = AccountScheduler(self.client, self.api, on_log=self._log).download_pdf_url(record)
        if result.url:
            return result.url
        if result.status == ResourceStatus.paid_unavailable:
            record.status = result.status
            record.error = result.error
            self.stats.paid_skipped += result.paid_unavailable
            return ""
        raise RuntimeError(result.error)

    def _scheduled_download_attempts(
        self,
        record: ResourceRecord,
    ) -> list[tuple[str, dict[str, str], object, dict[str, object]]]:
        attempts = AccountScheduler(self.client, self.api, on_log=self._log).scheduled_attempts(record)
        return [
            (attempt.name, attempt.headers, attempt.account, attempt.diagnosis)
            for attempt in attempts
        ]

    @staticmethod
    def _account_schedule_key(account: object, diagnosis: dict[str, object], index: int) -> tuple:
        return AccountScheduler.account_schedule_key(account, diagnosis, index)

    def _download_diagnosis(
        self,
        resource_id: str,
        headers: dict[str, str],
    ) -> dict[str, object]:
        return AccountScheduler(self.client, self.api, on_log=self._log).download_diagnosis(
            resource_id,
            headers,
        )

    @staticmethod
    def _format_download_diagnosis(info: dict[str, object]) -> str:
        return AccountScheduler.format_download_diagnosis(info)

    def _convert_pdf_to_pngs(self, pdf_path: Path, directory: Path) -> int:
        converter = DocumentConverter(self.settings, self.client, on_log=self._log, sleep=self._sleep)
        existing_count = converter.saved_picture_count_from_dir(directory)
        converted = converter.convert_pdf_to_pngs(pdf_path, directory)
        self.stats.images_downloaded += max(0, converted - existing_count)
        return converted

    def _saved_picture_count(self, record: ResourceRecord) -> int:
        return self._saved_picture_count_from_dir(self._resource_dir(record))

    @staticmethod
    def _saved_picture_count_from_dir(directory: Path) -> int:
        return DocumentConverter.saved_picture_count_from_dir(directory)

    def _convert_svg_to_png(self, svg_path: Path, png_path: Path) -> None:
        DocumentConverter.convert_svg_to_png(svg_path, png_path)

    @staticmethod
    def _svg_needs_browser_renderer(svg_path: Path) -> bool:
        return DocumentConverter.svg_needs_browser_renderer(svg_path)

    def _convert_svg_to_png_with_browser(self, svg_path: Path, png_path: Path) -> None:
        DocumentConverter.convert_svg_to_png_with_browser(svg_path, png_path)

    @staticmethod
    def _svg_size(svg_path: Path) -> tuple[int, int]:
        return DocumentConverter.svg_size(svg_path)

    @staticmethod
    def _svg_dimension(content: str, name: str) -> int | None:
        return DocumentConverter.svg_dimension(content, name)

    @staticmethod
    def _svg_render_html(svg_path: Path, width: int, height: int) -> str:
        return DocumentConverter.svg_render_html(svg_path, width, height)

    def _convert_image_to_png(self, image_path: Path, png_path: Path) -> None:
        DocumentConverter.convert_image_to_png(image_path, png_path)

    def _flatten_png_on_white(self, png_path: Path) -> None:
        DocumentConverter.flatten_png_on_white(png_path)

    def _save_image_on_white(self, image, png_path: Path) -> None:
        DocumentConverter.save_image_on_white(image, png_path)

    def _resource_dir(self, record: ResourceRecord) -> Path:
        return self.paths.resource_dir(record)

    @staticmethod
    def _term_dir_name(term: str) -> str:
        return ResourcePathBuilder.term_dir_name(term)

    @staticmethod
    def _province_dir_name(province: str) -> str:
        return ResourcePathBuilder.province_dir_name(province)

    @staticmethod
    def _matches_selected_province(item: dict[str, object], combo: CrawlCombo) -> bool:
        if not combo.province.code:
            return True
        actual_province = str(item.get("provinceName") or "").strip()
        return not actual_province or actual_province == combo.province.name

    def _sleep(self, base_seconds: float) -> None:
        delay = max(0.0, base_seconds) + random.uniform(0, 0.2)
        self._stop.wait(delay)

    def _log(self, message: str) -> None:
        self.on_log(message)

    def _emit_progress(self) -> None:
        self.on_progress(self.stats)
