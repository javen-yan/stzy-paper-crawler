from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from nicegui import background_tasks, run, ui

from stzy_app.browser import capture_login_state
from stzy_app.config import AppSettings, settings
from stzy_app.crawler import CrawlRunner, CrawlStats, TagCatalog
from stzy_app.http import StzyApiError, StzyHttpClient
from stzy_app.models import CrawlFilters
from stzy_app.storage import AccountCredential, AccountPool, Preferences, TaskHistory
from stzy_app.ui.file_actions import open_path, preview_first_file
from stzy_app.ui.folder_picker import choose_directory
from stzy_app.ui.state import UiState
from stzy_app.ui.style import LIGHT_THEME_CSS

ALL_VALUE = "__ALL__"
STUDY_PHASES = {"200": "初中", "300": "高中"}
DEFAULT_STUDY_PHASE_CODE = "200"


def status_view(stats: CrawlStats, running: bool) -> dict[str, str | int]:
    """Translate internal task state into user-facing product copy."""
    completed = stats.total_combos and stats.completed_combos >= stats.total_combos
    mode = stats.task_mode or "idle"
    outcome = stats.outcome or ""
    resource_total = stats.resources_total or stats.resources_seen
    resource_progress = f"{stats.resources_completed}/{resource_total}" if resource_total else "0/0"

    if running or stats.running:
        if mode == "estimate":
            return {
                "stage": "运行中",
                "detail": f"正在预估匹配试卷 {stats.completed_combos}/{stats.total_combos}",
                "class": "running",
                "count": stats.resources_seen,
            }
        current_name = f"：{stats.current_resource_name}" if stats.current_resource_name else ""
        return {
            "stage": "运行中",
            "detail": f"已处理 {resource_progress} 份试卷{current_name}",
            "class": "running",
            "count": resource_progress,
        }

    if outcome == "estimated" or (mode == "estimate" and completed):
        return {
            "stage": "预览",
            "detail": f"预估完成，找到 {stats.resources_seen} 份匹配试卷",
            "class": "estimated",
            "count": stats.resources_seen,
        }
    if outcome == "auth_expired":
        return {
            "stage": "结束",
            "detail": "登录失效，请重新登录后再开始任务",
            "class": "failed",
            "count": stats.resources_seen,
        }
    if stats.paused or outcome == "paused":
        return {
            "stage": "结束",
            "detail": f"已暂停，已处理 {stats.completed_combos}/{stats.total_combos} 个条件组合",
            "class": "paused",
            "count": stats.resources_seen,
        }
    if outcome == "partial" or (
        stats.total_combos and (stats.failed or stats.preview_limited or stats.paid_skipped)
    ):
        issue_count = stats.failed + stats.preview_limited + stats.paid_skipped
        return {
            "stage": "结束",
            "detail": f"部分完成，异常或未完整保存 {issue_count} 个",
            "class": "partial",
            "count": stats.resources_seen,
        }
    if outcome == "completed" or (mode == "crawl" and completed):
        return {
            "stage": "结束",
            "detail": "下载完成",
            "class": "done",
            "count": stats.resources_seen,
        }
    return {
        "stage": "预览",
        "detail": "等待预估或开始下载",
        "class": "idle",
        "count": stats.resources_seen,
    }


def progress_percent_text(value: float) -> str:
    percent = max(0, min(100, round(value * 100)))
    return f"{percent}%"


def fetch_subject_options() -> dict[str, dict[str, str]]:
    local_settings = AppSettings()
    client = StzyHttpClient(local_settings)
    response = client.get_json("/zw-zzw/api/v1/zzw/tag/getStudyPhaseSubjectTagData")
    subjects: dict[str, dict[str, str]] = {}
    for phase in response.get("data") or []:
        phase_code = str(phase.get("dictCode") or "")
        subjects[phase_code] = {
            str(item.get("dictCode")): str(item.get("dictName"))
            for item in phase.get("childList") or []
            if item.get("dictCode") and item.get("dictName")
        }
    return subjects


def fetch_tag_catalogs() -> dict[str, TagCatalog]:
    catalogs: dict[str, TagCatalog] = {}
    for study_phase_code in STUDY_PHASES:
        phase_settings = AppSettings(study_phase_code=study_phase_code)
        catalogs[study_phase_code] = TagCatalog.fetch(StzyHttpClient(phase_settings), phase_settings)
    return catalogs


def build_ui() -> None:
    app_state = UiState()
    ui.add_head_html(f"<style>{LIGHT_THEME_CSS}</style>")

    try:
        subject_options = fetch_subject_options()
    except Exception as exc:  # noqa: BLE001
        subject_options = {
            "200": {},
            "300": {},
        }
        app_state.log(f"学科标签加载失败：{exc}")
    else:
        app_state.log("学科分类已在启动时同步")

    try:
        catalogs = fetch_tag_catalogs()
    except Exception as exc:  # noqa: BLE001
        catalogs = {study_phase_code: TagCatalog({}) for study_phase_code in STUDY_PHASES}
        app_state.log(f"筛选分类加载失败：{exc}")
    else:
        app_state.log("筛选分类已在启动时同步")

    preferences = Preferences(settings.task_history_file)
    strategy_settings = preferences.get("strategy")

    def catalog() -> TagCatalog:
        return catalogs.get(study_phase.value, TagCatalog({}))

    def options(field: str) -> dict[str, str]:
        return {ALL_VALUE: "不限", **catalog().as_select_options(field)}

    def current_subject_options() -> dict[str, str]:
        return {ALL_VALUE: "不限", **subject_options.get(study_phase.value, {})}

    def selected(value: list[str] | str | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            values = [str(item) for item in value if item and item != ALL_VALUE]
            return values if ALL_VALUE not in value else []
        return [] if value in ("", ALL_VALUE) else [str(value)]

    def current_settings() -> AppSettings:
        subject_code = "" if subject_select.value == ALL_VALUE else str(subject_select.value or "")
        return AppSettings(
            output_dir=Path(output_dir.value),
            state_file=settings.state_file,
            csv_file=settings.csv_file,
            task_history_file=settings.task_history_file,
            cookie_file=Path(output_dir.value) / "cookies.json",
            account_pool_file=settings.account_pool_file,
            study_phase_code=study_phase.value,
            subject_code=subject_code,
            subject_name=current_subject_options().get(subject_select.value, "不限"),
            list_delay_seconds=float(list_delay.value or 0.8),
            image_delay_seconds=float(image_delay.value or 0.3),
            concurrency=int(concurrency.value or 1),
            access_token=None,
            cookie_header=None,
        )

    def current_filters() -> CrawlFilters:
        return CrawlFilters(
            scenes=selected(scene_select.value),
            years=selected(year_select.value),
            ranks=selected(rank_select.value),
            provinces=selected(province_select.value),
            grades=selected(grade_select.value),
            terms=selected(term_select.value),
            file_type=file_type.value or "PDF",
            max_pages_per_combo=int(max_pages.value) if max_pages.value else None,
            download_paid=False,
        )

    def task_history_path() -> Path:
        return settings.task_history_file

    def numeric_value(value: object, default: float) -> float:
        if value in (None, ""):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def selected_labels(values: list[str], option_map: dict[str, str]) -> str:
        if not values:
            return "不限"
        return "、".join(str(option_map.get(value, value)) for value in values)

    def current_filter_summary(
        local_settings: AppSettings,
        local_filters: CrawlFilters,
    ) -> dict[str, str]:
        phase_label = STUDY_PHASES.get(local_settings.study_phase_code, local_settings.study_phase_code)
        subject_label = local_settings.subject_name or "不限"
        province_label = selected_labels(local_filters.provinces, province_select.options)
        term_label = selected_labels(local_filters.terms, term_select.options)
        scene_label = selected_labels(local_filters.scenes, scene_select.options)
        year_label = selected_labels(local_filters.years, year_select.options)
        rank_label = selected_labels(local_filters.ranks, rank_select.options)
        grade_label = selected_labels(local_filters.grades, grade_select.options)
        brief_parts = [province_label, term_label, scene_label, subject_label]
        return {
            "brief": " / ".join(part for part in brief_parts if part and part != "不限") or "不限",
            "学段": phase_label,
            "学科": subject_label,
            "地区": province_label,
            "年级": grade_label,
            "学期": term_label,
            "场景": scene_label,
            "年份": year_label,
            "等级": rank_label,
            "保存位置": str(local_settings.output_dir),
        }

    def history_status_label(status: str) -> str:
        labels = {
            "running": "运行中",
            "estimated": "预估完成",
            "completed": "下载完成",
            "partial": "部分完成",
            "failed": "失败",
            "paused": "已暂停",
            "auth_expired": "登录失效",
        }
        return labels.get(status, status or "-")

    def display_task_rows(tasks: list[dict[str, object]]) -> list[dict[str, object]]:
        rows = []
        for task in tasks:
            stats = task.get("stats") if isinstance(task.get("stats"), dict) else {}
            filters = task.get("filters") if isinstance(task.get("filters"), dict) else {}
            started_at = str(task.get("started_at") or task.get("created_at") or "")
            local_dir = str(task.get("first_local_dir") or filters.get("保存位置") or "")
            rows.append(
                {
                    "id": str(task.get("id") or ""),
                    "started_at": started_at.replace("T", " ")[5:16] if started_at else "-",
                    "brief": str(filters.get("brief") or "不限"),
                    "status_label": history_status_label(str(task.get("status") or "")),
                    "resources_seen": stats.get("resources_seen", 0),
                    "images_downloaded": stats.get("images_downloaded", 0),
                    "local_dir": local_dir,
                }
            )
        return rows

    def run_crawler(
        mode: str,
        local_settings: AppSettings,
        local_filters: CrawlFilters,
        filter_summary: dict[str, str],
    ) -> None:
        started_at = datetime.now()
        task_id = started_at.strftime("%Y%m%d%H%M%S%f")
        task_history = TaskHistory(local_settings.task_history_file) if mode == "crawl" else None
        if task_history:
            task_history.start(
                {
                    "id": task_id,
                    "mode": mode,
                    "started_at": started_at.isoformat(timespec="seconds"),
                    "filters": filter_summary,
                    "stats": asdict(CrawlStats(task_mode=mode, phase="running", running=True)),
                }
            )
        subject_entries = [(local_settings.subject_code, local_settings.subject_name)]
        if not local_settings.subject_code:
            subject_entries = list(
                fetch_subject_options().get(local_settings.study_phase_code, {}).items()
            )
        if not subject_entries:
            app_state.log("没有可用学科，请重启工具或检查网络后再试")
            failed_stats = CrawlStats(task_mode=mode, phase="finished", outcome="failed", failed=1)
            app_state.progress(failed_stats)
            if task_history:
                task_history.finish(
                    task_id,
                    {
                        "status": "failed",
                        "ended_at": datetime.now().isoformat(timespec="seconds"),
                        "duration_seconds": int((datetime.now() - started_at).total_seconds()),
                        "stats": asdict(failed_stats),
                    },
                )
            return

        aggregate = CrawlStats(
            task_mode=mode,
            phase="running",
            total_combos=len(subject_entries),
            running=True,
        )

        def emit_subject_progress(subject_index: int, subject_stats: CrawlStats) -> None:
            aggregate.total_combos = max(
                aggregate.total_combos,
                subject_stats.total_combos * len(subject_entries),
            )
            aggregate.completed_combos = (
                subject_index * subject_stats.total_combos + subject_stats.completed_combos
            )
            aggregate.resources_seen = previous.resources_seen + subject_stats.resources_seen
            aggregate.resources_total = previous.resources_total + subject_stats.resources_total
            aggregate.resources_completed = (
                previous.resources_completed + subject_stats.resources_completed
            )
            aggregate.current_resource_name = subject_stats.current_resource_name
            aggregate.images_downloaded = previous.images_downloaded + subject_stats.images_downloaded
            aggregate.paid_skipped = previous.paid_skipped + subject_stats.paid_skipped
            aggregate.preview_limited = previous.preview_limited + subject_stats.preview_limited
            aggregate.failed = previous.failed + subject_stats.failed
            aggregate.paused = subject_stats.paused
            aggregate.outcome = subject_stats.outcome
            app_state.progress(aggregate)

        previous = CrawlStats(task_mode=mode)
        app_state.progress(aggregate)
        for subject_index, (subject_code, subject_name) in enumerate(subject_entries):
            app_state.log(f"当前学科：{subject_name}")
            subject_settings = local_settings.model_copy(
                update={"subject_code": subject_code, "subject_name": subject_name}
            )
            runner = CrawlRunner(
                subject_settings,
                local_filters,
                on_log=app_state.log,
                on_record=lambda record: (
                    app_state.record(record),
                    task_history.record_resource(task_id, record) if task_history else None,
                ),
                on_progress=lambda stats, index=subject_index: emit_subject_progress(index, stats),
            )
            app_state.runner = runner
            try:
                subject_stats = runner.estimate() if mode == "estimate" else runner.run()
            except StzyApiError as exc:
                aggregate.failed += 1
                aggregate.outcome = "auth_expired" if exc.requires_login else "failed"
                if exc.requires_login:
                    app_state.log("登录态已失效，请在账号配置中重新登录后再开始任务")
                else:
                    app_state.log(f"接口请求失败：{exc.message}")
                break
            except Exception as exc:  # noqa: BLE001
                aggregate.failed += 1
                aggregate.outcome = "failed"
                app_state.log(f"任务异常：{exc}")
                break
            previous.resources_seen += subject_stats.resources_seen
            previous.resources_total += subject_stats.resources_total
            previous.resources_completed += subject_stats.resources_completed
            previous.images_downloaded += subject_stats.images_downloaded
            previous.paid_skipped += subject_stats.paid_skipped
            previous.preview_limited += subject_stats.preview_limited
            previous.failed += subject_stats.failed
            if subject_stats.paused:
                aggregate.paused = True
                aggregate.outcome = "paused"
                break
        aggregate.running = False
        aggregate.phase = "preview" if mode == "estimate" and not aggregate.failed else "finished"
        if not aggregate.outcome:
            if aggregate.paused:
                aggregate.outcome = "paused"
            elif aggregate.failed or aggregate.paid_skipped:
                aggregate.outcome = "partial"
            elif aggregate.preview_limited:
                aggregate.outcome = "partial"
            elif mode == "estimate":
                aggregate.outcome = "estimated"
            else:
                aggregate.outcome = "completed"
        app_state.progress(aggregate)
        if task_history:
            task_history.finish(
                task_id,
                {
                    "status": aggregate.outcome or "failed",
                    "ended_at": datetime.now().isoformat(timespec="seconds"),
                    "duration_seconds": int((datetime.now() - started_at).total_seconds()),
                    "stats": asdict(aggregate),
                },
            )
        if aggregate.paused:
            app_state.log("任务已暂停")
        elif aggregate.outcome == "auth_expired":
            app_state.log("任务结束：登录态已失效")
        elif mode == "estimate" and aggregate.failed:
            app_state.log(
                f"预估部分完成：匹配 {aggregate.resources_seen} 份，异常 {aggregate.failed} 个"
            )
        elif mode == "estimate":
            app_state.log(f"预估完成：匹配 {aggregate.resources_seen} 份试卷")
        elif aggregate.failed or aggregate.preview_limited:
            app_state.log(
                f"下载部分完成：匹配 {aggregate.resources_seen} 份，"
                f"下载图片 {aggregate.images_downloaded} 张，"
                f"付费不可用 {aggregate.paid_skipped} 份，"
                f"异常或未完整保存 {aggregate.failed + aggregate.preview_limited} 个"
            )
        else:
            app_state.log(
                f"下载完成：下载 {aggregate.images_downloaded} 张图片，"
                f"付费不可用 {aggregate.paid_skipped} 份"
            )

    async def start(mode: str) -> None:
        _, _, _, running = app_state.snapshot()
        if running:
            ui.notify("已有任务在运行", type="warning")
            return
        await refresh_remote_categories(notify_success=False, fail_block=False)
        local_settings = current_settings()
        local_filters = current_filters()
        filter_summary = current_filter_summary(local_settings, local_filters)
        label = "预估" if mode == "estimate" else "抓取"
        app_state.log(f"启动{label}任务")
        background_tasks.create(
            run.io_bound(run_crawler, mode, local_settings, local_filters, filter_summary),
            name=f"stzy-{mode}",
        )

    def stop() -> None:
        if app_state.runner:
            app_state.runner.stop()
            app_state.log("收到暂停请求，当前请求完成后暂停")

    async def login() -> None:
        ui.notify("浏览器将打开；登录完成后关闭该窗口保存 Cookie")
        local_settings = current_settings()
        try:
            await run.io_bound(capture_login_state, local_settings)
        except Exception as exc:  # noqa: BLE001
            app_state.log(f"登录态保存失败：{exc}")
            ui.notify("登录态保存失败，请重新登录", type="negative")
            return
        cookie_header = StzyHttpClient._load_cookie_header(local_settings.cookie_file)
        access_token = StzyHttpClient._load_access_token(local_settings.cookie_file)
        if not cookie_header and not access_token:
            app_state.log("没有捕获到 Cookie，请确认登录后再关闭浏览器窗口")
            ui.notify("没有捕获到登录态，请登录完成后再关闭窗口", type="warning")
            return
        account_label = StzyHttpClient.account_label_from_auth(
            cookie_header=cookie_header,
            access_token=access_token,
        )
        account_name_value = f"浏览器登录-{account_label}" if account_label else "浏览器登录"
        AccountPool(local_settings.account_pool_file).upsert(
            AccountCredential(
                name=account_name_value,
                cookie=cookie_header,
                access_token=access_token,
                enabled=True,
            )
        )
        refresh_accounts()
        app_state.log(f"登录态已保存：{account_name_value}")
        ui.notify(f"登录态已保存：{account_name_value}", type="positive")

    def account_pool_path() -> Path:
        return settings.account_pool_file

    def account_rows() -> list[dict[str, str]]:
        pool = AccountPool(account_pool_path())
        enabled_index = 0
        rows = []
        for account in pool.accounts:
            is_valid = StzyHttpClient.auth_is_valid(
                cookie_header=account.cookie,
                access_token=account.access_token,
            )
            order = "-"
            if account.usable and is_valid:
                enabled_index += 1
                order = str(enabled_index)
            display_name = account.name
            if account.name == "浏览器登录":
                label = StzyHttpClient.account_label_from_auth(
                    cookie_header=account.cookie,
                    access_token=account.access_token,
                )
                if label:
                    display_name = f"浏览器登录-{label}"
            expires_at = StzyHttpClient.auth_expires_at(
                cookie_header=account.cookie,
                access_token=account.access_token,
            )
            expires_text = (
                datetime.fromtimestamp(expires_at).strftime("%m-%d %H:%M")
                if expires_at
                else "-"
            )
            if not account.enabled:
                status_text = "停用"
            elif not is_valid:
                status_text = "登录态过期"
            else:
                status_text = "可用"
            rows.append(
                {
                    "order": order,
                    "name": display_name,
                    "account_key": account.name,
                    "enabled": status_text,
                    "expires": expires_text,
                    "auth": "Cookie + Token"
                    if account.cookie and account.access_token
                    else ("Cookie" if account.cookie else "Token"),
                }
            )
        return rows

    def refresh_accounts() -> None:
        account_table.rows = account_rows()
        account_table.update()

    def display_record_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
        labels = {
            "completed": "完成",
            "partial": "部分完成",
            "skipped_paid": "跳过付费",
            "paid_unavailable": "付费不可用",
            "failed": "失败",
            "pending": "等待中",
        }
        rows = []
        for record in records:
            row = dict(record)
            status = str(row.get("status") or "")
            row["status_label"] = labels.get(status, status or "-")
            row["error_text"] = str(row.get("error") or "")
            rows.append(row)
        return rows

    def save_account() -> None:
        name = str(account_name.value or "").strip()
        if not name:
            ui.notify("请填写账号名称", type="warning")
            return
        if not account_cookie.value and not account_token.value:
            ui.notify("请填写 Cookie 或 Token", type="warning")
            return
        pool = AccountPool(account_pool_path())
        pool.upsert(
            AccountCredential(
                name=name,
                cookie=str(account_cookie.value or "").strip(),
                access_token=str(account_token.value or "").strip(),
                enabled=bool(account_enabled.value),
            )
        )
        account_name.value = ""
        account_cookie.value = ""
        account_token.value = ""
        refresh_accounts()
        ui.notify("账号已保存", type="positive")

    def remove_named_account(name: str) -> None:
        if not name:
            return
        AccountPool(account_pool_path()).remove(name)
        refresh_accounts()
        ui.notify("账号已删除")

    def toggle_account(name: str) -> None:
        pool = AccountPool(account_pool_path())
        for account in pool.accounts:
            if account.name == name:
                account.enabled = not account.enabled
                pool.save()
                refresh_accounts()
                ui.notify("账号状态已更新")
                return

    def handle_account_action(event) -> None:
        payload = event.args or {}
        action = payload.get("action")
        name = str(payload.get("account_key") or payload.get("name") or "")
        if action == "toggle":
            toggle_account(name)
        elif action == "delete":
            remove_named_account(name)

    def set_output_dir(path: Path) -> None:
        output_dir.value = str(path)
        output_dir.update()
        refresh_accounts()

    async def choose_output_dir() -> None:
        selected_dir = await run.io_bound(choose_directory, Path(output_dir.value))
        if selected_dir:
            set_output_dir(selected_dir)

    def open_account_dialog() -> None:
        refresh_accounts()
        account_dialog.open()

    def open_directory(path_value: str | Path) -> None:
        path = Path(path_value)
        if open_path(path):
            return
        ui.notify("目录不存在", type="warning")

    def preview_directory(path_value: str | Path) -> None:
        path = Path(path_value)
        if preview_first_file(path):
            return
        ui.notify("暂无可预览图片", type="warning")

    def latest_completed_dir() -> str:
        _, records, _, _ = app_state.snapshot()
        for record in records:
            if record.get("status") in {"completed", "partial"} and record.get("local_dir"):
                return str(record["local_dir"])
        return ""

    def open_output_dir() -> None:
        open_directory(output_dir.value)

    def preview_latest() -> None:
        local_dir = latest_completed_dir()
        if not local_dir:
            ui.notify("暂无已下载资源", type="warning")
            return
        preview_directory(local_dir)

    def handle_resource_action(event) -> None:
        payload = event.args or {}
        action = payload.get("action")
        local_dir = str(payload.get("local_dir") or "")
        if not local_dir:
            ui.notify("暂无本地目录", type="warning")
            return
        if action == "preview":
            preview_directory(local_dir)
        elif action == "open":
            open_directory(local_dir)

    def handle_task_action(event) -> None:
        payload = event.args or {}
        local_dir = str(payload.get("local_dir") or "")
        if not local_dir:
            ui.notify("暂无下载路径", type="warning")
            return
        open_directory(local_dir)

    def keep_or_reset(control, fallback: str = ALL_VALUE, *, reset: bool = True) -> None:
        if reset or control.value not in control.options:
            control.value = fallback if fallback in control.options else next(iter(control.options), "")
        control.update()

    def refresh_filter_options(*, reset: bool = True) -> None:
        subject_select.options = current_subject_options()
        keep_or_reset(subject_select, ALL_VALUE, reset=reset)
        scene_select.options = options("sceneCode")
        year_select.options = options("yearCode")
        province_select.options = options("provinceCode")
        grade_select.options = options("gradeCode")
        term_select.options = options("termCode")
        for control in [scene_select, year_select, province_select, grade_select, term_select]:
            keep_or_reset(control, reset=reset)
        rank_select.options = options("rank")
        keep_or_reset(rank_select, ALL_VALUE, reset=reset)
        try:
            quick_phase_select.value = study_phase.value
            quick_subject_select.options = current_subject_options()
            quick_province_select.options = options("provinceCode")
            quick_term_select.options = options("termCode")
            quick_scene_select.options = options("sceneCode")
            for control in [
                quick_subject_select,
                quick_province_select,
                quick_term_select,
                quick_scene_select,
            ]:
                keep_or_reset(control, ALL_VALUE, reset=reset)
            quick_phase_select.update()
        except NameError:
            pass

    def find_option_value(control, label: str) -> str:
        target = label.strip().replace("市", "")
        for value, option_label in control.options.items():
            normalized = str(option_label).strip().replace("市", "")
            if normalized == target:
                return str(value)
        return ""

    def apply_quick_filter() -> None:
        if (
            quick_subject_select.value == ALL_VALUE
            and quick_province_select.value == ALL_VALUE
            and quick_term_select.value == ALL_VALUE
            and quick_scene_select.value == ALL_VALUE
        ):
            ui.notify("请选择快速筛选条件", type="warning")
            return

        study_phase.value = quick_phase_select.value
        subject_select.value = quick_subject_select.value
        province_select.value = quick_province_select.value
        term_select.value = quick_term_select.value
        scene_select.value = quick_scene_select.value
        if quick_term_select.value != ALL_VALUE:
            term_label = str(quick_term_select.options.get(quick_term_select.value, ""))
            grade_name = term_label[:-1] if term_label.endswith(("上", "下")) else term_label
            grade_value = find_option_value(grade_select, grade_name)
            grade_select.value = grade_value or ALL_VALUE

        for control in [
            study_phase,
            subject_select,
            scene_select,
            province_select,
            grade_select,
            term_select,
        ]:
            control.update()
        ui.notify("快速筛选已应用", type="positive")

    def change_quick_phase() -> None:
        study_phase.value = quick_phase_select.value
        refresh_filter_options(reset=True)
        study_phase.update()

    async def refresh_remote_categories(
        *, notify_success: bool = True, fail_block: bool = True
    ) -> bool:
        nonlocal catalogs, subject_options
        try:
            new_subject_options, new_catalogs = await run.io_bound(
                lambda: (fetch_subject_options(), fetch_tag_catalogs())
            )
        except Exception as exc:  # noqa: BLE001
            app_state.log(f"同步分类失败：{exc}")
            if fail_block:
                ui.notify("同步分类失败，请稍后再试", type="negative")
            else:
                ui.notify("分类自动同步失败，继续使用当前分类", type="warning")
            return not fail_block
        subject_options = new_subject_options
        catalogs = new_catalogs
        refresh_filter_options(reset=False)
        app_state.log("分类已从远端同步")
        if notify_success:
            ui.notify("分类已同步", type="positive")
        return True

    def make_filter_toggle(label: str, options_map: dict[str, str], value: str, on_change=None):
        with ui.element("div").classes("filter-row"):
            ui.label(label).classes("filter-row-label")
            control = ui.toggle(
                options_map,
                value=value,
                on_change=on_change,
            ).classes("filter-toggle")
            control.props("flat no-caps")
        return control

    with ui.column().classes("stzy-shell w-full gap-0"):
        with ui.row().classes("topbar w-full items-center"):
            with ui.row().classes("topbar-inner items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("试卷图片下载").classes("text-lg font-semibold")
                    ui.label("本地下载工具").classes("muted text-xs")
                with ui.row().classes("items-center gap-2"):
                    with ui.row().classes("topbar-path items-center gap-1"):
                        output_dir = ui.input(
                            "保存位置",
                            value=str(settings.output_dir),
                        ).classes("topbar-path-input")
                        ui.button(
                            icon="folder_open",
                            on_click=choose_output_dir,
                        ).classes("topbar-path-button").props("flat round dense")
                    ui.button("采集策略", icon="speed", on_click=lambda: strategy_dialog.open()).props(
                        "flat no-caps"
                    )
                    ui.button("账号配置", icon="manage_accounts", on_click=open_account_dialog).props(
                        "flat no-caps"
                    )
                    status_label = ui.label("等待").classes("status-pill")

        with ui.column().classes("main-wrap gap-4 py-5"):
            with ui.element("div").classes("workbench"):
                with ui.column().classes("left-stack gap-4"):
                    with ui.column().classes("panel filter-panel p-5 gap-5"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("筛选条件").classes("section-title")
                            ui.label("不选表示不限").classes("muted text-xs")
                        with ui.element("div").classes("quick-filter"):
                            with ui.row().classes("quick-filter-head w-full items-center justify-between"):
                                ui.label("快速筛选").classes("quick-filter-title")
                            with ui.element("div").classes("quick-filter-fields"):
                                quick_phase_select = ui.select(
                                    STUDY_PHASES,
                                    label="学段",
                                    value=DEFAULT_STUDY_PHASE_CODE,
                                    on_change=change_quick_phase,
                                ).classes("quick-filter-input")
                                quick_subject_select = ui.select(
                                    {ALL_VALUE: "学科不限", **subject_options.get(DEFAULT_STUDY_PHASE_CODE, {})},
                                    label="学科",
                                    value=ALL_VALUE,
                                ).classes("quick-filter-input")
                                quick_province_select = ui.select(
                                    {ALL_VALUE: "地区不限"},
                                    label="地区",
                                    value=ALL_VALUE,
                                ).classes("quick-filter-input")
                                quick_term_select = ui.select(
                                    {ALL_VALUE: "年级学期不限"},
                                    label="年级学期",
                                    value=ALL_VALUE,
                                ).classes("quick-filter-input")
                                quick_scene_select = ui.select(
                                    {ALL_VALUE: "场景不限"},
                                    label="场景",
                                    value=ALL_VALUE,
                                ).classes("quick-filter-input")
                                ui.button("应用", icon="bolt", on_click=apply_quick_filter).classes(
                                    "quick-filter-button"
                                ).props("unelevated no-caps color=primary")
                        with ui.expansion("高级筛选").classes("filter-more advanced-filter w-full"):
                            with ui.element("div").classes("filter-list"):
                                study_phase = make_filter_toggle(
                                    "学段",
                                    STUDY_PHASES,
                                    value=DEFAULT_STUDY_PHASE_CODE,
                                    on_change=lambda: refresh_filter_options(reset=True),
                                )
                                subject_select = make_filter_toggle(
                                    "学科",
                                    {ALL_VALUE: "不限", **subject_options.get(DEFAULT_STUDY_PHASE_CODE, {})},
                                    value=ALL_VALUE,
                                    on_change=lambda: refresh_filter_options(reset=False),
                                )
                                scene_select = make_filter_toggle(
                                    "场景",
                                    {ALL_VALUE: "不限"},
                                    value=ALL_VALUE,
                                )
                                year_select = make_filter_toggle(
                                    "年份",
                                    {ALL_VALUE: "不限"},
                                    value=ALL_VALUE,
                                )
                                rank_select = make_filter_toggle(
                                    "等级",
                                    {ALL_VALUE: "不限"},
                                    value=ALL_VALUE,
                                )
                                province_select = make_filter_toggle(
                                    "地区",
                                    {ALL_VALUE: "不限"},
                                    value=ALL_VALUE,
                                )
                                grade_select = make_filter_toggle(
                                    "年级",
                                    {ALL_VALUE: "不限"},
                                    value=ALL_VALUE,
                                )
                                term_select = make_filter_toggle(
                                    "学期",
                                    {ALL_VALUE: "不限"},
                                    value=ALL_VALUE,
                                )
                        refresh_filter_options(reset=True)

                        with ui.element("div").classes("download-section task-control-panel"):
                            with ui.row().classes("task-control-head w-full items-center justify-between"):
                                ui.label("任务操作").classes("task-control-title")
                                action_context = ui.label("当前筛选：不限").classes("task-context")
                            with ui.element("div").classes("action-grid"):
                                estimate_button = ui.button(
                                    "预估",
                                    icon="analytics",
                                    on_click=lambda: start("estimate"),
                                ).classes(
                                    "secondary-action"
                                ).props("outline no-caps")
                                download_button = ui.button(
                                    "开始下载",
                                    icon="download",
                                    on_click=lambda: start("crawl"),
                                ).classes(
                                    "primary-action"
                                ).props("unelevated no-caps color=primary")
                                pause_button = ui.button("暂停", icon="pause", on_click=stop).classes(
                                    "secondary-action"
                                ).props("outline no-caps")
                                pause_button.disable()
                            action_hint = ui.label("先预估确认数量，再开始下载；下载结果会进入历史任务。").classes(
                                "task-action-hint"
                            )

                    with ui.column().classes("panel history-panel p-5 gap-3"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("历史任务").classes("section-title")
                            ui.label("只记录下载任务").classes("muted text-xs")
                        task_columns = [
                            {"name": "started_at", "label": "时间", "field": "started_at"},
                            {
                                "name": "brief",
                                "label": "筛选",
                                "field": "brief",
                                "align": "left",
                            },
                            {"name": "status_label", "label": "状态", "field": "status_label"},
                            {"name": "resources_seen", "label": "试卷", "field": "resources_seen"},
                            {"name": "images_downloaded", "label": "图片", "field": "images_downloaded"},
                            {"name": "actions", "label": "操作", "field": "actions", "align": "right"},
                        ]
                        task_table = ui.table(columns=task_columns, rows=[], row_key="id").classes(
                            "compact-table task-history-table w-full"
                        )
                        task_table.props('flat bordered dense no-data-label="暂无下载任务记录"')
                        task_table.on("task-action", handle_task_action)
                        task_table.add_slot(
                            "body-cell-actions",
                            """
                            <q-td :props="props">
                              <q-btn
                                dense flat no-caps size="sm"
                                icon="folder_open"
                                label="打开"
                                @click="$parent.$emit('task-action', {
                                  local_dir: props.row.local_dir
                                })"
                              />
                            </q-td>
                            """,
                        )

                with ui.column().classes("panel progress-panel p-5 gap-4"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("任务状态").classes("section-title")
                        summary = ui.label("").classes("muted text-sm")
                    status_overview = ui.html(
                        '<div class="status-overview status-idle">'
                        '<div><div class="status-stage">预览</div>'
                        '<div class="status-detail">等待预估或开始下载</div></div>'
                        '<strong>0</strong></div>'
                    ).classes("w-full")
                    with ui.element("div").classes("task-progress-wrap w-full"):
                        progress = ui.linear_progress(value=0, show_value=False).classes(
                            "w-full task-progress"
                        )
                        progress_text = ui.label("0%").classes("task-progress-label")

                    with ui.element("div").classes("metric-grid"):
                        combo_metric = ui.html(
                            '<div class="metric"><div class="metric-value">0/0</div>'
                            '<div class="metric-label">条件组合</div></div>'
                        )
                        resource_metric = ui.html(
                            '<div class="metric"><div class="metric-value">0</div>'
                            '<div class="metric-label">匹配试卷</div></div>'
                        )
                        image_metric = ui.html(
                            '<div class="metric"><div class="metric-value">0</div>'
                            '<div class="metric-label">已下载图片</div></div>'
                        )
                        skipped_metric = ui.html(
                            '<div class="metric"><div class="metric-value">0</div>'
                            '<div class="metric-label">跳过付费</div></div>'
                        )

                    with ui.row().classes("current-result-head w-full items-center justify-between"):
                        ui.label("当前结果").classes("subsection-title")
                        current_result_tip = ui.label("显示本次下载生成的资源").classes("muted text-xs")

                    columns = [
                        {
                            "name": "resource_name",
                            "label": "最近下载",
                            "field": "resource_name",
                            "align": "left",
                        },
                        {"name": "image_count", "label": "图片", "field": "image_count"},
                        {"name": "status_label", "label": "状态", "field": "status_label"},
                        {"name": "actions", "label": "操作", "field": "actions", "align": "right"},
                    ]
                    table = ui.table(columns=columns, rows=[], row_key="resource_id").classes(
                        "compact-table w-full"
                    )
                    table.props('flat bordered dense no-data-label="还没有下载记录"')
                    table.on("resource-action", handle_resource_action)
                    table.add_slot(
                        "body-cell-status_label",
                        """
                        <q-td :props="props">
                          <div :class="'record-status record-status-' + props.row.status">
                            {{ props.row.status_label }}
                          </div>
                          <div v-if="props.row.error_text" class="record-error">
                            {{ props.row.error_text }}
                          </div>
                        </q-td>
                        """,
                    )
                    table.add_slot(
                        "body-cell-actions",
                        """
                        <q-td :props="props">
                          <q-btn
                            dense flat no-caps size="sm" label="预览"
                            @click="$parent.$emit('resource-action', {
                              action: 'preview',
                              local_dir: props.row.local_dir
                            })"
                          />
                          <q-btn
                            dense flat no-caps size="sm" label="打开"
                            @click="$parent.$emit('resource-action', {
                              action: 'open',
                              local_dir: props.row.local_dir
                            })"
                          />
                        </q-td>
                        """,
                    )

                    with ui.element("div").classes("status-action-grid"):
                        ui.button("预览最近", icon="visibility", on_click=preview_latest).classes(
                            "secondary-action"
                        ).props("outline no-caps")
                        ui.button("打开目录", icon="folder_open", on_click=open_output_dir).classes(
                            "secondary-action"
                        ).props("outline no-caps")

                    with ui.column().classes("runtime-log w-full gap-2"):
                        with ui.row().classes("runtime-log-head w-full items-center justify-between"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon("subject").classes("muted")
                                ui.label("运行日志").classes("font-medium")
                            ui.button("清空", icon="delete_sweep", on_click=app_state.clear_logs).props(
                                "flat dense no-caps"
                            )
                        log_label = ui.html("").classes("log-box w-full")

    with ui.dialog() as strategy_dialog, ui.card().classes("modal-card gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("采集策略").classes("section-title")
            ui.button(icon="close", on_click=strategy_dialog.close).props("flat round dense")
        with ui.element("div").classes("settings-grid"):
            file_type = ui.select(
                {"PDF": "PDF", "IMG": "图片"},
                label="类型",
                value=str(strategy_settings.get("file_type") or "PDF"),
            ).classes("w-full")
            max_pages = ui.number(
                "每组合最多页数",
                value=strategy_settings.get("max_pages_per_combo"),
                min=1,
                step=1,
            ).classes("w-full")
            image_delay = ui.number(
                "图片间隔",
                value=numeric_value(
                    strategy_settings.get("image_delay_seconds"),
                    settings.image_delay_seconds,
                ),
                min=0.1,
                step=0.1,
                suffix="秒",
            ).classes("w-full")
            list_delay = ui.number(
                "请求间隔",
                value=numeric_value(
                    strategy_settings.get("list_delay_seconds"),
                    settings.list_delay_seconds,
                ),
                min=0.3,
                step=0.1,
                suffix="秒/次",
            ).classes("w-full")
            concurrency = ui.number(
                "并发",
                value=int(numeric_value(strategy_settings.get("concurrency"), settings.concurrency)),
                min=1,
                max=3,
                step=1,
            ).classes("w-full")
        ui.label("完整优先：10 页内保存预览图，超过 10 页直接下载 PDF 转图。").classes(
            "muted text-sm"
        )

        def save_strategy() -> None:
            saved = {
                "file_type": file_type.value or "PDF",
                "max_pages_per_combo": int(max_pages.value) if max_pages.value else None,
                "image_delay_seconds": float(image_delay.value or settings.image_delay_seconds),
                "list_delay_seconds": float(list_delay.value or settings.list_delay_seconds),
                "concurrency": int(concurrency.value or settings.concurrency),
            }
            preferences.set("strategy", saved)
            app_state.log("采集策略已保存")
            ui.notify("采集策略已保存，后续任务会使用新设置", type="positive")
            strategy_dialog.close()

        ui.button("保存", on_click=save_strategy).classes("dialog-primary").props(
            "unelevated no-caps color=primary"
        )

    with ui.dialog() as account_dialog, ui.card().classes("modal-card gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("账号配置").classes("section-title")
            ui.button(icon="close", on_click=account_dialog.close).props("flat round dense")
        ui.label("启用账号会按顺序轮询使用。").classes("muted text-sm")
        account_columns = [
            {"name": "order", "label": "轮询", "field": "order", "align": "center"},
            {"name": "name", "label": "账号", "field": "name", "align": "left"},
            {"name": "enabled", "label": "状态", "field": "enabled"},
            {"name": "expires", "label": "过期时间", "field": "expires"},
            {"name": "auth", "label": "凭证", "field": "auth"},
            {"name": "actions", "label": "操作", "field": "actions", "align": "right"},
        ]
        account_table = ui.table(columns=account_columns, rows=[], row_key="name").classes(
            "compact-table account-table w-full"
        )
        account_table.props('flat bordered dense no-data-label="暂无账号"')
        account_table.on("account-action", handle_account_action)
        account_table.add_slot(
            "body-cell-actions",
            """
            <q-td :props="props">
              <q-btn
                dense flat no-caps size="sm"
                :label="props.row.enabled === '停用' ? '启用' : '停用'"
                @click="$parent.$emit('account-action', {
                  action: 'toggle',
                  account_key: props.row.account_key
                })"
              />
              <q-btn
                dense flat no-caps size="sm" color="negative" label="删除"
                @click="$parent.$emit('account-action', {
                  action: 'delete',
                  account_key: props.row.account_key
                })"
              />
            </q-td>
            """,
        )
        with ui.element("div").classes("account-form"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("新增账号").classes("section-title")
                account_enabled = ui.checkbox("启用", value=True).classes("account-enabled")
            account_name = ui.input("账号名称", placeholder="例如：主账号").classes("w-full")
            with ui.element("div").classes("credential-grid"):
                account_cookie = ui.textarea(
                    "Cookie",
                    placeholder="粘贴浏览器 Cookie；也可以直接点击下方登录获取",
                ).props("autogrow outlined").classes("w-full credential-input")
                account_token = ui.input(
                    "Access Token",
                    placeholder="可选；有 Token 时优先使用",
                ).props("type=password outlined").classes("w-full")
            with ui.row().classes("account-actions w-full items-center justify-between"):
                ui.button("登录获取 Cookie", icon="login", on_click=login).classes(
                    "secondary-action"
                ).props("outline no-caps")
                with ui.row().classes("items-center gap-2"):
                    ui.button("清空输入", icon="backspace", on_click=lambda: (
                        account_name.set_value(""),
                        account_cookie.set_value(""),
                        account_token.set_value(""),
                    )).props("flat no-caps")
                    ui.button("保存账号", icon="save", on_click=save_account).classes(
                        "primary-action"
                    ).props("unelevated no-caps color=primary")

    def refresh() -> None:
        logs, records, stats, running = app_state.snapshot()
        view = status_view(stats, running)
        stage_text = str(view["stage"])
        detail_text = str(view["detail"])
        status_class = str(view["class"])
        headline_count = str(view["count"])
        filter_brief = current_filter_summary(current_settings(), current_filters())["brief"]
        action_context.set_text(f"当前筛选：{filter_brief}")
        status_label.set_text(stage_text)
        if running:
            estimate_button.disable()
            download_button.disable()
            pause_button.enable()
            action_hint.set_text("任务正在运行，当前请求完成后可以暂停。")
        else:
            estimate_button.enable()
            download_button.enable()
            pause_button.disable()
            if stats.task_mode == "estimate" and stats.outcome == "estimated":
                action_hint.set_text(f"预估找到 {stats.resources_seen} 份试卷，可以开始下载。")
            elif stats.task_mode == "crawl" and stats.phase == "finished":
                action_hint.set_text("下载任务已结束，可在历史任务打开对应目录。")
            else:
                action_hint.set_text("先预估确认数量，再开始下载；下载结果会进入历史任务。")
        if running and stats.task_mode == "crawl":
            resource_total = stats.resources_total or stats.resources_seen
            progress_value = (
                min(1, stats.resources_completed / resource_total)
                if resource_total
                else 0
            )
        elif stats.task_mode == "crawl" and stats.phase == "finished":
            progress_value = 1 if stats.resources_seen or stats.resources_total else 0
        else:
            progress_value = stats.completed_combos / stats.total_combos if stats.total_combos else 0
        progress.value = progress_value
        progress_text.set_text(progress_percent_text(progress_value))
        summary.set_text(detail_text)
        resource_total = stats.resources_total or stats.resources_seen
        if stats.task_mode == "crawl":
            combo_value = f"{stats.resources_completed}/{resource_total}" if resource_total else "0/0"
            combo_label = "试卷进度"
        else:
            combo_value = f"{stats.completed_combos}/{stats.total_combos}"
            combo_label = "条件组合"
        combo_metric.set_content(
            f'<div class="metric"><div class="metric-value">{combo_value}</div>'
            f'<div class="metric-label">{combo_label}</div></div>'
        )
        status_overview.set_content(
            f'<div class="status-overview status-{status_class}">'
            f'<div><div class="status-stage">{stage_text}</div>'
            f'<div class="status-detail">{detail_text}</div></div>'
            f'<strong>{headline_count}</strong></div>'
        )
        resource_label = "预估试卷" if stats.task_mode == "estimate" else "匹配试卷"
        resource_value = stats.resources_seen
        if stats.task_mode == "crawl" and stats.resources_total:
            resource_value = stats.resources_total
        image_label = "未下载图片" if stats.task_mode == "estimate" else "已下载图片"
        if stats.task_mode == "estimate":
            skipped_value = str(stats.paid_skipped)
            skipped_label = "预估不下载付费"
        else:
            skipped_value = f"{stats.paid_skipped}/{stats.preview_limited}"
            skipped_label = "付费不可用/部分完成"
        resource_metric.set_content(
            f'<div class="metric"><div class="metric-value">{resource_value}</div>'
            f'<div class="metric-label">{resource_label}</div></div>'
        )
        image_metric.set_content(
            f'<div class="metric"><div class="metric-value">{stats.images_downloaded}</div>'
            f'<div class="metric-label">{image_label}</div></div>'
        )
        skipped_metric.set_content(
            f'<div class="metric"><div class="metric-value">{skipped_value}</div>'
            f'<div class="metric-label">{skipped_label}</div></div>'
        )
        no_data_label = "预估不会生成下载记录" if stats.task_mode == "estimate" else "还没有下载记录"
        current_result_tip.set_text(
            "预估只更新匹配数量，不生成下载记录"
            if stats.task_mode == "estimate"
            else "显示本次下载生成的资源"
        )
        table.props(f'no-data-label="{no_data_label}"')
        table_records = [] if stats.task_mode == "estimate" else records
        table.rows = display_record_rows(table_records)
        table.update()
        task_table.rows = display_task_rows(TaskHistory(task_history_path()).recent(20, mode="crawl"))
        task_table.update()
        escaped = [line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for line in logs]
        log_label.set_content("<br>".join(escaped[-120:]) or "等待任务启动")

    ui.timer(0.8, refresh)
    refresh_filter_options()
