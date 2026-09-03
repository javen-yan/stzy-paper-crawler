from __future__ import annotations

import time
from typing import Any

from stzy_app.config import AppSettings
from stzy_app.domain.store import DomainStore
from stzy_app.http.client import PROXY_RUNTIME, ProxyPool, display_proxy_url
from stzy_app.proxy import create_proxy_provider
from stzy_app.proxy.public_ip import PUBLIC_IP_ENDPOINTS, detect_public_ip, extract_public_ipv4


def proxy_status(settings: AppSettings, store: DomainStore) -> dict[str, Any]:
    effective = effective_proxy_settings(settings, store)
    proxy_mode = str(effective.proxy_mode or "off").strip().lower()
    proxy_provider = str(effective.proxy_provider or "generic").strip().lower()
    proxy_pool = str(effective.proxy_pool or "")
    proxy_api_url = str(effective.proxy_api_url or "")

    fixed_proxies = ProxyPool.parse_proxy_pool(proxy_pool) if proxy_mode == "fixed" else []
    target_proxy_count = max(1, min(20, int(effective.concurrency or 1))) if proxy_mode == "api" else len(fixed_proxies)
    tasks = store.list_tasks(archived=False, limit=500, offset=0)
    running_tasks = [task for task in tasks if task.get("status") == "running"]
    active_proxies = [str(task.get("active_proxy") or "") for task in running_tasks if task.get("active_proxy")]
    runtime_items = {str(item.get("proxy") or ""): item for item in PROXY_RUNTIME.snapshot()}

    running_task_list = [
        {
            "id": str(task.get("id") or ""),
            "title": str(task.get("title") or task.get("id") or ""),
            "mode": str(task.get("mode") or ""),
            "active_proxy": str(task.get("active_proxy") or ""),
        }
        for task in running_tasks
    ]

    pool_items = [
        {
            "id": f"fixed-{index}",
            "source": "固定代理池",
            "address": display_proxy_url(proxy),
            "status": str(runtime_items.get(proxy, {}).get("status") or ("使用中" if active_proxies.count(proxy) else "空闲")),
            "running_count": active_proxies.count(proxy),
            "lease_task_id": str(runtime_items.get(proxy, {}).get("lease_task_id") or ""),
            "lease_resource_name": str(runtime_items.get(proxy, {}).get("lease_resource_name") or ""),
            "cooldown_until": runtime_items.get(proxy, {}).get("cooldown_until") or 0,
            "failure_count": int(runtime_items.get(proxy, {}).get("failure_count") or 0),
        }
        for index, proxy in enumerate(fixed_proxies, start=1)
    ]

    runtime_items.update(
        {
            proxy: {
                "source": "运行中",
                "address": display_proxy_url(proxy),
                "status": "使用中",
            }
            for proxy in dict.fromkeys(active_proxies)
            if proxy and proxy not in runtime_items
        }
    )
    active_items = [
        {
            "id": f"active-{index}",
            "source": str(item.get("source") or "运行中"),
            "address": str(item.get("address") or display_proxy_url(proxy)),
            "status": str(item.get("status") or "使用中"),
            "running_count": active_proxies.count(proxy),
            "lease_task_id": str(item.get("lease_task_id") or ""),
            "lease_resource_name": str(item.get("lease_resource_name") or ""),
            "cooldown_until": item.get("cooldown_until") or 0,
            "failure_count": int(item.get("failure_count") or 0),
        }
        for index, (proxy, item) in enumerate(runtime_items.items(), start=1)
        if proxy not in fixed_proxies
    ]
    items = pool_items + active_items
    leased_proxy_count = sum(1 for item in items if item["status"] == "使用中")
    cooldown_proxy_count = sum(1 for item in items if item["status"] == "冷却中")
    available_proxy_count = sum(1 for item in items if item["status"] == "空闲")
    configured_download_workers = max(1, int(effective.max_download_workers or 1))
    effective_download_workers = configured_download_workers
    if proxy_mode != "off":
        effective_download_workers = max(1, min(configured_download_workers, available_proxy_count or target_proxy_count or 1))
    public_ip = _detect_public_ip()

    return {
        "my_ip": public_ip["ip"],
        "my_ip_status": public_ip,
        "proxy_mode": proxy_mode if proxy_mode in {"off", "fixed", "api"} else "off",
        "proxy_provider": proxy_provider if proxy_provider in {"generic", "shenlong"} else "generic",
        "proxy_api_configured": bool(proxy_api_url),
        "pool_size": len(fixed_proxies),
        "target_proxy_count": target_proxy_count,
        "available_proxy_count": available_proxy_count,
        "leased_proxy_count": leased_proxy_count,
        "cooldown_proxy_count": cooldown_proxy_count,
        "running_task_count": len(running_tasks),
        "running_proxy_count": len(active_proxies),
        "running_tasks": running_task_list,
        "effective_download_workers": effective_download_workers,
        "items": items,
    }


def bind_local_ip(settings: AppSettings, store: DomainStore) -> dict[str, Any]:
    effective = effective_proxy_settings(settings, store)
    if str(effective.proxy_provider or "").strip().lower() != "shenlong":
        raise ValueError("当前代理服务商不是神龙HTTP")
    result = create_proxy_provider(effective).prepare()
    return {"ip": result.ip, "added": result.added, "message": result.message}


def effective_proxy_settings(settings: AppSettings, store: DomainStore) -> AppSettings:
    persisted = store.get_setting("app_settings", {}) or {}
    allowed = {
        "proxy_mode",
        "proxy_provider",
        "proxy_pool",
        "proxy_api_url",
        "proxy_max_failures",
        "proxy_cooldown_seconds",
        "shenlong_whitelist_key",
        "shenlong_whitelist_sign",
        "connect_timeout",
        "read_timeout",
        "concurrency",
        "max_download_workers",
    }
    return settings.model_copy(update={key: value for key, value in persisted.items() if key in allowed})


def _detect_public_ip() -> dict[str, Any]:
    result = detect_public_ip()
    return {
        "ok": result.ok,
        "ip": result.ip,
        "source": result.source,
        "error": result.error,
        "attempts": result.attempts,
    }


def _extract_ip(text: str) -> str:
    return extract_public_ipv4(text)
