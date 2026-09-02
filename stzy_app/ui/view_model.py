from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlparse

from stzy_app.crawler import CrawlStats


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
                "stage": "预估中",
                "detail": f"{stats.completed_combos}/{stats.total_combos} 个组合",
                "class": "running",
                "count": stats.resources_seen,
            }
        current_name = f"：{stats.current_resource_name}" if stats.current_resource_name else ""
        return {
            "stage": "下载中",
            "detail": f"{resource_progress} 份试卷{current_name}",
            "class": "running",
            "count": resource_progress,
        }

    if outcome == "estimated" or (mode == "estimate" and completed):
        return {
            "stage": "可下载",
            "detail": f"匹配 {stats.resources_seen} 份试卷",
            "class": "estimated",
            "count": stats.resources_seen,
        }
    if outcome == "auth_expired":
        return {
            "stage": "登录失效",
            "detail": "更新账号后重试",
            "class": "failed",
            "count": stats.resources_seen,
        }
    if stats.paused or outcome == "paused":
        return {
            "stage": "已停止",
            "detail": f"{stats.completed_combos}/{stats.total_combos} 个组合",
            "class": "paused",
            "count": stats.resources_seen,
        }
    if outcome == "partial" or (
        stats.total_combos and (stats.failed or stats.preview_limited or stats.paid_skipped)
    ):
        issue_count = stats.failed + stats.preview_limited + stats.paid_skipped
        return {
            "stage": "部分完成",
            "detail": f"{issue_count} 个未完成",
            "class": "partial",
            "count": stats.resources_seen,
        }
    if outcome == "completed" or (mode == "crawl" and completed):
        return {
            "stage": "完成",
            "detail": "下载完成",
            "class": "done",
            "count": stats.resources_seen,
        }
    return {
        "stage": "空闲",
        "detail": "等待任务",
        "class": "idle",
        "count": stats.resources_seen,
    }


def progress_percent_text(value: float) -> str:
    percent = max(0, min(100, round(value * 100)))
    return f"{percent}%"


def progress_value(stats: CrawlStats, running: bool) -> float:
    if running and stats.task_mode == "crawl":
        resource_total = stats.resources_total or stats.resources_seen
        return min(1, stats.resources_completed / resource_total) if resource_total else 0
    if stats.task_mode == "crawl" and stats.phase == "finished":
        return 1 if stats.resources_seen or stats.resources_total else 0
    return stats.completed_combos / stats.total_combos if stats.total_combos else 0


def action_hint(stats: CrawlStats, running: bool) -> str:
    if running:
        return "停止后不再发起新请求。"
    if stats.task_mode == "estimate" and stats.outcome == "estimated":
        return f"匹配 {stats.resources_seen} 份试卷。"
    if stats.paused or stats.outcome == "paused":
        return "可调整筛选后重新运行。"
    if stats.task_mode == "crawl" and stats.phase == "finished":
        return "结果已进入历史任务。"
    return "预估数量，确认后下载。"


def download_action_text(stats: CrawlStats, running: bool) -> str:
    if running:
        return "下载中"
    if stats.paused or stats.outcome == "paused":
        return "继续下载"
    if stats.task_mode == "crawl" and (stats.phase == "finished" or stats.outcome in {"paused", "partial", "completed"}):
        return "重新下载"
    return "开始下载"


def config_status_cards(
    output_dir: str,
    account_count: int,
    raw_settings: dict[str, object],
    active_proxy: object = "",
) -> list[dict[str, str]]:
    proxy_mode = str(raw_settings.get("proxy_mode") or "off").strip().lower()
    proxy_pool = str(raw_settings.get("proxy_pool") or "")
    proxy_api_url = str(raw_settings.get("proxy_api_url") or "").strip()
    proxy_provider = str(raw_settings.get("proxy_provider") or "generic").strip().lower()
    file_type = str(raw_settings.get("file_type") or "PDF")
    concurrency = str(raw_settings.get("concurrency") or "1")

    output_path = str(output_dir or "").strip()
    output_label = Path(output_path).name or output_path if output_path else "未设置"
    cards = [
        {
            "key": "path",
            "title": "保存位置",
            "status": "已配置" if output_path else "需要处理",
            "detail": output_label,
            "class": "done" if output_path else "warn",
            "icon": "folder_open",
        },
        {
            "key": "account",
            "title": "账号",
            "status": "已配置" if account_count else "需要处理",
            "detail": f"{account_count} 个账号可用" if account_count else "添加账号",
            "class": "done" if account_count else "warn",
            "icon": "manage_accounts",
        },
    ]

    if proxy_mode == "fixed":
        fixed_count = len([line for line in proxy_pool.splitlines() if line.strip()])
        proxy_card = {
            "key": "proxy",
            "title": "代理",
            "status": "已配置" if fixed_count else "需要处理",
            "detail": f"固定代理 · {fixed_count} 个" if fixed_count else "填写固定代理",
            "class": "done" if fixed_count else "warn",
            "icon": "hub",
        }
    elif proxy_mode == "api":
        provider_name = "神龙 HTTP" if proxy_provider == "shenlong" else "通用接口"
        if active_proxy:
            parsed = urlparse(str(active_proxy))
            host = parsed.hostname or str(active_proxy)
            proxy_card = {
                "key": "proxy",
                "title": "代理",
                "status": "检测通过",
                "detail": host,
                "class": "done",
                "icon": "hub",
            }
        else:
            proxy_card = {
                "key": "proxy",
                "title": "代理",
                "status": "已配置" if proxy_api_url else "需要处理",
                "detail": provider_name if proxy_api_url else "填写提取接口",
                "class": "done" if proxy_api_url else "warn",
                "icon": "hub",
            }
    else:
        proxy_card = {
            "key": "proxy",
            "title": "代理",
            "status": "已配置",
            "detail": "直连",
            "class": "idle",
            "icon": "hub",
        }
    cards.append(proxy_card)
    cards.append(
        {
            "key": "strategy",
            "title": "采集策略",
            "status": "已配置",
            "detail": f"{file_type} · {concurrency} 个并发",
            "class": "done",
            "icon": "speed",
        }
    )
    return cards


def combo_metric(stats: CrawlStats) -> tuple[str, str]:
    resource_total = stats.resources_total or stats.resources_seen
    if stats.task_mode == "crawl":
        return (f"{stats.resources_completed}/{resource_total}" if resource_total else "0/0", "试卷进度")
    return (f"{stats.completed_combos}/{stats.total_combos}", "条件组合")


def resource_metric(stats: CrawlStats) -> tuple[int, str]:
    if stats.task_mode == "crawl" and stats.resources_total:
        return stats.resources_total, "匹配试卷"
    return stats.resources_seen, "预估试卷" if stats.task_mode == "estimate" else "匹配试卷"


def image_metric(stats: CrawlStats) -> tuple[int, str]:
    return stats.images_downloaded, "未下载图片" if stats.task_mode == "estimate" else "已下载图片"


def issue_metric(stats: CrawlStats) -> tuple[str, str]:
    if stats.task_mode == "estimate":
        return str(stats.paid_skipped), "付费"
    return f"{stats.paid_skipped}/{stats.preview_limited}", "付费/未完整"


def current_result_empty_copy(task_mode: str) -> tuple[str, str]:
    if task_mode == "estimate":
        return "暂无下载记录", "预估只更新数量"
    return "暂无下载记录", "本次下载"


def history_status_label(status: str) -> str:
    labels = {
        "running": "运行中",
        "estimated": "预估完成",
        "completed": "下载完成",
        "partial": "部分完成",
        "failed": "失败",
        "paused": "已暂停",
        "auth_expired": "登录失效",
        "del": "已归档",
    }
    return labels.get(status, status or "-")


def history_status_class(status: str) -> str:
    classes = {
        "completed": "done",
        "partial": "partial",
        "failed": "failed",
        "paused": "paused",
        "auth_expired": "failed",
        "running": "running",
        "del": "idle",
    }
    return classes.get(status, "idle")


def display_task_rows(tasks: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for task in tasks:
        stats = task.get("stats") if isinstance(task.get("stats"), dict) else {}
        filters = task.get("filters") if isinstance(task.get("filters"), dict) else {}
        started_at = str(task.get("started_at") or task.get("created_at") or "")
        local_dir = str(task.get("first_local_dir") or filters.get("保存位置") or "")
        status = str(task.get("status") or "")
        can_manage = status in {"running", "paused", "partial", "failed", "auth_expired"}
        can_cancel = status in {"running", "paused"}
        can_archive = status in {"completed", "partial", "failed", "auth_expired"}
        rows.append(
            {
                "id": str(task.get("id") or ""),
                "started_at": started_at.replace("T", " ")[5:16] if started_at else "-",
                "brief": str(filters.get("brief") or "不限"),
                "status": status,
                "status_label": history_status_label(str(task.get("status") or "")),
                "status_class": history_status_class(status),
                "resources_seen": stats.get("resources_seen", 0),
                "images_downloaded": stats.get("images_downloaded", 0),
                "local_dir": local_dir,
                "filters": filters,
                "stats": stats,
                "mode": str(task.get("mode") or "crawl"),
                "can_manage": can_manage,
                "can_cancel": can_cancel,
                "can_archive": can_archive,
            }
        )
    return rows


def display_record_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    labels = {
        "completed": "完成",
        "partial": "部分完成",
        "skipped_paid": "跳过付费",
        "paid_unavailable": "付费不可用",
        "failed": "失败",
        "pending": "等待中",
        "downloading": "下载中",
    }
    rows = []
    for record in records:
        row = dict(record)
        status = str(row.get("status") or "")
        row["status_label"] = labels.get(status, status or "-")
        row["error_text"] = str(row.get("error") or "")
        rows.append(row)
    return rows


def log_line_level(line: str) -> str:
    if "跳过地区不匹配资源" in line or "接口返回非目标地区，已过滤" in line:
        return "filter"
    if any(keyword in line for keyword in ["失败", "异常", "错误", "失效"]):
        return "error"
    if any(keyword in line for keyword in ["警告", "部分完成", "预览图不完整", "跳过付费"]):
        return "warning"
    if any(keyword in line for keyword in ["完成", "成功", "已保存", "已同步", "已归档"]):
        return "success"
    return "info"


def render_log_lines(logs: list[str], limit: int = 120) -> str:
    if not logs:
        return "等待任务启动"
    lines = []
    for line in logs[-limit:]:
        level = log_line_level(line)
        lines.append(f'<span class="log-line log-line-{level}">{html.escape(line)}</span>')
    return "<br>".join(lines)


def log_level_counts(logs: list[str]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "filter": 0}
    for line in logs:
        level = log_line_level(line)
        if level in counts:
            counts[level] += 1
    return counts
