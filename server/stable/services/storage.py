from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone


def current_media_provider() -> str:
    return "oss" if getattr(settings, "MEDIA_STORAGE_BACKEND", "local") == "oss" else "local"


def resolve_media_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    url = default_storage.url(path_or_url)
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        return f"{settings.SITE_URL.rstrip('/')}{url}"
    return f"{settings.SITE_URL.rstrip('/')}/{url.lstrip('/')}"


def download_image(original_url: str) -> str:
    parsed = urlparse(original_url)
    extension = Path(parsed.path).suffix
    if not extension:
        guessed, _ = mimetypes.guess_type(original_url)
        extension = mimetypes.guess_extension(guessed or "image/jpeg") or ".jpg"
    relative_dir = Path("news_images") / f"{timezone.localtime():%Y/%m/%d}"
    filename = f"{uuid.uuid4().hex}{extension}"
    relative_path = (relative_dir / filename).as_posix()
    response = requests.get(original_url, timeout=10)
    response.raise_for_status()
    default_storage.save(relative_path, ContentFile(response.content))
    return relative_path

