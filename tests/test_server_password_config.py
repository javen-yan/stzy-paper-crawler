from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stzy_app.config import AppSettings
from stzy_app.domain.identity import hash_password, verify_password
from stzy_app.main import _settings_with_server_password


class ServerPasswordConfigTest(unittest.TestCase):
    def test_server_requires_explicit_admin_password(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            _settings_with_server_password(AppSettings())

        self.assertIn("必须配置管理员密码", str(raised.exception))

    def test_server_rejects_weak_plain_password(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            _settings_with_server_password(AppSettings(admin_password="1234567890"))

        self.assertIn("过于简单", str(raised.exception))

    def test_server_accepts_admin_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            password_file = Path(tmpdir) / "admin-password"
            password_file.write_text("Admin-pass-2026\n", encoding="utf-8")

            settings = _settings_with_server_password(AppSettings(admin_password_file=password_file))

        self.assertFalse(settings.admin_password)
        self.assertTrue(settings.admin_password_hash.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password("Admin-pass-2026", settings.admin_password_hash))

    def test_existing_hash_takes_precedence(self) -> None:
        encoded = hash_password("configured-secret")

        settings = _settings_with_server_password(
            AppSettings(admin_password_hash=encoded, admin_password="weak")
        )

        self.assertEqual(settings.admin_password_hash, encoded)


if __name__ == "__main__":
    unittest.main()
