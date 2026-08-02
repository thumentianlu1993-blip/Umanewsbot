"""Single bounded HTTPS transport implementation for race-event sources."""

from __future__ import annotations

import ipaddress
import re
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


__all__ = (
    "Request",
    "SafeHttpError",
    "ValidatingRedirectHandler",
    "fetch_https",
    "validate_https_url",
)


class SafeHttpError(RuntimeError):
    pass


def validate_https_url(url: str, *, allowed_hosts: Iterable[str]) -> str:
    parsed = urlparse(str(url or "").strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise SafeHttpError(
            "source URL must be an unauthenticated HTTPS URL"
        )
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {
        "localhost",
        "metadata.google.internal",
    } or hostname.endswith((".local", ".internal")):
        raise SafeHttpError("source URL uses a private or internal host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SafeHttpError("source URL uses a non-public IP address")
    normalized_hosts = tuple(
        str(host).rstrip(".").lower() for host in allowed_hosts
    )
    if not normalized_hosts or not any(
        hostname == allowed or hostname.endswith(f".{allowed}")
        for allowed in normalized_hosts
    ):
        raise SafeHttpError(
            f"source URL host is outside allowlist: {hostname}"
        )
    return hostname


class ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        allowed_path_pattern: str | None = None,
        max_redirects: int | None = None,
        url_validator: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.allowed_hosts = tuple(allowed_hosts)
        self.allowed_path_pattern = (
            re.compile(allowed_path_pattern)
            if allowed_path_pattern
            else None
        )
        if max_redirects is not None and max_redirects < 0:
            raise SafeHttpError("max_redirects must be non-negative")
        self.max_redirects = max_redirects
        self.url_validator = url_validator
        self.redirect_chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        absolute_url = urljoin(req.full_url, newurl)
        _validate_route(
            absolute_url,
            allowed_hosts=self.allowed_hosts,
            allowed_path_pattern=self.allowed_path_pattern,
            url_validator=self.url_validator,
        )
        if (
            self.max_redirects is not None
            and len(self.redirect_chain) >= self.max_redirects
        ):
            raise SafeHttpError(
                f"redirect count exceeds configured maximum {self.max_redirects}"
            )
        self.redirect_chain.append(absolute_url)
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )


def _validate_route(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    allowed_path_pattern: re.Pattern[str] | None,
    url_validator: Callable[[str], None] | None,
) -> None:
    validate_https_url(url, allowed_hosts=allowed_hosts)
    parsed = urlparse(url)
    if allowed_path_pattern:
        if parsed.query or parsed.fragment:
            raise SafeHttpError(
                "source URL route must not contain query or fragment"
            )
        if allowed_path_pattern.match(parsed.path) is None:
            raise SafeHttpError("source URL path is outside allowlist")
    if url_validator is not None:
        url_validator(url)


def _single_header(response, name: str) -> str | None:
    headers = response.headers
    if hasattr(headers, "get_all"):
        values = headers.get_all(name)
    else:
        values = [
            value
            for key, value in (
                headers.items() if hasattr(headers, "items") else ()
            )
            if str(key).casefold() == name.casefold()
        ]
    values = list(values or [])
    if len(
        {str(value).strip().casefold() for value in values}
    ) > 1:
        raise SafeHttpError(f"conflicting {name} response headers")
    return str(values[0]).strip() if values else None


def _read_bounded(response, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = response.read(min(64 * 1024, max_bytes + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise SafeHttpError(
                f"response body exceeds {max_bytes} bytes"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_https(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    timeout: int,
    headers: dict[str, str] | None = None,
    allowed_path_pattern: str | None = None,
    allowed_content_types: Iterable[str] | None = None,
    max_bytes: int | None = None,
    max_redirects: int | None = None,
    url_validator: Callable[[str], None] | None = None,
) -> tuple[bytes, dict]:
    allowed = tuple(allowed_hosts)
    if max_bytes is not None and max_bytes <= 0:
        raise SafeHttpError("max_bytes must be positive")
    compiled_path = (
        re.compile(allowed_path_pattern)
        if allowed_path_pattern
        else None
    )
    _validate_route(
        url,
        allowed_hosts=allowed,
        allowed_path_pattern=compiled_path,
        url_validator=url_validator,
    )
    redirect_handler = ValidatingRedirectHandler(
        allowed,
        allowed_path_pattern=allowed_path_pattern,
        max_redirects=max_redirects,
        url_validator=url_validator,
    )
    opener = build_opener(redirect_handler)
    request = Request(url, headers=headers or {})
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        _validate_route(
            final_url,
            allowed_hosts=allowed,
            allowed_path_pattern=compiled_path,
            url_validator=url_validator,
        )
        if allowed_content_types is not None:
            allowed_mime_types = {
                str(value).strip().casefold()
                for value in allowed_content_types
            }
            content_type = _single_header(response, "Content-Type")
            if content_type is None:
                raise SafeHttpError("response Content-Type is required")
            mime_type = (
                content_type.split(";", 1)[0].strip().casefold()
            )
            if mime_type not in allowed_mime_types:
                raise SafeHttpError(
                    f"unsupported response Content-Type: {mime_type}"
                )
        if max_bytes is None:
            body = response.read()
        else:
            content_length = _single_header(response, "Content-Length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError as exc:
                    raise SafeHttpError(
                        "invalid response Content-Length"
                    ) from exc
                if declared_size < 0 or declared_size > max_bytes:
                    raise SafeHttpError(
                        f"response Content-Length exceeds {max_bytes} bytes"
                    )
            body = _read_bounded(response, max_bytes=max_bytes)
        response_headers = (
            dict(response.headers.items())
            if hasattr(response.headers, "items")
            else {}
        )
        return body, {
            "status": int(getattr(response, "status", 200)),
            "final_url": final_url,
            "redirect_chain": list(redirect_handler.redirect_chain),
            "headers": response_headers,
        }
