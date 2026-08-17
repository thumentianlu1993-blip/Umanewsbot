from __future__ import annotations

import os
import sys
from pathlib import Path

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
    if not backup_path.is_file():
        print(f"Backup file not found: {backup_path}")
        return 1
    local_size = backup_path.stat().st_size
    if local_size <= 0:
        print(f"Backup file is empty: {backup_path}")
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
        result = bucket.put_object(object_key, fp)
    if getattr(result, "status", None) not in {200, 201}:
        print(f"OSS upload returned unexpected status: {getattr(result, 'status', None)}")
        return 1

    remote = bucket.head_object(object_key)
    remote_size = getattr(remote, "content_length", None)
    if remote_size != local_size:
        print(
            "OSS upload size mismatch: "
            f"local={local_size} remote={remote_size} key={object_key}"
        )
        return 1
    print(f"OSS upload verified: key={object_key} size={local_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
