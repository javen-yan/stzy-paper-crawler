from __future__ import annotations

import os
import secrets
import socket
import tempfile
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from stzy_app.config import AppSettings


@dataclass(frozen=True)
class RuntimeCapabilities:
    choose_directory: bool
    open_local_path: bool
    bootstrap_login: bool
    admin_login: bool


@dataclass(frozen=True)
class RuntimeInfo:
    mode: str
    host: str
    port: int
    public_base_url: str
    capabilities: RuntimeCapabilities


@dataclass
class RuntimeAdapter:
    settings: AppSettings
    mode: str = "gui"
    host: str = "127.0.0.1"
    port: int = 8080
    bootstrap_token: str = ""

    @classmethod
    def create(cls, settings: AppSettings, *, mode: str, host: str, port: int) -> "RuntimeAdapter":
        normalized_mode = "server" if mode == "server" else "gui"
        actual_host = host or ("0.0.0.0" if normalized_mode == "server" else "127.0.0.1")
        actual_port = port
        if normalized_mode == "gui" and actual_port <= 0:
            actual_port = find_free_port()
        if normalized_mode == "server" and actual_port <= 0:
            actual_port = 8080
        token = secrets.token_urlsafe(32) if normalized_mode == "gui" else ""
        return cls(
            settings=settings,
            mode=normalized_mode,
            host=actual_host,
            port=actual_port,
            bootstrap_token=token,
        )

    @property
    def base_url(self) -> str:
        display_host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        return f"http://{display_host}:{self.port}"

    @property
    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            choose_directory=self.mode == "gui",
            open_local_path=self.mode == "gui",
            bootstrap_login=self.mode == "gui",
            admin_login=self.mode == "server",
        )

    def info(self) -> RuntimeInfo:
        return RuntimeInfo(
            mode=self.mode,
            host=self.host,
            port=self.port,
            public_base_url=self.base_url,
            capabilities=self.capabilities,
        )

    def open_browser_later(self) -> None:
        if self.mode != "gui" or os.environ.get("STZY_NO_BROWSER") == "1":
            return
        url = f"{self.base_url}/#/bootstrap?token={self.bootstrap_token}"
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()


LOCK_PORT = 48723
PORT_FILE = Path(tempfile.gettempdir()) / "stzy-paper-crawler.port"
_LOCK_SOCKET: socket.socket | None = None


def find_free_port(start: int = 8080, attempts: int = 50) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No free port found in range {start}-{start + attempts - 1}")


def acquire_single_instance_lock() -> bool:
    global _LOCK_SOCKET
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        lock_socket.bind(("127.0.0.1", LOCK_PORT))
        lock_socket.listen(1)
    except OSError:
        lock_socket.close()
        return False
    _LOCK_SOCKET = lock_socket
    return True


def write_port_file(port: int) -> None:
    PORT_FILE.write_text(str(port), encoding="utf-8")


def open_existing_instance() -> None:
    try:
        port = int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        print("STZY Paper Crawler is already running.")
        return
    webbrowser.open(f"http://127.0.0.1:{port}")
