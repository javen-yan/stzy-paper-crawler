from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sqlite3
import json

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
        pool.upsert(
            AccountCredential(
                name="账号A",
                cookie="a=1",
                user_agent="Mozilla/5.0 Real Browser",
                request_headers_json=json.dumps({"sec-ch-ua": '"Chromium";v="152"'}),
                import_method="network_curl",
                enabled=True,
            )
        )

        reloaded = AccountPool(self.db_path)

        self.assertEqual(len(reloaded.accounts), 1)
        self.assertEqual(reloaded.accounts[0].name, "账号A")
        self.assertEqual(reloaded.enabled_accounts()[0].cookie, "a=1")
        self.assertEqual(reloaded.enabled_accounts()[0].user_agent, "Mozilla/5.0 Real Browser")
        self.assertEqual(
            reloaded.enabled_accounts()[0].request_headers["sec-ch-ua"],
            '"Chromium";v="152"',
        )
        self.assertEqual(reloaded.enabled_accounts()[0].import_method, "network_curl")

    def test_account_pool_persists_download_profile_and_health(self) -> None:
        pool = AccountPool(self.db_path)
        pool.upsert(AccountCredential(name="VIP账号", cookie="a=1", enabled=True))
        pool.update_download_profile(
            "VIP账号",
            {"price": 0, "surplusNum": 92, "userType": 3, "rank": 3},
        )
        pool.mark_failure("VIP账号", "临时失败")

        reloaded = AccountPool(self.db_path)
        account = reloaded.accounts[0]

        self.assertEqual(account.account_type_label, "VIP/高端")
        self.assertEqual(account.last_price, 0)
        self.assertEqual(account.surplus_num, 92)
        self.assertEqual(account.fail_count, 1)
        self.assertTrue(account.in_cooldown)

        reloaded.mark_success("VIP账号")
        recovered = AccountPool(self.db_path).accounts[0]

        self.assertEqual(recovered.fail_count, 0)
        self.assertFalse(recovered.in_cooldown)

    def test_account_upsert_preserves_download_profile(self) -> None:
        pool = AccountPool(self.db_path)
        pool.upsert(AccountCredential(name="VIP账号", cookie="old=1", enabled=True))
        pool.update_download_profile(
            "VIP账号",
            {"price": 0, "surplusNum": 92, "userType": 3, "rank": 3},
        )
        pool.mark_failure("VIP账号", "旧凭证失败")

        pool.upsert(AccountCredential(name="VIP账号", cookie="new=1", enabled=True))
        account = AccountPool(self.db_path).accounts[0]

        self.assertEqual(account.cookie, "new=1")
        self.assertEqual(account.account_type_label, "VIP/高端")
        self.assertEqual(account.surplus_num, 92)
        self.assertEqual(account.fail_count, 0)
        self.assertFalse(account.in_cooldown)

    def test_schema_versions_are_recorded(self) -> None:
        AccountPool(self.db_path)
        Preferences(self.db_path)
        TaskHistory(self.db_path)

        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT component, version FROM schema_versions ORDER BY component"
            ).fetchall()

        self.assertIn(("accounts", 4), rows)
        self.assertIn(("preferences", 1), rows)
        self.assertIn(("tasks", 1), rows)

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
        resources = history.resources("task-1")
        self.assertEqual(resources[0]["resource_id"], "r1")
        self.assertEqual(resources[0]["resource_name"], "试卷1")
        self.assertEqual(resources[0]["image_count"], 4)

    def test_task_history_can_filter_download_tasks(self) -> None:
        history = TaskHistory(self.db_path)
        history.start({"id": "estimate-1", "mode": "estimate"})
        history.finish("estimate-1", {"status": "estimated", "stats": {"resources_seen": 8}})
        history.start({"id": "crawl-1", "mode": "crawl"})
        history.finish("crawl-1", {"status": "completed", "stats": {"resources_seen": 2}})

        recent = history.recent(mode="crawl")

        self.assertEqual([task["id"] for task in recent], ["crawl-1"])

    def test_task_history_archive_only_terminal_task_without_removing_resources(self) -> None:
        history = TaskHistory(self.db_path)
        history.start({"id": "running-1", "mode": "crawl", "status": "running"})
        history.start({"id": "done-1", "mode": "crawl", "status": "running"})
        history.record_resource(
            "done-1",
            ResourceRecord(
                resource_id="r1",
                resource_name="试卷1",
                image_count=4,
                status=ResourceStatus.completed,
                local_dir="/tmp/stzy/试卷1",
            ),
        )
        history.finish("done-1", {"status": "completed", "stats": {"resources_seen": 1}})

        self.assertFalse(history.archive("running-1"))
        self.assertTrue(history.archive("done-1"))

        recent_ids = [task["id"] for task in history.recent(mode="crawl")]
        self.assertEqual(recent_ids, ["running-1"])
        self.assertEqual(history.resources("done-1")[0]["resource_id"], "r1")

    def test_task_history_cancel_active_task_without_resurrecting_on_finish(self) -> None:
        history = TaskHistory(self.db_path)
        history.start({"id": "running-1", "mode": "crawl", "status": "running"})

        self.assertTrue(history.cancel("running-1"))
        history.finish("running-1", {"status": "paused", "stats": {"resources_seen": 1}})

        self.assertEqual(history.recent(mode="crawl"), [])

    def test_task_history_resume_and_completed_resource_ids(self) -> None:
        history = TaskHistory(self.db_path)
        history.start({"id": "paused-1", "mode": "crawl", "status": "paused"})
        history.start({"id": "partial-1", "mode": "crawl", "status": "partial"})
        history.start({"id": "done-1", "mode": "crawl", "status": "completed"})
        history.record_resource(
            "paused-1",
            ResourceRecord(
                resource_id="done-resource",
                resource_name="已完成",
                status=ResourceStatus.completed,
            ),
        )
        history.record_resource(
            "paused-1",
            ResourceRecord(
                resource_id="partial-resource",
                resource_name="未完成",
                status=ResourceStatus.partial,
            ),
        )

        self.assertTrue(history.resume("paused-1", {"resources_seen": 1}))
        self.assertTrue(history.resume("partial-1", {"resources_seen": 1}))
        self.assertFalse(history.resume("done-1", {"resources_seen": 1}))
        self.assertEqual(history.completed_resource_ids("paused-1"), {"done-resource"})
        self.assertEqual(history.resource_ids("paused-1"), {"done-resource", "partial-resource"})
        self.assertEqual(history.retry_resource_ids("paused-1"), {"partial-resource"})

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
                "proxy_mode": "api",
                "proxy_provider": "shenlong",
                "proxy_pool": "http://127.0.0.1:7890",
                "proxy_api_url": "http://api.example/proxy",
                "shenlong_whitelist_key": "account",
                "shenlong_whitelist_sign": "sign",
            },
        )

        saved = Preferences(self.db_path).get("strategy")

        self.assertEqual(saved["max_pages_per_combo"], 2)
        self.assertEqual(saved["list_delay_seconds"], 1.2)
        self.assertEqual(saved["proxy_mode"], "api")
        self.assertEqual(saved["proxy_provider"], "shenlong")
        self.assertEqual(saved["proxy_pool"], "http://127.0.0.1:7890")
        self.assertEqual(saved["proxy_api_url"], "http://api.example/proxy")
        self.assertEqual(saved["shenlong_whitelist_key"], "account")
        self.assertEqual(saved["shenlong_whitelist_sign"], "sign")


if __name__ == "__main__":
    unittest.main()
