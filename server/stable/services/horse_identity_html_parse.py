"""Pure parsers for horse identity links in locally cached HTML pages.

No Django imports and no network access: these functions are shared between
the offline enrichment service tests and the runtime reparse tool that walks
the local HTML cache directories.

Supported same-origin ID shapes:
- HKJC result pages link horses with ``HorseId=<id>`` query parameters.
- NAR (keiba.go.jp) pages link horses with ``k_lineageLoginCode=<id>``.
"""

from __future__ import annotations

import re

_HKJC_LINK_RE = re.compile(
    r"<a\b[^>]*horseid=([A-Za-z0-9_%-]+)[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_NAR_LINK_RE = re.compile(
    r"<a\b[^>]*k_lineagelogincode=(\d+)[^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_anchor_text(fragment: str) -> str:
    text = _TAG_RE.sub("", fragment)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _extract(link_re: re.Pattern[str], html: str) -> list[dict[str, str]]:
    pairs: dict[str, str] = {}
    for match in link_re.finditer(html or ""):
        external_id = match.group(1).strip()
        name = _clean_anchor_text(match.group(2))
        if not external_id:
            continue
        # Keep the longest name seen for an ID; anchors sometimes wrap only an
        # icon while a sibling anchor carries the actual horse name.
        if not pairs.get(external_id) or (name and len(name) > len(pairs[external_id])):
            pairs[external_id] = name
    return [
        {"external_id": external_id, "name": name}
        for external_id, name in sorted(pairs.items())
    ]


def parse_hkjc_horse_links(html: str) -> list[dict[str, str]]:
    """Return ``{external_id, name}`` pairs from HKJC ``HorseId=`` anchors."""
    return _extract(_HKJC_LINK_RE, html)


def parse_nar_horse_links(html: str) -> list[dict[str, str]]:
    """Return ``{external_id, name}`` pairs from NAR ``k_lineageLoginCode=`` anchors."""
    return _extract(_NAR_LINK_RE, html)


def parse_horse_links(html: str, *, namespace: str) -> list[dict[str, str]]:
    if namespace == "hkjc":
        return parse_hkjc_horse_links(html)
    if namespace == "nar":
        return parse_nar_horse_links(html)
    raise ValueError(f"unsupported horse-link namespace: {namespace}")
