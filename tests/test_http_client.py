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
from stzy_app.http.client import ProxyPool, RequestStopped, StzyHttpClient, display_proxy_url
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

    def test_fixed_proxy_pool_round_robins_available_proxies(self) -> None:
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

    def test_proxy_pool_logs_cooldown_without_request_level_switch_spam(self) -> None:
        events: list[str] = []
        settings = AppSettings(
            proxy_mode="fixed",
            proxy_pool="http://user:secret@proxy-a.test:7000\nproxy-b.test:7001",
            proxy_api_url="",
            proxy_max_failures=1,
        )
        pool = ProxyPool(settings, on_event=events.append)

        first = pool.next_proxy_url()
        pool.record_failure(first)
        second = pool.next_proxy_url()

        self.assertEqual(first, "http://user:secret@proxy-a.test:7000")
        self.assertEqual(second, "http://proxy-b.test:7001")
        log_text = "\n".join(events)
        self.assertIn("代理不可用，已换下一个：http://proxy-a.test:7000", log_text)
        self.assertNotIn("代理切换", log_text)
        self.assertNotIn("secret", log_text)

    def test_display_proxy_url_hides_credentials(self) -> None:
        self.assertEqual(
            display_proxy_url("socks5://user:pass@149.119.185.209:443"),
            "socks5://149.119.185.209:443",
        )

    def test_default_proxy_mode_keeps_direct_connection(self) -> None:
        client = StzyHttpClient(AppSettings())

        self.assertIsNone(client._request_proxies())

    def test_http_session_ignores_environment_proxy(self) -> None:
        client = StzyHttpClient(AppSettings())

        self.assertFalse(client.session.trust_env)

    def test_stopped_client_does_not_start_new_request(self) -> None:
        client = StzyHttpClient(AppSettings(), should_stop=lambda: True)
        client.session.get = Mock()

        with self.assertRaises(RequestStopped):
            client.get_json("/resource", headers={})

        client.session.get.assert_not_called()

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
            client.proxy_pool.fixed_urls,
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

    def test_proxy_api_pool_is_shared_across_clients(self) -> None:
        settings = AppSettings(
            proxy_mode="api",
            proxy_pool="",
            proxy_api_url="http://api.shenlongip.com/ip",
        )
        proxy_pool = ProxyPool(settings)
        first_client = StzyHttpClient(settings, proxy_pool=proxy_pool)
        second_client = StzyHttpClient(settings, proxy_pool=proxy_pool)
        first_client.session.get = Mock(return_value=FakeResponse(payload={"code": 200, "data": {}}))
        second_client.session.get = Mock(return_value=FakeResponse(payload={"code": 200, "data": {}}))

        with patch(
            "stzy_app.proxy.providers._direct_get",
            return_value=FakeResponse(
                payload={"code": 200, "data": [{"ip": "113.88.12.34", "port": 16888}]}
            ),
        ) as proxy_api:
            first_client.get_json("/first", headers={})
            second_client.get_json("/second", headers={})

        self.assertEqual(proxy_api.call_count, 1)
        expected = {"http": "http://113.88.12.34:16888", "https": "http://113.88.12.34:16888"}
        self.assertEqual(first_client.session.get.call_args.kwargs["proxies"], expected)
        self.assertEqual(second_client.session.get.call_args.kwargs["proxies"], expected)

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

    def test_proxy_api_fills_pool_to_concurrency_and_round_robins(self) -> None:
        settings = AppSettings(
            proxy_mode="api",
            proxy_pool="",
            proxy_api_url="http://api.shenlongip.com/ip?count=1&pattern=json",
            concurrency=3,
        )
        pool = ProxyPool(settings)

        with patch(
            "stzy_app.proxy.providers._direct_get",
            return_value=FakeResponse(
                payload={
                    "code": 200,
                    "data": [
                        {"ip": "113.88.12.34", "port": 16888},
                        {"ip": "49.85.120.175", "port": 40078},
                        {"ip": "60.167.20.98", "port": 40031},
                    ],
                }
            ),
        ) as proxy_api:
            proxies = [pool.next_proxy_url() for _ in range(4)]

        self.assertIn("count=3", proxy_api.call_args.args[0])
        self.assertEqual(
            proxies,
            [
                "http://113.88.12.34:16888",
                "http://49.85.120.175:40078",
                "http://60.167.20.98:40031",
                "http://113.88.12.34:16888",
            ],
        )
        self.assertEqual(proxy_api.call_count, 1)

    def test_proxy_api_removes_failed_proxy_and_refills_missing_slot(self) -> None:
        settings = AppSettings(
            proxy_mode="api",
            proxy_pool="",
            proxy_api_url="http://api.shenlongip.com/ip?count=1",
            concurrency=2,
            proxy_max_failures=1,
            proxy_cooldown_seconds=60,
        )
        pool = ProxyPool(settings)

        with patch(
            "stzy_app.proxy.providers._direct_get",
            side_effect=[
                FakeResponse(
                    payload={
                        "code": 200,
                        "data": [
                            {"ip": "113.88.12.34", "port": 16888},
                            {"ip": "49.85.120.175", "port": 40078},
                        ],
                    }
                ),
                FakeResponse(
                    payload={"code": 200, "data": [{"ip": "60.167.20.98", "port": 40031}]}
                ),
            ],
        ) as proxy_api:
            failed_proxy = pool.next_proxy_url()
            pool.next_proxy_url()
            pool.record_failure(failed_proxy)

        self.assertEqual(proxy_api.call_count, 2)
        self.assertNotIn(failed_proxy, pool.api_urls)
        self.assertEqual(
            set(pool.api_urls),
            {"http://49.85.120.175:40078", "http://60.167.20.98:40031"},
        )
        self.assertIn(failed_proxy, pool.cooldowns)

    def test_invalid_download_content_retries_with_next_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "paper.pdf"
            client = StzyHttpClient(
                AppSettings(
                    proxy_mode="fixed",
                    proxy_pool="proxy-a.test:7000\nproxy-b.test:7001",
                    proxy_max_failures=1,
                )
            )
            client.session.get = Mock(
                side_effect=[
                    FakeResponse(content=b"<html>proxy failed</html>", headers={"content-type": "text/html"}),
                    FakeResponse(content=b"%PDF-1.7\nok", headers={"content-type": "application/pdf"}),
                ]
            )

            written = client.download("https://cdn.test/paper.pdf", target, headers={})
            downloaded = target.read_bytes()

            self.assertEqual(written, 11)
            self.assertEqual(downloaded, b"%PDF-1.7\nok")
            first = client.session.get.call_args_list[0].kwargs["proxies"]
            second = client.session.get.call_args_list[1].kwargs["proxies"]
            self.assertEqual(first["http"], "http://proxy-a.test:7000")
            self.assertEqual(second["http"], "http://proxy-b.test:7001")

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
        self.assertIn("http://proxy-a.test:7000", client.proxy_pool.cooldowns)

    def test_late_success_does_not_restore_cooled_proxy(self) -> None:
        pool = ProxyPool(
            AppSettings(
                proxy_mode="fixed",
                proxy_pool="proxy-a.test:7000\nproxy-b.test:7001",
                proxy_api_url="",
                proxy_max_failures=1,
                proxy_cooldown_seconds=60,
            )
        )

        first = pool.next_proxy_url()
        pool.record_failure(first)
        pool.record_success(first)
        second = pool.next_proxy_url()

        self.assertEqual(first, "http://proxy-a.test:7000")
        self.assertEqual(second, "http://proxy-b.test:7001")
        self.assertIn(first, pool.cooldowns)

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
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload or {}
        self.cookies = cookies or []
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]
