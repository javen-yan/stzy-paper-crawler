from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from stzy_app.config import AppSettings
from stzy_app.crawler.converters import DocumentConverter
from stzy_app.models import ResourceRecord


class SvgConversionTest(unittest.TestCase):
    def test_embedded_pdf_subset_fonts_use_font_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = Path(tmpdir) / "练习1.svg"
            svg_path.write_text(
                """
                <svg xmlns="http://www.w3.org/2000/svg">
                  <style>
                    @font-face {
                      font-family: 'HLEOCO+MicrosoftYaHei';
                      src: url("data:font/truetype;base64,AAEAAA==");
                    }
                  </style>
                  <text style="font-family:'HLEOCO+MicrosoftYaHei';">宣城市</text>
                </svg>
                """,
                encoding="utf-8",
            )

            self.assertTrue(DocumentConverter.svg_needs_font_fallback(svg_path))

    def test_svg_font_fallback_overrides_inline_subset_font(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = Path(tmpdir) / "练习1.svg"
            svg_path.write_text(
                """
                <svg xmlns="http://www.w3.org/2000/svg">
                  <text style="font-family:'HLEOCO+MicrosoftYaHei';">宣城市</text>
                </svg>
                """,
                encoding="utf-8",
            )

            with patch.object(DocumentConverter, "detect_svg_font_family", return_value="Noto Sans CJK SC"):
                content = DocumentConverter.svg_with_font_fallback(svg_path)

            self.assertIn("'Noto Sans CJK SC'", content)
            self.assertIn("!important", content)

    def test_svg_font_detection_returns_empty_without_fontconfig(self) -> None:
        with patch("stzy_app.crawler.converters.shutil.which", return_value=None):
            self.assertEqual(DocumentConverter.detect_svg_font_family(), "")

    def test_svg_conversion_uses_pymupdf_without_cairo_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = Path(tmpdir) / "simple.svg"
            png_path = Path(tmpdir) / "simple.png"
            svg_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="80">'
                '<rect width="200" height="80" fill="white"/>'
                '<text x="20" y="45" font-size="28">OK</text>'
                '</svg>',
                encoding="utf-8",
            )

            self.assertFalse(DocumentConverter.svg_needs_font_fallback(svg_path))
            DocumentConverter.convert_svg_to_png(svg_path, png_path)
            self.assertGreater(png_path.stat().st_size, 0)

    def test_pdf_conversion_uses_python_dependency(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            pdf_path = directory / "sample.pdf"
            document = pymupdf.open()
            page = document.new_page(width=200, height=120)
            page.insert_text((24, 60), "STZY")
            document.save(pdf_path)
            document.close()

            converted = DocumentConverter.convert_pdf_to_pngs_with_pymupdf(pdf_path, directory)

            self.assertEqual(converted, 1)
            self.assertGreater((directory / "练习1.png").stat().st_size, 0)

    def test_preview_originals_generate_sibling_pdf_and_cleanup_originals(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fixture_png = root / "source.png"
            Image.new("RGB", (120, 80), "white").save(fixture_png)
            client = FakeClient(
                {
                    "https://cdn.test/1.svg": (
                        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="80">'
                        '<rect width="200" height="80" fill="white"/>'
                        '<text x="20" y="45" font-size="28">A</text>'
                        "</svg>"
                    ).encode("utf-8"),
                    "https://cdn.test/2.png": fixture_png.read_bytes(),
                }
            )
            converter = DocumentConverter(AppSettings(output_dir=root), client, sleep=lambda _: None)
            directory = root / "试卷A"

            added = converter.download_preview_images(
                ResourceRecord(resource_id="r1", resource_name="试卷A"),
                ["https://cdn.test/1.svg", "https://cdn.test/2.png"],
                directory,
            )

            self.assertEqual(added, 2)
            self.assertGreater((directory / "练习1.png").stat().st_size, 0)
            self.assertGreater((directory / "练习2.png").stat().st_size, 0)
            self.assertFalse((directory / "original").exists())
            final_pdf = root / "试卷A.pdf"
            self.assertGreater(final_pdf.stat().st_size, 0)
            with pymupdf.open(final_pdf) as document:
                self.assertEqual(document.page_count, 2)

    def test_pdf_download_moves_to_sibling_pdf_and_removes_legacy_pdf(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_pdf = root / "download.pdf"
            document = pymupdf.open()
            page = document.new_page(width=200, height=120)
            page.insert_text((24, 60), "STZY")
            document.save(source_pdf)
            document.close()
            client = FakeClient({"https://cdn.test/file.pdf": source_pdf.read_bytes()})
            converter = DocumentConverter(AppSettings(output_dir=root), client, sleep=lambda _: None)
            directory = root / "试卷B"

            converted, added = converter.download_pdf_and_convert(
                "https://cdn.test/file.pdf",
                directory / "原文.pdf",
                directory,
            )

            self.assertEqual(converted, 1)
            self.assertEqual(added, 1)
            self.assertGreater((directory / "练习1.png").stat().st_size, 0)
            self.assertFalse((directory / "原文.pdf").exists())
            self.assertGreater((root / "试卷B.pdf").stat().st_size, 0)

    def test_bad_existing_preview_original_is_downloaded_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            directory = root / "试卷C"
            original_dir = directory / "original"
            original_dir.mkdir(parents=True)
            (original_dir / "练习1.svg").write_text("<html>proxy failed</html>", encoding="utf-8")
            client = FakeClient(
                {
                    "https://cdn.test/1.svg": (
                        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="80">'
                        '<rect width="200" height="80" fill="white"/>'
                        "</svg>"
                    ).encode("utf-8"),
                }
            )
            converter = DocumentConverter(AppSettings(output_dir=root), client, sleep=lambda _: None)

            added = converter.download_preview_images(
                ResourceRecord(resource_id="r1", resource_name="试卷C"),
                ["https://cdn.test/1.svg"],
                directory,
            )

            self.assertEqual(added, 1)
            self.assertEqual(client.download_calls, 1)


class FakeClient:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.download_calls = 0

    def download(self, url: str, target: Path, *, headers: dict[str, str] | None = None) -> int:
        self.download_calls += 1
        payload = self.payloads[url]
        target.write_bytes(payload)
        return len(payload)


if __name__ == "__main__":
    unittest.main()
