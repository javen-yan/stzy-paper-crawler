from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from stzy_app.crawler.api import StzyCrawlerApi
from stzy_app.http import StzyHttpClient
from stzy_app.models import ResourceRecord, ResourceStatus

LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class DownloadAttempt:
    name: str
    headers: dict[str, str]
    account: object | None = None
    diagnosis: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DownloadUrlResult:
    url: str = ""
    status: ResourceStatus | None = None
    error: str = ""
    paid_unavailable: int = 0


class AccountScheduler:
    """Ranks accounts for a resource and tries direct PDF download URLs."""

    def __init__(
        self,
        client: StzyHttpClient,
        api: StzyCrawlerApi,
        *,
        on_log: LogCallback | None = None,
    ) -> None:
        self.client = client
        self.api = api
        self.on_log = on_log or (lambda message: None)

    def download_pdf_url(self, record: ResourceRecord) -> DownloadUrlResult:
        attempts = self.scheduled_attempts(record)
        if not attempts:
            attempts.append(DownloadAttempt("当前登录", self.client._auth_headers(), None, {}))
        last_error = "没有可用账号"
        diagnostics: list[dict[str, object]] = []
        for attempt in attempts:
            try:
                pdf_url = self.api.download_resource_url(
                    record.resource_id,
                    headers=attempt.headers,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = self.user_facing_error(str(exc))
                diagnosis = attempt.diagnosis or self.download_diagnosis(
                    record.resource_id,
                    attempt.headers,
                )
                if diagnosis:
                    diagnostics.append({"account": attempt.name, **diagnosis})
                    diagnosis_text = self.format_download_diagnosis(diagnosis)
                    if diagnosis_text and diagnosis_text not in last_error:
                        last_error = f"{last_error}；{diagnosis_text}"
                self._mark_failure(attempt.account, last_error)
                self.on_log(f"账号 {attempt.name} 下载失败，尝试下一个账号：{last_error}")
                continue
            if pdf_url:
                self._mark_success(attempt.account)
                self.on_log(f"账号 {attempt.name} 下载成功：{record.resource_id}")
                return DownloadUrlResult(url=pdf_url)
            last_error = "接口未返回 PDF 地址"
            diagnosis = attempt.diagnosis or self.download_diagnosis(
                record.resource_id,
                attempt.headers,
            )
            if diagnosis:
                diagnostics.append({"account": attempt.name, **diagnosis})
                diagnosis_text = self.format_download_diagnosis(diagnosis)
                if diagnosis_text and diagnosis_text not in last_error:
                    last_error = f"{last_error}；{diagnosis_text}"
            self._mark_failure(attempt.account, last_error)
            self.on_log(f"账号 {attempt.name} 下载失败，尝试下一个账号：{last_error}")

        has_zero_price_account = any(item.get("price") == 0 for item in diagnostics)
        if record.price > 0 and not has_zero_price_account:
            return DownloadUrlResult(
                status=ResourceStatus.paid_unavailable,
                error=self.final_error(last_error),
                paid_unavailable=1,
            )
        return DownloadUrlResult(error=self.final_error(last_error))

    def scheduled_attempts(self, record: ResourceRecord) -> list[DownloadAttempt]:
        accounts = self.client.enabled_valid_accounts()
        attempts = []
        for index, account in enumerate(accounts):
            headers = self.client.headers_for_account(account)
            diagnosis: dict[str, object] = {}
            if record.price > 0:
                diagnosis = self.download_diagnosis(record.resource_id, headers)
                if diagnosis and not diagnosis.get("check_error"):
                    self.client.account_pool.update_download_profile(account.name, diagnosis)
            attempts.append((DownloadAttempt(account.name, headers, account, diagnosis), index))
        attempts.sort(key=lambda item: self.account_schedule_key(item[0].account, item[0].diagnosis, item[1]))
        sorted_attempts = [attempt for attempt, _ in attempts]
        if record.price > 0 and sorted_attempts:
            order = " -> ".join(
                f"{attempt.name}({self.format_download_diagnosis(attempt.diagnosis)})"
                if attempt.diagnosis
                else attempt.name
                for attempt in sorted_attempts
            )
            self.on_log(f"付费资源账号调度：{order}")
        return sorted_attempts

    @staticmethod
    def account_schedule_key(account: object, diagnosis: dict[str, object], index: int) -> tuple:
        price = diagnosis.get("price")
        try:
            effective_price = float(price) if price is not None else None
        except (TypeError, ValueError):
            effective_price = None
        surplus = diagnosis.get("surplusNum")
        try:
            surplus_num = int(surplus) if surplus is not None else -1
        except (TypeError, ValueError):
            surplus_num = -1
        user_type = diagnosis.get("userType", getattr(account, "user_type", None))
        rank = diagnosis.get("rank", getattr(account, "rank", None))
        vip_score = 1 if user_type == 3 or rank == 3 or effective_price == 0 else 0
        fail_count = int(getattr(account, "fail_count", 0) or 0)
        price_score = effective_price if effective_price is not None else 9999
        return (-vip_score, price_score, -surplus_num, fail_count, index)

    def download_diagnosis(
        self,
        resource_id: str,
        headers: dict[str, str],
    ) -> dict[str, object]:
        try:
            info = self.api.check_download_info(resource_id, headers=headers)
        except Exception as exc:  # noqa: BLE001
            return {"check_error": str(exc)}
        result: dict[str, object] = {}
        for key in ("price", "economizePrice", "surplusNum", "dayLimit", "weekLimit", "rank", "userType"):
            if key in info:
                result[key] = info.get(key)
        return result

    @staticmethod
    def format_download_diagnosis(info: dict[str, object]) -> str:
        if info.get("check_error"):
            return AccountScheduler.user_facing_error(str(info["check_error"]))
        parts = []
        if "price" in info:
            parts.append(f"实付 {info['price']}")
        if "surplusNum" in info:
            parts.append(f"剩余额度 {info['surplusNum']}")
        if "userType" in info:
            parts.append(f"用户类型 {info['userType']}")
        if "rank" in info:
            parts.append(f"资源等级 {info['rank']}")
        return "，".join(parts) or "无下载资格明细"

    @staticmethod
    def user_facing_error(message: str) -> str:
        if "暂未登录" in message or "token已经过期" in message or "请登录" in message:
            return "登录态已失效"
        if "额度不足" in message or "豆" in message:
            return "账号额度不足"
        if "无权限" in message:
            return "账号无下载权限"
        return message

    @staticmethod
    def final_error(last_error: str) -> str:
        compact = AccountScheduler.user_facing_error(last_error)
        if compact == "登录态已失效":
            return "登录态已失效，请重新登录或换一个可用账号"
        if "账号额度不足" in compact or "账号无下载权限" in compact:
            return f"无账号支持，请补充 VIP 账号后恢复任务（{compact}）"
        return f"所有账号均不可用或额度不足：{compact}"

    def _mark_success(self, account: object | None) -> None:
        if account:
            self.client.account_pool.mark_success(account.name)

    def _mark_failure(self, account: object | None, error: str) -> None:
        if account:
            self.client.account_pool.mark_failure(account.name, error)
