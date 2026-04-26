from __future__ import annotations

import posixpath
import uuid
from datetime import datetime
from email.utils import parsedate_to_datetime
from io import BytesIO
from urllib.parse import urlparse

import oss2
from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible


def _normalize_endpoint(endpoint: str) -> str:
    value = (endpoint or "").strip()
    if not value:
        raise ValueError("OSS_ENDPOINT is required when MEDIA_STORAGE_BACKEND=oss")
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _build_public_base_url() -> str:
    custom = (getattr(settings, "OSS_PUBLIC_BASE_URL", "") or "").strip()
    if custom:
        return custom.rstrip("/")
    endpoint = _normalize_endpoint(getattr(settings, "OSS_ENDPOINT", ""))
    parsed = urlparse(endpoint)
    return f"{parsed.scheme}://{settings.OSS_BUCKET_NAME}.{parsed.netloc}"


@deconstructible
class AliyunOSSStorage(Storage):
    def __init__(self) -> None:
        self.bucket_name = settings.OSS_BUCKET_NAME
        self.endpoint = _normalize_endpoint(settings.OSS_ENDPOINT)
        self.media_prefix = (getattr(settings, "OSS_MEDIA_PREFIX", "media") or "media").strip("/ ")
        self.public_base_url = _build_public_base_url()
        auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
        self.bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)

    def _full_key(self, name: str) -> str:
        normalized = str(name).replace("\\", "/").lstrip("/")
        if not self.media_prefix:
            return normalized
        return posixpath.join(self.media_prefix, normalized)

    def _strip_prefix(self, key: str) -> str:
        normalized = str(key).replace("\\", "/").lstrip("/")
        prefix = f"{self.media_prefix}/" if self.media_prefix else ""
        if prefix and normalized.startswith(prefix):
            return normalized[len(prefix) :]
        return normalized

    def _open(self, name: str, mode: str = "rb") -> File:
        if "r" not in mode:
            raise ValueError("AliyunOSSStorage only supports read mode for open()")
        result = self.bucket.get_object(self._full_key(name))
        return File(BytesIO(result.read()), name=name)

    def _save(self, name: str, content) -> str:
        name = self.get_available_name(name)
        key = self._full_key(name)
        if hasattr(content, "seek"):
            content.seek(0)
        self.bucket.put_object(key, content.read())
        return name

    def delete(self, name: str) -> None:
        if not name:
            return
        self.bucket.delete_object(self._full_key(name))

    def exists(self, name: str) -> bool:
        return self.bucket.object_exists(self._full_key(name))

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        prefix = self._full_key(path).rstrip("/")
        if prefix:
            prefix = f"{prefix}/"
        directories: set[str] = set()
        files: list[str] = []
        for item in oss2.ObjectIteratorV2(self.bucket, prefix=prefix, delimiter="/"):
            key = item.key.rstrip("/")
            if key.endswith("/"):
                directories.add(self._strip_prefix(key))
            else:
                files.append(self._strip_prefix(key))
        return sorted(directories), sorted(files)

    def size(self, name: str) -> int:
        return self.bucket.get_object_meta(self._full_key(name)).content_length

    def url(self, name: str) -> str:
        normalized = str(name).lstrip("/")
        return f"{self.public_base_url}/{self._full_key(normalized)}"

    def get_modified_time(self, name: str) -> datetime:
        headers = self.bucket.get_object_meta(self._full_key(name)).headers
        last_modified = headers.get("Last-Modified")
        if not last_modified:
            return datetime.utcnow()
        return parsedate_to_datetime(last_modified)

    def get_available_name(self, name: str, max_length: int | None = None) -> str:
        candidate = str(name).replace("\\", "/").lstrip("/")
        if not self.exists(candidate):
            return candidate
        stem, dot, suffix = candidate.rpartition(".")
        if not dot:
            stem, suffix = candidate, ""
        unique = uuid.uuid4().hex[:8]
        if suffix:
            candidate = f"{stem}-{unique}.{suffix}"
        else:
            candidate = f"{stem}-{unique}"
        if max_length and len(candidate) > max_length:
            candidate = candidate[:max_length]
        return candidate
