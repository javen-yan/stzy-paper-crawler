from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from stzy_app.config import AppSettings
from stzy_app.http import StzyHttpClient
from stzy_app.models import ResourceRecord
from stzy_app.utils import ensure_directory

LogCallback = Callable[[str], None]
SleepCallback = Callable[[float], None]


class DocumentConverter:
    """Saves preview originals and converts SVG/image/PDF documents to PNG pages."""

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
        original_dir = directory / "original"
        ensure_directory(directory)
        ensure_directory(original_dir)
        images_added = 0
        for index, url in enumerate(pictures, start=1):
            suffix = Path(url.split("?", 1)[0]).suffix or ".svg"
            original = original_dir / f"练习{index}{suffix}"
            target = directory / f"练习{index}.png"
            had_target = target.exists() and target.stat().st_size > 0
            if not original.exists() or original.stat().st_size <= 0:
                self.client.download(url, original)
            self.convert_original_to_png(original, target)
            if not had_target and target.exists() and target.stat().st_size > 0:
                images_added += 1
            self.sleep(self.settings.image_delay_seconds)
        return images_added

    def download_pdf_and_convert(self, pdf_url: str, pdf_path: Path, directory: Path) -> tuple[int, int]:
        ensure_directory(directory)
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            self.client.download(pdf_url, pdf_path, headers={})
        existing_count = self.saved_picture_count_from_dir(directory)
        converted = self.convert_pdf_to_pngs(pdf_path, directory)
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
        with pymupdf.open(pdf_path) as document:
            for index, page in enumerate(document, start=1):
                target = directory / f"练习{index}.png"
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
    def svg_size(svg_path: Path) -> tuple[int, int]:
        content = svg_path.read_text(encoding="utf-8", errors="ignore")[:2000]
        width = DocumentConverter.svg_dimension(content, "width") or 612
        height = DocumentConverter.svg_dimension(content, "height") or 879
        return max(1, width), max(1, height)

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
    def svg_dimension(content: str, name: str) -> int | None:
        match = re.search(rf'\b{name}=["\']([0-9.]+)', content)
        if not match:
            return None
        return int(float(match.group(1)))

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
