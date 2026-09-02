from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def choose_directory(initial_dir: Path) -> Path | None:
    """Open a native folder picker and return the selected directory."""

    initial_dir = initial_dir.expanduser()
    try:
        if platform.system() == "Darwin":
            return _choose_directory_macos(initial_dir)
        return _choose_directory_tk(initial_dir)
    except Exception:
        return None


def _choose_directory_macos(initial_dir: Path) -> Path | None:
    default_dir = initial_dir if initial_dir.exists() else Path.home()
    script = (
        'POSIX path of (choose folder with prompt "选择保存位置" '
        f'default location POSIX file "{default_dir}")'
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
