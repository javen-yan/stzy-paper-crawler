from __future__ import annotations

import os
from pathlib import Path

import oss2


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    access_key_id = require_env("ALIYUN_OSS_ACCESS_KEY_ID")
    access_key_secret = require_env("ALIYUN_OSS_ACCESS_KEY_SECRET")
    bucket_name = require_env("ALIYUN_OSS_BUCKET")
    endpoint = require_env("ALIYUN_OSS_ENDPOINT")
    public_base_url = require_env("ALIYUN_OSS_PUBLIC_BASE_URL").rstrip("/")
    local_dir = Path(require_env("UPLOAD_DIR"))
    oss_prefix = os.environ.get("OSS_PREFIX", "stzy-paper-crawler").strip().strip("/")

    if not local_dir.exists():
        raise SystemExit(f"Upload directory does not exist: {local_dir}")

    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    uploaded: list[str] = []
    for path in sorted(local_dir.glob("*")):
        if not path.is_file():
            continue
        object_key = f"{oss_prefix}/{path.name}" if oss_prefix else path.name
        bucket.put_object_from_file(object_key, str(path))
        uploaded.append(f"{public_base_url}/{object_key}")

    if not uploaded:
        raise SystemExit(f"No files to upload in: {local_dir}")

    print("Uploaded files:")
    for url in uploaded:
        print(url)

    output_path = os.environ.get("OSS_URLS_OUTPUT", "").strip()
    if output_path:
        Path(output_path).write_text("\n".join(uploaded) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
