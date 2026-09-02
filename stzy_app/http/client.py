from __future__ import annotations

import json
import base64
import time
from pathlib import Path
from typing import Any

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stzy_app.config import AppSettings
from stzy_app.storage.accounts import AccountCredential, AccountPool


class StzyApiError(RuntimeError):
    """Error returned by the STZY JSON API."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"STZY API error {code}: {message}")

    @property
    def requires_login(self) -> bool:
        return self.code == "-1" or "登录" in self.message


class StzyHttpClient:
    """Small requests-based client for STZY public endpoints."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.account_pool = AccountPool(settings.account_pool_file)
        self.session = self._build_session()

    def _build_session(self) -> Session:
        session = requests.Session()
        retry = Retry(
            total=self.settings.max_retries,
            connect=self.settings.max_retries,
            read=self.settings.max_retries,
            status=self.settings.max_retries,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST", "PUT"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(self._base_headers())
        return session

    def _base_headers(self) -> dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": self.settings.site_base_url,
            "referer": f"{self.settings.site_base_url}/layout/paper-lib",
            "user-agent": self.settings.user_agent,
            "x-plat-type": "pt_stw",
        }

    def _auth_headers(self) -> dict[str, str]:
        headers = {}
        account = self.account_pool.next_matching(self.account_is_valid)
        if account:
            return self.headers_for_account(account)
        if self.settings.access_token:
            headers["token"] = self.settings.access_token
        if self.settings.cookie_header:
            headers["cookie"] = self.settings.cookie_header
            token = self._token_from_cookie_header(self.settings.cookie_header)
            if token and "token" not in headers:
                headers["token"] = token
        elif self.settings.cookie_file.exists():
            cookie_header = self._load_cookie_header(self.settings.cookie_file)
            if cookie_header:
                headers["cookie"] = cookie_header
                token = self._load_access_token(
                    self.settings.cookie_file
                ) or self._token_from_cookie_header(cookie_header)
                if token and "token" not in headers:
                    headers["token"] = token
        return headers

    def headers_for_account(self, account: AccountCredential) -> dict[str, str]:
        headers = {
            key: value
            for key, value in account.request_headers.items()
            if key not in {"host", "content-length"} and value
        }
        token = account.access_token or self._token_from_cookie_header(account.cookie)
        if token:
            headers["token"] = token
        if account.cookie:
            headers["cookie"] = account.cookie
        if account.user_agent:
            headers["user-agent"] = account.user_agent
        return headers

    def probe_auth(
        self,
        *,
        cookie_header: str = "",
        access_token: str = "",
        user_agent: str = "",
        request_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = self.headers_for_account(
            AccountCredential(
                name="probe",
                cookie=cookie_header,
                access_token=access_token,
                user_agent=user_agent,
                request_headers_json=json.dumps(request_headers or {}, ensure_ascii=False),
            )
        )
        if not headers.get("token"):
            raise StzyApiError("-1", "没有识别到 Token")
        return self.get_json("/zw-zzw/api/v1/zzw/user/detail", headers=headers)

    def has_auth(self) -> bool:
        if any(self.account_is_valid(account) for account in self.account_pool.enabled_accounts()):
            return True
        if self.auth_is_valid(
            cookie_header=self.settings.cookie_header or "",
            access_token=self.settings.access_token or "",
        ):
            return True
        if self.settings.cookie_file.exists():
            return self.auth_is_valid(
                cookie_header=self._load_cookie_header(self.settings.cookie_file),
                access_token=self._load_access_token(self.settings.cookie_file),
            )
        return False

    def enabled_account_names(self) -> list[str]:
        return [
            account.name
            for account in self.account_pool.schedulable_accounts()
            if self.account_is_valid(account)
        ]

    def enabled_valid_accounts(self) -> list[AccountCredential]:
        return [
            account
            for account in self.account_pool.schedulable_accounts()
            if self.account_is_valid(account)
        ]

    def account_is_valid(self, account) -> bool:
        if account.access_token or self._token_from_cookie_header(account.cookie):
            try:
                self.probe_auth(
                    cookie_header=account.cookie,
                    access_token=account.access_token,
                    user_agent=account.user_agent,
                    request_headers=account.request_headers,
                )
                return True
            except Exception:  # noqa: BLE001
                pass
        if self.refresh_account_from_cookie(account):
            return True
        if not account.login_phone:
            return False
        try:
            from stzy_app.auth import login_with_phone_password

            refreshed = login_with_phone_password(
                self.settings,
                account.login_phone,
                account.login_password,
            )
        except Exception:  # noqa: BLE001
            return False
        refreshed.name = account.name
        refreshed.enabled = account.enabled
        self.account_pool.upsert(refreshed)
        account.cookie = refreshed.cookie
        account.access_token = refreshed.access_token
        account.user_agent = refreshed.user_agent
        account.request_headers_json = refreshed.request_headers_json
        account.import_method = refreshed.import_method
        account.login_phone = refreshed.login_phone
        account.login_password = refreshed.login_password
        return True

    def refresh_account_from_cookie(self, account: AccountCredential, *, persist: bool = True) -> bool:
        if not account.cookie:
            return False
        headers = self.headers_for_account(account)
        headers.pop("token", None)
        headers.update(
            {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "referer": self.settings.site_base_url,
            }
        )
        try:
            response = self.session.get(
                f"{self.settings.site_base_url}/layout/paper-lib",
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException:
            return False
        refreshed_cookie = self._merge_cookie_header(account.cookie, response)
        refreshed_token = self._token_from_cookie_header(refreshed_cookie)
        if not refreshed_token:
            return False
        try:
            self.probe_auth(
                cookie_header=refreshed_cookie,
                access_token=refreshed_token,
                user_agent=account.user_agent,
                request_headers=account.request_headers,
            )
        except Exception:  # noqa: BLE001
            return False
        account.cookie = refreshed_cookie
        account.access_token = refreshed_token
        account.request_headers_json = self._headers_json_with_auth(account)
        account.last_checked_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        if persist:
            self.account_pool.upsert(account)
        return True

    @classmethod
    def auth_is_valid(cls, *, cookie_header: str = "", access_token: str = "") -> bool:
        token = access_token or cls._token_from_cookie_header(cookie_header)
        if not token:
            return False
        expires_at = cls.token_expires_at(token)
        if expires_at is None:
            return True
        return expires_at > time.time() + 60

    @staticmethod
    def _load_cookie_header(path: Path) -> str:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        cookies = data.get("cookies", data if isinstance(data, list) else [])
        pairs = []
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value:
                pairs.append(f"{name}={value}")
        return "; ".join(pairs)

    @staticmethod
    def _load_access_token(path: Path) -> str:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        token_keys = {"ACCESS_TOKEN", "access-token", "accessToken", "token"}
        for origin in data.get("origins") or []:
            for item in origin.get("localStorage") or []:
                name = str(item.get("name") or "")
                value = str(item.get("value") or "")
                if name in token_keys and value:
                    return value
        return ""

    @staticmethod
    def _token_from_cookie_header(cookie_header: str) -> str:
        for pair in cookie_header.split(";"):
            if "=" not in pair:
                continue
            name, value = pair.strip().split("=", 1)
            if name == "ACCESS_TOKEN" and value:
                return value
        return ""

    @classmethod
    def _merge_cookie_header(cls, current_cookie: str, response: Response) -> str:
        cookies = cls._parse_cookie_header(current_cookie)
        for cookie in response.cookies:
            if cookie.name and cookie.value:
                cookies[cookie.name] = cookie.value
        return "; ".join(f"{name}={value}" for name, value in cookies.items() if value)

    @staticmethod
    def _parse_cookie_header(cookie_header: str) -> dict[str, str]:
        cookies = {}
        for pair in cookie_header.split(";"):
            if "=" not in pair:
                continue
            name, value = pair.strip().split("=", 1)
            if name:
                cookies[name] = value
        return cookies

    def _headers_json_with_auth(self, account: AccountCredential) -> str:
        headers = self.headers_for_account(account)
        return json.dumps(headers, ensure_ascii=False, sort_keys=True)

    @classmethod
    def account_label_from_auth(cls, *, cookie_header: str = "", access_token: str = "") -> str:
        token = access_token or cls._token_from_cookie_header(cookie_header)
        data = cls._decode_jwt_payload(token)
        for key in ("nickName", "nickname", "userName", "username", "mobile", "phone", "id"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    @classmethod
    def token_expires_at(cls, token: str) -> float | None:
        data = cls._decode_jwt_payload(token)
        value = data.get("exp")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def auth_expires_at(cls, *, cookie_header: str = "", access_token: str = "") -> float | None:
        token = access_token or cls._token_from_cookie_header(cookie_header)
        return cls.token_expires_at(token)

    @staticmethod
    def _decode_jwt_payload(token: str) -> dict[str, Any]:
        if not token or token.count(".") < 2:
            return {}
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        try:
            data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.settings.connect_timeout, self.settings.read_timeout)

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self.session.post(
            self._url(path),
            json=payload,
            headers=self._auth_headers() if headers is None else headers,
            timeout=self.timeout,
        )
        return self._decode(response)

    def get_json(self, path: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = self.session.get(
            self._url(path),
            headers=self._auth_headers() if headers is None else headers,
            timeout=self.timeout,
        )
        return self._decode(response)

    def download(self, url: str, target: Path, *, headers: dict[str, str] | None = None) -> int:
        with self.session.get(
            url,
            stream=True,
            headers=self._auth_headers() if headers is None else headers,
            timeout=self.timeout,
        ) as response:
            response.raise_for_status()
            written = 0
            with target.open("wb") as file:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        file.write(chunk)
                        written += len(chunk)
            return written

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.settings.api_base_url}{path}"

    @staticmethod
    def _decode(response: Response) -> dict[str, Any]:
        response.raise_for_status()
        data = response.json()
        if str(data.get("code")) not in {"200", "0"}:
            raise StzyApiError(str(data.get("code")), str(data.get("message") or "请求失败"))
        return data
