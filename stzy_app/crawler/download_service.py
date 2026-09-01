from __future__ import annotations

from typing import Callable

from stzy_app.config import AppSettings
from stzy_app.crawler.account_scheduler import AccountScheduler, DownloadAttempt
from stzy_app.crawler.api import StzyCrawlerApi
from stzy_app.crawler.converters import DocumentConverter
from stzy_app.crawler.paths import ResourcePathBuilder
from stzy_app.http import StzyHttpClient
from stzy_app.models import DownloadResult, ResourceRecord, ResourceStatus
from stzy_app.utils import ensure_directory

LogCallback = Callable[[str], None]
SleepCallback = Callable[[float], None]


class DownloadService:
    """Applies the resource download policy and returns a single domain result."""

    def __init__(
        self,
        settings: AppSettings,
        client: StzyHttpClient,
        api: StzyCrawlerApi,
        *,
        on_log: LogCallback | None = None,
        sleep: SleepCallback | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.api = api
        self.on_log = on_log or (lambda message: None)
        self.paths = ResourcePathBuilder(settings)
        self.converter = DocumentConverter(settings, client, on_log=self.on_log, sleep=sleep)
        self.account_scheduler = AccountScheduler(client, api, on_log=self.on_log)

    def handle_resource(self, record: ResourceRecord) -> DownloadResult:
        directory = self.paths.resource_dir(record)
        record.local_dir = str(directory)
        ensure_directory(directory)
        expected_pages = record.page_count or 0
        if record.page_count > 10:
            return self.download_full_pdf(record)

        pictures = self.api.resource_pictures(record.resource_id)
        images_added = self.converter.download_preview_images(record, pictures, directory)
        saved_count = self.converter.saved_picture_count_from_dir(directory)
        if record.page_count and saved_count < record.page_count:
            self.on_log(
                f"预览图不完整：{record.resource_id} - "
                f"已保存 {saved_count}/{record.page_count} 页，尝试下载 PDF 补全"
            )
            try:
                pdf_result = self.download_full_pdf(record, source="preview_fallback_pdf")
            except Exception as exc:  # noqa: BLE001
                return DownloadResult(
                    status=ResourceStatus.partial,
                    saved_pages=saved_count,
                    expected_pages=expected_pages,
                    source="preview",
                    local_dir=str(directory),
                    error=(
                        f"预览接口仅返回 {saved_count}/{record.page_count} 页，"
                        f"PDF 补全失败：{exc}"
                    ),
                    images_added=images_added,
                )
            return DownloadResult(
                status=pdf_result.status,
                saved_pages=max(saved_count, pdf_result.saved_pages),
                expected_pages=expected_pages,
                source=pdf_result.source,
                local_dir=str(directory),
                error=pdf_result.error,
                images_added=images_added + pdf_result.images_added,
                paid_unavailable=pdf_result.paid_unavailable,
            )

        return self._result_from_count(
            saved_count=saved_count,
            expected_pages=expected_pages,
            source="preview",
            local_dir=str(directory),
            images_added=images_added,
        )

    def download_full_pdf(self, record: ResourceRecord, *, source: str = "pdf") -> DownloadResult:
        suffix = str(record.raw.get("resourceSuffix") or "").lower()
        if suffix and suffix != ".pdf":
            raise RuntimeError(f"原文格式 {suffix} 暂不支持 PDF 转图片")
        directory = self.paths.resource_dir(record)
        ensure_directory(directory)
        pdf_path = directory / "原文.pdf"
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            url_result = self.account_scheduler.download_pdf_url(record)
            if url_result.status == ResourceStatus.paid_unavailable:
                return DownloadResult(
                    status=ResourceStatus.paid_unavailable,
                    saved_pages=0,
                    expected_pages=record.page_count or 0,
                    source=source,
                    local_dir=str(directory),
                    error=url_result.error,
                    paid_unavailable=url_result.paid_unavailable,
                )
            if not url_result.url:
                raise RuntimeError(url_result.error or "未获取到 PDF 下载地址")
            pdf_url = url_result.url
        else:
            pdf_url = ""
        converted, images_added = self.converter.download_pdf_and_convert(pdf_url, pdf_path, directory)
        self.on_log(f"完成：{record.resource_id} - 已保存 {converted} 页")
        return self._result_from_count(
            saved_count=converted,
            expected_pages=record.page_count or 0,
            source=source,
            local_dir=str(directory),
            images_added=images_added,
        )

    def scheduled_download_attempts(self, record: ResourceRecord) -> list[DownloadAttempt]:
        return self.account_scheduler.scheduled_attempts(record)

    @staticmethod
    def _result_from_count(
        *,
        saved_count: int,
        expected_pages: int,
        source: str,
        local_dir: str,
        images_added: int,
    ) -> DownloadResult:
        if expected_pages and saved_count < expected_pages:
            return DownloadResult(
                status=ResourceStatus.partial,
                saved_pages=saved_count,
                expected_pages=expected_pages,
                source=source,
                local_dir=local_dir,
                error=f"部分完成：已保存 {saved_count}/{expected_pages} 页",
                images_added=images_added,
            )
        return DownloadResult(
            status=ResourceStatus.completed,
            saved_pages=saved_count,
            expected_pages=expected_pages,
            source=source,
            local_dir=local_dir,
            images_added=images_added,
        )
