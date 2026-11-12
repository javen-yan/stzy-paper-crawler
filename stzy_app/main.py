from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
from pathlib import Path

import uvicorn

from stzy_app.config import AppSettings
from stzy_app.domain.context import create_context
from stzy_app.domain.identity import hash_password
from stzy_app.runtime import RuntimeAdapter, acquire_single_instance_lock, open_existing_instance, write_port_file
from stzy_app.web import create_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="STZY Paper Crawler")
    parser.add_argument("--mode", choices=["gui", "server"], default="gui")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--admin-password-hash", default="")
    parser.add_argument("--hash-password", default="")
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.no_browser:
        os.environ["STZY_NO_BROWSER"] = "1"
    if args.hash_password:
        print(hash_password(args.hash_password))
        return
    mode = args.mode
    if mode == "gui" and not acquire_single_instance_lock():
        open_existing_instance()
        return
    host = args.host or ("0.0.0.0" if mode == "server" else "127.0.0.1")
    if args.data_dir:
        # Conversion runs in child processes that re-read config, so export it too.
        os.environ["STZY_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    settings = AppSettings()
    updates = {}
    if args.data_dir:
        updates["data_dir"] = Path(args.data_dir)
        updates["output_dir"] = Path(args.data_dir)
    if args.admin_password_hash:
        updates["admin_password_hash"] = args.admin_password_hash
    if updates:
        settings = settings.model_copy(update=updates)
    if mode == "server":
        settings = _settings_with_server_password(settings)
    runtime = RuntimeAdapter.create(settings, mode=mode, host=host, port=args.port)
    if mode == "gui":
        write_port_file(runtime.port)
    context = create_context(settings, runtime)
    app = create_app(context)

    print("", flush=True)
    print("STZY Paper Crawler", flush=True)
    print(f"[mode] {runtime.mode}", flush=True)
    print(f"[listen] {runtime.host}:{runtime.port}", flush=True)
    print(f"[data] {context.settings.data_dir}", flush=True)
    if runtime.mode == "gui":
        print(f"[open] {runtime.base_url}", flush=True)
        if args.no_browser:
            print("[browser] disabled by --no-browser", flush=True)
        else:
            runtime.open_browser_later()
    else:
        print("[server] external nginx/https is managed outside this app", flush=True)
    print("", flush=True)

    uvicorn.run(
        app,
        host=runtime.host,
        port=runtime.port,
        log_level="info" if runtime.mode == "server" else "warning",
    )


def _settings_with_server_password(settings: AppSettings) -> AppSettings:
    if settings.admin_password_hash:
        return settings
    password = _read_admin_password(settings)
    if not password:
        raise SystemExit(
            "Server 模式必须配置管理员密码。推荐先运行：\n"
            "  python -m stzy_app.main --hash-password 'your-admin-password'\n"
            "然后设置环境变量 STZY_ADMIN_PASSWORD_HASH。也可使用 STZY_ADMIN_PASSWORD_FILE 指向密码文件。"
        )
    _validate_admin_password_strength(password)
    return settings.model_copy(update={"admin_password_hash": hash_password(password), "admin_password": ""})


def _read_admin_password(settings: AppSettings) -> str:
    if settings.admin_password_file:
        try:
            return settings.admin_password_file.expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SystemExit(f"读取 STZY_ADMIN_PASSWORD_FILE 失败：{exc}") from exc
    return settings.admin_password.strip()


def _validate_admin_password_strength(password: str) -> None:
    if len(password) < 10:
        raise SystemExit("Server 管理员密码至少需要 10 位。")
    if password.lower() in {"password", "admin123456", "1234567890", "stzy123456"}:
        raise SystemExit("Server 管理员密码过于简单，请更换。")
    if password.isdigit() or password.isalpha():
        raise SystemExit("Server 管理员密码需要同时包含字母和非字母字符。")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        pass
