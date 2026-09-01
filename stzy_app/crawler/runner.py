from __future__ import annotations

import random
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from stzy_app.config import AppSettings
from stzy_app.crawler.api import StzyCrawlerApi, build_record
from stzy_app.crawler.tags import TagCatalog
from stzy_app.http import StzyHttpClient
from stzy_app.models import CrawlCombo, CrawlFilters, ResourceRecord, ResourceStatus
from stzy_app.storage import CrawlState, CsvIndex
from stzy_app.utils import ensure_directory, safe_filename

LogCallback = Callable[[str], None]
RecordCallback = Callable[[ResourceRecord], None]
ProgressCallback = Callable[["CrawlStats"], None]


@dataclass
class CrawlStats:
    task_mode: str = "idle"
    phase: str = "preview"
    outcome: str = ""
    total_combos: int = 0
    completed_combos: int = 0
    resources_seen: int = 0
    resources_total: int = 0
    resources_completed: int = 0
    current_resource_name: str = ""
    images_downloaded: int = 0
    paid_skipped: int = 0
    preview_limited: int = 0
    failed: int = 0
    running: bool = False
    paused: bool = False


class CrawlRunner:
    """Coordinates combinations, pagination, downloads and resumable state."""

    def __init__(
        self,
        settings: AppSettings,
        filters: CrawlFilters,
        *,
        on_log: LogCallback | None = None,
        on_record: RecordCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.settings = settings
        self.filters = filters
        self.client = StzyHttpClient(settings)
        self.api = StzyCrawlerApi(self.client, settings)
        self.index = CsvIndex(settings.csv_file)
        self.state = CrawlState(settings.state_file)
        self.on_log = on_log or (lambda message: None)
        self.on_record = on_record or (lambda record: None)
        self.on_progress = on_progress or (lambda stats: None)
        self.stats = CrawlStats()
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> CrawlStats:
        self.stats.task_mode = "crawl"
        self.stats.phase = "running"
        self.stats.outcome = ""
        self.stats.running = True
        self._emit_progress()
        try:
            catalog = TagCatalog.fetch(self.client, self.settings)
            combos = catalog.combos(self.filters)
            self.stats.total_combos = len(combos)
            self._log(f"已生成 {len(combos)} 个筛选组合")
            account_names = self.client.enabled_account_names()
            if account_names:
                self._log(f"账号轮询顺序：{' -> '.join(account_names)}")
            for combo in combos:
                if self._stop.is_set():
                    self.stats.paused = True
                    self._log("任务已暂停")
                    break
                if self.state.is_combo_completed(combo, self.settings.subject_code):
                    self._log("组合曾经跑过，本次继续检查新增或缺失资源")
                self._crawl_combo(combo)
                self.state.mark_combo_completed(combo, self.settings.subject_code)
                self.stats.completed_combos += 1
                self._emit_progress()
        finally:
            self.stats.running = False
            self.stats.phase = "finished"
            if self.stats.paused:
                self.stats.outcome = "paused"
            elif self.stats.failed or self.stats.paid_skipped:
                self.stats.outcome = "partial"
            elif self.stats.preview_limited:
                self.stats.outcome = "partial"
            else:
                self.stats.outcome = "completed"
            self._emit_progress()
        return self.stats

    def estimate(self) -> CrawlStats:
        catalog = TagCatalog.fetch(self.client, self.settings)
        combos = catalog.combos(self.filters)
        stats = CrawlStats(
            task_mode="estimate",
            phase="running",
            total_combos=len(combos),
            running=True,
        )
        self._log(f"开始预估 {len(combos)} 个组合")
        for combo in combos:
            if self._stop.is_set():
                stats.paused = True
                break
            try:
                data = self.api.list_resources(combo, self.filters, 1)
                stats.resources_seen += int(data.get("total") or 0)
            except Exception as exc:  # noqa: BLE001
                stats.failed += 1
                self._log(f"预估失败：{combo.names()} - {exc}")
            stats.completed_combos += 1
            self.on_progress(stats)
            self._sleep(self.settings.list_delay_seconds)
        stats.running = False
        stats.phase = "finished" if stats.paused else "preview"
        stats.outcome = "paused" if stats.paused else "estimated"
        self.on_progress(stats)
        return stats

    def _crawl_combo(self, combo: CrawlCombo) -> None:
        page_num = 1
        names = combo.names()
        self._log(
            "抓取组合："
            f"{names['year']} / {names['scene']} / {names['rank']} / "
            f"{names['province']} / {names['grade']} / {names['term']}"
        )
        while not self._stop.is_set():
            if self.filters.max_pages_per_combo and page_num > self.filters.max_pages_per_combo:
                return
            data = self.api.list_resources(combo, self.filters, page_num)
            if page_num == 1:
                self.stats.resources_total += int(data.get("total") or 0)
                self._emit_progress()
            items = data.get("list") or []
            if not items:
                return
            for item in items:
                if self._stop.is_set():
                    return
                if not self._matches_selected_province(item, combo):
                    actual_province = str(item.get("provinceName") or "未知地区")
                    resource_name = str(item.get("resourceName") or item.get("resourceId") or "")
                    self._log(
                        "跳过地区不匹配资源："
                        f"已选 {names['province']}，返回 {actual_province} - {resource_name}"
                    )
                    continue
                record = build_record(item, combo)
                record.subject = self.settings.subject_name
                self._handle_resource(record)
            total_page = int(data.get("totalPage") or 0)
            if page_num >= total_page:
                return
            page_num += 1
            self._sleep(self.settings.list_delay_seconds)

    def _handle_resource(self, record: ResourceRecord) -> None:
        self.stats.resources_seen += 1
        self.stats.current_resource_name = record.resource_name
        self._emit_progress()
        record.local_dir = str(self._resource_dir(record))
        try:
            if record.page_count > 10:
                saved_count = self._download_full_pdf_with_accounts(record)
            else:
                pictures = self.api.resource_pictures(record.resource_id)
                self._download_preview_images(record, pictures)
                saved_count = self._saved_picture_count(record)
                if record.page_count and saved_count < record.page_count:
                    self._log(
                        f"预览图不完整：{record.resource_id} - "
                        f"已保存 {saved_count}/{record.page_count} 页，尝试下载 PDF 补全"
                    )
                    try:
                        pdf_count = self._download_full_pdf_with_accounts(record)
                    except Exception as exc:  # noqa: BLE001
                        record.error = (
                            f"预览接口仅返回 {saved_count}/{record.page_count} 页，"
                            f"PDF 补全失败：{exc}"
                        )
                    else:
                        saved_count = max(saved_count, pdf_count)
            record.image_count = saved_count
            if record.page_count and saved_count >= record.page_count:
                record.status = ResourceStatus.completed
                self.index.append(record)
                self.state.mark_resource(record.resource_id, record.status.value)
            elif record.status == ResourceStatus.paid_unavailable:
                self.index.append(record)
                self.state.mark_resource(record.resource_id, record.status.value, record.error)
            else:
                record.status = ResourceStatus.partial
                record.error = record.error or (
                    f"部分完成：已保存 {saved_count}/{record.page_count or '?'} 页"
                )
                self.stats.preview_limited += 1
                self.index.append(record)
                self.state.mark_resource(record.resource_id, record.status.value, record.error)
        except Exception as exc:  # noqa: BLE001
            record.status = ResourceStatus.failed
            record.error = str(exc)
            self.stats.failed += 1
            self.index.append(record)
            self.state.mark_resource(record.resource_id, record.status.value, record.error)
            self._log(f"资源失败：{record.resource_id} - {exc}")
        finally:
            self.stats.resources_completed += 1
        self.on_record(record)
        self._emit_progress()

    def _download_preview_images(self, record: ResourceRecord, pictures: list[str]) -> None:
        directory = self._resource_dir(record)
        original_dir = directory / "original"
        ensure_directory(directory)
        ensure_directory(original_dir)
        for index, url in enumerate(pictures, start=1):
            suffix = Path(url.split("?", 1)[0]).suffix or ".svg"
            original = original_dir / f"练习{index}{suffix}"
            target = directory / f"练习{index}.png"
            had_target = target.exists() and target.stat().st_size > 0
            if not original.exists() or original.stat().st_size <= 0:
                self.client.download(url, original)
            if suffix.lower() == ".svg":
                if self._svg_needs_browser_renderer(original):
                    self._log(f"使用浏览器转换 SVG：{original.name}")
                    self._convert_svg_to_png_with_browser(original, target)
                elif not target.exists() or target.stat().st_size <= 0:
                    self._convert_svg_to_png(original, target)
            elif suffix.lower() == ".png":
                if not target.exists() or target.stat().st_size <= 0:
                    self._convert_image_to_png(original, target)
            else:
                if not target.exists() or target.stat().st_size <= 0:
                    self._convert_image_to_png(original, target)
            if not had_target and target.exists() and target.stat().st_size > 0:
                self.stats.images_downloaded += 1
            self._sleep(self.settings.image_delay_seconds)

    def _download_full_pdf_with_accounts(self, record: ResourceRecord) -> int:
        suffix = str(record.raw.get("resourceSuffix") or "").lower()
        if suffix and suffix != ".pdf":
            raise RuntimeError(f"原文格式 {suffix} 暂不支持 PDF 转图片")
        directory = self._resource_dir(record)
        ensure_directory(directory)
        pdf_path = directory / "原文.pdf"
        if not pdf_path.exists() or pdf_path.stat().st_size <= 0:
            pdf_url = self._download_pdf_url_with_accounts(record)
            if not pdf_url:
                return 0
            self.client.download(pdf_url, pdf_path, headers={})
        converted = self._convert_pdf_to_pngs(pdf_path, directory)
        self._log(f"完成：{record.resource_id} - 已保存 {converted} 页")
        return converted

    def _download_pdf_url_with_accounts(self, record: ResourceRecord) -> str:
        attempts: list[tuple[str, dict[str, str]]] = [
            (account.name, self.client.headers_for_account(account))
            for account in self.client.enabled_valid_accounts()
        ]
        if not attempts:
            attempts.append(("当前登录", self.client._auth_headers()))
        last_error = "没有可用账号"
        for account_name, headers in attempts:
            try:
                pdf_url = self.api.download_resource_url(record.resource_id, headers=headers)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                self._log(f"账号 {account_name} 下载失败，尝试下一个账号：{last_error}")
                continue
            if pdf_url:
                self._log(f"账号 {account_name} 下载成功：{record.resource_id}")
                return pdf_url
            last_error = "接口未返回 PDF 地址"
            self._log(f"账号 {account_name} 下载失败，尝试下一个账号：{last_error}")
        if record.price > 0:
            record.status = ResourceStatus.paid_unavailable
            record.error = f"所有账号均不可用或额度不足：{last_error}"
            self.stats.paid_skipped += 1
            return ""
        raise RuntimeError(f"所有账号均不可用或额度不足：{last_error}")

    def _convert_pdf_to_pngs(self, pdf_path: Path, directory: Path) -> int:
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
        existing_count = self._saved_picture_count_from_dir(directory)
        for index, source in enumerate(generated, start=1):
            target = directory / f"练习{index}.png"
            if target.exists() and target.stat().st_size > 0:
                target.unlink()
            source.rename(target)
        self.stats.images_downloaded += max(0, len(generated) - existing_count)
        return len(generated)

    def _saved_picture_count(self, record: ResourceRecord) -> int:
        return self._saved_picture_count_from_dir(self._resource_dir(record))

    @staticmethod
    def _saved_picture_count_from_dir(directory: Path) -> int:
        return len([path for path in directory.glob("练习*.png") if path.stat().st_size > 0])

    def _convert_svg_to_png(self, svg_path: Path, png_path: Path) -> None:
        import cairosvg

        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), background_color="white")
        self._flatten_png_on_white(png_path)

    @staticmethod
    def _svg_needs_browser_renderer(svg_path: Path) -> bool:
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

    def _convert_svg_to_png_with_browser(self, svg_path: Path, png_path: Path) -> None:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        width, height = self._svg_size(svg_path)
        html_content = self._svg_render_html(svg_path, width, height)
        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                except PlaywrightError:
                    browser = playwright.chromium.launch(headless=True)
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
                    context.close()
                    browser.close()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Playwright 转换 SVG 失败：{exc}") from exc
        if not png_path.exists() or png_path.stat().st_size <= 0:
            raise RuntimeError(f"Playwright 未生成 PNG：{svg_path.name}")
        self._flatten_png_on_white(png_path)

    @staticmethod
    def _svg_size(svg_path: Path) -> tuple[int, int]:
        content = svg_path.read_text(encoding="utf-8", errors="ignore")[:2000]
        width = CrawlRunner._svg_dimension(content, "width") or 612
        height = CrawlRunner._svg_dimension(content, "height") or 879
        return max(1, width), max(1, height)

    @staticmethod
    def _svg_dimension(content: str, name: str) -> int | None:
        match = re.search(rf'\b{name}=["\']([0-9.]+)', content)
        if not match:
            return None
        return int(float(match.group(1)))

    @staticmethod
    def _svg_render_html(svg_path: Path, width: int, height: int) -> str:
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

    def _convert_image_to_png(self, image_path: Path, png_path: Path) -> None:
        from PIL import Image

        with Image.open(image_path) as image:
            self._save_image_on_white(image, png_path)

    def _flatten_png_on_white(self, png_path: Path) -> None:
        from PIL import Image

        with Image.open(png_path) as image:
            self._save_image_on_white(image, png_path)

    def _save_image_on_white(self, image, png_path: Path) -> None:
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

    def _resource_dir(self, record: ResourceRecord) -> Path:
        return (
            self.settings.output_dir
            / safe_filename(record.subject, fallback=self.settings.subject_code)
            / safe_filename(record.grade)
            / safe_filename(self._term_dir_name(record.term))
            / safe_filename(self._province_dir_name(record.province))
            / safe_filename(record.scene)
            / safe_filename(record.resource_name, fallback=record.resource_id)
        )

    @staticmethod
    def _term_dir_name(term: str) -> str:
        if term.endswith("上"):
            return "上学期"
        if term.endswith("下"):
            return "下学期"
        return term

    @staticmethod
    def _province_dir_name(province: str) -> str:
        municipalities = {"北京", "天津", "上海", "重庆"}
        if province in municipalities:
            return f"{province}市"
        return province

    @staticmethod
    def _matches_selected_province(item: dict[str, object], combo: CrawlCombo) -> bool:
        if not combo.province.code:
            return True
        actual_province = str(item.get("provinceName") or "").strip()
        return not actual_province or actual_province == combo.province.name

    def _sleep(self, base_seconds: float) -> None:
        delay = max(0.0, base_seconds) + random.uniform(0, 0.2)
        self._stop.wait(delay)

    def _log(self, message: str) -> None:
        self.on_log(message)

    def _emit_progress(self) -> None:
        self.on_progress(self.stats)
