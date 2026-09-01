from __future__ import annotations

import threading
from dataclasses import asdict
from datetime import datetime

from stzy_app.crawler import CrawlStats
from stzy_app.models import ResourceRecord


class UiState:
    """Thread-safe bridge between background crawler and NiceGUI widgets."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.logs: list[str] = []
        self.records: list[dict[str, object]] = []
        self.stats = CrawlStats()
        self.runner = None
        self.task_running = False

    def log(self, message: str) -> None:
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.logs.append(f"[{timestamp}] {message}")
            self.logs = self.logs[-300:]

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

    def snapshot(self) -> tuple[list[str], list[dict[str, object]], CrawlStats, bool]:
        with self.lock:
            return list(self.logs), list(self.records), self.stats, self.task_running

    def clear_logs(self) -> None:
        with self.lock:
            self.logs.clear()

