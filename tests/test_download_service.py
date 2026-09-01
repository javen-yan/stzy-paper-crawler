from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stzy_app.config import AppSettings
from stzy_app.crawler.download_service import DownloadService
from stzy_app.models import ResourceRecord, ResourceStatus


class DownloadServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.tmpdir.name)
        self.settings = AppSettings(output_dir=self.output_dir)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_preview_complete_does_not_request_pdf(self) -> None:
        service = self._service(
            pictures=["https://cdn.test/1.svg", "https://cdn.test/2.svg"],
            converter=FakeConverter(saved_count=2, preview_added=2),
            scheduler=FakeScheduler(),
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=2)

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(result.saved_pages, 2)
        self.assertEqual(result.images_added, 2)
        self.assertEqual(service.account_scheduler.download_calls, 0)

    def test_preview_incomplete_falls_back_to_pdf(self) -> None:
        service = self._service(
            pictures=["https://cdn.test/1.svg", "https://cdn.test/2.svg"],
            converter=FakeConverter(saved_count=2, preview_added=2, pdf_count=4, pdf_added=2),
            scheduler=FakeScheduler(url="https://cdn.test/file.pdf"),
        )
        record = ResourceRecord(resource_id="r1", resource_name="试卷", page_count=4)

        result = service.handle_resource(record)

        self.assertEqual(result.status, ResourceStatus.completed)
        self.assertEqual(result.saved_pages, 4)
        self.assertEqual(result.source, "preview_fallback_pdf")
        self.assertEqual(service.account_scheduler.download_calls, 1)

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
        self.assertIn("额度不足", result.error)

    def _service(
        self,
        *,
        pictures: list[str],
        converter: "FakeConverter",
        scheduler: "FakeScheduler",
    ) -> DownloadService:
        service = DownloadService(self.settings, FakeClient(), FakeApi(pictures))
        service.converter = converter
        service.account_scheduler = scheduler
        return service


class FakeApi:
    def __init__(self, pictures: list[str]) -> None:
        self.pictures = pictures
        self.picture_calls = 0

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
    ) -> None:
        self.saved_count = saved_count
        self.preview_added = preview_added
        self.pdf_count = pdf_count
        self.pdf_added = pdf_added

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
        return self.pdf_count, self.pdf_added


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
