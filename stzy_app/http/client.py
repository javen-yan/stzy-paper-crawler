from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stzy_app.config import AppSettings
from stzy_app.proxy import create_proxy_provider, normalize_proxy_url
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


class RequestStopped(RuntimeError):
    """Raised before starting a new request after the user stops a task."""


class InvalidDownloadContent(RuntimeError):
    """Raised when a successful response is not the expected document content."""


def display_proxy_url(proxy: str) -> str:
    """Return a log-safe proxy label without credentials."""
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname:
        return proxy
    host = parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


class ProxyPool:
    """Shared proxy state for one crawl task."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.on_event = on_event or (lambda _message: None)
        self.provider = create_proxy_provider(settings) if self.proxy_mode == "api" else None
        self.fixed_urls = self._load_fixed_urls()
        self.api_urls: list[str] = []
        self.failures: dict[str, int] = {}
        self.cooldowns: dict[str, float] = {}
        self.current_proxy = ""
        self._cursor = 0
        self.lock = threading.Lock()
        if self.proxy_mode == "fixed" and self.fixed_urls:
            self._emit(f"固定代理池：{len(self.fixed_urls)} 个")
        elif self.proxy_mode == "api" and self.provider:
            self._emit(f"代理服务商：{self.provider.display_name}")

    @property
    def proxy_mode(self) -> str:
        mode = str(getattr(self.settings, "proxy_mode", "off") or "off").strip().lower()
        return mode if mode in {"off", "fixed", "api"} else "off"

    def next_proxy_url(self) -> str:
        if self.proxy_mode == "off":
            return ""
        now = time.time()
        with self.lock:
            if self.proxy_mode == "api":
                self._refill_api_urls(now)
                proxy = self._next_available(self.api_urls, now)
                return proxy
            proxy = self._next_available(self.fixed_urls, now)
            if proxy:
                return proxy
            return ""

    def record_success(self, proxy: str) -> None:
        if not proxy:
            return
        with self.lock:
            cooldown_until = self.cooldowns.get(proxy, 0)
            if cooldown_until > time.time():
                return
            had_failure = proxy in self.failures
            self.failures.pop(proxy, None)
            self.cooldowns.pop(proxy, None)
            self.current_proxy = proxy
            if had_failure:
                self._emit(f"代理恢复：{display_proxy_url(proxy)}")

    def record_failure(self, proxy: str) -> None:
        if not proxy:
            return
        with self.lock:
            failures = self.failures.get(proxy, 0) + 1
            self.failures[proxy] = failures
            max_failures = max(1, self.settings.proxy_max_failures)
            self._emit(f"代理请求失败：{display_proxy_url(proxy)}（{failures}/{max_failures}）")
            if failures >= max_failures:
                self.cooldowns[proxy] = time.time() + self.settings.proxy_cooldown_seconds
                self.failures[proxy] = 0
                if self.proxy_mode == "api":
                    self.api_urls = [url for url in self.api_urls if url != proxy]
                if self.current_proxy == proxy:
                    self.current_proxy = ""
                self._emit(f"代理不可用，已换下一个：{display_proxy_url(proxy)}")
                if self.proxy_mode == "api":
                    self._refill_api_urls(time.time())

    def request_proxies(self) -> dict[str, str] | None:
        proxy = self.next_proxy_url()
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def _load_fixed_urls(self) -> list[str]:
        if self.proxy_mode != "fixed":
            return []
        return list(dict.fromkeys(self.parse_proxy_pool(self.settings.proxy_pool)))

    @classmethod
    def parse_proxy_pool(cls, value: str) -> list[str]:
        proxies: list[str] = []
        for raw_item in value.splitlines():
            item = normalize_proxy_url(raw_item)
            if not item:
                continue
            proxies.append(item)
        return proxies

    def _fetch_proxies_from_api(self, count: int | None = None) -> list[str]:
        if self.proxy_mode != "api" or not self.provider:
            return []
        return [endpoint.url for endpoint in self.provider.fetch_proxies(count=count) if endpoint.url]

    def _is_available(self, proxy: str, now: float) -> bool:
        return bool(proxy) and self.cooldowns.get(proxy, 0) <= now

    def _available_count(self, proxies: list[str], now: float) -> int:
        return sum(1 for proxy in proxies if self._is_available(proxy, now))

    def _api_target_size(self) -> int:
        return max(1, min(20, int(getattr(self.settings, "concurrency", 1) or 1)))

    def _refill_api_urls(self, now: float) -> None:
        target_size = self._api_target_size()
        available_count = self._available_count(self.api_urls, now)
        missing = target_size - available_count
        if missing <= 0:
            return
        self._emit(f"提取接口补充代理：需要 {missing} 个")
        fetched = list(dict.fromkeys(self._fetch_proxies_from_api(missing)))
        existing = set(self.api_urls) | set(self.cooldowns)
        new_urls = [proxy for proxy in fetched if proxy not in existing]
        self.api_urls.extend(new_urls)
        if new_urls:
            available_count = self._available_count(self.api_urls, time.time())
            self._emit(f"提取接口返回代理：{len(new_urls)} 个，可用 {available_count}/{target_size}")
        else:
            self._emit("提取接口暂时没有返回可用代理")

    def _next_available(self, proxies: list[str], now: float) -> str:
        if not proxies:
            return ""
        size = len(proxies)
        start = self._cursor % size
        for offset in range(size):
            index = (start + offset) % size
            proxy = proxies[index]
            if self._is_available(proxy, now):
                self._cursor = (index + 1) % size
                self._activate_proxy(proxy)
                return proxy
        return ""

    def _activate_proxy(self, proxy: str) -> None:
        self.current_proxy = proxy

    def _emit(self, message: str) -> None:
        self.on_event(message)


class StzyHttpClient:
    """Small requests-based client for STZY public endpoints."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        on_proxy: Callable[[str], None] | None = None,
        on_proxy_event: Callable[[str], None] | None = None,
        proxy_pool: ProxyPool | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.on_proxy = on_proxy or (lambda _proxy: None)
        self.should_stop = should_stop or (lambda: False)
        self.account_pool = AccountPool(settings.account_pool_file)
        self.proxy_pool = proxy_pool or ProxyPool(settings, on_event=on_proxy_event)
        self.session = self._build_session()

    def _build_session(self) -> Session:
        session = requests.Session()
        session.trust_env = False
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
            response = self._request(
                "get",
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

    @property
    def proxy_mode(self) -> str:
        return self.proxy_pool.proxy_mode

    def _load_proxy_urls(self) -> list[str]:
        return self.proxy_pool._load_fixed_urls()

    @classmethod
    def _parse_proxy_pool(cls, value: str) -> list[str]:
        return ProxyPool.parse_proxy_pool(value)

    @staticmethod
    def _normalize_proxy_url(value: object) -> str:
        return normalize_proxy_url(value)

    def _fetch_proxy_from_api(self, count: int | None = None) -> str:
        proxies = self._fetch_proxies_from_api(count)
        return proxies[0] if proxies else ""

    def _fetch_proxies_from_api(self, count: int | None = None) -> list[str]:
        return self.proxy_pool._fetch_proxies_from_api(count)

    def _next_proxy_url(self) -> str:
        return self.proxy_pool.next_proxy_url()

    def _request_proxies(self) -> dict[str, str] | None:
        return self.proxy_pool.request_proxies()

    def _record_proxy_success(self, proxy: str) -> None:
        self.proxy_pool.record_success(proxy)

    def _record_proxy_failure(self, proxy: str) -> None:
        self.proxy_pool.record_failure(proxy)

    def _request(
        self,
        method: str,
        url: str,
        *,
        mark_proxy_success: bool = True,
        **kwargs,
    ) -> Response:
        if self.should_stop():
            raise RequestStopped("任务已停止")
        proxy = self._next_proxy_url()
        kwargs["proxies"] = {"http": proxy, "https": proxy} if proxy else None
        try:
            response = getattr(self.session, method)(url, **kwargs)
        except requests.RequestException:
            self._record_proxy_failure(proxy)
            raise
        setattr(response, "_stzy_proxy", proxy)
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code in {403, 429, 500, 502, 503, 504}:
            self._record_proxy_failure(proxy)
        elif mark_proxy_success:
            self._record_proxy_success(proxy)
            self.on_proxy(proxy)
        return response

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            "post",
            self._url(path),
            json=payload,
            headers=self._auth_headers() if headers is None else headers,
            timeout=self.timeout,
        )
        return self._decode(response)

    def get_json(self, path: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = self._request(
            "get",
            self._url(path),
            headers=self._auth_headers() if headers is None else headers,
            timeout=self.timeout,
        )
        return self._decode(response)

    def download(self, url: str, target: Path, *, headers: dict[str, str] | None = None) -> int:
        attempts = max(1, int(self.settings.proxy_max_failures or 1) + 1)
        if self.proxy_mode == "off":
            attempts = 1
        last_error: Exception | None = None
        for _ in range(attempts):
            partial = target.with_name(f"{target.name}.download")
            if partial.exists():
                partial.unlink()
            response = self._request(
                "get",
                url,
                stream=True,
                headers=self._auth_headers() if headers is None else headers,
                timeout=self.timeout,
                mark_proxy_success=False,
            )
            proxy = str(getattr(response, "_stzy_proxy", "") or "")
            try:
                with response:
                    response.raise_for_status()
                    written = 0
                    with partial.open("wb") as file:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if chunk:
                                file.write(chunk)
                                written += len(chunk)
                self._validate_download_content(partial, target, url, response)
            except InvalidDownloadContent as exc:
                self._record_proxy_failure(proxy)
                last_error = exc
                if partial.exists():
                    partial.unlink()
                continue
            except Exception:
                if partial.exists():
                    partial.unlink()
                raise
            os.replace(partial, target)
            self._record_proxy_success(proxy)
            self.on_proxy(proxy)
            return written
        raise last_error or InvalidDownloadContent("下载内容异常")

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

    @classmethod
    def _validate_download_content(
        cls,
        path: Path,
        target: Path,
        url: str,
        response: Response,
    ) -> None:
        if not path.exists() or path.stat().st_size <= 0:
            raise InvalidDownloadContent("下载内容为空")
        head = path.read_bytes()[:4096]
        lower_head = head.lower()
        suffix = (target.suffix or Path(url.split("?", 1)[0]).suffix).lower()
        content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
        if b"<html" in lower_head or b"<!doctype html" in lower_head:
            raise InvalidDownloadContent("下载内容不是试卷文件，可能是代理或登录返回页")
        if suffix == ".pdf" or "application/pdf" in content_type:
            if not head.startswith(b"%PDF"):
                raise InvalidDownloadContent("PDF 下载内容异常，已尝试切换代理")
            return
        if suffix == ".svg" or "image/svg" in content_type:
            if b"<svg" not in lower_head:
                raise InvalidDownloadContent("预览图下载内容异常，已尝试切换代理")
            return
