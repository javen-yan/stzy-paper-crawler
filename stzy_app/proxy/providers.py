from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

import requests

from stzy_app.config import AppSettings


SHENLONG_API_BASE = "http://api.shenlongip.com"
PUBLIC_IP_ENDPOINTS = (
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "http://myip.ipip.net",
)


@dataclass(frozen=True)
class ProxyEndpoint:
    url: str
    expires_at: str | None = None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProxyPrepareResult:
    ip: str = ""
    added: bool = False
    message: str = ""


class ProxyProvider:
    display_name = "通用接口"
    supports_whitelist = False

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.timeout = (settings.connect_timeout, settings.read_timeout)

    def prepare(self) -> ProxyPrepareResult:
        return ProxyPrepareResult(message="")

    def fetch_proxies(self, count: int | None = None) -> list[ProxyEndpoint]:
        raise NotImplementedError


class GenericProxyProvider(ProxyProvider):
    display_name = "通用接口"

    def fetch_proxies(self, count: int | None = None) -> list[ProxyEndpoint]:
        if not self.settings.proxy_api_url:
            return []
        try:
            response = _direct_get(self._url_for_count(count), timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException:
            return []
        try:
            data = response.json()
        except ValueError:
            proxy = normalize_proxy_url(response.text)
            return [ProxyEndpoint(proxy)] if proxy else []
        return self.proxies_from_payload(data)

    def _url_for_count(self, count: int | None) -> str:
        if not count or count <= 0:
            return self.settings.proxy_api_url
        parsed = urlparse(self.settings.proxy_api_url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        found = False
        updated = []
        for key, value in query:
            if key == "count":
                updated.append((key, str(count)))
                found = True
            else:
                updated.append((key, value))
        if not found:
            updated.append(("count", str(count)))
        return urlunparse(parsed._replace(query=urlencode(updated)))

    @classmethod
    def proxies_from_payload(cls, data: object) -> list[ProxyEndpoint]:
        if isinstance(data, dict):
            proxies = cls.proxies_from_ip_port_payload(data.get("data"))
            if proxies:
                return proxies
            proxies = cls.proxies_from_ip_port_payload(data)
            if proxies:
                return proxies
            for key in ("proxy", "https", "http", "data"):
                proxy = normalize_proxy_url(data.get(key))
                if proxy:
                    return [ProxyEndpoint(proxy)]
            return []
        proxy = normalize_proxy_url(data)
        return [ProxyEndpoint(proxy)] if proxy else []

    @classmethod
    def proxies_from_ip_port_payload(cls, payload: object) -> list[ProxyEndpoint]:
        if isinstance(payload, list):
            proxies: list[ProxyEndpoint] = []
            for item in payload:
                proxies.extend(cls.proxies_from_ip_port_payload(item))
            return proxies
        if not isinstance(payload, dict):
            return []
        host = str(payload.get("ip") or payload.get("host") or "").strip()
        port = str(payload.get("port") or "").strip()
        if not host or not port:
            return []
        protocol = str(payload.get("protocol") or payload.get("type") or "http").strip().lower()
        if protocol in {"1", "http", "https"}:
            scheme = "http"
        elif protocol in {"2", "socks5", "socks"}:
            scheme = "socks5"
        else:
            scheme = protocol if "://" not in protocol else protocol.split("://", 1)[0]
        proxy = normalize_proxy_url(f"{scheme}://{host}:{port}")
        expires_at = str(payload.get("expire") or payload.get("expires_at") or "").strip() or None
        meta = {str(key): value for key, value in payload.items() if key not in {"ip", "host", "port"}}
        return [ProxyEndpoint(proxy, expires_at=expires_at, meta=meta)] if proxy else []


class ShenlongProxyProvider(GenericProxyProvider):
    display_name = "神龙 HTTP"
    supports_whitelist = True

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(settings)
        query = parse_qs(urlparse(settings.proxy_api_url).query)
        self.key = settings.shenlong_whitelist_key.strip() or _first_query_value(query, "key")
        self.sign = settings.shenlong_whitelist_sign.strip() or _first_query_value(query, "sign")

    def prepare(self) -> ProxyPrepareResult:
        if not self.key or not self.sign:
            raise ValueError("请填写白名单账号和签名")
        ip = self.current_public_ip()
        if self.is_bound(ip):
            return ProxyPrepareResult(ip=ip, added=False, message=f"本机 IP 已绑定：{ip}")
        self.add(ip)
        return ProxyPrepareResult(ip=ip, added=True, message=f"本机 IP 已绑定：{ip}")

    def current_public_ip(self) -> str:
        return current_public_ip(self.timeout)

    def is_bound(self, ip: str) -> bool:
        payload = self._request("/white/fetch", ip)
        data = payload.get("data")
        if isinstance(data, list):
            return ip in {str(item).strip() for item in data}
        return False

    def add(self, ip: str) -> None:
        payload = self._request("/white/add", ip)
        code = str(payload.get("code") or "")
        if code not in {"200", "1007"}:
            raise ValueError(str(payload.get("msg") or "白名单绑定失败"))

    def _request(self, path: str, ip: str) -> dict[str, Any]:
        query = urlencode({"key": self.key, "sign": self.sign, "ip": ip})
        response = _direct_get(f"{SHENLONG_API_BASE}{path}?{query}", timeout=self.timeout)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("神龙接口返回异常") from exc
        if not isinstance(payload, dict):
            raise ValueError("神龙接口返回异常")
        code = str(payload.get("code") or "")
        if path.endswith("/fetch") and code == "200":
            return payload
        if path.endswith("/add") and code in {"200", "1007"}:
            return payload
        raise ValueError(str(payload.get("msg") or "神龙接口请求失败"))


def create_proxy_provider(settings: AppSettings) -> ProxyProvider:
    provider = infer_proxy_provider(settings.proxy_provider)
    if provider == "shenlong":
        return ShenlongProxyProvider(settings)
    return GenericProxyProvider(settings)


def infer_proxy_provider(value: object = "") -> str:
    provider = str(value or "").strip().lower()
    if provider in {"generic", "shenlong"}:
        return provider
    return "generic"


def normalize_proxy_url(value: object) -> str:
    item = str(value or "").strip()
    if not item or item.startswith("#"):
        return ""
    if "://" not in item:
        item = f"http://{item}"
    return item


def current_public_ip(timeout: tuple[float, float]) -> str:
    last_error = "无法获取本机公网 IP"
    for endpoint in PUBLIC_IP_ENDPOINTS:
        try:
            response = _direct_get(endpoint, timeout=timeout)
            response.raise_for_status()
            ip = _extract_ip(response)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        if ip:
            return ip
    raise ValueError(last_error)


def _direct_get(url: str, *, timeout: tuple[float, float]) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    return session.get(url, timeout=timeout)


def _first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return str(values[0]).strip() if values else ""


def _extract_ip(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        for key in ("ip", "origin"):
            ip = _first_ip(str(data.get(key) or ""))
            if ip:
                return ip
    return _first_ip(response.text)


def _first_ip(value: str) -> str:
    match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", value)
    return match.group(0) if match else ""
