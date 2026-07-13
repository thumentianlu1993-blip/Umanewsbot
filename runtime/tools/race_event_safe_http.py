#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
from typing import Iterable
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SafeHttpError(RuntimeError):
    pass


def validate_https_url(url: str, *, allowed_hosts: Iterable[str]) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SafeHttpError("source URL must be an unauthenticated HTTPS URL")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "metadata.google.internal"} or hostname.endswith((".local", ".internal")):
        raise SafeHttpError("source URL uses a private or internal host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise SafeHttpError("source URL uses a non-public IP address")
    normalized_hosts = tuple(str(host).rstrip(".").lower() for host in allowed_hosts)
    if not normalized_hosts or not any(
        hostname == allowed or hostname.endswith(f".{allowed}") for allowed in normalized_hosts
    ):
        raise SafeHttpError(f"source URL host is outside allowlist: {hostname}")
    return hostname


class ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: Iterable[str]):
        super().__init__()
        self.allowed_hosts = tuple(allowed_hosts)
        self.redirect_chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_https_url(newurl, allowed_hosts=self.allowed_hosts)
        self.redirect_chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_https(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    timeout: int,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, dict]:
    allowed = tuple(allowed_hosts)
    validate_https_url(url, allowed_hosts=allowed)
    redirect_handler = ValidatingRedirectHandler(allowed)
    opener = build_opener(redirect_handler)
    request = Request(url, headers=headers or {})
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        validate_https_url(final_url, allowed_hosts=allowed)
        body = response.read()
        response_headers = dict(response.headers.items()) if hasattr(response.headers, "items") else {}
        return body, {
            "status": int(getattr(response, "status", 200)),
            "final_url": final_url,
            "redirect_chain": list(redirect_handler.redirect_chain),
            "headers": response_headers,
        }
