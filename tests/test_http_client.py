from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

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
                proxy_pool="",
                proxy_api_url="",
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

    def test_proxy_pool_is_normalized_and_rotated_per_request(self) -> None:
        settings = AppSettings(
            proxy_mode="fixed",
            proxy_pool="127.0.0.1:7890\nhttps://proxy.example:8443",
            proxy_api_url="",
        )
        client = StzyHttpClient(settings)
        client.session.get = Mock(
            side_effect=[
                FakeResponse(payload={"code": 200, "data": {}}),
                FakeResponse(payload={"code": 200, "data": {}}),
                FakeResponse(payload={"code": 200, "data": {}}),
            ]
        )

        client.get_json("/first", headers={})
        client.get_json("/second", headers={})
        client.get_json("/third", headers={})

        first = client.session.get.call_args_list[0].kwargs["proxies"]
        second = client.session.get.call_args_list[1].kwargs["proxies"]
        third = client.session.get.call_args_list[2].kwargs["proxies"]
        self.assertEqual(
            first,
            {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        )
        self.assertEqual(
            second,
            {"http": "https://proxy.example:8443", "https": "https://proxy.example:8443"},
        )
        self.assertEqual(third, first)

    def test_default_proxy_mode_keeps_direct_connection(self) -> None:
        client = StzyHttpClient(AppSettings())

        self.assertIsNone(client._request_proxies())

    def test_http_session_ignores_environment_proxy(self) -> None:
        client = StzyHttpClient(AppSettings())

        self.assertFalse(client.session.trust_env)

    def test_default_proxy_settings_are_off(self) -> None:
        settings = AppSettings()

        self.assertEqual(settings.proxy_mode, "off")
        self.assertEqual(settings.proxy_pool, "")
        self.assertEqual(settings.proxy_api_url, "")

    def test_proxy_api_url_is_ignored_when_proxy_mode_is_off(self) -> None:
        client = StzyHttpClient(
            AppSettings(proxy_mode="off", proxy_pool="", proxy_api_url="http://api.example/get")
        )

        with patch("stzy_app.proxy.providers._direct_get") as proxy_api:
            self.assertIsNone(client._request_proxies())

        proxy_api.assert_not_called()

    def test_socks5_proxy_pool_is_preserved(self) -> None:
        proxy = "socks5://user:pass@proxy.example:443"
        client = StzyHttpClient(AppSettings(proxy_mode="fixed", proxy_pool=proxy, proxy_api_url=""))

        self.assertEqual(client._request_proxies(), {"http": proxy, "https": proxy})

    def test_fixed_proxy_pool_uses_one_proxy_per_line(self) -> None:
        client = StzyHttpClient(
            AppSettings(
                proxy_mode="fixed",
                proxy_pool="proxy-a.test:7000,proxy-b.test:7001;proxy-c.test:7002",
                proxy_api_url="",
            )
        )

        self.assertEqual(
            client._proxy_urls,
            ["http://proxy-a.test:7000,proxy-b.test:7001;proxy-c.test:7002"],
        )

    def test_proxy_api_is_used_when_static_pool_is_empty(self) -> None:
        client = StzyHttpClient(
            AppSettings(
                proxy_mode="api",
                proxy_pool="",
                proxy_api_url="http://api.example/proxy",
            )
        )
        client.session.get = Mock(return_value=FakeResponse(payload={"code": 200, "data": {}}))

        with patch(
            "stzy_app.proxy.providers._direct_get",
            return_value=FakeResponse(payload={"proxy": "api-proxy.test:9000"}),
        ):
            client.get_json("/resource", headers={})

        self.assertEqual(
            client.session.get.call_args.kwargs["proxies"],
            {"http": "http://api-proxy.test:9000", "https": "http://api-proxy.test:9000"},
        )

    def test_proxy_api_accepts_shenlong_json_payload(self) -> None:
        client = StzyHttpClient(
            AppSettings(proxy_mode="api", proxy_pool="", proxy_api_url="http://api.shenlongip.com/ip")
        )
        client.session.get = Mock(return_value=FakeResponse(payload={"code": 200, "data": {}}))

        with patch(
            "stzy_app.proxy.providers._direct_get",
            return_value=FakeResponse(
                payload={
                    "code": 200,
                    "data": [
                        {
                            "ip": "113.88.12.34",
                            "port": 16888,
                            "expire": "2026-09-02 12:00:00",
                            "city": "广州",
                            "isp": "电信",
                        }
                    ],
                }
            ),
        ):
            client.get_json("/resource", headers={})

        self.assertEqual(
            client.session.get.call_args.kwargs["proxies"],
            {"http": "http://113.88.12.34:16888", "https": "http://113.88.12.34:16888"},
        )

    def test_proxy_api_proxy_is_reused_until_failure(self) -> None:
        client = StzyHttpClient(
            AppSettings(proxy_mode="api", proxy_pool="", proxy_api_url="http://api.shenlongip.com/ip")
        )
        client.session.get = Mock(
            side_effect=[
                FakeResponse(payload={"code": 200, "data": {}}),
                FakeResponse(payload={"code": 200, "data": {}}),
            ]
        )

        with patch(
            "stzy_app.proxy.providers._direct_get",
            return_value=FakeResponse(
                payload={"code": 200, "data": [{"ip": "113.88.12.34", "port": 16888}]}
            ),
        ) as proxy_api:
            client.get_json("/first", headers={})
            client.get_json("/second", headers={})

        self.assertEqual(proxy_api.call_count, 1)
        self.assertEqual(
            client.session.get.call_args_list[1].kwargs["proxies"],
            {"http": "http://113.88.12.34:16888", "https": "http://113.88.12.34:16888"},
        )

    def test_proxy_api_refreshes_after_cached_proxy_failure(self) -> None:
        client = StzyHttpClient(
            AppSettings(
                proxy_mode="api",
                proxy_pool="",
                proxy_api_url="http://api.shenlongip.com/ip",
                proxy_max_failures=1,
                proxy_cooldown_seconds=60,
            )
        )
        client.session.get = Mock(
            side_effect=[
                requests.ConnectionError("proxy failed"),
                FakeResponse(payload={"code": 200, "data": {}}),
            ]
        )

        with patch(
            "stzy_app.proxy.providers._direct_get",
            side_effect=[
                FakeResponse(payload={"code": 200, "data": [{"ip": "113.88.12.34", "port": 16888}]}),
                FakeResponse(payload={"code": 200, "data": [{"ip": "49.85.120.175", "port": 40078}]}),
            ],
        ) as proxy_api:
            with self.assertRaises(requests.ConnectionError):
                client.get_json("/first", headers={})
            client.get_json("/second", headers={})

        self.assertEqual(proxy_api.call_count, 2)
        self.assertEqual(
            client.session.get.call_args_list[1].kwargs["proxies"],
            {"http": "http://49.85.120.175:40078", "https": "http://49.85.120.175:40078"},
        )

    def test_failed_proxy_enters_cooldown(self) -> None:
        client = StzyHttpClient(
            AppSettings(
                proxy_mode="fixed",
                proxy_pool="proxy-a.test:7000\nproxy-b.test:7001",
                proxy_api_url="",
                proxy_max_failures=1,
                proxy_cooldown_seconds=60,
            )
        )
        client.session.get = Mock(
            side_effect=[
                FakeResponse(payload={"code": 200, "data": {}}, status_code=429),
                FakeResponse(payload={"code": 200, "data": {}}, status_code=200),
            ]
        )

        client.get_json("/first", headers={})
        client.get_json("/second", headers={})

        first = client.session.get.call_args_list[0].kwargs["proxies"]
        second = client.session.get.call_args_list[1].kwargs["proxies"]
        self.assertEqual(first["http"], "http://proxy-a.test:7000")
        self.assertEqual(second["http"], "http://proxy-b.test:7001")
        self.assertIn("http://proxy-a.test:7000", client._proxy_cooldowns)

    def test_proxy_callback_runs_after_successful_request(self) -> None:
        proxies = []
        client = StzyHttpClient(
            AppSettings(proxy_mode="fixed", proxy_pool="proxy-a.test:7000", proxy_api_url=""),
            on_proxy=proxies.append,
        )
        client.session.get = Mock(return_value=FakeResponse(payload={"code": 200, "data": {}}))

        client.get_json("/resource", headers={})

        self.assertEqual(proxies, ["http://proxy-a.test:7000"])

    @staticmethod
    def _jwt(payload: dict[str, object]) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{encoded}.signature"


class FakeResponse:
    def __init__(
        self,
        *,
        payload: dict[str, object] | None = None,
        cookies=None,
        status_code: int = 200,
        text: str = "",
    ) -> None:
        self._payload = payload or {}
        self.cookies = cookies or []
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload
