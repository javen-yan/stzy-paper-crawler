from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stzy_app.crawler.converters import DocumentConverter


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


if __name__ == "__main__":
    unittest.main()
