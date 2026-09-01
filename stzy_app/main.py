from __future__ import annotations

import socket

from nicegui import ui

from stzy_app.ui import build_ui


def find_free_port(start: int = 8080, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No free port found in range {start}-{start + attempts - 1}")


def main() -> None:
    build_ui()
    port = find_free_port()
    ui.run(title="STZY 试卷图片抓取", reload=False, port=port)


if __name__ in {"__main__", "__mp_main__"}:
    main()
