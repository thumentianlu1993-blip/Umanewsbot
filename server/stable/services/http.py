from __future__ import annotations

import requests

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}


def get_bytes(url: str, params: dict | None = None, encoding: str | None = None) -> bytes | str:
    response = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    if encoding:
        response.encoding = encoding
        return response.text
    return response.content
