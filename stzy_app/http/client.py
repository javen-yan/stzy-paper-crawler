from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stzy_app.config import AppSettings
from stzy_app.proxy import create_proxy_provider, normalize_proxy_url
from stzy_app.storage.accounts import AccountCredential, get_shared_account_pool


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


class ProxyUnavailable(RuntimeError):
    """Raised when proxy mode is enabled but no proxy lease is available."""


def display_proxy_url(proxy: str) -> str:
    """Return a log-safe proxy label without credentials."""
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname:
        return proxy
    host = parsed.hostname
    try:
        parsed_port = parsed.port
    except ValueError:
        return f"{parsed.scheme}://{host}"
    port = f":{parsed_port}" if parsed_port else ""
    return f"{parsed.scheme}://{host}{port}"


@dataclass
class ProxyLeaseInfo:
    task_id: str = ""
    resource_name: str = ""
    leased_at: float = 0


class ProxyRuntimeRegistry:
    """Best-effort in-process view of proxy pool and leases for diagnostics."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def sync_pool(self, pool: "ProxyPool") -> None:
        if pool.proxy_mode == "off":
            return
        now = time.time()
        source = pool.proxy_source_label
        known_proxies = set(pool.known_proxy_urls)
        with self._lock:
            for proxy, item in list(self._items.items()):
                if str(item.get("source") or "") != source or proxy in known_proxies:
                    continue
                cooldown_until = float(item.get("cooldown_until") or 0)
                is_leased = str(item.get("lease_task_id") or "") or float(item.get("leased_at") or 0)
                if not is_leased and cooldown_until <= now:
                    self._items.pop(proxy, None)
            for proxy in pool.known_proxy_urls:
                item = self._items.setdefault(
                    proxy,
                    {
                        "proxy": proxy,
                        "address": display_proxy_url(proxy),
                        "source": source,
                        "status": "空闲",
                        "lease_task_id": "",
                        "lease_resource_name": "",
                        "leased_at": 0,
                        "cooldown_until": 0,
                        "failure_count": 0,
                    },
                )
                item["source"] = source
                item["failure_count"] = int(pool.failures.get(proxy, 0) or 0)
                item["cooldown_until"] = float(pool.cooldowns.get(proxy, 0) or 0)
                if proxy in pool.leases:
                    lease = pool.leases[proxy]
                    item["status"] = "使用中"
                    item["lease_task_id"] = lease.task_id
                    item["lease_resource_name"] = lease.resource_name
                    item["leased_at"] = lease.leased_at
                elif item["cooldown_until"] > now:
                    item["status"] = "冷却中"
                    item["lease_task_id"] = ""
                    item["lease_resource_name"] = ""
                    item["leased_at"] = 0
                else:
                    item["status"] = "空闲"
                    item["lease_task_id"] = ""
                    item["lease_resource_name"] = ""
                    item["leased_at"] = 0

    def lease(self, proxy: str, source: str, lease: ProxyLeaseInfo) -> None:
        if not proxy:
            return
        with self._lock:
            item = self._items.setdefault(
                proxy,
                {
                    "proxy": proxy,
                    "address": display_proxy_url(proxy),
                    "source": source,
                    "failure_count": 0,
                    "cooldown_until": 0,
                },
            )
            item.update(
                {
                    "status": "使用中",
                    "lease_task_id": lease.task_id,
                    "lease_resource_name": lease.resource_name,
                    "leased_at": lease.leased_at,
                }
            )

    def release(self, proxy: str, *, failure_count: int = 0, cooldown_until: float = 0) -> None:
        if not proxy:
            return
        with self._lock:
            item = self._items.get(proxy)
            if not item:
                return
            item["failure_count"] = int(failure_count or 0)
            item["cooldown_until"] = float(cooldown_until or 0)
            item["lease_task_id"] = ""
            item["lease_resource_name"] = ""
            item["leased_at"] = 0
            item["status"] = "冷却中" if item["cooldown_until"] > time.time() else "空闲"

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items.values()]


PROXY_RUNTIME = ProxyRuntimeRegistry()


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
        self.leases: dict[str, ProxyLeaseInfo] = {}
        self.current_proxy = ""
        self._cursor = 0
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self._local = threading.local()
        if self.proxy_mode == "fixed" and self.fixed_urls:
            self._emit(f"固定代理池：{len(self.fixed_urls)} 个")
        elif self.proxy_mode == "api" and self.provider:
            self._emit(f"代理服务商：{self.provider.display_name}")
        PROXY_RUNTIME.sync_pool(self)

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

    def set_lease_context(self, *, task_id: str = "", resource_name: str = "") -> None:
        self._local.task_id = task_id
        self._local.resource_name = resource_name

    def acquire_proxy(self, *, timeout: float | None = None) -> str:
        if self.proxy_mode == "off":
            return ""
        timeout = self._lease_timeout() if timeout is None else max(0.1, float(timeout))
        deadline = time.time() + timeout
        with self.condition:
            while True:
                now = time.time()
                if self.proxy_mode == "api":
                    self._refill_api_urls(now)
                proxy = self._next_available_unleased(self.known_proxy_urls, now)
                if proxy:
                    lease = ProxyLeaseInfo(
                        task_id=str(getattr(self.settings, "task_scope", "") or getattr(self._local, "task_id", "") or ""),
                        resource_name=str(getattr(self._local, "resource_name", "") or ""),
                        leased_at=now,
                    )
                    self.leases[proxy] = lease
                    self._activate_proxy(proxy)
                    PROXY_RUNTIME.lease(proxy, self.proxy_source_label, lease)
                    return proxy
                remaining = deadline - now
                if remaining <= 0:
                    raise ProxyUnavailable("代理池可用 IP 不足，请增加代理数量或降低下载并发")
                self.condition.wait(min(0.25, remaining))

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
            self.leases.pop(proxy, None)
            self.current_proxy = proxy
            PROXY_RUNTIME.release(proxy, failure_count=0, cooldown_until=0)
            self.condition.notify_all()
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
            self.leases.pop(proxy, None)
            PROXY_RUNTIME.release(
                proxy,
                failure_count=self.failures.get(proxy, 0),
                cooldown_until=self.cooldowns.get(proxy, 0),
            )
            self.condition.notify_all()

    def request_proxies(self) -> dict[str, str] | None:
        proxy = self.acquire_proxy()
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    @property
    def proxy_source_label(self) -> str:
        if self.proxy_mode == "fixed":
            return "固定代理池"
        if self.proxy_mode == "api" and self.provider:
            return self.provider.display_name
        if self.proxy_mode == "api":
            return "API 提取"
        return "直连"

    @property
    def known_proxy_urls(self) -> list[str]:
        return self.api_urls if self.proxy_mode == "api" else self.fixed_urls

    def target_size(self) -> int:
        if self.proxy_mode == "api":
            return self._api_target_size()
        if self.proxy_mode == "fixed":
            return len(self.fixed_urls)
        return 0

    def available_capacity(self) -> int:
        if self.proxy_mode == "off":
            return max(1, int(getattr(self.settings, "max_download_workers", 1) or 1))
        now = time.time()
        with self.lock:
            if self.proxy_mode == "api":
                self._refill_api_urls(now)
            return sum(
                1
                for proxy in self.known_proxy_urls
                if self._is_available(proxy, now) and proxy not in self.leases
            )

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
        PROXY_RUNTIME.sync_pool(self)

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

    def _next_available_unleased(self, proxies: list[str], now: float) -> str:
        if not proxies:
            return ""
        size = len(proxies)
        start = self._cursor % size
        for offset in range(size):
            index = (start + offset) % size
            proxy = proxies[index]
            if self._is_available(proxy, now) and proxy not in self.leases:
                self._cursor = (index + 1) % size
                return proxy
        return ""

    def _lease_timeout(self) -> float:
        return max(1.0, min(60.0, float(getattr(self.settings, "read_timeout", 30) or 30)))

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
        self.account_pool = get_shared_account_pool(settings.account_pool_file)
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
        with self.account_pool.auth_lock(account.name):
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
        return self.proxy_pool.acquire_proxy()

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
        setattr(response, "_stzy_proxy_released", False)
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code in {403, 429, 500, 502, 503, 504}:
            self._record_proxy_failure(proxy)
            setattr(response, "_stzy_proxy_released", True)
        elif mark_proxy_success:
            self._record_proxy_success(proxy)
            self.on_proxy(proxy)
            setattr(response, "_stzy_proxy_released", True)
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
            proxy_released = bool(getattr(response, "_stzy_proxy_released", False))
            try:
                with response:
                    response.raise_for_status()
                    written = 0
                    with partial.open("wb") as file:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if self.should_stop():
                                raise RequestStopped("任务已停止")
                            if chunk:
                                file.write(chunk)
                                written += len(chunk)
                self._validate_download_content(partial, target, url, response)
            except InvalidDownloadContent as exc:
                if not proxy_released:
                    self._record_proxy_failure(proxy)
                last_error = exc
                if partial.exists():
                    partial.unlink()
                continue
            except Exception:
                if not proxy_released:
                    self._record_proxy_failure(proxy)
                if partial.exists():
                    partial.unlink()
                raise
            os.replace(partial, target)
            if not proxy_released:
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
