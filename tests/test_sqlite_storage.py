from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stzy_app.models import CrawlCombo, ResourceRecord, ResourceStatus, TagOption
from stzy_app.storage import (
    AccountCredential,
    AccountPool,
    CrawlState,
    CsvIndex,
    Preferences,
    TaskHistory,
)


class SqliteStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "stzy.db"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_account_pool_persists_accounts_in_sqlite(self) -> None:
        pool = AccountPool(self.db_path)
        pool.upsert(AccountCredential(name="账号A", cookie="a=1", enabled=True))

        reloaded = AccountPool(self.db_path)

        self.assertEqual(len(reloaded.accounts), 1)
        self.assertEqual(reloaded.accounts[0].name, "账号A")
        self.assertEqual(reloaded.enabled_accounts()[0].cookie, "a=1")

    def test_crawl_state_persists_combo_and_resource_state(self) -> None:
        combo = CrawlCombo(
            scene=TagOption("sceneCode", "8", "月考"),
            year=TagOption("yearCode", "", "不限"),
            rank=TagOption("rank", "", "不限"),
            province=TagOption("provinceCode", "340000", "安徽"),
            grade=TagOption("gradeCode", "7", "七年级"),
            term=TagOption("termCode", "13", "七年级上"),
        )
        state = CrawlState(self.db_path)
        state.mark_combo_completed(combo, "2")
        state.mark_resource("r1", "completed")

        reloaded = CrawlState(self.db_path)

        self.assertTrue(reloaded.is_combo_completed(combo, "2"))

    def test_resource_index_upserts_resource_rows(self) -> None:
        index = CsvIndex(self.db_path)
        record = ResourceRecord(
            resource_id="r1",
            resource_name="安徽七年级上月考数学试卷",
            subject="数学",
            image_count=2,
            status=ResourceStatus.completed,
        )

        self.assertTrue(index.append(record))
        record.image_count = 3
        self.assertFalse(index.append(record))

    def test_task_history_tracks_task_and_resources(self) -> None:
        history = TaskHistory(self.db_path)
        history.start(
            {
                "id": "task-1",
                "mode": "crawl",
                "status": "running",
                "started_at": "2026-09-01T21:00:00",
                "filters": {"brief": "安徽 / 七年级上 / 月考 / 数学"},
                "stats": {"resources_seen": 0},
            }
        )
        history.record_resource(
            "task-1",
            ResourceRecord(
                resource_id="r1",
                resource_name="试卷1",
                image_count=4,
                status=ResourceStatus.completed,
                local_dir="/tmp/stzy/试卷1",
            ),
        )
        history.finish(
            "task-1",
            {
                "status": "completed",
                "ended_at": "2026-09-01T21:00:05",
                "duration_seconds": 5,
                "stats": {"resources_seen": 1, "images_downloaded": 4},
            },
        )

        recent = history.recent()

        self.assertEqual(recent[0]["status"], "completed")
        self.assertEqual(recent[0]["filters"]["brief"], "安徽 / 七年级上 / 月考 / 数学")
        self.assertEqual(recent[0]["resource_record_count"], 1)
        self.assertEqual(recent[0]["first_local_dir"], "/tmp/stzy/试卷1")

    def test_task_history_can_filter_download_tasks(self) -> None:
        history = TaskHistory(self.db_path)
        history.start({"id": "estimate-1", "mode": "estimate"})
        history.finish("estimate-1", {"status": "estimated", "stats": {"resources_seen": 8}})
        history.start({"id": "crawl-1", "mode": "crawl"})
        history.finish("crawl-1", {"status": "completed", "stats": {"resources_seen": 2}})

        recent = history.recent(mode="crawl")

        self.assertEqual([task["id"] for task in recent], ["crawl-1"])

    def test_preferences_persist_strategy_settings(self) -> None:
        preferences = Preferences(self.db_path)
        preferences.set(
            "strategy",
            {
                "file_type": "PDF",
                "max_pages_per_combo": 2,
                "image_delay_seconds": 0.4,
                "list_delay_seconds": 1.2,
                "concurrency": 1,
            },
        )

        saved = Preferences(self.db_path).get("strategy")

        self.assertEqual(saved["max_pages_per_combo"], 2)
        self.assertEqual(saved["list_delay_seconds"], 1.2)


if __name__ == "__main__":
    unittest.main()
