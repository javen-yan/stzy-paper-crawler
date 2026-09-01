from __future__ import annotations

import socket
import tempfile
import webbrowser
from pathlib import Path

from nicegui import app
from nicegui import ui
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from stzy_app.ui import build_ui

LOCK_PORT = 48723
PORT_FILE = Path(tempfile.gettempdir()) / "stzy-paper-crawler.port"
_LOCK_SOCKET: socket.socket | None = None


def find_free_port(start: int = 8080, attempts: int = 20) -> int:
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


def open_existing_instance() -> None:
    try:
        port = int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        print("STZY Paper Crawler 已在运行，请在浏览器中打开现有窗口。")
        return
    url = f"http://127.0.0.1:{port}"
    print(f"STZY Paper Crawler 已在运行，正在打开：{url}")
    webbrowser.open(url)


def main() -> None:
    if not acquire_single_instance_lock():
        open_existing_instance()
        return
    build_ui()
    port = find_free_port()
    PORT_FILE.write_text(str(port), encoding="utf-8")
    ui.run(title="STZY 试卷图片抓取", reload=False, port=port)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> PlainTextResponse:
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


if __name__ in {"__main__", "__mp_main__"}:
    try:
        main()
    except KeyboardInterrupt:
        pass
