from __future__ import annotations

import unittest
from unittest.mock import patch

from stzy_app.config import AppSettings
from stzy_app.proxy import GenericProxyProvider, ShenlongProxyProvider, create_proxy_provider
from stzy_app.proxy.providers import current_public_ip


class ShenlongWhitelistTest(unittest.TestCase):
    def test_ensure_whitelist_adds_current_public_ip_when_missing(self) -> None:
        client = ShenlongProxyProvider(
            AppSettings(
                proxy_provider="shenlong",
                shenlong_whitelist_key="account",
                shenlong_whitelist_sign="sign",
            )
        )

        with patch.object(client, "current_public_ip", return_value="49.85.120.175"), patch.object(
            client, "_request",
            side_effect=[
                {"code": 200, "data": []},
                {"code": 200, "msg": "ok"},
            ],
        ) as api:
            result = client.prepare()

        self.assertTrue(result.added)
        self.assertEqual(result.ip, "49.85.120.175")
        self.assertEqual(api.call_args_list[0].args, ("/white/fetch", "49.85.120.175"))
        self.assertEqual(api.call_args_list[1].args, ("/white/add", "49.85.120.175"))

    def test_ensure_whitelist_keeps_existing_public_ip(self) -> None:
        client = ShenlongProxyProvider(
            AppSettings(
                proxy_provider="shenlong",
                shenlong_whitelist_key="account",
                shenlong_whitelist_sign="sign",
            )
        )

        with patch.object(client, "current_public_ip", return_value="49.85.120.175"), patch.object(
            client,
            "_request",
            return_value={"code": 200, "data": ["49.85.120.175"]},
        ) as api:
            result = client.prepare()

        self.assertFalse(result.added)
        self.assertEqual(result.ip, "49.85.120.175")
        self.assertEqual(api.call_count, 1)

    def test_settings_can_read_whitelist_credentials_from_proxy_api_url(self) -> None:
        settings = AppSettings(
            proxy_mode="api",
            proxy_api_url="http://api.shenlongip.com/ip?key=account&sign=sign",
        )

        client = ShenlongProxyProvider(settings)

        self.assertEqual(client.key, "account")
        self.assertEqual(client.sign, "sign")

    def test_public_ip_is_read_from_json_or_text(self) -> None:
        client = ShenlongProxyProvider(
            AppSettings(
                proxy_provider="shenlong",
                shenlong_whitelist_key="account",
                shenlong_whitelist_sign="sign",
            )
        )

        with patch(
            "stzy_app.proxy.providers._direct_get",
            return_value=FakeResponse(payload={"ip": "49.85.120.175"}),
        ):
            self.assertEqual(client.current_public_ip(), "49.85.120.175")

        with patch(
            "stzy_app.proxy.providers._direct_get",
            return_value=FakeResponse(text="当前 IP：49.85.120.175"),
        ):
            self.assertEqual(client.current_public_ip(), "49.85.120.175")

    def test_public_ip_request_ignores_environment_proxy(self) -> None:
        sessions = []

        class FakeSession:
            def __init__(self) -> None:
                self.trust_env = True

            def get(self, url: str, *, timeout: tuple[float, float]) -> FakeResponse:
                return FakeResponse(payload={"ip": "49.85.120.175"})

        def create_session() -> FakeSession:
            session = FakeSession()
            sessions.append(session)
            return session

        with patch("stzy_app.proxy.providers.requests.Session", side_effect=create_session):
            self.assertEqual(current_public_ip((1, 2)), "49.85.120.175")

        self.assertFalse(sessions[0].trust_env)

    def test_missing_credentials_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "白名单账号和签名"):
            ShenlongProxyProvider(AppSettings(proxy_provider="shenlong")).prepare()

    def test_factory_uses_explicit_provider(self) -> None:
        self.assertIsInstance(
            create_proxy_provider(AppSettings(proxy_provider="shenlong")),
            ShenlongProxyProvider,
        )
        self.assertIsInstance(
            create_proxy_provider(
                AppSettings(
                    proxy_provider="generic",
                    proxy_api_url="http://api.shenlongip.com/ip?key=account&sign=sign",
                )
            ),
            GenericProxyProvider,
        )


class FakeResponse:
    def __init__(self, *, payload=None, text: str = "") -> None:
        self._payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


if __name__ == "__main__":
    unittest.main()
