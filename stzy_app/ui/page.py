from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from nicegui import background_tasks, run, ui

from stzy_app.auth import (
    COOKIE_TOKEN_CONSOLE_SCRIPT,
    credential_from_auth_import,
    login_with_phone_password,
)
from stzy_app.config import AppSettings, settings
from stzy_app.crawler import CrawlRunner, CrawlStats, TagCatalog
from stzy_app.http import (
    StzyApiError,
    StzyHttpClient,
)
from stzy_app.models import CrawlFilters
from stzy_app.proxy import (
    create_proxy_provider,
    current_public_ip,
    infer_proxy_provider,
    normalize_proxy_url,
)
from stzy_app.storage import AccountCredential, AccountPool, Preferences, TaskHistory
from stzy_app.ui.catalogs import (
    ALL_VALUE,
    DEFAULT_STUDY_PHASE_CODE,
    STUDY_PHASES,
    load_catalog_cache,
    save_catalog_cache,
    fetch_subject_options,
    fetch_tag_catalogs,
)
from stzy_app.ui.file_actions import open_path, preview_first_file
from stzy_app.ui.folder_picker import choose_directory
from stzy_app.ui.state import UiState
from stzy_app.ui.style import LIGHT_THEME_CSS
from stzy_app.ui.view_model import (
    action_hint,
    combo_metric as build_combo_metric,
    current_result_empty_copy,
    display_record_rows,
    display_task_rows,
    download_action_text,
    image_metric as build_image_metric,
    issue_metric as build_issue_metric,
    log_level_counts,
    progress_percent_text,
    progress_value as build_progress_value,
    render_log_lines,
    resource_metric as build_resource_metric,
    status_view,
)

def build_ui() -> None:
    app_state = UiState()
    ui.add_head_html(f"<style>{LIGHT_THEME_CSS}</style>")

    def notify(message: str, **kwargs) -> None:
        kwargs.setdefault("position", "top")
        ui.notify(message, **kwargs)

    preferences = Preferences(settings.task_history_file)
    strategy_settings = preferences.get("strategy")
    subject_options, catalogs, catalog_cache_updated_at = load_catalog_cache(preferences)
    if catalog_cache_updated_at:
        app_state.log(f"分类缓存已加载：{catalog_cache_updated_at}")
    else:
        app_state.log("分类缓存为空，可手动刷新")
    history_page = 1
    history_page_size = 10
    managed_history_task: dict[str, object] | None = None
    unfinished_task_statuses = {"running", "paused"}
    terminal_task_statuses = {"completed", "partial", "failed", "auth_expired"}

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

    def normalized_proxy_mode(raw_settings: dict[str, object]) -> str:
        mode = str(raw_settings.get("proxy_mode") or "").strip().lower()
        if mode in {"off", "fixed", "api"}:
            return mode
        return "off"

    def normalized_proxy_provider(raw_settings: dict[str, object]) -> str:
        return infer_proxy_provider(raw_settings.get("proxy_provider"))

    def proxy_status_text(raw_settings: dict[str, object]) -> str:
        mode = normalized_proxy_mode(raw_settings)
        if mode == "off":
            return "未启用"
        if mode == "api":
            return "待获取" if str(raw_settings.get("proxy_api_url") or "").strip() else "未配置"
        proxy = first_fixed_proxy(raw_settings.get("proxy_pool"))
        return proxy if proxy else "未配置"

    def first_fixed_proxy(value: object) -> str:
        for line in str(value or "").splitlines():
            proxy = normalize_proxy_url(line)
            if not proxy:
                continue
            parsed = urlparse(proxy)
            if parsed.hostname:
                return parsed.hostname
            return proxy
        return ""

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
            concurrency=int(concurrency.value or settings.concurrency),
            proxy_mode=str(proxy_mode.value or "off"),
            proxy_provider=str(proxy_provider.value or settings.proxy_provider),
            proxy_pool=str(proxy_pool.value or "").strip(),
            proxy_api_url=str(proxy_api_url.value or "").strip(),
            shenlong_whitelist_key=str(shenlong_whitelist_key.value or "").strip(),
            shenlong_whitelist_sign=str(shenlong_whitelist_sign.value or "").strip(),
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

    def run_crawler(
        mode: str,
        local_settings: AppSettings,
        local_filters: CrawlFilters,
        filter_summary: dict[str, str],
        subject_entries: list[tuple[str, str]],
        resume_task_id: str | None = None,
    ) -> None:
        started_at = datetime.now()
        task_id = resume_task_id or started_at.strftime("%Y%m%d%H%M%S%f")
        task_history = TaskHistory(local_settings.task_history_file) if mode == "crawl" else None
        completed_resource_ids: set[str] = set()
        if task_history:
            initial_stats = asdict(CrawlStats(task_mode=mode, phase="running", running=True))
            if resume_task_id:
                completed_resource_ids = task_history.completed_resource_ids(task_id)
                task_history.resume(task_id, initial_stats)
                app_state.log(f"继续未结束任务：跳过已完成资源 {len(completed_resource_ids)} 份")
            else:
                task_history.start(
                    {
                        "id": task_id,
                        "mode": mode,
                        "started_at": started_at.isoformat(timespec="seconds"),
                        "filters": filter_summary,
                        "stats": initial_stats,
                    }
                )
        if not subject_entries and local_settings.subject_code:
            subject_entries = [(local_settings.subject_code, local_settings.subject_name)]
        if not subject_entries:
            app_state.log("没有可用学科，请刷新分类后再试")
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
                on_proxy=app_state.proxy,
                completed_resource_ids=completed_resource_ids,
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
        nonlocal managed_history_task
        _, _, _, running, _ = app_state.snapshot()
        if running:
            notify("已有任务在运行", type="warning")
            return
        local_settings = current_settings()
        if not await prepare_proxy_provider(local_settings, notify_success=False):
            return
        local_filters = current_filters()
        subject_entries = (
            [(local_settings.subject_code, local_settings.subject_name)]
            if local_settings.subject_code
            else list(subject_options.get(local_settings.study_phase_code, {}).items())
        )
        filter_summary = current_filter_summary(local_settings, local_filters)
        task_filter_summary = dict(filter_summary)
        task_filter_summary["_settings"] = {
            "output_dir": str(local_settings.output_dir),
            "study_phase_code": local_settings.study_phase_code,
            "subject_code": local_settings.subject_code,
            "proxy_mode": local_settings.proxy_mode,
            "proxy_provider": local_settings.proxy_provider,
            "proxy_pool": local_settings.proxy_pool,
            "proxy_api_url": local_settings.proxy_api_url,
            "shenlong_whitelist_key": local_settings.shenlong_whitelist_key,
            "shenlong_whitelist_sign": local_settings.shenlong_whitelist_sign,
        }
        task_filter_summary["_filters"] = asdict(local_filters)
        resume_task_id = None
        if mode == "crawl" and managed_history_task:
            task_status = str(managed_history_task.get("status") or "")
            task_id = str(managed_history_task.get("id") or "")
            if task_status in unfinished_task_statuses and task_id:
                resume_task_id = task_id
            else:
                managed_history_task = None
        else:
            managed_history_task = None
        label = "预估" if mode == "estimate" else "抓取"
        app_state.log(f"{'继续' if resume_task_id else '启动'}{label}任务")
        background_tasks.create(
            run.io_bound(
                run_crawler,
                mode,
                local_settings,
                local_filters,
                task_filter_summary,
                subject_entries,
                resume_task_id,
            ),
            name=f"stzy-{mode}",
        )

    def stop() -> None:
        if app_state.runner:
            app_state.runner.stop()
            app_state.log("收到暂停请求，当前请求完成后暂停")

    async def phone_login() -> None:
        phone = str(account_phone.value or "").strip()
        password = str(account_password.value or "").strip()
        if not phone:
            notify("请填写手机号", type="warning")
            return
        local_settings = current_settings()
        try:
            credential = await run.io_bound(login_with_phone_password, local_settings, phone, password)
        except Exception as exc:  # noqa: BLE001
            app_state.log(f"手机号登录失败：{exc}")
            notify(f"手机号登录失败：{exc}", type="negative")
            return
        AccountPool(local_settings.account_pool_file).upsert(credential)
        account_phone.value = ""
        account_password.value = ""
        refresh_accounts()
        app_state.log(f"手机号登录成功：{credential.name}")
        notify(f"手机号登录成功：{credential.name}", type="positive")

    def account_pool_path() -> Path:
        return settings.account_pool_file

    def account_rows() -> list[dict[str, str]]:
        pool = AccountPool(account_pool_path())
        enabled_index = 0
        rows = []
        for account in pool.accounts:
            display_name = account.name
            can_auto_login = bool(account.login_phone)
            token_locally_valid = StzyHttpClient.auth_is_valid(
                cookie_header=account.cookie,
                access_token=account.access_token,
            )
            is_valid = bool(account.enabled and account.usable and token_locally_valid)

            order = "-"
            if is_valid:
                enabled_index += 1
                order = str(enabled_index)
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
            elif account.in_cooldown:
                status_text = "冷却中"
            elif is_valid:
                status_text = "可用"
            elif account.cookie and not token_locally_valid and not can_auto_login:
                status_text = "失效"
            elif account.cookie and not token_locally_valid:
                status_text = "需刷新"
            else:
                status_text = "失效"
            quota_parts = []
            if account.last_price is not None:
                quota_parts.append(f"实付 {account.last_price:g}")
            if account.surplus_num is not None:
                quota_parts.append(f"余 {account.surplus_num}")
            rows.append(
                {
                    "order": order,
                    "name": display_name,
                    "account_key": account.name,
                    "enabled": status_text,
                    "type": account.account_type_label,
                    "quota": " / ".join(quota_parts) or "-",
                    "health": account.health_label,
                    "expires": expires_text,
                    "auth": account_auth_label(account),
                }
            )
        return rows

    def account_auth_label(account: AccountCredential) -> str:
        if account.login_phone:
            return "手机号"
        if account.import_method == "network_fetch":
            return "Network fetch"
        if account.import_method == "network_curl":
            return "Network cURL"
        if account.import_method == "token":
            return "Token"
        if account.cookie and account.access_token:
            return "Cookie + Token"
        return "Cookie" if account.cookie else "Token"

    @ui.refreshable
    def account_list() -> None:
        rows = account_rows()
        with ui.element("div").classes("account-list"):
            if not rows:
                with ui.element("div").classes("account-empty"):
                    ui.icon("person_add").classes("account-empty-icon")
                    ui.label("暂无账号").classes("account-empty-title")
                    ui.label("可使用手机号登录，或在高级导入里粘贴 Token。").classes(
                        "muted text-sm"
                    )
                return
            for row in rows:
                status_class = {
                    "可用": "is-ok",
                    "停用": "is-muted",
                    "需刷新": "is-warn",
                    "失效": "is-danger",
                    "冷却中": "is-warn",
                }.get(row["enabled"], "is-muted")
                with ui.element("div").classes("account-item"):
                    with ui.element("div").classes("account-order-pill"):
                        ui.label(row["order"])
                    with ui.element("div").classes("account-identity"):
                        ui.label(row["name"]).classes("account-name-main")
                        with ui.element("div").classes("account-meta-line"):
                            for text in (
                                row["type"],
                                row["quota"],
                                row["health"],
                                f"过期 {row['expires']}",
                            ):
                                ui.label(text).classes("account-meta-chip")
                    ui.label(row["enabled"]).classes(f"account-status {status_class}")
                    ui.label(row["auth"]).classes("account-auth")
                    with ui.row().classes("account-row-actions items-center"):
                        ui.button(
                            icon="play_arrow" if row["enabled"] == "停用" else "pause",
                            on_click=lambda _row=row: toggle_account(_row["account_key"]),
                        ).props(
                            f"flat round dense title={'启用' if row['enabled'] == '停用' else '停用'}"
                        )
                        ui.button(
                            icon="delete",
                            on_click=lambda _row=row: remove_named_account(_row["account_key"]),
                        ).props("flat round dense color=negative title=删除")

    def refresh_accounts() -> None:
        account_list.refresh()

    async def save_account() -> None:
        name = str(account_name.value or "").strip()
        auth_value = str(account_auth_value.value or "").strip()
        if not auth_value:
            notify("请粘贴 Token、Cookie 或脚本复制的 JSON", type="warning")
            return
        local_settings = current_settings()
        try:
            credential = await run.io_bound(
                credential_from_auth_import,
                auth_value,
                name=name,
                enabled=bool(account_enabled.value),
                settings=local_settings,
            )
        except ValueError as exc:
            notify(str(exc), type="warning")
            return
        except Exception as exc:  # noqa: BLE001
            notify(f"官网接口验证失败：{exc}", type="negative")
            return
        pool = AccountPool(local_settings.account_pool_file)
        pool.upsert(credential)
        account_name.value = ""
        account_auth_value.value = ""
        refresh_accounts()
        app_state.log(f"高级导入账号已验证并保存：{credential.name}")
        notify("账号已验证并保存", type="positive")

    def remove_named_account(name: str) -> None:
        if not name:
            return
        AccountPool(account_pool_path()).remove(name)
        refresh_accounts()
        notify("账号已删除")

    def toggle_account(name: str) -> None:
        pool = AccountPool(account_pool_path())
        for account in pool.accounts:
            if account.name == name:
                account.enabled = not account.enabled
                pool.save()
                refresh_accounts()
                notify("账号状态已更新")
                return

    def set_output_dir(path: Path) -> None:
        output_dir.value = str(path)
        output_dir.update()
        refresh_accounts()

    async def choose_output_dir() -> None:
        selected_dir = await run.io_bound(choose_directory, Path(output_dir.value))
        if selected_dir:
            set_output_dir(selected_dir)
            return
        notify("未选择目录，可直接编辑保存位置。", type="warning")

    def open_account_dialog() -> None:
        refresh_accounts()
        account_dialog.open()

    def open_directory(path_value: str | Path) -> None:
        path = Path(path_value)
        if open_path(path):
            return
        notify("目录不存在", type="warning")

    def set_history_page(page: int) -> None:
        nonlocal history_page
        history_page = max(1, page)
        refresh()

    def preview_directory(path_value: str | Path) -> None:
        path = Path(path_value)
        if preview_first_file(path):
            return
        notify("暂无可预览图片", type="warning")

    def handle_resource_action(event) -> None:
        payload = event.args or {}
        action = payload.get("action")
        local_dir = str(payload.get("local_dir") or "")
        if not local_dir:
            notify("暂无本地目录", type="warning")
            return
        if action == "preview":
            preview_directory(local_dir)
        elif action == "open":
            open_directory(local_dir)

    def handle_task_action(event) -> None:
        nonlocal managed_history_task
        payload = event.args or {}
        action = str(payload.get("action") or "open")
        local_dir = str(payload.get("local_dir") or "")
        if action == "manage":
            managed_history_task = payload
            restore_history_task(payload)
            refresh()
            return
        if action == "archive":
            task_id = str(payload.get("id") or "")
            if not task_id:
                notify("缺少任务 ID，无法归档", type="warning")
                return
            if not TaskHistory(task_history_path()).archive(task_id):
                notify("只有已结束任务可以归档", type="warning")
                return
            if managed_history_task and str(managed_history_task.get("id") or "") == task_id:
                managed_history_task = None
            refresh()
            notify("任务已归档，下载资源未删除", type="positive")
            return
        if not local_dir:
            notify("暂无下载路径", type="warning")
            return
        open_directory(local_dir)

    def restore_history_task(task: dict[str, object]) -> None:
        filters = task.get("filters") if isinstance(task.get("filters"), dict) else {}
        raw_settings = filters.get("_settings") if isinstance(filters.get("_settings"), dict) else {}
        raw_filters = filters.get("_filters") if isinstance(filters.get("_filters"), dict) else {}
        if not raw_settings or not raw_filters:
            notify("已选择历史任务；旧任务缺少筛选快照，可打开目录或按当前筛选重新下载。", type="warning")
            return
        output_dir.value = str(raw_settings.get("output_dir") or output_dir.value)
        study_phase.value = str(raw_settings.get("study_phase_code") or study_phase.value)
        refresh_filter_options(reset=False)
        subject_select.value = str(raw_settings.get("subject_code") or ALL_VALUE) or ALL_VALUE
        for control, key in [
            (scene_select, "scenes"),
            (year_select, "years"),
            (rank_select, "ranks"),
            (province_select, "provinces"),
            (grade_select, "grades"),
            (term_select, "terms"),
        ]:
            values = raw_filters.get(key) if isinstance(raw_filters.get(key), list) else []
            control.value = str(values[0]) if values else ALL_VALUE
        file_type.value = str(raw_filters.get("file_type") or file_type.value)
        max_pages.value = raw_filters.get("max_pages_per_combo") or max_pages.value
        proxy_mode.value = normalized_proxy_mode(raw_settings)
        proxy_provider.value = normalized_proxy_provider(raw_settings)
        proxy_pool.value = str(raw_settings.get("proxy_pool") or "")
        proxy_api_url.value = str(raw_settings.get("proxy_api_url") or "")
        shenlong_whitelist_key.value = str(raw_settings.get("shenlong_whitelist_key") or "")
        shenlong_whitelist_sign.value = str(raw_settings.get("shenlong_whitelist_sign") or "")
        proxy_ip_value.text = proxy_status_text(raw_settings)
        proxy_ip_value.update()
        for control in [
            output_dir,
            study_phase,
            subject_select,
            scene_select,
            year_select,
            rank_select,
            province_select,
            grade_select,
            term_select,
            file_type,
            max_pages,
        ]:
            control.update()
        notify("已载入暂停任务的筛选条件，可重新预估或重新下载。", type="positive")

    def history_task_stats(task: dict[str, object]) -> CrawlStats:
        raw_stats = task.get("stats") if isinstance(task.get("stats"), dict) else {}
        stat_fields = CrawlStats.__dataclass_fields__
        values = {key: value for key, value in raw_stats.items() if key in stat_fields}
        stats = CrawlStats(**values)
        stats.task_mode = str(stats.task_mode or task.get("mode") or "crawl")
        stats.phase = str(stats.phase or "finished")
        stats.outcome = str(stats.outcome or task.get("status") or "")
        stats.running = False
        return stats

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
            quick_year_select.options = options("yearCode")
            quick_term_select.options = options("termCode")
            quick_scene_select.options = options("sceneCode")
            for control in [
                quick_subject_select,
                quick_province_select,
                quick_year_select,
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
        nonlocal managed_history_task
        if (
            quick_subject_select.value == ALL_VALUE
            and quick_province_select.value == ALL_VALUE
            and quick_year_select.value == ALL_VALUE
            and quick_term_select.value == ALL_VALUE
            and quick_scene_select.value == ALL_VALUE
        ):
            notify("请选择快速筛选条件", type="warning")
            return

        study_phase.value = quick_phase_select.value
        subject_select.value = quick_subject_select.value
        province_select.value = quick_province_select.value
        year_select.value = quick_year_select.value
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
            year_select,
            province_select,
            grade_select,
            term_select,
        ]:
            control.update()
        managed_history_task = None
        notify("快速筛选已应用", type="positive")

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
                notify("同步分类失败，请稍后再试", type="negative")
            else:
                notify("分类自动同步失败，继续使用当前分类", type="warning")
            return not fail_block
        subject_options = new_subject_options
        catalogs = new_catalogs
        save_catalog_cache(preferences, subject_options, catalogs)
        refresh_filter_options(reset=False)
        app_state.log("分类已刷新并保存")
        if notify_success:
            notify("分类已刷新", type="positive")
        return True

    async def prepare_proxy_provider(
        local_settings: AppSettings | None = None,
        *,
        notify_success: bool = True,
    ) -> bool:
        local_settings = local_settings or current_settings()
        if local_settings.proxy_mode != "api":
            if notify_success:
                notify("切换到提取接口后再绑定", type="warning")
            return True
        provider = create_proxy_provider(local_settings)
        if not provider.supports_whitelist:
            if notify_success:
                notify("当前服务商无需绑定", type="positive")
            return True
        try:
            result = await run.io_bound(provider.prepare)
        except Exception as exc:  # noqa: BLE001
            app_state.log(f"{provider.display_name} 准备失败：{exc}")
            notify(f"{provider.display_name} 准备失败：{exc}", type="negative")
            return False
        if result.message:
            app_state.log(result.message)
        if notify_success:
            notify("白名单已绑定" if result.added else "白名单已存在", type="positive")
        return True

    async def bind_current_ip() -> None:
        await prepare_proxy_provider(notify_success=True)

    async def load_current_ip() -> None:
        try:
            ip = await run.io_bound(
                current_public_ip,
                (settings.connect_timeout, settings.read_timeout),
            )
        except Exception as exc:  # noqa: BLE001
            my_ip_value.text = "获取失败"
            my_ip_value.update()
            app_state.log(f"当前 IP 获取失败：{exc}")
            return
        my_ip_value.text = ip
        my_ip_value.update()
        app_state.log(f"当前 IP：{ip}")

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

    def configure_task_table(task_table, *, empty_icon: str, include_manage: bool) -> None:
        task_table.on("task-action", handle_task_action)
        task_table.add_slot(
            "no-data",
            f"""
            <div class="table-empty-state">
              <q-icon name="{empty_icon}" size="20px" />
              <span>{{{{ props.message }}}}</span>
            </div>
            """,
        )
        task_table.add_slot(
            "body-cell-status_label",
            """
            <q-td :props="props">
              <span :class="'history-status-badge history-status-' + props.row.status_class">
                {{ props.row.status_label }}
              </span>
            </q-td>
            """,
        )
        manage_button = (
            """
              <q-btn
                v-if="props.row.can_manage"
                dense unelevated no-caps size="sm"
                class="task-action-btn task-action-manage"
                icon="tune"
                label="管理"
                title="管理任务"
                @click="$parent.$emit('task-action', {
                  action: 'manage',
                  ...props.row
                })"
              />
            """
            if include_manage
            else ""
        )
        archive_button = (
            """
              <q-btn
                v-if="props.row.can_archive"
                dense flat no-caps size="sm"
                class="task-action-btn task-action-archive"
                icon="archive"
                label="归档"
                title="归档任务"
                @click="$parent.$emit('task-action', {
                  action: 'archive',
                  id: props.row.id
                })"
              />
            """
            if not include_manage
            else ""
        )
        task_table.add_slot(
            "body-cell-actions",
            f"""
            <q-td :props="props">
              <div class="task-row-actions">
                {manage_button}
                <q-btn
                  dense flat no-caps size="sm"
                  class="task-action-btn task-action-open"
                  icon="folder_open"
                  label="目录"
                  title="打开目录"
                  @click="$parent.$emit('task-action', {{
                    action: 'open',
                    local_dir: props.row.local_dir
                  }})"
                />
                {archive_button}
              </div>
            </q-td>
            """,
        )

    with ui.column().classes("stzy-shell w-full gap-0"):
        with ui.row().classes("topbar w-full items-center"):
            with ui.row().classes("topbar-inner items-center justify-between"):
                with ui.row().classes("topbar-left items-center"):
                    with ui.column().classes("topbar-brand gap-0"):
                        ui.label("试卷下载器").classes("text-lg font-semibold")
                        ui.label("本地控制台").classes("muted text-xs")
                    with ui.row().classes("topbar-path items-center gap-1"):
                        output_dir = ui.input(
                            "保存位置",
                            value=str(settings.output_dir),
                        ).classes("topbar-path-input")
                        ui.button(
                            icon="folder_open",
                            on_click=choose_output_dir,
                        ).classes("topbar-path-button").props("flat round dense")
                with ui.row().classes("topbar-actions items-center gap-2"):
                    with ui.row().classes("topbar-network items-center"):
                        ui.icon("public").classes("topbar-network-icon")
                        ui.label("我的 IP").classes("topbar-network-label")
                        my_ip_value = ui.label("获取中").classes("topbar-network-value")
                    with ui.row().classes("topbar-network items-center"):
                        ui.icon("hub").classes("topbar-network-icon")
                        ui.label("代理 IP").classes("topbar-network-label")
                        proxy_ip_value = ui.label(proxy_status_text(strategy_settings)).classes(
                            "topbar-network-value"
                        )
                    ui.button(
                        "代理配置",
                        icon="hub",
                        on_click=lambda: proxy_dialog.open(),
                    ).props("flat no-caps")
                    ui.button("采集策略", icon="speed", on_click=lambda: strategy_dialog.open()).props(
                        "flat no-caps"
                    )
                    ui.button(
                        "刷新分类",
                        icon="sync",
                        on_click=lambda: refresh_remote_categories(
                            notify_success=True,
                            fail_block=False,
                        ),
                    ).props("flat no-caps")
                    ui.button("账号配置", icon="manage_accounts", on_click=open_account_dialog).props(
                        "flat no-caps"
                    )

        with ui.column().classes("main-wrap gap-4 py-5"):
            with ui.element("div").classes("workbench"):
                with ui.column().classes("left-stack gap-4"):
                    with ui.column().classes("panel filter-panel p-5 gap-5"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("筛选条件").classes("section-title")
                            ui.label("快速 + 高级").classes("muted text-xs")
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
                                quick_year_select = ui.select(
                                    {ALL_VALUE: "年份不限"},
                                    label="年份",
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
                                    "quick-filter-button step-action step-action-one"
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

                    with ui.column().classes("panel history-panel p-5 gap-3"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("当前任务").classes("section-title")
                            ui.label("运行中 / 已暂停").classes("muted text-xs")
                        active_task_table = ui.table(columns=task_columns, rows=[], row_key="id").classes(
                            "compact-table task-history-table w-full"
                        )
                        active_task_table.props('flat bordered dense no-data-label="暂无当前任务"')
                        configure_task_table(active_task_table, empty_icon="inbox", include_manage=True)

                    with ui.column().classes("panel history-panel p-5 gap-3"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("历史任务").classes("section-title")
                            ui.label("已结束任务").classes("muted text-xs")
                        task_table = ui.table(columns=task_columns, rows=[], row_key="id").classes(
                            "compact-table task-history-table w-full"
                        )
                        task_table.props('flat bordered dense no-data-label="暂无历史任务记录"')
                        configure_task_table(task_table, empty_icon="inventory_2", include_manage=False)
                        with ui.row().classes("history-pagination w-full items-center justify-between"):
                            history_page_label = ui.label("第 1 / 1 页").classes("muted text-xs")
                            with ui.row().classes("items-center gap-2") as history_page_actions:
                                history_prev_button = ui.button(
                                    "上一页",
                                    icon="chevron_left",
                                    on_click=lambda: set_history_page(history_page - 1),
                                ).props("flat dense no-caps")
                                history_next_button = ui.button(
                                    "下一页",
                                    icon="chevron_right",
                                    on_click=lambda: set_history_page(history_page + 1),
                                ).props("flat dense no-caps")

                with ui.column().classes("panel progress-panel p-5 gap-4"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("任务状态").classes("section-title")
                        summary = ui.label("").classes("muted text-sm")
                    with ui.element("div").classes("download-section task-control-panel status-task-control"):
                        with ui.row().classes("task-control-head w-full items-center justify-between"):
                            ui.label("任务操作").classes("task-control-title")
                            action_context = ui.label("当前筛选：不限").classes("task-context")
                        with ui.element("div").classes("action-grid status-action-flow"):
                            estimate_button = ui.button(
                                "预估数量",
                                icon="analytics",
                                on_click=lambda: start("estimate"),
                            ).classes(
                                "task-control-action secondary-action step-action step-action-two"
                            ).props("outline no-caps")
                            download_button = ui.button(
                                "开始下载",
                                icon="download",
                                on_click=lambda: start("crawl"),
                            ).classes(
                                "task-control-action primary-action step-action step-action-three"
                            ).props("unelevated no-caps color=primary")
                            pause_button = ui.button("停止任务", icon="stop_circle", on_click=stop).classes(
                                "task-control-action secondary-action stop-action"
                            ).props("outline no-caps")
                            pause_button.disable()
                        managed_task_label = ui.label("").classes("managed-task-label")
                        action_hint_label = ui.label("预估数量，确认后下载。").classes(
                            "task-action-hint"
                        )
                    status_overview = ui.html(
                        '<div class="status-overview status-idle">'
                        '<div><div class="status-stage">空闲</div>'
                        '<div class="status-detail">等待任务</div></div>'
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
                        "no-data",
                        """
                        <div class="table-empty-state">
                          <q-icon name="download_done" size="20px" />
                          <span>{{ props.message }}</span>
                        </div>
                        """,
                    )
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

        with ui.element("details").classes("runtime-log-drawer"):
            with ui.element("summary").classes("runtime-log-summary"):
                log_summary_counts = ui.html(
                    '<div class="log-counter-wrap">'
                    '<span class="log-counter log-counter-error">'
                    '<i class="material-icons log-counter-icon">cancel</i><span>0</span>'
                    '</span>'
                    '<span class="log-counter log-counter-warning">'
                    '<i class="material-icons log-counter-icon">warning</i><span>0</span>'
                    '</span>'
                    '</div>'
                )
                ui.label("运行日志").classes("runtime-log-title")
            with ui.column().classes("runtime-log-panel gap-2"):
                with ui.row().classes("runtime-log-head w-full items-center justify-between"):
                    ui.label("运行日志").classes("font-medium")
                    ui.button("清空", icon="delete_sweep", on_click=app_state.clear_logs).props(
                        "flat dense no-caps"
                    )
                log_label = ui.html("").classes("log-box w-full")

    with ui.dialog() as strategy_dialog, ui.card().classes("modal-card strategy-modal-card gap-4"):
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
                "试卷并发",
                value=int(strategy_settings.get("concurrency") or settings.concurrency),
                min=1,
                max=8,
                step=1,
                suffix="个",
            ).classes("w-full")
        ui.label("10 页内保存预览图，超过 10 页保存 PDF 并转图。").classes(
            "muted text-sm"
        )

        def save_strategy() -> None:
            saved = {
                "file_type": file_type.value or "PDF",
                "max_pages_per_combo": int(max_pages.value) if max_pages.value else None,
                "image_delay_seconds": float(image_delay.value or settings.image_delay_seconds),
                "list_delay_seconds": float(list_delay.value or settings.list_delay_seconds),
                "concurrency": int(concurrency.value or settings.concurrency),
                "proxy_mode": str(proxy_mode.value or "off"),
                "proxy_provider": str(proxy_provider.value or settings.proxy_provider),
                "proxy_pool": str(proxy_pool.value or "").strip(),
                "proxy_api_url": str(proxy_api_url.value or "").strip(),
                "shenlong_whitelist_key": str(shenlong_whitelist_key.value or "").strip(),
                "shenlong_whitelist_sign": str(shenlong_whitelist_sign.value or "").strip(),
            }
            preferences.set("strategy", saved)
            app_state.log("采集策略已保存")
            notify("采集策略已保存", type="positive")
            strategy_dialog.close()

        ui.button("保存", on_click=save_strategy).classes("dialog-primary").props(
            "unelevated no-caps color=primary"
        )

    with ui.dialog() as proxy_dialog, ui.card().classes("modal-card strategy-modal-card gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("代理配置").classes("section-title")
            ui.button(icon="close", on_click=proxy_dialog.close).props("flat round dense")

        def sync_proxy_controls() -> None:
            using_fixed = proxy_mode.value == "fixed"
            using_api = proxy_mode.value == "api"
            using_shenlong = using_api and proxy_provider.value == "shenlong"
            proxy_pool_wrap.visible = using_fixed
            proxy_provider_wrap.visible = using_api
            proxy_api_wrap.visible = using_api
            whitelist_wrap.visible = using_shenlong
            bind_ip_button.visible = using_shenlong

        def save_proxy_settings() -> None:
            saved = {
                "file_type": file_type.value or "PDF",
                "max_pages_per_combo": int(max_pages.value) if max_pages.value else None,
                "image_delay_seconds": float(image_delay.value or settings.image_delay_seconds),
                "list_delay_seconds": float(list_delay.value or settings.list_delay_seconds),
                "concurrency": int(concurrency.value or settings.concurrency),
                "proxy_mode": str(proxy_mode.value or "off"),
                "proxy_provider": str(proxy_provider.value or settings.proxy_provider),
                "proxy_pool": str(proxy_pool.value or "").strip(),
                "proxy_api_url": str(proxy_api_url.value or "").strip(),
                "shenlong_whitelist_key": str(shenlong_whitelist_key.value or "").strip(),
                "shenlong_whitelist_sign": str(shenlong_whitelist_sign.value or "").strip(),
            }
            preferences.set("strategy", saved)
            proxy_ip_value.text = proxy_status_text(saved)
            proxy_ip_value.update()
            app_state.log("代理配置已保存")
            notify("代理配置已保存", type="positive")
            proxy_dialog.close()

        with ui.element("div").classes("proxy-settings"):
            proxy_mode = ui.toggle(
                {"off": "不使用代理", "fixed": "固定代理", "api": "提取接口"},
                value=normalized_proxy_mode(strategy_settings),
                on_change=lambda _: sync_proxy_controls(),
            ).classes("proxy-mode-toggle")
            proxy_mode.props("flat no-caps")
            with ui.element("div").classes("proxy-fields"):
                with ui.element("div").classes("proxy-provider-wrap") as proxy_provider_wrap:
                    proxy_provider = ui.select(
                        {"generic": "通用接口", "shenlong": "神龙 HTTP"},
                        label="服务商",
                        value=normalized_proxy_provider(strategy_settings),
                        on_change=lambda _: sync_proxy_controls(),
                    ).classes("w-full compact-field")
                with ui.element("div").classes("proxy-api-wrap") as proxy_api_wrap:
                    proxy_api_url = ui.input(
                        "提取接口",
                        value=str(strategy_settings.get("proxy_api_url") or settings.proxy_api_url or ""),
                        placeholder="http://api.shenlongip.com/ip?key=...&pattern=json&count=1&sign=...",
                    ).classes("w-full compact-field")
                with ui.element("div").classes("proxy-pool-wrap") as proxy_pool_wrap:
                    proxy_pool = ui.textarea(
                        "固定代理",
                        value=str(strategy_settings.get("proxy_pool") or settings.proxy_pool or ""),
                        placeholder="http://127.0.0.1:7890",
                    ).classes("w-full compact-field proxy-pool-input")
                with ui.element("div").classes("proxy-whitelist-wrap") as whitelist_wrap:
                    shenlong_whitelist_key = ui.input(
                        "白名单账号",
                        value=str(
                            strategy_settings.get("shenlong_whitelist_key")
                            or settings.shenlong_whitelist_key
                            or ""
                        ),
                    ).classes("w-full compact-field")
                    shenlong_whitelist_sign = ui.input(
                        "白名单签名",
                        value=str(
                            strategy_settings.get("shenlong_whitelist_sign")
                            or settings.shenlong_whitelist_sign
                            or ""
                        ),
                    ).props("type=password").classes("w-full compact-field")

        with ui.row().classes("w-full items-center justify-end"):
            bind_ip_button = ui.button(
                "绑定本机 IP",
                icon="link",
                on_click=bind_current_ip,
            )
            bind_ip_button.props("flat no-caps")
            ui.button("保存", on_click=save_proxy_settings).classes("dialog-primary").props(
                "unelevated no-caps color=primary"
            )
        sync_proxy_controls()

    with ui.dialog() as account_dialog, ui.card().classes("modal-card account-modal-card gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("账号配置").classes("section-title")
            ui.button(icon="close", on_click=account_dialog.close).props("flat round dense")
        with ui.element("div").classes("account-modal-body"):
            ui.label("已启用账号按顺序使用。").classes("muted text-sm")
            account_list()

            with ui.tabs().classes("account-tabs") as account_tabs:
                phone_tab = ui.tab("手机号登录", icon="phone_iphone")
                manual_tab = ui.tab("高级导入", icon="vpn_key")
            with ui.tab_panels(account_tabs, value=phone_tab).classes("account-panels"):
                with ui.tab_panel(phone_tab).classes("account-panel"):
                    with ui.element("div").classes("account-form"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("手机号登录").classes("section-title")
                            ui.label("密码为空时使用手机号后六位").classes(
                                "muted text-sm"
                            )
                        with ui.element("div").classes("credential-grid two-cols"):
                            account_phone = ui.input("手机号", placeholder="请输入 11 位手机号").props(
                                "outlined"
                            ).classes("w-full")
                            account_password = ui.input("密码", placeholder="空白则使用手机号后六位").props(
                                "type=password outlined"
                            ).classes("w-full")
                        with ui.row().classes("account-actions w-full items-center justify-end"):
                            ui.button("登录并保存", icon="login", on_click=phone_login).classes(
                                "primary-action"
                            ).props("unelevated no-caps color=primary")

                with ui.tab_panel(manual_tab).classes("account-panel"):
                    with ui.element("div").classes("account-form"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("请求导入").classes("section-title")
                            account_enabled = ui.checkbox("启用", value=True).classes(
                                "account-enabled"
                            )
                        with ui.expansion("导入步骤", icon="help_outline").classes("console-script-box"):
                            ui.label(
                                "登录 stzy.com，在浏览器开发者工具 Network 中复制 user/detail 或资源接口的 fetch/cURL。"
                            ).classes("muted text-sm")
                        with ui.expansion(
                            "Console Token 脚本",
                            icon="code",
                        ).classes("console-script-box"):
                            ui.textarea(value=COOKIE_TOKEN_CONSOLE_SCRIPT).props(
                                "readonly outlined"
                            ).classes("w-full credential-input console-script")
                        account_name = ui.input(
                            "账号名称", placeholder="可选；不填会从 Token 识别"
                        ).props("outlined").classes("w-full")
                        account_auth_value = ui.textarea(
                            "fetch / cURL / Token / Cookie / JSON",
                            placeholder="粘贴 fetch(...)、curl -H ...、Token、Cookie 或 JSON。",
                        ).props("outlined").classes("w-full credential-input auth-import-box")
                        with ui.row().classes("account-actions w-full items-center justify-end"):
                            ui.button("清空输入", icon="backspace", on_click=lambda: (
                                account_name.set_value(""),
                                account_auth_value.set_value(""),
                            )).props("flat no-caps")
                            ui.button(
                                "验证并保存",
                                icon="verified_user",
                                on_click=save_account,
                            ).classes("primary-action").props("unelevated no-caps color=primary")

    def refresh() -> None:
        nonlocal history_page
        logs, records, stats, running, active_proxy = app_state.snapshot()
        display_records = records
        if active_proxy:
            proxy_ip_value.text = first_fixed_proxy(active_proxy)
            proxy_ip_value.update()
        if managed_history_task and not running:
            stats = history_task_stats(managed_history_task)
            task_id = str(managed_history_task.get("id") or "")
            display_records = TaskHistory(task_history_path()).resources(task_id) if task_id else []
        view = status_view(stats, running)
        stage_text = str(view["stage"])
        detail_text = str(view["detail"])
        status_class = str(view["class"])
        headline_count = str(view["count"])
        filter_brief = current_filter_summary(current_settings(), current_filters())["brief"]
        if managed_history_task:
            managed_brief = str(managed_history_task.get("brief") or "历史任务")
            action_context.set_text(f"管理任务：{managed_brief}")
            managed_task_label.set_text(f"已选择：{managed_brief}")
        else:
            action_context.set_text(f"当前筛选：{filter_brief}")
            managed_task_label.set_text("")
        if running:
            estimate_button.disable()
            download_button.disable()
            pause_button.enable()
            action_hint_label.set_text(action_hint(stats, running))
        else:
            estimate_button.enable()
            download_button.enable()
            pause_button.disable()
            if managed_history_task:
                action_hint_label.set_text("当前任务已载入。")
            else:
                action_hint_label.set_text(action_hint(stats, running))
        download_button.set_text(
            "继续下载" if managed_history_task and not running else download_action_text(stats, running)
        )
        progress_value = build_progress_value(stats, running)
        progress.value = progress_value
        progress_text.set_text(progress_percent_text(progress_value))
        summary.set_text(detail_text)
        combo_value, combo_label = build_combo_metric(stats)
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
        resource_value, resource_label = build_resource_metric(stats)
        image_value, image_label = build_image_metric(stats)
        skipped_value, skipped_label = build_issue_metric(stats)
        resource_metric.set_content(
            f'<div class="metric"><div class="metric-value">{resource_value}</div>'
            f'<div class="metric-label">{resource_label}</div></div>'
        )
        image_metric.set_content(
            f'<div class="metric"><div class="metric-value">{image_value}</div>'
            f'<div class="metric-label">{image_label}</div></div>'
        )
        skipped_metric.set_content(
            f'<div class="metric"><div class="metric-value">{skipped_value}</div>'
            f'<div class="metric-label">{skipped_label}</div></div>'
        )
        no_data_label, result_tip = current_result_empty_copy(stats.task_mode)
        current_result_tip.set_text(result_tip)
        table.props(f'no-data-label="{no_data_label}"')
        table_records = [] if stats.task_mode == "estimate" else display_records
        table.rows = display_record_rows(table_records)
        table.update()
        all_tasks = TaskHistory(task_history_path()).recent(200, mode="crawl")
        unfinished_tasks = [
            task for task in all_tasks if str(task.get("status") or "") in unfinished_task_statuses
        ]
        history_tasks = [
            task for task in all_tasks if str(task.get("status") or "") in terminal_task_statuses
        ]
        active_task_table.rows = display_task_rows(unfinished_tasks)
        active_task_table.update()
        total_history = len(history_tasks)
        total_pages = max(1, (total_history + history_page_size - 1) // history_page_size)
        history_page = min(max(1, history_page), total_pages)
        history_start = (history_page - 1) * history_page_size
        history_end = history_start + history_page_size
        task_table.rows = display_task_rows(history_tasks[history_start:history_end])
        task_table.update()
        history_page_label.set_text(f"第 {history_page} / {total_pages} 页，共 {total_history} 条")
        has_multiple_history_pages = total_pages > 1
        history_page_actions.visible = has_multiple_history_pages
        history_page_actions.update()
        if not has_multiple_history_pages:
            history_prev_button.disable()
            history_next_button.disable()
        else:
            history_prev_button.enable()
            history_next_button.enable()
            if history_page <= 1:
                history_prev_button.disable()
            if history_page >= total_pages:
                history_next_button.disable()
        log_label.set_content(render_log_lines(logs))
        log_counts = log_level_counts(logs)
        error_count = log_counts["error"]
        warning_count = log_counts["warning"]
        filter_count = log_counts["filter"]
        log_summary_counts.set_content(
            '<div class="log-counter-wrap">'
            f'<span class="log-counter log-counter-error{" has-issues" if error_count else ""}" title="错误">'
            f'<i class="material-icons log-counter-icon">cancel</i><span>错误 {error_count}</span>'
            '</span>'
            f'<span class="log-counter log-counter-warning{" has-issues" if warning_count else ""}" title="告警">'
            f'<i class="material-icons log-counter-icon">warning</i><span>告警 {warning_count}</span>'
            '</span>'
            f'<span class="log-counter log-counter-filter{" has-issues" if filter_count else ""}" title="过滤">'
            f'<i class="material-icons log-counter-icon">filter_alt</i><span>过滤 {filter_count}</span>'
            '</span>'
            '</div>'
        )

    ui.timer(0.8, refresh)
    ui.timer(
        0.1,
        lambda: background_tasks.create(load_current_ip(), name="stzy-current-ip"),
        once=True,
    )
    refresh_filter_options()
