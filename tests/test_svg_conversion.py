from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stzy_app.crawler.runner import CrawlRunner


class SvgConversionTest(unittest.TestCase):
    def test_embedded_pdf_subset_fonts_use_browser_renderer(self) -> None:
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

            self.assertTrue(CrawlRunner._svg_needs_browser_renderer(svg_path))

    def test_simple_svg_can_still_use_cairosvg(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = Path(tmpdir) / "simple.svg"
            svg_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><text>OK</text></svg>',
                encoding="utf-8",
            )

            self.assertFalse(CrawlRunner._svg_needs_browser_renderer(svg_path))


if __name__ == "__main__":
    unittest.main()
