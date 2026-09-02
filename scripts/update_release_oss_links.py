from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


SECTION_TITLE = "### 阿里云 OSS"


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def asset_label(url: str) -> str:
    filename = url.rstrip("/").rsplit("/", 1)[-1]
    if "windows-x64" in filename:
        return "Windows x64"
    if "macos-arm64" in filename:
        return "macOS Apple Silicon"
    if "macos-x64" in filename:
        return "macOS Intel"
    if "linux-x64" in filename:
        return "Linux x64"
    return filename


def replace_section(body: str, section: str) -> str:
    pattern = rf"\n?{re.escape(SECTION_TITLE)}\n.*?(?=\n### |\Z)"
    cleaned = re.sub(pattern, "", body, flags=re.S).rstrip()
    return f"{cleaned}\n\n{section}\n"


def main() -> None:
    version = require_env("RELEASE_VERSION")
    repo = require_env("GITHUB_REPOSITORY")
    urls_path = Path(require_env("OSS_URLS_OUTPUT"))
    urls = [line.strip() for line in urls_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not urls:
        raise SystemExit(f"No OSS URLs found in: {urls_path}")

    body = subprocess.check_output(
        ["gh", "release", "view", version, "--repo", repo, "--json", "body", "--jq", ".body"],
        text=True,
    )
    links = "\n".join(f"- [{asset_label(url)}]({url})" for url in urls)
    section = f"{SECTION_TITLE}\n{links}"
    notes_path = Path("release-notes-with-oss.md")
    notes_path.write_text(replace_section(body, section), encoding="utf-8")

    subprocess.run(
        ["gh", "release", "edit", version, "--repo", repo, "--notes-file", str(notes_path)],
        check=True,
    )
    print(f"Updated release notes with {len(urls)} OSS links.")


if __name__ == "__main__":
    main()
