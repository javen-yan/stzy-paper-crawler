from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from stzy_app.auth import (
    credential_from_auth_import,
    login_with_phone_password,
    normalize_auth_import,
    parse_auth_import,
)
from stzy_app.config import AppSettings
from stzy_app.http.client import StzyHttpClient
from stzy_app.security import decrypt_text
from stzy_app.storage import AccountCredential, AccountPool


class PhoneLoginTest(unittest.TestCase):
    def test_manual_import_extracts_token_from_cookie_json(self) -> None:
        token = self._jwt({"exp": time.time() + 3600, "nickName": "151****3888"})
        raw_value = json.dumps(
            {
                "cookie": f"B_USER_INFO_KEY={{}}; ACCESS_TOKEN={token}; selectInfo={{}}",
                "access_token": "",
                "user_agent": "Mozilla/5.0 Real Browser",
            }
        )

        cookie, access_token, user_agent = normalize_auth_import(raw_value)
        credential = credential_from_auth_import(raw_value)

        self.assertEqual(cookie, f"B_USER_INFO_KEY={{}}; ACCESS_TOKEN={token}; selectInfo={{}}")
        self.assertEqual(access_token, token)
        self.assertEqual(user_agent, "Mozilla/5.0 Real Browser")
        self.assertEqual(credential.cookie, f"B_USER_INFO_KEY={{}}; ACCESS_TOKEN={token}; selectInfo={{}}")
        self.assertEqual(credential.access_token, token)
        self.assertEqual(credential.user_agent, "Mozilla/5.0 Real Browser")
        self.assertEqual(credential.name, "151****3888")

    def test_manual_import_parses_devtools_fetch_request(self) -> None:
        token = self._jwt({"exp": time.time() + 3600, "nickName": "151****3888"})
        raw_value = f'''fetch("https://qms.stzy.com/matrix/zw-zzw/api/v1/zzw/user/detail", {{
  "headers": {{
    "accept": "application/json, text/plain, */*",
    "origin": "https://www.stzy.com",
    "sec-ch-ua": "\\"Chromium\\";v=\\"152\\"",
    "token": "{token}",
    "user-agent": "Mozilla/5.0 Real Browser",
    "x-plat-type": "pt_stw"
  }},
  "referrer": "https://www.stzy.com/",
  "body": null,
  "method": "GET",
  "mode": "cors",
  "credentials": "omit"
}});'''

        parsed = parse_auth_import(raw_value)

        self.assertEqual(parsed["access_token"], token)
        self.assertEqual(parsed["user_agent"], "Mozilla/5.0 Real Browser")
        self.assertEqual(parsed["request_headers"]["referer"], "https://www.stzy.com/")
        self.assertEqual(parsed["request_headers"]["sec-ch-ua"], '"Chromium";v="152"')
        self.assertEqual(parsed["request_headers"]["x-plat-type"], "pt_stw")
        self.assertEqual(parsed["import_method"], "network_fetch")

    def test_manual_import_parses_devtools_curl_request(self) -> None:
        token = self._jwt({"exp": time.time() + 3600, "nickName": "151****3888"})
        raw_value = f"""curl --url 'https://qms.stzy.com/matrix/zw-zzw/api/v1/zzw/user/detail' \\
  -H 'accept: application/json, text/plain, */*' \\
  -H 'origin: https://www.stzy.com' \\
  -H 'referer: https://www.stzy.com/' \\
  -H 'sec-ch-ua: "Chromium";v="152", "Google Chrome";v="152"' \\
  -H 'token: {token}' \\
  -H 'user-agent: Mozilla/5.0 Real Browser' \\
  -H 'x-plat-type: pt_stw'"""

        parsed = parse_auth_import(raw_value)

        self.assertEqual(parsed["access_token"], token)
        self.assertEqual(parsed["user_agent"], "Mozilla/5.0 Real Browser")
        self.assertEqual(parsed["request_headers"]["origin"], "https://www.stzy.com")
        self.assertIn("Google Chrome", parsed["request_headers"]["sec-ch-ua"])
        self.assertEqual(parsed["import_method"], "network_curl")

    def test_manual_import_chooses_freshest_token_from_candidates(self) -> None:
        expired = self._jwt({"exp": time.time() - 60, "nickName": "old"})
        fresh = self._jwt({"exp": time.time() + 3600, "nickName": "fresh"})
        raw_value = json.dumps(
            {
                "cookie": f"foo=bar; ACCESS_TOKEN={expired}; selectInfo={{}}",
                "access_token": expired,
                "tokens": [
                    {"source": "localStorage", "access_token": expired},
                    {"source": "cookie.ACCESS_TOKEN", "access_token": fresh},
                ],
            }
        )

        cookie, access_token, _user_agent = normalize_auth_import(raw_value)
        credential = credential_from_auth_import(raw_value)

        self.assertEqual(cookie, f"foo=bar; ACCESS_TOKEN={fresh}; selectInfo={{}}")
        self.assertEqual(access_token, fresh)
        self.assertEqual(credential.access_token, fresh)
        self.assertEqual(credential.cookie, f"foo=bar; ACCESS_TOKEN={fresh}; selectInfo={{}}")
        self.assertEqual(credential.name, "fresh")

    def test_manual_import_headers_keep_cookie_token_and_user_agent(self) -> None:
        token = self._jwt({"exp": time.time() + 3600, "nickName": "fresh"})
        cookie = f"B_USER_INFO_KEY={{}}; ACCESS_TOKEN={token}; selectInfo={{}}"
        credential = credential_from_auth_import(
            json.dumps(
                {
                    "cookie": cookie,
                    "access_token": token,
                    "user_agent": "Mozilla/5.0 Real Browser",
                }
            )
        )
        client = StzyHttpClient(AppSettings(proxy_pool="", proxy_api_url=""))

        headers = client.headers_for_account(credential)

        self.assertEqual(headers["cookie"], cookie)
        self.assertEqual(headers["token"], token)
        self.assertEqual(headers["user-agent"], "Mozilla/5.0 Real Browser")

    def test_manual_import_rejects_expired_token_with_expiration_time(self) -> None:
        expires_at = time.time() - 60
        token = self._jwt({"exp": expires_at, "nickName": "151****3888"})
        expires_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at))

        with self.assertRaisesRegex(ValueError, expires_text):
            credential_from_auth_import(json.dumps({"access_token": token}))

    def test_phone_login_defaults_to_last_six_digits_password(self) -> None:
        captured_payload: dict[str, str] = {}
        token = self._jwt({"exp": time.time() + 3600, "mobile": "13800138000"})

        def fake_post_json(_client, path, payload, *, headers=None):
            captured_payload.update(payload)
            self.assertEqual(path, "/zw-auth/oauth/passwordLogin")
            self.assertEqual(headers, {})
            return {"code": 200, "data": {"access_token": token}}

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = AppSettings(
                state_file=Path(tmpdir) / "stzy.db",
                account_pool_file=Path(tmpdir) / "stzy.db",
                proxy_pool="",
                proxy_api_url="",
            )
            with patch("stzy_app.http.client.StzyHttpClient.post_json", fake_post_json):
                credential = login_with_phone_password(settings, "13800138000")

        self.assertEqual(self._decrypt(captured_payload["loginName"]), "13800138000")
        self.assertEqual(self._decrypt(captured_payload["password"]), "138000")
        self.assertEqual(credential.access_token, token)
        self.assertEqual(credential.cookie, f"ACCESS_TOKEN={token}")
        self.assertEqual(credential.user_agent, settings.user_agent)
        self.assertEqual(credential.name, "手机号登录-13800138000")

    def test_client_refreshes_expired_phone_account(self) -> None:
        expired = self._jwt({"exp": time.time() - 60, "mobile": "13800138000"})
        fresh = self._jwt({"exp": time.time() + 3600, "mobile": "13800138000"})

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = AppSettings(
                state_file=Path(tmpdir) / "stzy.db",
                account_pool_file=Path(tmpdir) / "stzy.db",
                proxy_pool="",
                proxy_api_url="",
            )
            AccountPool(settings.account_pool_file).upsert(
                AccountCredential(
                    name="手机号登录-13800138000",
                    cookie=f"ACCESS_TOKEN={expired}",
                    access_token=expired,
                    login_phone="13800138000",
                    login_password="138000",
                )
            )

            with patch("stzy_app.auth.login_with_phone_password") as login_mock:
                login_mock.return_value = AccountCredential(
                    name="手机号登录-13800138000",
                    cookie=f"ACCESS_TOKEN={fresh}",
                    access_token=fresh,
                    login_phone="13800138000",
                    login_password="138000",
                )

                client = StzyHttpClient(settings)
                account = client.account_pool.accounts[0]

                self.assertTrue(client.account_is_valid(account))

            saved = AccountPool(settings.account_pool_file).accounts[0]
            self.assertEqual(saved.access_token, fresh)

    @staticmethod
    def _decrypt(value: str) -> str:
        return decrypt_text(value)

    @staticmethod
    def _jwt(payload: dict[str, object]) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return f"header.{encoded}.signature"
