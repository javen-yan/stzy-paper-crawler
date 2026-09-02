from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from stzy_app.config import AppSettings
from stzy_app.http.client import StzyHttpClient
from stzy_app.storage import AccountCredential, AccountPool


class HttpClientAuthTest(unittest.TestCase):
    def test_expired_jwt_is_not_valid(self) -> None:
        token = self._jwt({"exp": time.time() - 60})

        self.assertFalse(StzyHttpClient.auth_is_valid(access_token=token))

    def test_future_jwt_reports_expiration(self) -> None:
        expires_at = time.time() + 3600
        token = self._jwt({"exp": expires_at})

        self.assertTrue(StzyHttpClient.auth_is_valid(access_token=token))
        self.assertAlmostEqual(StzyHttpClient.auth_expires_at(access_token=token), expires_at)

    def test_refresh_account_from_cookie_updates_token_and_headers(self) -> None:
        old_token = self._jwt({"exp": time.time() - 60})
        new_token = self._jwt({"exp": time.time() + 3600, "nickName": "fresh"})

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = AppSettings(
                state_file=Path(tmpdir) / "stzy.db",
                account_pool_file=Path(tmpdir) / "stzy.db",
            )
            pool = AccountPool(settings.account_pool_file)
            pool.upsert(
                AccountCredential(
                    name="账号A",
                    cookie=f"foo=bar; ACCESS_TOKEN={old_token}",
                    access_token=old_token,
                    user_agent="Mozilla/5.0 Real Browser",
                    request_headers_json=json.dumps({"referer": "https://www.stzy.com/"}),
                )
            )
            client = StzyHttpClient(settings)
            account = client.account_pool.accounts[0]
            html_response = FakeResponse(
                cookies=[SimpleNamespace(name="ACCESS_TOKEN", value=new_token)]
            )
            api_response = FakeResponse(payload={"code": 200, "data": {"nickName": "fresh"}})
            client.session.get = Mock(side_effect=[html_response, api_response])

            self.assertTrue(client.refresh_account_from_cookie(account))

            saved = AccountPool(settings.account_pool_file).accounts[0]
            self.assertEqual(saved.access_token, new_token)
            self.assertIn(f"ACCESS_TOKEN={new_token}", saved.cookie)
            self.assertEqual(saved.request_headers["token"], new_token)
            self.assertEqual(saved.request_headers["user-agent"], "Mozilla/5.0 Real Browser")

    @staticmethod
    def _jwt(payload: dict[str, object]) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{encoded}.signature"


class FakeResponse:
    def __init__(self, *, payload: dict[str, object] | None = None, cookies=None) -> None:
        self._payload = payload or {}
        self.cookies = cookies or []

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload
