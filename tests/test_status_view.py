import unittest

from stzy_app.crawler import CrawlStats
from stzy_app.ui.page import status_view


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

        self.assertEqual(view["stage"], "预览")
        self.assertEqual(view["detail"], "预估完成，找到 24 份匹配试卷")
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

        self.assertEqual(view["stage"], "结束")
        self.assertEqual(view["detail"], "下载完成")
        self.assertEqual(view["class"], "done")

    def test_auth_expired_is_explicit_end_state(self) -> None:
        stats = CrawlStats(task_mode="crawl", phase="finished", outcome="auth_expired")

        view = status_view(stats, running=False)

        self.assertEqual(view["stage"], "结束")
        self.assertEqual(view["detail"], "登录失效，请重新登录后再开始任务")
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

        self.assertEqual(view["stage"], "结束")
        self.assertEqual(view["detail"], "部分完成，异常或未完整保存 2 个")
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

        self.assertEqual(view["stage"], "结束")
        self.assertEqual(view["detail"], "部分完成，异常或未完整保存 3 个")
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

        self.assertEqual(status_view(estimate, running=True)["detail"], "正在预估匹配试卷 1/3")
        self.assertEqual(
            status_view(crawl, running=True)["detail"],
            "已处理 1/13 份试卷：山东省青岛市高一英语期末试卷",
        )
        self.assertEqual(status_view(crawl, running=True)["count"], "1/13")


if __name__ == "__main__":
    unittest.main()
