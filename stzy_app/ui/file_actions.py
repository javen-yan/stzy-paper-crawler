from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def open_path(path: Path) -> bool:
    target = path.expanduser()
    if not target.exists():
        return False
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", str(target)])
    elif system == "Windows":
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return True


def preview_first_file(directory: Path) -> bool:
    target_dir = directory.expanduser()
    if not target_dir.exists():
        return False
    for pattern in ("*.svg", "*.png", "*.jpg", "*.jpeg", "*.webp"):
        files = sorted(target_dir.glob(pattern))
        if files:
            return open_path(files[0])
    return open_path(target_dir)
