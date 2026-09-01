from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from stzy_app.config import AppSettings
from stzy_app.utils import ensure_directory


AUTH_TOKEN_KEYS = {"ACCESS_TOKEN", "access-token", "accessToken", "token"}
LOGIN_TIMEOUT_SECONDS = 600


def _write_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _has_auth_state(state: dict) -> bool:
    for cookie in state.get("cookies") or []:
        name = str(cookie.get("name") or "").lower()
        value = str(cookie.get("value") or "")
        if value and ("token" in name or "session" in name or "auth" in name):
            return True
    for origin in state.get("origins") or []:
        for item in origin.get("localStorage") or []:
            name = str(item.get("name") or "")
            value = str(item.get("value") or "")
            if name in AUTH_TOKEN_KEYS and value:
                return True
    return False


def capture_login_state(settings: AppSettings, *, wait_for_close: bool = True) -> Path:
    """Open a browser for manual login and save cookies/storage state."""

    ensure_directory(settings.cookie_file.parent)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(f"{settings.site_base_url}/login", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            last_state = context.storage_state()

            if wait_for_close:
                print("请在打开的浏览器中完成登录；检测到登录成功后会自动保存并关闭窗口。")
                deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
                while time.monotonic() < deadline and any(
                    not tab.is_closed() for tab in context.pages
                ):
                    last_state = context.storage_state()
                    _write_state(settings.cookie_file, last_state)
                    if _has_auth_state(last_state):
                        page.wait_for_timeout(1000)
                        last_state = context.storage_state()
                        break
                    time.sleep(0.5)
            else:
                input("请在打开的浏览器中完成登录，然后回到终端按 Enter 保存登录态...")
                last_state = context.storage_state()

            _write_state(settings.cookie_file, last_state)
        finally:
            context.close()
            browser.close()
    return settings.cookie_file
