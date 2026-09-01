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

    output_dir: Path = Field(default=Path("output/stzy"))
    state_file: Path = Field(default=Path("stzy.db"))
    csv_file: Path = Field(default=Path("stzy.db"))
    task_history_file: Path = Field(default=Path("stzy.db"))
    cookie_file: Path = Field(default=Path("output/stzy/cookies.json"))
    account_pool_file: Path = Field(default=Path("stzy.db"))

    api_base_url: str = "https://qms.stzy.com/matrix"
    site_base_url: str = "https://www.stzy.com"
    study_phase_code: str = "200"
    subject_code: str = ""
    subject_name: str = "不限"

    list_delay_seconds: float = 0.8
    image_delay_seconds: float = 0.3
    concurrency: int = 1
    max_retries: int = 3
    connect_timeout: float = 6.0
    read_timeout: float = 30.0
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    access_token: Optional[str] = None
    cookie_header: Optional[str] = None


settings = AppSettings()
