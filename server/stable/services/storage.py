from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.utils import timezone


def download_image(original_url: str) -> str:
    parsed = urlparse(original_url)
    extension = Path(parsed.path).suffix
    if not extension:
        guessed, _ = mimetypes.guess_type(original_url)
        extension = mimetypes.guess_extension(guessed or "image/jpeg") or ".jpg"
    relative_dir = Path("news_images") / f"{timezone.localtime():%Y/%m/%d}"
    target_dir = Path(settings.MEDIA_ROOT) / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{extension}"
    response = requests.get(original_url, timeout=10, stream=True)
    response.raise_for_status()
    with open(target_dir / filename, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)
    return str((relative_dir / filename).as_posix())
