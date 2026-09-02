from __future__ import annotations

import os
import threading
from dataclasses import asdict
from datetime import datetime

from stzy_app.crawler import CrawlStats
from stzy_app.models import ResourceRecord


class UiState:
    """Thread-safe bridge between background crawler and NiceGUI widgets."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.console_log = os.environ.get("STZY_CONSOLE_LOG") == "1"
        self.logs: list[str] = []
        self.records: list[dict[str, object]] = []
        self.stats = CrawlStats()
        self.runner = None
        self.task_running = False
        self.active_proxy = ""

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-300:]
        if self.console_log:
            print(line, flush=True)

    def record(self, record: ResourceRecord) -> None:
        row = asdict(record)
        row["status"] = record.status.value
        row.pop("raw", None)
        with self.lock:
            self.records.insert(0, row)
            self.records = self.records[:500]

    def progress(self, stats: CrawlStats) -> None:
        with self.lock:
            self.stats = CrawlStats(**asdict(stats))
            self.task_running = stats.running

    def proxy(self, value: str) -> None:
        with self.lock:
            self.active_proxy = value

    def snapshot(self) -> tuple[list[str], list[dict[str, object]], CrawlStats, bool, str]:
        with self.lock:
            return list(self.logs), list(self.records), self.stats, self.task_running, self.active_proxy

    def clear_logs(self) -> None:
        with self.lock:
            self.logs.clear()
