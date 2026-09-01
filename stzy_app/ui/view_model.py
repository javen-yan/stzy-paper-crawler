from __future__ import annotations

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


def progress_value(stats: CrawlStats, running: bool) -> float:
    if running and stats.task_mode == "crawl":
        resource_total = stats.resources_total or stats.resources_seen
        return min(1, stats.resources_completed / resource_total) if resource_total else 0
    if stats.task_mode == "crawl" and stats.phase == "finished":
        return 1 if stats.resources_seen or stats.resources_total else 0
    return stats.completed_combos / stats.total_combos if stats.total_combos else 0


def action_hint(stats: CrawlStats, running: bool) -> str:
    if running:
        return "任务正在运行，当前请求完成后可以暂停。"
    if stats.task_mode == "estimate" and stats.outcome == "estimated":
        return f"预估找到 {stats.resources_seen} 份试卷，可以开始下载。"
    if stats.task_mode == "crawl" and stats.phase == "finished":
        return "下载任务已结束，可在历史任务打开对应目录。"
    return "先预估确认数量，再开始下载；下载结果会进入历史任务。"


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
        return str(stats.paid_skipped), "预估不下载付费"
    return f"{stats.paid_skipped}/{stats.preview_limited}", "付费不可用/部分完成"


def current_result_empty_copy(task_mode: str) -> tuple[str, str]:
    if task_mode == "estimate":
        return "预估不会生成下载记录", "预估只更新匹配数量，不生成下载记录"
    return "还没有下载记录", "显示本次下载生成的资源"


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
