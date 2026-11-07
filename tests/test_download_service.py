from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stzy_app.config import AppSettings
from stzy_app.crawler.download_service import DownloadService
from stzy_app.crawler.paths import ResourcePathBuilder
from stzy_app.models import ResourceRecord, ResourceStatus


class DownloadServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmpdir.name)
        self.settings = AppSettings(output_dir=self.output_dir)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_preview_complete_does_not_request_pdf(self) -> None:
        logs: list[str] = []
        service = self._service(
            pictures=["https://cdn.test/1.svg", "https://cdn.test/2.svg"],
            converter=FakeConverter(saved_count=2, preview_added=2),
            scheduler=FakeScheduler(),
            logs=logs,
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=2)

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(result.saved_pages, 2)
        self.assertEqual(result.images_added, 2)
        self.assertEqual(service.account_scheduler.download_calls, 0)
        self.assertIn("资源进度：r1 - 获取预览图", logs)
        self.assertIn("资源进度：r1 - 预览图 2 张", logs)

    def test_preview_incomplete_falls_back_to_pdf(self) -> None:
        logs: list[str] = []
        service = self._service(
            pictures=["https://cdn.test/1.svg", "https://cdn.test/2.svg"],
            converter=FakeConverter(saved_count=2, preview_added=2, pdf_count=4, pdf_added=2),
            scheduler=FakeScheduler(url="https://cdn.test/file.pdf"),
            logs=logs,
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=4)

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(result.saved_pages, 4)
        self.assertEqual(result.source, "preview_fallback_pdf")
        self.assertEqual(service.account_scheduler.download_calls, 1)
        self.assertIn("资源进度：r1 - 获取 PDF 地址", logs)
        self.assertIn("资源进度：r1 - PDF 转图片", logs)

    def test_large_resource_goes_directly_to_pdf(self) -> None:
        service = self._service(
            pictures=[],
            converter=FakeConverter(pdf_count=12, pdf_added=12),
            scheduler=FakeScheduler(url="https://cdn.test/file.pdf"),
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=12)

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(result.saved_pages, 12)
        self.assertEqual(result.source, "pdf")
        self.assertEqual(service.api.picture_calls, 0)

    def test_existing_complete_files_are_marked_completed_without_pdf_download(self) -> None:
        service = self._service(
            pictures=[],
            converter=FakeConverter(saved_count=14),
            scheduler=FakeScheduler(url="https://cdn.test/file.pdf"),
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=14)

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(result.saved_pages, 14)
        self.assertEqual(result.source, "existing")
        self.assertEqual(service.account_scheduler.download_calls, 0)

    def test_task_scoped_resource_dir_uses_original_remote_name(self) -> None:
        settings = AppSettings(output_dir=self.output_dir, task_scope="task-1")
        record = ResourceRecord(
            resource_id="733284653911044096",
            resource_name="安徽六安市2025-2026学年高一下学期期末考试数学",
            subject="数学",
            grade="高一",
            term="高一下",
            province="安徽",
            scene="期末",
        )

        directory = ResourcePathBuilder(settings).resource_dir(record)

        self.assertEqual(directory.name, "安徽六安市2025-2026学年高一下学期期末考试数学")
        self.assertNotIn("733284653911044096", str(directory))

    def test_bad_existing_sibling_pdf_requests_download_url_again(self) -> None:
        service = self._service(
            pictures=[],
            converter=FakeConverter(pdf_count=12, pdf_added=12, pdf_valid=False),
            scheduler=FakeScheduler(url="https://cdn.test/file.pdf"),
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=12)
        existing_pdf = self.output_dir / "试卷.pdf"
        existing_pdf.write_text("<html>proxy failed</html>", encoding="utf-8")

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(service.account_scheduler.download_calls, 1)

    def test_pdf_conversion_error_with_complete_files_is_marked_completed(self) -> None:
        service = self._service(
            pictures=[],
            converter=FakeConverter(saved_count=14, pdf_exception=RuntimeError()),
            scheduler=FakeScheduler(url="https://cdn.test/file.pdf"),
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=14)

        result = service.download_full_pdf(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(result.saved_pages, 14)

    def test_all_accounts_failed_returns_paid_unavailable(self) -> None:
        service = self._service(
            pictures=[],
            converter=FakeConverter(),
            scheduler=FakeScheduler(status=ResourceStatus.paid_unavailable, error="额度不足"),
        )
        record = ResourceRecord(resource_id="r1", resource_name="付费试卷", page_count=12, price=3)

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.paid_unavailable)
        self.assertEqual(result.paid_unavailable, 1)
        self.assertIn("无账号支持，请补充 VIP 账号", result.error)

    def test_preview_incomplete_force_refetches_real_pdf(self) -> None:
        """预览拼版 PDF 已存在时，补全仍须强制重新获取真实原文 PDF（回归测试）。"""
        logs: list[str] = []
        service = self._service(
            pictures=["https://cdn.test/1.svg", "https://cdn.test/2.svg"],
            converter=FakeConverter(saved_count=2, preview_added=2, pdf_count=4, pdf_added=2),
            scheduler=FakeScheduler(url="https://cdn.test/file.pdf"),
            logs=logs,
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=4)
        stale_pdf = self.output_dir / "试卷.pdf"
        stale_pdf.write_bytes(b"%PDF-1.4 stale preview pdf")

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(service.account_scheduler.download_calls, 1)

    def test_word_and_zip_convert_original_and_reuse_download(self) -> None:
        from unittest.mock import Mock, patch

        for suffix in ("doc", ".DOCX", ".zip"):
            with self.subTest(suffix=suffix):
                converter = Mock()
                converter.convert_source_and_publish.return_value = (7, 7)
                service = self._service(pictures=[], converter=converter,
                                        scheduler=FakeScheduler(url="https://cdn.test/original"))
                record = ResourceRecord(resource_id=suffix, resource_name=suffix, page_count=7,
                                        raw={"resourceSuffix": suffix})
                with patch("stzy_app.crawler.source_documents.source_kind", return_value='.' + suffix.lower().lstrip('.')):
                    result = service.handle_resource(record)
                    service.handle_resource(record)
                self.assertEqual(result.status, ResourceStatus.completed)
                self.assertEqual(result.source, "original_pdf")
                self.assertEqual(result.saved_pages, 7)
                self.assertEqual(service.api.picture_calls, 0)
                self.assertEqual(service.account_scheduler.download_calls, 1)
                self.assertEqual(len(list(Path(result.local_dir).glob('源文件.*'))), 1)

    def test_font_failure_is_partial_and_preserves_original(self) -> None:
        from unittest.mock import Mock, patch

        converter = Mock()
        converter.convert_source_and_publish.side_effect = RuntimeError('缺少原文字体：宋体')
        service = self._service(pictures=[], converter=converter,
                                scheduler=FakeScheduler(url="https://cdn.test/original"))
        record = ResourceRecord(resource_id='word', resource_name='Word', page_count=11,
                                raw={'resourceSuffix': '.docx'})
        with patch('stzy_app.crawler.source_documents.source_kind', return_value='.docx'):
            result = service.handle_resource(record)
        self.assertEqual(result.status, ResourceStatus.partial)
        self.assertIn('缺少原文字体', result.error)
        self.assertEqual(result.saved_pages, 0)
        self.assertTrue((Path(result.local_dir) / '源文件.docx').exists())

    def test_zip_uses_sum_of_child_pages_instead_of_top_level_page_count(self) -> None:
        from unittest.mock import Mock, patch

        converter = Mock()
        converter.convert_source_and_publish.return_value = (13, 13)
        service = self._service(pictures=[], converter=converter,
                                scheduler=FakeScheduler(url='https://cdn.test/original'))
        files = [{'fileName': name, 'totalPage': count} for name, count in [('paper.pdf',7),('card.pdf',2),('answers.pdf',4)]]
        service.api.resource_detail = Mock(return_value={'fileList':files})
        record = ResourceRecord(resource_id='zip',resource_name='Zip',page_count=7,raw={'resourceSuffix':'.zip'})
        with patch('stzy_app.crawler.source_documents.source_kind', return_value='.zip'):
            result = service.handle_resource(record)
        self.assertEqual(result.saved_pages,13)
        self.assertEqual(converter.convert_source_and_publish.call_args.kwargs, {'expected_pages':13,'files':files})

    def test_invalid_original_is_not_marked_completed(self) -> None:
        service = self._service(pictures=[], converter=FakeConverter(),
                                scheduler=FakeScheduler(url="https://cdn.test/file.docx"))
        record = ResourceRecord(resource_id="word", resource_name="Word", page_count=11,
                                raw={"resourceSuffix": ".docx"})
        with self.assertRaises(RuntimeError):
            service.handle_resource(record)
        self.assertFalse((Path(record.local_dir) / "源文件.docx").exists())

    def test_word_permission_failure_returns_paid_unavailable(self) -> None:
        service = self._service(pictures=[], converter=FakeConverter(),
                                scheduler=FakeScheduler(status=ResourceStatus.paid_unavailable))
        record = ResourceRecord(resource_id="word", resource_name="Word", page_count=11,
                                raw={"resourceSuffix": ".docx"})
        result = service.handle_resource(record)
        self.assertEqual(result.status, ResourceStatus.paid_unavailable)
        self.assertEqual(service.api.picture_calls, 0)

    def test_no_preview_unknown_page_count_downloads_original(self) -> None:
        service = self._service(pictures=[], converter=FakeConverter(pdf_count=2),
                                scheduler=FakeScheduler(url="https://cdn.test/file.pdf"))
        result = service.handle_resource(ResourceRecord(resource_id="r1", resource_name="paper"))
        self.assertEqual(result.saved_pages, 2)
        self.assertEqual(service.account_scheduler.download_calls, 1)

    def test_zero_pages_not_completed(self) -> None:
        result = DownloadService._result_from_count(saved_count=0, expected_pages=0,
                    source="preview", local_dir="", images_added=0)
        self.assertEqual(result.status, ResourceStatus.partial)

    def _service(
        self,
        *,
        pictures: list[str],
        converter: "FakeConverter",
        scheduler: "FakeScheduler",
        logs: list[str] | None = None,
    ) -> DownloadService:
        log_sink = logs.append if logs is not None else None
        service = DownloadService(self.settings, FakeClient(), FakeApi(pictures), on_log=log_sink)
        service.converter = converter
        service.account_scheduler = scheduler
        return service


class FakeApi:
    def __init__(self, pictures: list[str]) -> None:
        self.pictures = pictures
        self.picture_calls = 0

    def resource_detail(self, resource_id: str) -> dict:
        return {}

    def resource_pictures(self, resource_id: str) -> list[str]:
        self.picture_calls += 1
        return self.pictures


class FakeClient:
    def download(self, url: str, target: Path, *, headers: dict[str, str] | None = None) -> int:
        target.write_bytes(b"pdf")
        return 3


class FakeConverter:
    def __init__(
        self,
        *,
        saved_count: int = 0,
        preview_added: int = 0,
        pdf_count: int = 0,
        pdf_added: int = 0,
        pdf_valid: bool = True,
        pdf_exception: Exception | None = None,
    ) -> None:
        self.saved_count = saved_count
        self.preview_added = preview_added
        self.pdf_count = pdf_count
        self.pdf_added = pdf_added
        self.pdf_valid = pdf_valid
        self.pdf_exception = pdf_exception

    def download_preview_images(
        self,
        record: ResourceRecord,
        pictures: list[str],
        directory: Path,
    ) -> int:
        return self.preview_added

    def saved_picture_count_from_dir(self, directory: Path) -> int:
        return self.saved_count

    def download_pdf_and_convert(self, pdf_url: str, pdf_path: Path, directory: Path) -> tuple[int, int]:
        if self.pdf_exception:
            raise self.pdf_exception
        return self.pdf_count, self.pdf_added

    def pdf_file_looks_valid(self, path: Path) -> bool:
        return self.pdf_valid


class FakeUrlResult:
    def __init__(
        self,
        *,
        url: str = "",
        status: ResourceStatus | None = None,
        error: str = "",
        paid_unavailable: int = 0,
    ) -> None:
        self.url = url
        self.status = status
        self.error = error
        self.paid_unavailable = paid_unavailable


class FakeScheduler:
    def __init__(
        self,
        *,
        url: str = "",
        status: ResourceStatus | None = None,
        error: str = "",
    ) -> None:
        self.url = url
        self.status = status
        self.error = error
        self.download_calls = 0

    def download_pdf_url(self, record: ResourceRecord) -> FakeUrlResult:
        self.download_calls += 1
        return FakeUrlResult(
            url=self.url,
            status=self.status,
            error=self.error,
            paid_unavailable=1 if self.status == ResourceStatus.paid_unavailable else 0,
        )


if __name__ == "__main__":
    unittest.main()
