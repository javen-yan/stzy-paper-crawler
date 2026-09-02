from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from stzy_app.config import AppSettings
from stzy_app.crawler.artifacts import ResourceArtifacts
from stzy_app.http import StzyHttpClient
from stzy_app.models import ResourceRecord
from stzy_app.utils import ensure_directory

LogCallback = Callable[[str], None]
SleepCallback = Callable[[float], None]


class DocumentConverter:
    """Converts SVG/image/PDF documents to final PNG and PDF artifacts."""

    def __init__(
        self,
        settings: AppSettings,
        client: StzyHttpClient,
        *,
        on_log: LogCallback | None = None,
        sleep: SleepCallback | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.on_log = on_log or (lambda message: None)
        self.sleep = sleep or self._default_sleep

    def download_preview_images(
        self,
        record: ResourceRecord,
        pictures: list[str],
        directory: Path,
    ) -> int:
        artifacts = ResourceArtifacts(directory)
        artifacts.prepare_resource_dir()
        artifacts.prepare_original_dir()
        images_added = 0
        originals: list[Path] = []
        for index, url in enumerate(pictures, start=1):
            suffix = Path(url.split("?", 1)[0]).suffix or ".svg"
            original = artifacts.original_dir / f"练习{index}{suffix}"
            target = artifacts.page_png(index)
            had_target = target.exists() and target.stat().st_size > 0
            if not original.exists() or original.stat().st_size <= 0:
                self.client.download(url, original)
            self.convert_original_to_png(original, target)
            originals.append(original)
            if not had_target and target.exists() and target.stat().st_size > 0:
                images_added += 1
            self.sleep(self.settings.image_delay_seconds)
        if originals:
            self.convert_originals_to_pdf(originals, artifacts.temp_pdf)
            artifacts.publish_pdf(artifacts.temp_pdf)
            artifacts.cleanup_transient_artifacts()
        return images_added

    def download_pdf_and_convert(self, pdf_url: str, pdf_path: Path, directory: Path) -> tuple[int, int]:
        artifacts = ResourceArtifacts(directory)
        artifacts.prepare_resource_dir()
        source_pdf = pdf_path
        if not source_pdf.exists() or source_pdf.stat().st_size <= 0:
            self.client.download(pdf_url, artifacts.temp_pdf, headers={})
            source_pdf = artifacts.temp_pdf
        existing_count = self.saved_picture_count_from_dir(directory)
        converted = self.convert_pdf_to_pngs(source_pdf, directory)
        artifacts.publish_pdf(source_pdf)
        artifacts.cleanup_transient_artifacts()
        return converted, max(0, converted - existing_count)

    def convert_original_to_png(self, original: Path, target: Path) -> None:
        suffix = original.suffix.lower()
        if suffix == ".svg":
            if not target.exists() or target.stat().st_size <= 0:
                if self.svg_needs_font_fallback(original):
                    self.on_log(f"使用内置转换器处理复杂 SVG：{original.name}")
                self.convert_svg_to_png(original, target)
            return
        if not target.exists() or target.stat().st_size <= 0:
            self.convert_image_to_png(original, target)

    def convert_pdf_to_pngs(self, pdf_path: Path, directory: Path) -> int:
        if not pdf_path:
            return 0
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            return 0
        return self.convert_pdf_to_pngs_with_pymupdf(pdf_path, directory)

    @staticmethod
    def convert_pdf_to_pngs_with_pymupdf(pdf_path: Path, directory: Path) -> int:
        import pymupdf

        generated_count = 0
        artifacts = ResourceArtifacts(directory)
        with pymupdf.open(pdf_path) as document:
            for index, page in enumerate(document, start=1):
                target = artifacts.page_png(index)
                if target.exists() and target.stat().st_size > 0:
                    target.unlink()
                pixmap = page.get_pixmap(dpi=180, alpha=False)
                pixmap.save(target)
                generated_count += 1
        return generated_count

    @staticmethod
    def saved_picture_count_from_dir(directory: Path) -> int:
        return len([path for path in directory.glob("练习*.png") if path.stat().st_size > 0])

    @staticmethod
    def convert_svg_to_png(svg_path: Path, png_path: Path) -> None:
        import pymupdf

        content = DocumentConverter.svg_with_font_fallback(svg_path)
        with pymupdf.open(stream=content.encode("utf-8"), filetype="svg") as document:
            page = document[0]
            pixmap = page.get_pixmap(dpi=180, alpha=False)
            pixmap.save(png_path)
        DocumentConverter.flatten_png_on_white(png_path)

    @staticmethod
    def convert_originals_to_pdf(originals: list[Path], pdf_path: Path) -> None:
        import pymupdf

        ensure_directory(pdf_path.parent)
        output = pymupdf.open()
        try:
            for original in originals:
                if original.suffix.lower() == ".svg":
                    content = DocumentConverter.svg_with_font_fallback(original)
                    with pymupdf.open(
                        stream=content.encode("utf-8"),
                        filetype="svg",
                    ) as svg_document:
                        pdf_bytes = svg_document.convert_to_pdf()
                    with pymupdf.open("pdf", pdf_bytes) as page_pdf:
                        output.insert_pdf(page_pdf)
                    continue
                DocumentConverter.append_image_page(output, original)
            if output.page_count:
                if pdf_path.exists():
                    pdf_path.unlink()
                output.save(pdf_path)
        finally:
            output.close()

    @staticmethod
    def append_image_page(document, image_path: Path) -> None:
        import pymupdf
        from PIL import Image

        with Image.open(image_path) as image:
            width, height = image.size
        page = document.new_page(width=width, height=height)
        page.insert_image(pymupdf.Rect(0, 0, width, height), filename=str(image_path))

    @staticmethod
    def svg_needs_font_fallback(svg_path: Path) -> bool:
        try:
            content = svg_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        known_pdf_fonts = [
            "MicrosoftYaHei",
            "SimHei",
            "SimSun",
            "SymbolMT",
            "Arial-BoldMT",
        ]
        return (
            "<text" in content
            and "@font-face" in content
            and "data:font/" in content
            and any(font_name in content for font_name in known_pdf_fonts)
        )

    @staticmethod
    def svg_with_font_fallback(svg_path: Path) -> str:
        content = svg_path.read_text(encoding="utf-8", errors="ignore")
        fallback_css = (
            "<style>"
            "text,tspan{font-family:"
            "Arial,'Helvetica Neue','PingFang SC','Hiragino Sans GB',"
            "'Microsoft YaHei','Noto Sans CJK SC','SimHei','SimSun',sans-serif;}"
            "</style>"
        )
        if "<svg" not in content:
            return content
        return re.sub(r"(<svg\b[^>]*>)", r"\1" + fallback_css, content, count=1)

    @staticmethod
    def convert_image_to_png(image_path: Path, png_path: Path) -> None:
        from PIL import Image

        with Image.open(image_path) as image:
            DocumentConverter.save_image_on_white(image, png_path)

    @staticmethod
    def flatten_png_on_white(png_path: Path) -> None:
        from PIL import Image

        with Image.open(png_path) as image:
            DocumentConverter.save_image_on_white(image, png_path)

    @staticmethod
    def save_image_on_white(image, png_path: Path) -> None:
        from PIL import Image

        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            background.alpha_composite(rgba)
            background.convert("RGB").save(png_path, format="PNG")
            return
        image.convert("RGB").save(png_path, format="PNG")

    @staticmethod
    def _default_sleep(base_seconds: float) -> None:
        import random

        delay = max(0.0, base_seconds) + random.uniform(0, 0.2)
        if delay:
            import time

            time.sleep(delay)
