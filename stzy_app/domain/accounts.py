from __future__ import annotations

from dataclasses import asdict
from typing import Any

from stzy_app.auth import credential_from_auth_import, login_with_phone_password
from stzy_app.config import AppSettings
from stzy_app.http import StzyHttpClient
from stzy_app.storage.accounts import AccountCredential, get_shared_account_pool


class AccountService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.pool = get_shared_account_pool(settings.account_pool_file)

    def list_accounts(self) -> list[dict[str, Any]]:
        return [self._public(account) for account in self.pool.accounts]

    def upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        credential = AccountCredential(
            name=str(payload.get("name") or "").strip(),
            cookie=str(payload.get("cookie") or ""),
            access_token=str(payload.get("access_token") or ""),
            user_agent=str(payload.get("user_agent") or ""),
            request_headers_json=str(payload.get("request_headers_json") or ""),
            import_method=str(payload.get("import_method") or "manual"),
            login_phone=str(payload.get("login_phone") or ""),
            login_password=str(payload.get("login_password") or ""),
            enabled=bool(payload.get("enabled", True)),
        )
        if not credential.name:
            raise ValueError("账号名称不能为空")
        self.pool.upsert(credential)
        return self._public(credential)

    def import_credential(self, raw_value: str, *, name: str = "") -> dict[str, Any]:
        credential = credential_from_auth_import(raw_value, name=name, settings=self.settings)
        self.pool.upsert(credential)
        return self._public(credential)

    def phone_login(self, phone: str, password: str = "", *, name: str = "") -> dict[str, Any]:
        credential = login_with_phone_password(self.settings, phone, password or None)
        if name.strip():
            credential.name = name.strip()
        self.pool.upsert(credential)
        return self._public(credential)

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        for account in self.pool.accounts:
            if account.name == name:
                account.enabled = enabled
                self.pool.upsert(account)
                return self._public(account)
        raise FileNotFoundError("Account not found")

    def delete(self, name: str) -> None:
        self.pool.remove(name)

    def verify(self, name: str) -> dict[str, Any]:
        for account in self.pool.accounts:
            if account.name == name:
                ok = StzyHttpClient(self.settings).account_is_valid(account)
                return {**self._public(account), "valid": ok}
        raise FileNotFoundError("Account not found")

    @staticmethod
    def _public(account: AccountCredential) -> dict[str, Any]:
        data = asdict(account)
        for key in ("cookie", "access_token", "request_headers_json", "login_password"):
            if data.get(key):
                data[key] = "***"
        data["usable"] = account.usable
        data["in_cooldown"] = account.in_cooldown
        data["account_type_label"] = account.account_type_label
        data["health_label"] = account.health_label
        return data
