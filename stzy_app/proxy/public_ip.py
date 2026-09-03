from __future__ import annotations

import ipaddress
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

PUBLIC_IP_ENDPOINTS = (
    "https://api.ipify.org?format=json",
    "https://checkip.amazonaws.com/",
    "https://ifconfig.me/ip",
    "https://icanhazip.com/",
    "https://ident.me/",
    "https://v4.ident.me/",
    "https://ipinfo.io/ip",
    "https://www.cloudflare.com/cdn-cgi/trace",
    "https://httpbin.org/ip",
    "http://myip.ipip.net",
)
PUBLIC_IP_SUCCESS_CACHE_TTL_SECONDS = 30 * 60.0
PUBLIC_IP_FAILURE_CACHE_TTL_SECONDS = 10.0


@dataclass(frozen=True)
class PublicIpResult:
    ok: bool
    ip: str = ""
    source: str = ""
    error: str = ""
    attempts: int = 0


_PUBLIC_IP_CACHE: dict[str, Any] = {
    "checked_at": 0.0,
    "success_at": 0.0,
    "value": PublicIpResult(ok=False),
    "last_success": None,
}


def detect_public_ip(
    timeout: tuple[float, float] = (1.5, 1.5),
    *,
    endpoints: tuple[str, ...] = PUBLIC_IP_ENDPOINTS,
    rounds: int = 2,
    getter: Callable[[str, tuple[float, float]], requests.Response] | None = None,
    force_refresh: bool = False,
) -> PublicIpResult:
    now = time.monotonic()
    cached = _PUBLIC_IP_CACHE.get("value")
    if not force_refresh and isinstance(cached, PublicIpResult):
        ttl = PUBLIC_IP_SUCCESS_CACHE_TTL_SECONDS if cached.ok else PUBLIC_IP_FAILURE_CACHE_TTL_SECONDS
        if now - float(_PUBLIC_IP_CACHE.get("checked_at") or 0) < ttl:
            return cached

    errors: list[str] = []
    request_get = getter or _direct_get
    attempt_count = 0
    for _ in range(max(1, rounds)):
        for endpoint in endpoints:
            attempt_count += 1
            try:
                response = request_get(endpoint, timeout)
                response.raise_for_status()
                ip = extract_public_ipv4(response.text)
                if not ip:
                    try:
                        ip = extract_public_ipv4_from_json(response.json())
                    except ValueError:
                        ip = ""
                if ip:
                    result = PublicIpResult(ok=True, ip=ip, source=endpoint, attempts=attempt_count)
                    _PUBLIC_IP_CACHE.update({"checked_at": now, "success_at": now, "value": result, "last_success": result})
                    return result
                errors.append(f"{endpoint}: 未识别IPv4")
            except requests.RequestException as exc:
                errors.append(f"{endpoint}: {exc}")
    error = "；".join(errors[-4:]) or "公共IP检测失败"
    last_success = _PUBLIC_IP_CACHE.get("last_success")
    if isinstance(last_success, PublicIpResult) and last_success.ip:
        result = PublicIpResult(
            ok=True,
            ip=last_success.ip,
            source=f"cache:stale:{last_success.source}",
            error=error,
            attempts=attempt_count,
        )
    else:
        result = PublicIpResult(ok=False, error=error, attempts=attempt_count)
    _PUBLIC_IP_CACHE.update({"checked_at": now, "value": result})
    return result


def current_public_ip(timeout: tuple[float, float]) -> str:
    result = detect_public_ip(timeout)
    if result.ok and result.ip:
        return result.ip
    raise ValueError(result.error or "无法获取本机公网 IP")


def extract_public_ipv4(value: object) -> str:
    if isinstance(value, (dict, list)):
        return extract_public_ipv4_from_json(value)
    text = str(value or "")
    try:
        return extract_public_ipv4_from_json(json.loads(text))
    except ValueError:
        pass
    for candidate in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        if _is_public_ipv4(candidate):
            return candidate
    return ""


def extract_public_ipv4_from_json(value: Any) -> str:
    if isinstance(value, dict):
        preferred_keys = ("ip", "origin", "query", "address")
        for key in preferred_keys:
            ip = extract_public_ipv4(value.get(key))
            if ip:
                return ip
        for item in value.values():
            ip = extract_public_ipv4(item)
            if ip:
                return ip
    if isinstance(value, list):
        for item in value:
            ip = extract_public_ipv4(item)
            if ip:
                return ip
    return ""


def _direct_get(url: str, timeout: tuple[float, float]) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    return session.get(url, timeout=timeout, headers={"user-agent": "stzy-public-ip-check/1.0"})


def _is_public_ipv4(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.version == 4 and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)
