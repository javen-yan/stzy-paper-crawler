import unittest

from stzy_app.crawler import CrawlStats
from stzy_app.ui.view_model import (
    action_hint,
    combo_metric,
    config_status_cards,
    current_result_empty_copy,
    display_record_rows,
    display_task_rows,
    download_action_text,
    log_level_counts,
    progress_value,
    render_log_lines,
    status_view,
)


class StatusViewTest(unittest.TestCase):
    def test_estimate_complete_stays_in_preview_state(self) -> None:
        stats = CrawlStats(
            task_mode="estimate",
            phase="preview",
            outcome="estimated",
            total_combos=1,
            completed_combos=1,
            resources_seen=24,
        )

        view = status_view(stats, running=False)

        self.assertEqual(view["stage"], "可下载")
        self.assertEqual(view["detail"], "匹配 24 份试卷")
        self.assertEqual(view["class"], "estimated")

    def test_crawl_complete_shows_download_complete(self) -> None:
        stats = CrawlStats(
            task_mode="crawl",
            phase="finished",
            outcome="completed",
            total_combos=1,
            completed_combos=1,
            resources_seen=10,
            images_downloaded=32,
        )

        view = status_view(stats, running=False)

        self.assertEqual(view["stage"], "完成")
        self.assertEqual(view["detail"], "下载完成")
        self.assertEqual(view["class"], "done")

    def test_auth_expired_is_explicit_end_state(self) -> None:
        stats = CrawlStats(task_mode="crawl", phase="finished", outcome="auth_expired")

        view = status_view(stats, running=False)

        self.assertEqual(view["stage"], "登录失效")
        self.assertEqual(view["detail"], "更新账号后重试")
        self.assertEqual(view["class"], "failed")

    def test_partial_resources_are_reported_as_partial_completion(self) -> None:
        stats = CrawlStats(
            task_mode="crawl",
            phase="finished",
            outcome="partial",
            total_combos=1,
            completed_combos=1,
            resources_seen=8,
            preview_limited=2,
        )

        view = status_view(stats, running=False)

        self.assertEqual(view["stage"], "部分完成")
        self.assertEqual(view["detail"], "2 个未完成")
        self.assertEqual(view["class"], "partial")

    def test_paid_unavailable_is_reported_as_partial_completion(self) -> None:
        stats = CrawlStats(
            task_mode="crawl",
            phase="finished",
            outcome="partial",
            total_combos=1,
            completed_combos=1,
            resources_seen=8,
            paid_skipped=3,
        )

        view = status_view(stats, running=False)

        self.assertEqual(view["stage"], "部分完成")
        self.assertEqual(view["detail"], "3 个未完成")
        self.assertEqual(view["class"], "partial")

    def test_running_copy_depends_on_task_mode(self) -> None:
        estimate = CrawlStats(
            task_mode="estimate",
            total_combos=3,
            completed_combos=1,
            running=True,
        )
        crawl = CrawlStats(
            task_mode="crawl",
            total_combos=1,
            completed_combos=0,
            resources_total=13,
            resources_seen=2,
            resources_completed=1,
            current_resource_name="山东省青岛市高一英语期末试卷",
            running=True,
        )

        self.assertEqual(status_view(estimate, running=True)["stage"], "预估中")
        self.assertEqual(status_view(estimate, running=True)["detail"], "1/3 个组合")
        self.assertEqual(
            status_view(crawl, running=True)["detail"],
            "1/13 份试卷：山东省青岛市高一英语期末试卷",
        )
        self.assertEqual(status_view(crawl, running=True)["count"], "1/13")

    def test_crawl_progress_uses_resource_dimension(self) -> None:
        stats = CrawlStats(
            task_mode="crawl",
            resources_total=4,
            resources_completed=2,
            running=True,
        )

        self.assertEqual(progress_value(stats, running=True), 0.5)
        self.assertEqual(combo_metric(stats), ("2/4", "试卷进度"))

    def test_estimate_ui_copy_does_not_show_download_records(self) -> None:
        stats = CrawlStats(
            task_mode="estimate",
            outcome="estimated",
            resources_seen=9,
        )

        self.assertEqual(action_hint(stats, running=False), "匹配 9 份试卷。")
        self.assertEqual(
            current_result_empty_copy("estimate"),
            ("暂无下载记录", "预估只更新数量"),
        )

    def test_running_task_hint_explains_stop_flow(self) -> None:
        stats = CrawlStats(task_mode="crawl", running=True)

        self.assertEqual(action_hint(stats, running=True), "停止后不再发起新请求。")
        self.assertEqual(download_action_text(stats, running=True), "下载中")

    def test_stopped_crawl_can_be_restarted(self) -> None:
        stats = CrawlStats(task_mode="crawl", phase="finished", outcome="paused", paused=True)

        self.assertEqual(action_hint(stats, running=False), "可调整筛选后重新运行。")
        self.assertEqual(download_action_text(stats, running=False), "继续下载")

    def test_config_status_cards_show_core_setup(self) -> None:
        cards = config_status_cards(
            "/tmp/output",
            2,
            {
                "proxy_mode": "fixed",
                "proxy_pool": "http://127.0.0.1:7890\nhttp://10.0.0.1:8080",
                "file_type": "PDF",
                "concurrency": 3,
            },
        )

        by_key = {card["key"]: card for card in cards}
        self.assertEqual(by_key["path"]["status"], "已配置")
        self.assertEqual(by_key["path"]["detail"], "output")
        self.assertEqual(by_key["account"]["detail"], "2 个账号可用")
        self.assertEqual(by_key["proxy"]["status"], "已配置")
        self.assertEqual(by_key["proxy"]["detail"], "固定代理 · 2 个")
        self.assertEqual(by_key["strategy"]["detail"], "PDF · 3 个并发")

    def test_config_status_cards_show_api_proxy_runtime_ip(self) -> None:
        cards = config_status_cards(
            "output",
            0,
            {
                "proxy_mode": "api",
                "proxy_provider": "shenlong",
                "proxy_api_url": "http://api.shenlongip.com/ip?count=1",
            },
            "http://49.85.120.175:40078",
        )

        by_key = {card["key"]: card for card in cards}
        self.assertEqual(by_key["account"]["status"], "需要处理")
        self.assertEqual(by_key["proxy"]["status"], "检测通过")
        self.assertEqual(by_key["proxy"]["detail"], "49.85.120.175")

    def test_task_rows_expose_manage_cancel_and_archive_actions_by_status(self) -> None:
        rows = display_task_rows(
            [
                {
                    "id": "task-1",
                    "status": "completed",
                    "started_at": "2026-09-02T11:28:00",
                    "filters": {"brief": "安徽 / 高一下 / 数学"},
                    "stats": {"resources_seen": 1, "images_downloaded": 17},
                },
                {
                    "id": "task-2",
                    "status": "paused",
                    "started_at": "2026-09-02T11:29:00",
                    "filters": {"brief": "安徽 / 高一下 / 语文"},
                    "stats": {"resources_seen": 2},
                },
                {
                    "id": "task-3",
                    "status": "running",
                    "started_at": "2026-09-02T11:30:00",
                    "filters": {"brief": "安徽 / 高一下 / 英语"},
                    "stats": {"resources_seen": 3},
                },
                {
                    "id": "task-4",
                    "status": "partial",
                    "started_at": "2026-09-02T11:31:00",
                    "filters": {"brief": "安徽 / 高一下 / 生物"},
                    "stats": {"resources_seen": 4},
                }
            ]
        )

        self.assertEqual(rows[0]["status_label"], "下载完成")
        self.assertEqual(rows[0]["status_class"], "done")
        self.assertFalse(rows[0]["can_manage"])
        self.assertTrue(rows[0]["can_archive"])
        self.assertEqual(rows[0]["stats"]["images_downloaded"], 17)
        self.assertTrue(rows[1]["can_manage"])
        self.assertTrue(rows[1]["can_cancel"])
        self.assertFalse(rows[1]["can_archive"])
        self.assertTrue(rows[2]["can_manage"])
        self.assertTrue(rows[2]["can_cancel"])
        self.assertFalse(rows[2]["can_archive"])
        self.assertTrue(rows[3]["can_manage"])
        self.assertFalse(rows[3]["can_cancel"])
        self.assertTrue(rows[3]["can_archive"])

    def test_record_rows_show_downloading_state(self) -> None:
        rows = display_record_rows(
            [
                {
                    "resource_id": "r1",
                    "resource_name": "试卷1",
                    "status": "downloading",
                }
            ]
        )

        self.assertEqual(rows[0]["status_label"], "下载中")

    def test_logs_distinguish_filter_from_warning_and_error(self) -> None:
        logs = [
            "[13:01:00] 接口返回非目标地区，已过滤：已选 贵州，返回 全国 - 试卷",
            "[13:01:16] 下载完成：下载 9 张图片，付费不可用 0 份",
            "[13:02:00] PDF 补全失败：无权限",
        ]

        self.assertEqual(log_level_counts(logs), {"error": 1, "warning": 0, "filter": 1})
        rendered = render_log_lines(logs)
        self.assertIn("log-line-filter", rendered)
        self.assertIn("log-line-success", rendered)
        self.assertIn("log-line-error", rendered)


if __name__ == "__main__":
    unittest.main()
