from __future__ import annotations

import re
from pathlib import Path


def safe_filename(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\n\r\t]+', "_", value).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or fallback


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

