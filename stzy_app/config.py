from __future__ import annotations

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class AppSettings(BaseSettings):
    """Runtime settings shared by the GUI, crawler and HTTP client."""

    model_config = SettingsConfigDict(env_prefix="STZY_", extra="ignore")

    output_dir: Path = Field(default=Path("output"))
    data_dir: Path = Field(default=Path("."))
    state_file: Path = Field(default=Path("stzy.db"))
    csv_file: Path = Field(default=Path("stzy.db"))
    task_history_file: Path = Field(default=Path("stzy.db"))
    cookie_file: Path = Field(default=Path("output/cookies.json"))
    account_pool_file: Path = Field(default=Path("stzy.db"))

    runtime_mode: str = "gui"
    host: str = "127.0.0.1"
    port: int = 8080
    admin_password: str = ""
    admin_password_file: Optional[Path] = None
    admin_password_hash: str = ""
    secret_key: str = ""
    max_active_tasks: int = 2
    max_download_workers: int = 4
    max_convert_workers: int = 2
    max_export_workers: int = 1
    preview_max_pages: int = 300
    preview_max_pixels: int = 24_000_000
    preview_timeout_seconds: int = 45
    document_timeout_seconds: int = 180
    export_ttl_hours: int = 24
    disk_low_watermark_mb: int = 1024
    task_scope: str = ""

    api_base_url: str = "https://qms.stzy.com/matrix"
    site_base_url: str = "https://www.stzy.com"
    study_phase_code: str = "200"
    subject_code: str = ""
    subject_name: str = "不限"
    file_type: str = ""
    max_pages_per_combo: Optional[int] = None

    list_delay_seconds: float = 0.8
    image_delay_seconds: float = 0.3
    list_max_retries: int = 3
    combo_failure_limit: int = 10
    concurrency: int = 1
    max_retries: int = 3
    connect_timeout: float = 6.0
    read_timeout: float = 30.0
    proxy_mode: str = "off"
    proxy_provider: str = "generic"
    proxy_pool: str = ""
    proxy_api_url: str = ""
    proxy_max_failures: int = 3
    proxy_cooldown_seconds: float = 300.0
    proxy_min_ttl_seconds: float = 30.0
    shenlong_whitelist_key: str = ""
    shenlong_whitelist_sign: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    access_token: Optional[str] = None
    cookie_header: Optional[str] = None


settings = AppSettings()
