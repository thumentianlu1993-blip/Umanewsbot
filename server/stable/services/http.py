from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

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


@dataclass(frozen=True)
class BoundedHtmlResponse:
    text: str
    final_url: str
    status_code: int
    content_type: str
    content_length: int
    redirect_count: int


class BoundedHttpError(ValueError):
    """有界请求的安全结构化失败，不携带响应正文或请求头。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        final_url: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.final_url = final_url


def _validated_https_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").casefold()
    if parsed.scheme.casefold() != "https":
        raise ValueError("bounded_http_https_required")
    if parsed.username or parsed.password:
        raise ValueError("bounded_http_credentials_forbidden")
    if not host or host not in allowed_hosts:
        raise ValueError("bounded_http_host_not_allowed")
    return url


def get_bounded_html(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] | list[str] | set[str],
    max_redirects: int = 3,
    max_bytes: int = 2 * 1024 * 1024,
    connect_timeout: int | float = 5,
    read_timeout: int | float = 15,
    user_agent: str | None = None,
    accepted_content_types: tuple[str, ...] | list[str] | set[str] | None = None,
) -> BoundedHtmlResponse:
    """为新增官方新闻来源执行 fail-closed 的有界 HTML GET。

    旧来源继续使用原有 ``get_bytes``/``requests`` 路径，避免本次变更改变既有
    网络行为。调用者必须显式提供静态 host allowlist。
    """

    normalized_hosts = {
        str(host).strip().rstrip(".").casefold()
        for host in allowed_hosts
        if str(host).strip()
    }
    if not normalized_hosts:
        raise ValueError("bounded_http_empty_host_allowlist")
    if max_redirects < 0 or max_redirects > 3:
        raise ValueError("bounded_http_invalid_redirect_limit")
    if max_bytes <= 0 or max_bytes > 2 * 1024 * 1024:
        raise ValueError("bounded_http_invalid_size_limit")
    normalized_content_types = {
        str(content_type).strip().casefold()
        for content_type in (
            accepted_content_types
            if accepted_content_types is not None
            else ("text/html", "application/xhtml+xml")
        )
        if str(content_type).strip()
    }
    if not normalized_content_types:
        raise ValueError("bounded_http_empty_content_types")
    if user_agent is None:
        request_headers = DEFAULT_HEADERS
    else:
        normalized_user_agent = str(user_agent).strip()
        if not normalized_user_agent:
            raise ValueError("bounded_http_empty_user_agent")
        request_headers = {"User-Agent": normalized_user_agent}

    current_url = _validated_https_url(url, normalized_hosts)
    session = requests.Session()
    redirects = 0
    while True:
        response = session.get(
            current_url,
            headers=request_headers,
            timeout=(connect_timeout, read_timeout),
            allow_redirects=False,
            stream=True,
        )
        try:
            status_code = int(response.status_code)
            if status_code in {301, 302, 303, 307, 308}:
                location = (response.headers.get("Location") or "").strip()
                if not location:
                    raise ValueError("bounded_http_redirect_without_location")
                if redirects >= max_redirects:
                    raise ValueError("bounded_http_too_many_redirects")
                current_url = _validated_https_url(urljoin(current_url, location), normalized_hosts)
                redirects += 1
                continue

            final_url = _validated_https_url(
                str(getattr(response, "url", "") or current_url),
                normalized_hosts,
            )
            if status_code != 200:
                raise BoundedHttpError(
                    f"bounded_http_unexpected_status:{status_code}",
                    status_code=status_code,
                    final_url=final_url,
                )
            response.raise_for_status()
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
            if content_type not in normalized_content_types:
                raise ValueError("bounded_http_non_html")
            raw_length = (response.headers.get("Content-Length") or "").strip()
            if raw_length:
                try:
                    declared_length = int(raw_length)
                except ValueError as exc:
                    raise ValueError("bounded_http_invalid_content_length") from exc
                if declared_length > max_bytes:
                    raise ValueError("bounded_http_response_too_large")

            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError("bounded_http_response_too_large")
            if not body:
                raise ValueError("bounded_http_empty_response")

            encoding = response.encoding or "utf-8"
            text = bytes(body).decode(encoding, errors="replace")
            folded = text[:200_000].casefold()
            blocked_markers = (
                "captcha",
                "verify you are human",
                "checking your browser",
                "access denied",
                "cloudflare ray id",
                "please log in",
                "sign in to continue",
            )
            if any(marker in folded for marker in blocked_markers):
                raise ValueError("bounded_http_login_or_captcha")
            return BoundedHtmlResponse(
                text=text,
                final_url=final_url,
                status_code=status_code,
                content_type=content_type,
                content_length=len(body),
                redirect_count=redirects,
            )
        finally:
            response.close()
