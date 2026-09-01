from __future__ import annotations

import re
import shutil
import subprocess
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
            if self.svg_needs_browser_renderer(original):
                self.on_log(f"使用浏览器转换 SVG：{original.name}")
                self.convert_svg_to_png_with_browser(original, target)
            elif not target.exists() or target.stat().st_size <= 0:
                self.convert_svg_to_png(original, target)
            return
        if not target.exists() or target.stat().st_size <= 0:
            self.convert_image_to_png(original, target)

    def convert_pdf_to_pngs(self, pdf_path: Path, directory: Path) -> int:
        if not pdf_path:
            return 0
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            return 0
        if not shutil.which("pdftoppm"):
            raise RuntimeError("缺少 pdftoppm，无法把 PDF 转为 PNG")
        temp_prefix = directory / ".pdf_page"
        process = subprocess.run(
            ["pdftoppm", "-png", "-r", "180", str(pdf_path), str(temp_prefix)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            message = process.stderr.decode(errors="replace").strip() or "PDF 转 PNG 失败"
            raise RuntimeError(message)
        generated = sorted(
            directory.glob(".pdf_page-*.png"),
            key=lambda path: int(path.stem.rsplit("-", 1)[-1]),
        )
        for index, source in enumerate(generated, start=1):
            target = directory / f"练习{index}.png"
            if target.exists() and target.stat().st_size > 0:
                target.unlink()
            source.rename(target)
        return len(generated)

    @staticmethod
    def saved_picture_count_from_dir(directory: Path) -> int:
        return len([path for path in directory.glob("练习*.png") if path.stat().st_size > 0])

    @staticmethod
    def convert_svg_to_png(svg_path: Path, png_path: Path) -> None:
        import cairosvg

        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), background_color="white")
        DocumentConverter.flatten_png_on_white(png_path)

    @staticmethod
    def svg_needs_browser_renderer(svg_path: Path) -> bool:
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
    def convert_svg_to_png_with_browser(svg_path: Path, png_path: Path) -> None:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        width, height = DocumentConverter.svg_size(svg_path)
        html_content = DocumentConverter.svg_render_html(svg_path, width, height)
        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                except PlaywrightError:
                    browser = playwright.chromium.launch(headless=True)
                context = None
                try:
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        device_scale_factor=2,
                    )
                    page = context.new_page()
                    page.set_content(html_content, wait_until="load")
                    try:
                        page.wait_for_function(
                            "document.fonts ? document.fonts.status === 'loaded' : true",
                            timeout=5000,
                        )
                    except PlaywrightError:
                        pass
                    page.locator(".page > svg").wait_for(state="visible", timeout=5000)
                    page.screenshot(path=str(png_path), full_page=False)
                finally:
                    if context:
                        context.close()
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Playwright 转换 SVG 失败：{exc}") from exc
        if not png_path.exists() or png_path.stat().st_size <= 0:
            raise RuntimeError(f"Playwright 未生成 PNG：{svg_path.name}")
        DocumentConverter.flatten_png_on_white(png_path)

    @staticmethod
    def svg_size(svg_path: Path) -> tuple[int, int]:
        content = svg_path.read_text(encoding="utf-8", errors="ignore")[:2000]
        width = DocumentConverter.svg_dimension(content, "width") or 612
        height = DocumentConverter.svg_dimension(content, "height") or 879
        return max(1, width), max(1, height)

    @staticmethod
    def svg_dimension(content: str, name: str) -> int | None:
        match = re.search(rf'\b{name}=["\']([0-9.]+)', content)
        if not match:
            return None
        return int(float(match.group(1)))

    @staticmethod
    def svg_render_html(svg_path: Path, width: int, height: int) -> str:
        svg_content = svg_path.read_text(encoding="utf-8", errors="ignore")
        svg_content = re.sub(r"^\s*<\?xml[^>]*>\s*", "", svg_content)
        svg_content = re.sub(r"^\s*<!DOCTYPE[^>]*(?:\[[\s\S]*?\]\s*)?>\s*", "", svg_content)
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>"
            f"html,body{{margin:0;padding:0;width:{width}px;height:{height}px;"
            "overflow:hidden;background:#fff;}"
            f".page{{width:{width}px;height:{height}px;background:#fff;overflow:hidden;}}"
            ".page>svg{display:block;width:100%;height:100%;}"
            "</style></head>"
            f"<body><div class='page'>{svg_content}</div></body></html>"
        )

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
