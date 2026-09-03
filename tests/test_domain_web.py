from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
import sqlite3
import time
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from stzy_app.config import AppSettings
from stzy_app.crawler import CrawlStats
from stzy_app.domain.context import create_context
from stzy_app.domain.identity import hash_password
from stzy_app.domain.proxy_status import PUBLIC_IP_ENDPOINTS, _extract_ip
from stzy_app.runtime import RuntimeAdapter
from stzy_app.storage.accounts import AccountCredential, AccountPool
from stzy_app.web import create_app


class DomainWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        settings = AppSettings(
            data_dir=self.root,
            output_dir=self.root,
            admin_password_hash=hash_password("secret"),
        )
        runtime = RuntimeAdapter.create(settings, mode="server", host="0.0.0.0", port=8080)
        self.context = create_context(settings, runtime)
        self.client = TestClient(create_app(self.context))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_server_requires_login_and_rejects_local_api(self) -> None:
        self.assertEqual(self.client.get("/api/v1/tasks").status_code, 401)

        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.assertEqual(login.status_code, 200)
        csrf = login.json()["csrf_token"]

        blocked = self.client.post(
            "/api/v1/local/open",
            json={"path": str(self.root)},
            headers={"x-csrf-token": csrf},
        )
        self.assertEqual(blocked.status_code, 404)

    def test_csrf_is_required_after_login(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.assertEqual(login.status_code, 200)

        response = self.client.post("/api/v1/tasks/task-x/archive")

        self.assertEqual(response.status_code, 403)

    def test_artifact_download_and_zip_export_stay_inside_data_root(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        csrf = login.json()["csrf_token"]
        task = self.context.store.create_task(
            task_id="task-1",
            mode="crawl",
            spec={"title": "测试任务"},
            output_dir=self.root / "tasks" / "task-1",
        )
        resource_dir = self.root / "tasks" / "task-1" / "生物" / "七年级" / "上学期" / "重庆市" / "月考" / "试卷"
        resource_dir.mkdir(parents=True)
        artifact_path = resource_dir / "练习1.png"
        artifact_path.write_bytes(b"png")
        search = self.client.get(
            "/api/v1/artifacts/browser/search",
            params={"task_id": "task-1", "path": "", "filter": "练习1", "deep": "1"},
        )
        self.assertEqual(search.status_code, 200)
        relative_path = search.json()["items"][0]["relative_path"]

        download = self.client.get("/api/v1/artifacts/browser/download", params={"task_id": "task-1", "path": relative_path})
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"png")

        export = self.client.post(
            "/api/v1/exports",
            json={"task_id": "task-1", "file_paths": [relative_path]},
            headers={"x-csrf-token": csrf},
        )
        self.assertEqual(export.status_code, 200)
        export_id = export.json()["id"]
        for _ in range(20):
            export_status = self.client.get(f"/api/v1/exports/{export_id}").json()
            if export_status["status"] == "completed":
                break
            time.sleep(0.05)
        self.assertEqual(export_status["status"], "completed")
        zip_download = self.client.get(f"/api/v1/exports/{export_id}/download")
        self.assertEqual(zip_download.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(zip_download.content)) as archive:
            names = archive.namelist()
        self.assertIn("生物/七年级/上学期/重庆市/月考/试卷/练习1.png", names)
        self.assertNotIn("r1/练习1.png", names)

        outside = self.root.parent / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.context.artifacts.register_file(task_id="task-1", resource_id="r1", path=outside)

    def test_artifact_list_uses_task_title_or_filter_display_name(self) -> None:
        self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.context.store.set_setting(
            "catalog_cache",
            {
                "study_phases": {"300": "高中"},
                "subjects": {"300": {"2": "数学"}},
                "catalogs": {
                    "300": {
                        "provinceCode": [{"code": "340000", "name": "安徽"}],
                        "gradeCode": [{"code": "11", "name": "高二"}],
                        "termCode": [{"code": "21", "name": "上学期"}],
                        "sceneCode": [{"code": "8", "name": "期末"}],
                    }
                },
            },
        )
        task = self.context.store.create_task(
            task_id="task-filter-name",
            mode="crawl",
            spec={
                "title": "",
                "filters": {
                    "provinces": ["340000"],
                    "grades": ["11"],
                    "terms": ["21"],
                    "scenes": ["8"],
                },
                "subjects": [{"code": "2"}],
                "settings": {"study_phase_code": "300", "file_type": "PDF"},
            },
            output_dir=self.root / "tasks" / "task-filter-name",
        )
        resource_dir = self.root / "tasks" / "task-filter-name" / "数学" / "高二" / "上学期" / "安徽" / "期末" / "试卷_r1"
        resource_dir.mkdir(parents=True)
        artifact_path = resource_dir / "练习1.png"
        artifact_path.write_bytes(b"png")
        self.context.artifacts.register_file(task_id=task["id"], resource_id="r1", path=artifact_path)

        items = self.context.artifacts.list_artifacts()
        item = items[0]
        self.assertEqual(item["task_title"], "")
        self.assertIn("高中", item["task_display_name"])
        self.assertIn("数学", item["task_display_name"])
        self.assertIn("安徽", item["task_display_name"])
        self.assertIn("PDF", item["task_display_name"])
        self.assertEqual(item["hierarchy_parts"], ["数学", "高二", "上学期", "安徽", "期末"])
        self.assertEqual(item["hierarchy_path"], "数学/高二/上学期/安徽/期末")
        self.assertEqual(item["resource_dir_name"], "试卷_r1")
        self.assertEqual(item["kind_label"], "图片")

        titled_task = self.context.store.create_task(
            task_id="task-explicit-title",
            mode="crawl",
            spec={"title": "高三英语专项"},
            output_dir=self.root / "tasks" / "task-explicit-title",
        )
        titled_dir = self.root / "tasks" / "task-explicit-title" / "英语" / "试卷_r2"
        titled_dir.mkdir(parents=True)
        titled_path = titled_dir / "练习1.png"
        titled_path.write_bytes(b"png")
        self.context.artifacts.register_file(task_id=titled_task["id"], resource_id="r2", path=titled_path)

        titled_items = self.context.artifacts.list_artifacts(task_id="task-explicit-title")

        self.assertEqual(titled_items[0]["task_display_name"], "高三英语专项")

    def test_artifact_browser_lists_task_files_by_virtual_path(self) -> None:
        self.client.post("/api/v1/auth/login", json={"password": "secret"})
        task = self.context.store.create_task(
            task_id="task-browser",
            mode="crawl",
            spec={"title": "生物七上重庆月考"},
            output_dir=self.root / "tasks" / "task-browser",
        )
        resource_dir = self.root / "tasks" / "task-browser" / "生物" / "七年级" / "上学期" / "重庆市" / "月考" / "试卷"
        resource_dir.mkdir(parents=True)
        image_path = resource_dir / "练习1.png"
        image_path.write_bytes(b"png")
        pdf_path = resource_dir / "试卷.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")

        root = self.client.get("/api/v1/artifacts/browser/list", params={"task_id": "task-browser"})

        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json()["current_path"], "")
        self.assertEqual(root.json()["items"][0]["name"], "生物")
        self.assertEqual(root.json()["items"][0]["relative_path"], "生物")
        self.assertNotIn(str(self.root), str(root.json()))

        biological_path = root.json()["items"][0]["relative_path"]
        grade = self.client.get("/api/v1/artifacts/browser/list", params={"task_id": "task-browser", "path": biological_path})
        self.assertEqual(grade.json()["items"][0]["name"], "七年级")

        pdf_search = self.client.get(
            "/api/v1/artifacts/browser/search",
            params={"task_id": "task-browser", "path": "", "filter": "试卷.pdf", "deep": "1"},
        )
        self.assertEqual(pdf_search.status_code, 200)
        self.assertEqual(pdf_search.json()["items"][0]["name"], "试卷.pdf")
        self.assertEqual(pdf_search.json()["items"][0]["relative_path"], "生物/七年级/上学期/重庆市/月考/试卷/试卷.pdf")

        search = self.client.get(
            "/api/v1/artifacts/browser/search",
            params={"task_id": "task-browser", "path": "", "filter": "练习1", "deep": "1"},
        )
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["items"][0]["relative_path"], "生物/七年级/上学期/重庆市/月考/试卷/练习1.png")

        relative_file = search.json()["items"][0]["relative_path"]
        download = self.client.get("/api/v1/artifacts/browser/download", params={"task_id": "task-browser", "path": relative_file})
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"png")

    def test_artifact_browser_global_root_uses_task_display_name(self) -> None:
        self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.context.store.create_task(
            task_id="task-global-browser",
            mode="crawl",
            spec={"title": "重庆月考下载"},
            output_dir=self.root / "tasks" / "task-global-browser",
        )
        resource_dir = self.root / "tasks" / "task-global-browser" / "生物" / "七年级" / "上学期" / "重庆市" / "月考" / "试卷_r1"
        resource_dir.mkdir(parents=True)
        artifact_path = resource_dir / "练习1.png"
        artifact_path.write_bytes(b"png")

        response = self.client.get("/api/v1/artifacts/browser/list")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["name"], "task-global-browser")
        self.assertEqual(response.json()["items"][0]["relative_path"], "task-global-browser")
        self.assertEqual(response.json()["items"][0]["item_type"], "folder")

    def test_task_list_uses_named_filter_snapshot_without_generic_specified_labels(self) -> None:
        self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.context.store.set_setting(
            "catalog_cache",
            {
                "study_phases": {"300": "高中"},
                "subjects": {"300": {"2": "数学"}},
                "catalogs": {
                    "300": {
                        "provinceCode": [{"code": "340000", "name": "安徽"}],
                        "gradeCode": [{"code": "11", "name": "高二"}],
                        "termCode": [{"code": "21", "name": "上学期"}],
                        "sceneCode": [{"code": "8", "name": "期末"}],
                    }
                },
            },
        )
        self.context.store.create_task(
            task_id="task-named-filters",
            mode="crawl",
            spec={
                "title": "",
                "filters": {"provinces": ["340000"], "grades": ["11"], "terms": ["21"], "scenes": ["8"]},
                "subjects": [{"code": "2"}],
                "settings": {"study_phase_code": "300", "file_type": "PDF"},
            },
            output_dir=self.root / "tasks" / "task-named-filters",
        )

        response = self.client.get("/api/v1/tasks")
        name = response.json()["items"][0]["task_display_name"]

        self.assertIn("安徽", name)
        self.assertIn("高二", name)
        self.assertNotIn("指定地区", name)
        self.assertNotIn("指定年级", name)

    def test_artifact_browser_preview_serves_original_pdf_inline(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.assertEqual(login.status_code, 200)
        task = self.context.store.create_task(
            task_id="task-preview",
            mode="crawl",
            spec={"title": "预览原文件"},
            output_dir=self.root / "tasks" / "task-preview",
        )
        resource_dir = self.root / "tasks" / "task-preview" / "数学" / "试卷"
        resource_dir.mkdir(parents=True)
        pdf_path = resource_dir / "试卷.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        search = self.client.get(
            "/api/v1/artifacts/browser/search",
            params={"task_id": "task-preview", "path": "", "filter": "试卷.pdf", "deep": "1"},
        )
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["items"][0]["name"], "试卷.pdf")

        response = self.client.get(
            "/api/v1/artifacts/browser/preview",
            params={"task_id": "task-preview", "path": search.json()["items"][0]["relative_path"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("inline", response.headers["content-disposition"])
        self.assertIn("%E8%AF%95%E5%8D%B7.pdf", response.headers["content-disposition"])
        self.assertEqual(response.content, b"%PDF-1.4 fake")

        download = self.client.get(
            "/api/v1/artifacts/browser/download",
            params={"task_id": "task-preview", "path": search.json()["items"][0]["relative_path"]},
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertIn("%E8%AF%95%E5%8D%B7.pdf", download.headers["content-disposition"])

    def test_artifact_browser_preview_rejects_attachments(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.assertEqual(login.status_code, 200)
        task = self.context.store.create_task(
            task_id="task-attachment-preview",
            mode="crawl",
            spec={"title": "附件预览"},
            output_dir=self.root / "tasks" / "task-attachment-preview",
        )
        resource_dir = self.root / "tasks" / "task-attachment-preview" / "数学" / "试卷_r1"
        resource_dir.mkdir(parents=True)
        txt_path = resource_dir / "答案.txt"
        txt_path.write_text("answer")

        search = self.client.get(
            "/api/v1/artifacts/browser/search",
            params={"task_id": "task-attachment-preview", "path": "", "filter": "答案.txt", "deep": "1"},
        )
        self.assertEqual(search.status_code, 200)

        response = self.client.get(
            "/api/v1/artifacts/browser/preview",
            params={"task_id": "task-attachment-preview", "path": search.json()["items"][0]["relative_path"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be previewed", response.json()["detail"])

    def test_file_browser_rejects_unsafe_paths(self) -> None:
        self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.context.store.create_task(
            task_id="task-safe-browser",
            mode="crawl",
            spec={"title": "安全路径"},
            output_dir=self.root / "tasks" / "task-safe-browser",
        )
        task_root = self.root / "tasks" / "task-safe-browser"
        task_root.mkdir(parents=True)
        (task_root / "visible.txt").write_text("visible", encoding="utf-8")
        (task_root / ".secret.txt").write_text("secret", encoding="utf-8")
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link_path = task_root / "outside-link.txt"
        if hasattr(os, "symlink"):
            os.symlink(outside, link_path)

        root = self.client.get("/api/v1/artifacts/browser/list", params={"task_id": "task-safe-browser"})
        self.assertEqual(root.status_code, 200)
        names = [item["name"] for item in root.json()["items"]]
        self.assertIn("visible.txt", names)
        self.assertNotIn(".secret.txt", names)
        self.assertNotIn("outside-link.txt", names)

        traversal = self.client.get("/api/v1/artifacts/browser/download", params={"task_id": "task-safe-browser", "path": "../outside.txt"})
        self.assertEqual(traversal.status_code, 403)

        absolute = self.client.get("/api/v1/artifacts/browser/download", params={"task_id": "task-safe-browser", "path": str(outside)})
        self.assertEqual(absolute.status_code, 403)

        hidden = self.client.get("/api/v1/artifacts/browser/download", params={"task_id": "task-safe-browser", "path": ".secret.txt"})
        self.assertEqual(hidden.status_code, 403)

        if link_path.exists() or link_path.is_symlink():
            symlink = self.client.get("/api/v1/artifacts/browser/download", params={"task_id": "task-safe-browser", "path": "outside-link.txt"})
            self.assertEqual(symlink.status_code, 403)

    def test_account_credentials_are_encrypted_at_rest(self) -> None:
        db_path = self.root / "accounts.db"
        pool = AccountPool(db_path)
        pool.upsert(
            AccountCredential(
                name="账号A",
                cookie="ACCESS_TOKEN=secret-cookie",
                access_token="secret-token",
                request_headers_json='{"token":"secret-token"}',
                login_password="secret-password",
            )
        )

        with sqlite3.connect(db_path) as connection:
            row = connection.execute(
                "SELECT cookie, access_token, request_headers_json, login_password FROM accounts"
            ).fetchone()

        self.assertTrue(all(str(value).startswith("enc:v1:") for value in row))
        reloaded = AccountPool(db_path).accounts[0]
        self.assertEqual(reloaded.cookie, "ACCESS_TOKEN=secret-cookie")
        self.assertEqual(reloaded.access_token, "secret-token")
        self.assertEqual(reloaded.login_password, "secret-password")

    def test_proxy_status_masks_proxy_credentials(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        csrf = login.json()["csrf_token"]
        response = self.client.put(
            "/api/v1/settings",
            json={
                "proxy_mode": "fixed",
                "proxy_pool": "http://user:pass@127.0.0.1:8088\n10.0.0.2:9000",
            },
            headers={"x-csrf-token": csrf},
        )
        self.assertEqual(response.status_code, 200)

        with patch(
            "stzy_app.domain.proxy_status._detect_public_ip",
            return_value={"ok": True, "ip": "203.0.113.9", "source": "test", "error": ""},
        ):
            status = self.client.get("/api/v1/proxy/status")
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        addresses = [item["address"] for item in payload["items"]]

        self.assertEqual(payload["my_ip"], "203.0.113.9")
        self.assertTrue(payload["my_ip_status"]["ok"])
        self.assertEqual(payload["proxy_mode"], "fixed")
        self.assertEqual(payload["pool_size"], 2)
        self.assertEqual(payload["target_proxy_count"], 2)
        self.assertIn("available_proxy_count", payload)
        self.assertIn("leased_proxy_count", payload)
        self.assertIn("cooldown_proxy_count", payload)
        self.assertIn("effective_download_workers", payload)
        self.assertIn("http://127.0.0.1:8088", addresses)
        self.assertIn("http://10.0.0.2:9000", addresses)
        self.assertNotIn("user:pass", str(payload))

    def test_public_ip_parser_supports_cip_cc_text(self) -> None:
        self.assertIn("https://cip.cc", PUBLIC_IP_ENDPOINTS)
        self.assertEqual(_extract_ip("IP\t: 203.0.113.12\n地址\t: TEST"), "203.0.113.12")

    def test_auth_script_endpoint_returns_console_import_script(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        self.assertEqual(login.status_code, 200)

        response = self.client.get("/api/v1/accounts/auth-script")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ACCESS_TOKEN", response.json()["script"])
        self.assertIn("copy(JSON.stringify", response.json()["script"])

    def test_phone_login_accepts_empty_password_and_custom_name(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        csrf = login.json()["csrf_token"]
        with patch("stzy_app.domain.accounts.login_with_phone_password") as login_mock:
            login_mock.return_value = AccountCredential(
                name="手机号登录-13800138000",
                cookie="ACCESS_TOKEN=fresh",
                access_token="fresh",
                login_phone="13800138000",
                login_password="138000",
            )

            response = self.client.post(
                "/api/v1/accounts/phone-login",
                json={"phone": "13800138000", "password": "", "name": "主账号"},
                headers={"x-csrf-token": csrf},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "主账号")
        login_mock.assert_called_once()
        self.assertEqual(login_mock.call_args.args[1], "13800138000")
        self.assertIsNone(login_mock.call_args.args[2])

    def test_shenlong_bind_local_ip_endpoint_uses_saved_settings(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        csrf = login.json()["csrf_token"]
        response = self.client.put(
            "/api/v1/settings",
            json={
                "proxy_mode": "api",
                "proxy_provider": "shenlong",
                "proxy_api_url": "http://example.test/proxy?key=k&sign=s",
                "shenlong_whitelist_key": "k",
                "shenlong_whitelist_sign": "s",
            },
            headers={"x-csrf-token": csrf},
        )
        self.assertEqual(response.status_code, 200)

        with patch("stzy_app.domain.proxy_status.create_proxy_provider") as provider_mock:
            provider_mock.return_value.prepare.return_value = type(
                "Result",
                (),
                {"ip": "127.0.0.1", "added": True, "message": "本机 IP 已绑定：127.0.0.1"},
            )()
            bind = self.client.post("/api/v1/proxy/bind-local-ip", headers={"x-csrf-token": csrf})

        self.assertEqual(bind.status_code, 200)
        self.assertEqual(bind.json()["ip"], "127.0.0.1")
        provider_mock.assert_called_once()

    def test_settings_strategy_fields_are_saved_and_used_for_task_snapshot(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        csrf = login.json()["csrf_token"]
        response = self.client.put(
            "/api/v1/settings",
            json={"file_type": "IMAGE", "max_pages_per_combo": 2, "study_phase_code": "300"},
            headers={"x-csrf-token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["file_type"], "IMAGE")
        self.assertEqual(response.json()["max_pages_per_combo"], 2)

        runtime_settings = self.context.tasks._runtime_settings()  # noqa: SLF001 - verifies persisted settings are consumed
        snapshot = self.context.tasks._public_settings_snapshot(runtime_settings, {})  # noqa: SLF001

        self.assertEqual(snapshot["file_type"], "IMAGE")
        self.assertEqual(snapshot["max_pages_per_combo"], 2)
        self.assertEqual(snapshot["study_phase_code"], "300")

    def test_task_update_accepts_stats_json_without_double_suffix(self) -> None:
        self.context.store.create_task(
            task_id="task-stats",
            mode="estimate",
            spec={"title": "统计测试"},
            output_dir=self.root / "tasks" / "task-stats",
        )

        self.context.store.update_task("task-stats", stats_json={"resources_seen": 3})
        task = self.context.store.task("task-stats")

        self.assertEqual(task["stats"]["resources_seen"], 3)

        self.context.store.update_task("task-stats", stats={"resources_seen": 5})
        task = self.context.store.task("task-stats")

        self.assertEqual(task["stats"]["resources_seen"], 5)

    def test_completed_task_clears_stale_error_after_resume(self) -> None:
        self.context.store.create_task(
            task_id="task-clear-error",
            mode="crawl",
            spec={"title": "清理错误", "mode": "crawl", "filters": {}, "subjects": [{"code": "math", "name": "数学"}]},
            output_dir=self.root / "tasks" / "task-clear-error",
        )
        self.context.store.set_task_status("task-clear-error", "failed", error="旧代理错误")

        with patch("stzy_app.domain.tasks.CrawlRunner.run", autospec=True) as run_mock:
            run_mock.return_value = CrawlStats(
                task_mode="crawl",
                phase="completed",
                outcome="completed",
                total_combos=1,
                completed_combos=1,
                resources_seen=1,
                resources_completed=1,
            )
            self.context.tasks._run_task("task-clear-error")  # noqa: SLF001 - verifies resume cleanup

        task = self.context.store.task("task-clear-error")

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["error"], "")

    def test_estimate_endpoint_does_not_create_task_record(self) -> None:
        login = self.client.post("/api/v1/auth/login", json={"password": "secret"})
        csrf = login.json()["csrf_token"]
        self.context.store.set_setting(
            "catalog_cache",
            {
                "subjects": {
                    "300": {
                        "math": "数学",
                    }
                }
            },
        )
        seen_settings = {}

        def estimate_stub(runner):
            seen_settings["study_phase_code"] = runner.settings.study_phase_code
            seen_settings["subject_code"] = runner.settings.subject_code
            seen_settings["subject_name"] = runner.settings.subject_name
            return CrawlStats(
                task_mode="estimate",
                phase="preview",
                outcome="estimated",
                total_combos=1,
                completed_combos=1,
                resources_seen=8,
            )

        with patch("stzy_app.domain.tasks.CrawlRunner.estimate", autospec=True) as estimate_mock:
            estimate_mock.side_effect = estimate_stub
            response = self.client.post(
                "/api/v1/tasks/estimate",
                json={
                    "mode": "estimate",
                    "filters": {"terms": ["t1"]},
                    "subjects": [{"code": "math", "name": "数学"}],
                    "settings": {"study_phase_code": "300"},
                    "title": "临时预估",
                },
                headers={"x-csrf-token": csrf},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stats"]["resources_seen"], 8)
        self.assertEqual(seen_settings["study_phase_code"], "300")
        self.assertEqual(seen_settings["subject_code"], "math")
        self.assertEqual(seen_settings["subject_name"], "数学")
        self.assertEqual(self.context.store.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
