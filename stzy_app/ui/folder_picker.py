from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def choose_directory(initial_dir: Path) -> Path | None:
    """Open a native folder picker and return the selected directory."""

    initial_dir = initial_dir.expanduser()
    try:
        system = platform.system()
        if system == "Darwin":
            return _choose_directory_macos(initial_dir)
        if system == "Linux" and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        ):
            return None
        return _choose_directory_tk(initial_dir)
    except Exception:
        return None


def _choose_directory_macos(initial_dir: Path) -> Path | None:
    default_dir = initial_dir if initial_dir.exists() else Path.home()
    escaped_dir = _escape_applescript_string(str(default_dir))
    script = (
        'POSIX path of (choose folder with prompt "选择保存位置" '
        f'default location POSIX file "{escaped_dir}")'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    selected = result.stdout.strip()
    return Path(selected) if selected else None


def _escape_applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _choose_directory_tk(initial_dir: Path) -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(
            initialdir=str(initial_dir if initial_dir.exists() else Path.home()),
            title="选择保存位置",
        )
    finally:
        root.destroy()
    return Path(selected) if selected else None
