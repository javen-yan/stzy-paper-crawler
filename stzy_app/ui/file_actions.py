from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def open_path(path: Path) -> bool:
    target = path.expanduser()
    if not target.exists():
        return False
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(
                ["open", str(target)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Windows":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                ["cmd", "/c", "start", "", str(target)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        else:
            subprocess.Popen(
                ["xdg-open", str(target)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except OSError:
        return False


def preview_first_file(directory: Path) -> bool:
    target_dir = directory.expanduser()
    if not target_dir.exists():
        return False
    for pattern in ("*.svg", "*.png", "*.jpg", "*.jpeg", "*.webp"):
        files = sorted(target_dir.glob(pattern))
        if files:
            return open_path(files[0])
    return open_path(target_dir)
