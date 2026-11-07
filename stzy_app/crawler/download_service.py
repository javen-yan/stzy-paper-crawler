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
        suffix = str(record.raw.get("resourceSuffix") or "").strip().lower().lstrip(".")
        if suffix in {"doc", "docx", "zip", "rar", "7z"}:
            return self.download_other_source(record, "." + suffix)
        if record.page_count > 10:
            saved_count = self.converter.saved_picture_count_from_dir(directory)
            if expected_pages and saved_count >= expected_pages:
                self.on_log(f"资源进度：{record.resource_id} - 已有完整文件 {saved_count}/{expected_pages}，标记完成")
                return DownloadResult(
                    status=ResourceStatus.completed,
                    saved_pages=saved_count,
                    expected_pages=expected_pages,
                    source="existing",
                    local_dir=str(directory),
                )
            self.on_log(f"资源进度：{record.resource_id} - 页数 {record.page_count}，下载原文")
            return self.download_full_pdf(record)

        self.on_log(f"资源进度：{record.resource_id} - 获取预览图")
        pictures = self.api.resource_pictures(record.resource_id)
        if pictures:
            self.on_log(f"资源进度：{record.resource_id} - 预览图 {len(pictures)} 张")
        else:
            self.on_log(f"资源进度：{record.resource_id} - 未返回预览图，下载原文")
        images_added = self.converter.download_preview_images(record, pictures, directory)
        saved_count = self.converter.saved_picture_count_from_dir(directory)
        if not pictures or (record.page_count and saved_count < record.page_count):
            self.on_log(
                f"预览图不完整：{record.resource_id} - "
                f"已保存 {saved_count}/{record.page_count} 页，尝试下载原文补全"
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
                        f"原文补全失败：{exc}"
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
        suffix = str(record.raw.get("resourceSuffix") or "").strip().lower()
        suffix = "." + suffix.lstrip(".") if suffix else ""
        if suffix and suffix != ".pdf":
            return self.download_other_source(record, suffix)
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
        try:
            converted, images_added = self.converter.download_pdf_and_convert(pdf_url, pdf_path, directory)
        except Exception as exc:  # noqa: BLE001
            saved_count = self.converter.saved_picture_count_from_dir(directory)
            expected_pages = record.page_count or 0
            if expected_pages and saved_count >= expected_pages:
                self.on_log(
                    f"PDF 转图片异常但文件已完整：{record.resource_id} - "
                    f"已保存 {saved_count}/{expected_pages} 页，标记完成"
                )
                return DownloadResult(
                    status=ResourceStatus.completed,
                    saved_pages=saved_count,
                    expected_pages=expected_pages,
                    source=source,
                    local_dir=str(directory),
                )
            raise RuntimeError(str(exc) or exc.__class__.__name__) from exc
        self.on_log(f"完成：{record.resource_id} - 已保存 {converted} 页")
        return self._result_from_count(
            saved_count=converted,
            expected_pages=record.page_count or 0,
            source=source,
            local_dir=str(directory),
            images_added=images_added,
        )

    def download_other_source(self, record: ResourceRecord, suffix: str) -> DownloadResult:
        from stzy_app.crawler.source_documents import SUPPORTED, source_kind

        if suffix not in SUPPORTED:
            raise RuntimeError(f"暂不支持原文格式 {suffix}（支持 Word、ZIP、RAR、7z、PDF 和图片）")
        directory = self.paths.resource_dir(record)
        ensure_directory(directory)
        original = directory / f"源文件{suffix}"
        if original.exists():
            try:
                source_kind(original)
            except (RuntimeError, OSError):
                original.unlink()
        if not original.exists():
            self.on_log(f"资源进度：{record.resource_id} - 获取 {suffix} 原文地址")
            result = self.account_scheduler.download_pdf_url(record)
            if result.status == ResourceStatus.paid_unavailable:
                return DownloadResult(
                    status=ResourceStatus.paid_unavailable, saved_pages=0,
                    expected_pages=record.page_count or 0, source="original",
                    local_dir=str(directory), paid_unavailable=result.paid_unavailable,
                    error=f"无账号支持，请补充 VIP 账号后恢复任务（{result.error or '原文不可下载'}）",
                )
            if not result.url:
                raise RuntimeError(result.error or "未获取到原文下载地址")
            temporary = original.with_suffix(original.suffix + ".download")
            try:
                self.client.download(result.url, temporary, headers={})
                # Image detection also uses the suffix, so validate after the atomic rename.
                temporary.replace(original)
                source_kind(original)
            except Exception:
                temporary.unlink(missing_ok=True)
                original.unlink(missing_ok=True)
                raise
        expected_pages = record.page_count or 0
        files = []
        if source_kind(original) == ".zip":
            try:
                detail = self.api.resource_detail(record.resource_id)
                files = [item for item in detail.get("fileList", []) if isinstance(item, dict)]
            except Exception as exc:
                self.on_log(f"ZIP 子文件目录不可用，按文件名排序：{record.resource_id} - {exc}")
            # For archives, top-level pageNum describes only the first member.
            counts = [int(item.get("totalPage") or 0) for item in files]
            expected_pages = sum(counts) if counts and all(count > 0 for count in counts) else 0
        self.on_log(f"资源进度：{record.resource_id} - 校验原文并生成 PDF 和图片")
        try:
            converted, added = self.converter.convert_source_and_publish(
                original, directory, expected_pages=expected_pages, files=files,
            )
        except Exception as exc:
            return DownloadResult(
                status=ResourceStatus.partial, saved_pages=0, expected_pages=expected_pages,
                source="original", local_dir=str(directory),
                error=f"原件已保存，PDF 尚未通过校验：{str(exc) or type(exc).__name__}",
            )
        record.raw.setdefault("sourcePageNum", record.page_count)
        record.page_count = converted
        return self._result_from_count(
            saved_count=converted, expected_pages=converted, source="original_pdf",
            local_dir=str(directory), images_added=added,
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
        if not saved_count or (expected_pages and saved_count < expected_pages):
            return DownloadResult(
                status=ResourceStatus.partial,
                saved_pages=saved_count,
                expected_pages=expected_pages,
                source=source,
                local_dir=local_dir,
                error=(f"部分完成：已保存 {saved_count}/{expected_pages} 页" if saved_count else "未生成有效页面"),
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
