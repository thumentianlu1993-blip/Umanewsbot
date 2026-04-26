from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import oss2


def _normalize_endpoint(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("OSS endpoint is empty")
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python deploy/upload_backup_to_oss.py <backup-file>")
        return 1

    backup_path = Path(sys.argv[1]).resolve()
    if not backup_path.exists():
        print(f"Backup file not found: {backup_path}")
        return 1

    access_key_id = os.getenv("OSS_ACCESS_KEY_ID", "").strip()
    access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "").strip()
    bucket_name = os.getenv("OSS_BUCKET_NAME", "").strip()
    endpoint = _normalize_endpoint(os.getenv("OSS_ENDPOINT", "").strip())
    backup_prefix = os.getenv("OSS_BACKUP_PREFIX", "db_backups").strip("/ ")

    if not access_key_id or not access_key_secret or not bucket_name:
        print("Missing OSS credentials or bucket settings in environment variables.")
        return 1

    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    object_key = f"{backup_prefix}/{backup_path.name}" if backup_prefix else backup_path.name
    with backup_path.open("rb") as fp:
        bucket.put_object(object_key, fp)

    parsed = urlparse(endpoint)
    public_url = f"{parsed.scheme}://{bucket_name}.{parsed.netloc}/{object_key}"
    print(f"Uploaded to OSS: {public_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

