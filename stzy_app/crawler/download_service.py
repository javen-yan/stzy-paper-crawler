from __future__ import annotations

from typing import Callable

from stzy_app.config import AppSettings
from stzy_app.crawler.account_scheduler import AccountScheduler
from stzy_app.crawler.api import StzyCrawlerApi
from stzy_app.crawler.artifacts import ResourceArtifacts
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
            self.on_log(f"资源进度：{record.resource_id} - 页数 {record.page_count}，下载 PDF")
            return self.download_full_pdf(record)

        self.on_log(f"资源进度：{record.resource_id} - 获取预览图")
        pictures = self.api.resource_pictures(record.resource_id)
        if pictures:
            self.on_log(f"资源进度：{record.resource_id} - 预览图 {len(pictures)} 张")
        else:
            self.on_log(f"资源进度：{record.resource_id} - 未返回预览图，下载 PDF")
        images_added = self.converter.download_preview_images(record, pictures, directory)
        saved_count = self.converter.saved_picture_count_from_dir(directory)
        if record.page_count and saved_count < record.page_count:
            self.on_log(
                f"预览图不完整：{record.resource_id} - "
                f"已保存 {saved_count}/{record.page_count} 页，尝试下载 PDF 补全"
            )
            try:
                pdf_result = self.download_full_pdf(record, source="preview_fallback_pdf", force=True)
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

    def download_full_pdf(self, record: ResourceRecord, *, source: str = "pdf", force: bool = False) -> DownloadResult:
        suffix = str(record.raw.get("resourceSuffix") or "").lower()
        if suffix and suffix != ".pdf":
            raise RuntimeError(f"原文格式 {suffix} 暂不支持 PDF 转图片")
        directory = self.paths.resource_dir(record)
        artifacts = ResourceArtifacts(directory)
        artifacts.prepare_resource_dir()
        if force:
            # 预览拼版 PDF 不完整，强制重新获取真实原文 PDF（覆盖掉预览版 PDF）
            if artifacts.temp_pdf.exists():
                artifacts.temp_pdf.unlink()
            if artifacts.final_pdf.exists():
                artifacts.final_pdf.unlink()
        pdf_path = artifacts.temp_pdf if artifacts.temp_pdf.exists() else artifacts.final_pdf
        if pdf_path.exists() and not self.converter.pdf_file_looks_valid(pdf_path):
            pdf_path.unlink()
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            self.on_log(f"资源进度：{record.resource_id} - 获取 PDF 地址")
            url_result = self.account_scheduler.download_pdf_url(record)
            if url_result.status == ResourceStatus.paid_unavailable:
                error = url_result.error or "无账号支持，请补充 VIP 账号后恢复任务"
                if "无账号支持，请补充 VIP 账号" not in error:
                    error = f"无账号支持，请补充 VIP 账号后恢复任务（{error}）"
                return DownloadResult(
                    status=ResourceStatus.paid_unavailable,
                    saved_pages=0,
                    expected_pages=record.page_count or 0,
                    source=source,
                    local_dir=str(directory),
                    error=error,
                    paid_unavailable=url_result.paid_unavailable,
                )
            if not url_result.url:
                raise RuntimeError(url_result.error or "未获取到 PDF 下载地址")
            pdf_url = url_result.url
            pdf_path = artifacts.temp_pdf
        else:
            pdf_url = ""
        self.on_log(f"资源进度：{record.resource_id} - PDF 转图片")
        converted, images_added = self.converter.download_pdf_and_convert(pdf_url, pdf_path, directory)
        self.on_log(f"完成：{record.resource_id} - 已保存 {converted} 页")
        return self._result_from_count(
            saved_count=converted,
            expected_pages=record.page_count or 0,
            source=source,
            local_dir=str(directory),
            images_added=images_added,
        )

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
