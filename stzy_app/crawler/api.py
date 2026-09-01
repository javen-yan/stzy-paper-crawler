from __future__ import annotations

import json
from base64 import b64decode, b64encode
from typing import Any
from urllib.parse import urljoin

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from stzy_app.config import AppSettings
from stzy_app.http import StzyHttpClient
from stzy_app.models import CrawlCombo, CrawlFilters, ResourceRecord, ResourceStatus

AES_KEY = "abADefg234cdegsd"
CDN_BASE_URL = "https://cdn.stzy.com/"


class StzyCrawlerApi:
    """Thin API wrapper that knows STZY request/response shapes."""

    def __init__(self, client: StzyHttpClient, settings: AppSettings) -> None:
        self.client = client
        self.settings = settings

    def list_resources(
        self,
        combo: CrawlCombo,
        filters: CrawlFilters,
        page_num: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "sort": 0,
            "answerFlag": 2,
            "explainsFlag": 2,
            "audio": 2,
            "studyPhaseCode": self.settings.study_phase_code,
            "cityCode": "",
            "areaCode": "",
            "organizationCode": "",
            "area": "",
            "keyWord": "",
            "filterQuestionFlag": False,
            "searchScope": 0,
            "searchType": 1,
            "source": 1,
            "treeIds": [],
            "fileType": filters.file_type,
        }
        if self.settings.subject_code:
            params["subjectCode"] = self.settings.subject_code
        params.update(combo.params())
        payload = {"pageNum": page_num, "pageSize": 10, "params": params}
        response = self.client.post_json(
            "/zw-search/api/v1/homeEs/resource/textbookQuery", payload
        )
        return response.get("data", {})

    def resource_detail(self, resource_id: str) -> dict[str, Any]:
        response = self.client.get_json(f"/zw-resource/api/v1/tkResource/detail/{resource_id}")
        return response.get("data", {})

    def resource_pictures(self, resource_id: str) -> list[str]:
        response = self.client.get_json(
            f"/zw-resource/api/v1/tkResource/resourcePicList/{resource_id}"
        )
        return list(response.get("data") or [])

    def download_resource_url(
        self,
        resource_id: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        response = self.client.post_json(
            "/zw-resource/api/v1/tkResource/download",
            {"resourceDownloadDto": _encrypt_download_payload({"id": resource_id})},
            headers=headers,
        )
        data = response.get("data") or {}
        encrypted_url = str(data.get("resUrl") or "")
        if not encrypted_url:
            return ""
        resource_path = _decrypt_download_value(encrypted_url).strip()
        return urljoin(CDN_BASE_URL, resource_path)


def build_record(item: dict[str, Any], combo: CrawlCombo) -> ResourceRecord:
    names = combo.names()
    price = float(item.get("price") or 0)
    rank_name = item.get("rankName") or names["rank"]
    return ResourceRecord(
        resource_id=str(item.get("resourceId") or item.get("id")),
        resource_name=str(item.get("resourceName") or ""),
        year=str(item.get("yearCode") or names["year"]),
        scene=str(item.get("sceneName") or names["scene"]),
        rank=str(rank_name),
        province=str(item.get("provinceName") or names["province"]),
        grade=str(item.get("gradeName") or names["grade"]),
        term=str(item.get("termName") or names["term"]),
        price=price,
        page_count=int(item.get("pageNum") or 0),
        status=ResourceStatus.pending,
        raw=item,
    )


def _encrypt_download_payload(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    key = AES_KEY.encode()
    cipher = AES.new(key, AES.MODE_CBC, iv=key)
    return b64encode(cipher.encrypt(pad(payload, AES.block_size))).decode()


def _decrypt_download_value(value: str) -> str:
    key = AES_KEY.encode()
    cipher = AES.new(key, AES.MODE_CBC, iv=key)
    return unpad(cipher.decrypt(b64decode(value)), AES.block_size).decode()
