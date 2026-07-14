from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from bs4 import Tag

from stable.models import SourceSite
from stable.services.text import extract_article_text, normalize_whitespace


# ``extract_article_text`` emits a newline at every block boundary. Pretty
# printed HTML may add another newline between sibling tags, while minified
# production HTML does not, so a single newline is the stable DOM boundary.
_PARAGRAPH_SPLIT_RE = re.compile(r"\n+")
# These expressions deliberately do not match a bare bookmaker name, "bet" in
# a sponsored race title, or factual odds. Only explicit promotion/advice
# signals are removed.
_BETTING_PROMOTION_RE = re.compile(
    r"(?:\bbet now\b|\bfree bets?\b|\bbest bets?\b|\bcharity bet\b|"
    r"\bcharity tipping challenge\b|\bwinning tipster\b|"
    r"\bbetting tips?\b|\bdaily racing tips?\b|\bclaim\s+(?:£|\$|€)\s*\d+|"
    r"\bsign up\b.*\b(?:bet|offer|bonus)\b|\bexclusive offers?\b|"
    r"\bgambling problem\b|\bsafer gambling\b|\bresponsible gambling\b|"
    r"\bdownload (?:our|the) app\b.*\b(?:bet|offer|tip))",
    re.IGNORECASE,
)
_STANDALONE_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_LINK_CTA_SENTENCE_RE = re.compile(
    r"(?:^|\s+)(?:"
    r"click here\b[^.!?]*\.?|"
    r"(?:to|for)\b[^.!?]{0,180}\bclick here\.?)",
    re.IGNORECASE,
)

_STRUCTURED_NOISE_SELECTORS = (
    "nav",
    "footer",
    "aside",
    "form",
    "script",
    "style",
    "noscript",
    "[class*='ShareBlock']",
    "[class*='ArticleShare']",
    "[class*='ArticleSocialMediaButtons__StyledInnerContainer']",
    "[class*='SocialShare']",
)

_SPONICHI_STRUCTURED_NOISE_SELECTORS = (
    "figure",
    "#article_more_area",
    "#login_article_more_area",
)

_SPONICHI_PROMOTION_RE = re.compile(
    r"(?:スポニチ予想.*(?:販売中|プリントサービス)|e-printservice\.net)",
    re.IGNORECASE,
)

_TDN_LEADING_RULES = (
    ("tdn_editor_note", re.compile(r"^editor[’']s note\s*:", re.IGNORECASE)),
    (
        "tdn_leading_link",
        re.compile(r"^to (?:view|read|access)\b", re.IGNORECASE),
    ),
)

_TDN_TAIL_RULES = (
    ("tdn_results_cta", re.compile(r"^for a complete (?:list of )?results\b.*\b(?:go|click) here\.?$", re.IGNORECASE)),
    ("tdn_read_paper", re.compile(r"^read today[’']s paper\.?$", re.IGNORECASE)),
)

_SPORTING_LIFE_TAIL_RULES = (
    ("sporting_life_more", re.compile(r"^more from sporting life\.?$", re.IGNORECASE)),
    ("sporting_life_like", re.compile(r"^like what you(?:'|’)ve read\??", re.IGNORECASE)),
)

_SPORTING_LIFE_INLINE_RULES = (
    (
        "sponsor_clause",
        re.compile(r"^backed by [^,]{1,80}(?:again\s+)?for\s+20\d{2},\s*", re.IGNORECASE),
    ),
    ("link_cta", re.compile(r"^book now\s+", re.IGNORECASE)),
)


@dataclass(frozen=True)
class ArticleContentCleanResult:
    text: str
    status: str
    removed_rules: dict[str, int]

    @property
    def removed_count(self) -> int:
        return sum(self.removed_rules.values())

    def metadata(self) -> dict[str, object]:
        return {
            "removed_count": self.removed_count,
            "removed_rules": dict(self.removed_rules),
        }


def _source_value(source_site: SourceSite | str) -> str:
    return source_site.value if isinstance(source_site, SourceSite) else str(source_site)


def _remove_structured_noise(node: Tag, removed: Counter[str]) -> None:
    for selector in _STRUCTURED_NOISE_SELECTORS:
        matches = list(node.select(selector))
        for match in matches:
            match.decompose()
        if matches:
            removed["structured_noise"] += len(matches)


def _remove_source_structured_noise(node: Tag, source: str, removed: Counter[str]) -> None:
    if source != SourceSite.SPONICHI:
        return
    for selector in _SPONICHI_STRUCTURED_NOISE_SELECTORS:
        matches = list(node.select(selector))
        for match in matches:
            match.decompose()
        if matches:
            removed["sponichi_structured_noise"] += len(matches)


def _paragraphs(node: Tag) -> list[str]:
    raw = extract_article_text(node)
    return [normalize_whitespace(part) for part in _PARAGRAPH_SPLIT_RE.split(raw) if normalize_whitespace(part)]


def _drop_leading(paragraphs: list[str], rules: tuple[tuple[str, re.Pattern[str]], ...], removed: Counter[str]) -> list[str]:
    remaining = list(paragraphs)
    while remaining:
        matched_rule = next((name for name, pattern in rules if pattern.search(remaining[0])), "")
        if not matched_rule:
            break
        removed[matched_rule] += 1
        remaining.pop(0)
    return remaining


def _truncate_tail(paragraphs: list[str], rules: tuple[tuple[str, re.Pattern[str]], ...], removed: Counter[str]) -> list[str]:
    for index, paragraph in enumerate(paragraphs):
        for name, pattern in rules:
            if pattern.search(paragraph):
                removed[name] += len(paragraphs) - index
                return paragraphs[:index]
    return paragraphs


def _remove_betting_promotions(paragraphs: list[str], removed: Counter[str]) -> list[str]:
    kept: list[str] = []
    for paragraph in paragraphs:
        if _BETTING_PROMOTION_RE.search(paragraph):
            removed["betting_promotion"] += 1
        else:
            kept.append(paragraph)
    return kept


def _remove_sponichi_promotions(paragraphs: list[str], removed: Counter[str]) -> list[str]:
    kept: list[str] = []
    for paragraph in paragraphs:
        if _SPONICHI_PROMOTION_RE.search(paragraph):
            removed["sponichi_betting_promotion"] += 1
        else:
            kept.append(paragraph)
    return kept


def _remove_standalone_urls(paragraphs: list[str], removed: Counter[str]) -> list[str]:
    kept: list[str] = []
    for paragraph in paragraphs:
        if _STANDALONE_URL_RE.fullmatch(paragraph):
            removed["standalone_url"] += 1
        else:
            kept.append(paragraph)
    return kept


def _strip_link_ctas(paragraphs: list[str], removed: Counter[str]) -> list[str]:
    kept: list[str] = []
    for paragraph in paragraphs:
        cleaned, count = _LINK_CTA_SENTENCE_RE.subn("", paragraph)
        cleaned = cleaned.strip()
        if count:
            removed["link_cta"] += count
        if cleaned:
            kept.append(cleaned)
    return kept


def _strip_sporting_life_inline_noise(paragraphs: list[str], removed: Counter[str]) -> list[str]:
    kept: list[str] = []
    for paragraph in paragraphs:
        cleaned = paragraph
        for name, pattern in _SPORTING_LIFE_INLINE_RULES:
            updated = pattern.sub("", cleaned).strip()
            if updated != cleaned:
                removed[name] += 1
                cleaned = updated
        if cleaned:
            kept.append(cleaned)
    return kept


def clean_international_article_body(node: Tag, *, source_site: SourceSite | str) -> ArticleContentCleanResult:
    removed: Counter[str] = Counter()
    source = _source_value(source_site)
    _remove_structured_noise(node, removed)
    _remove_source_structured_noise(node, source, removed)
    paragraphs = _paragraphs(node)
    paragraphs = _remove_standalone_urls(paragraphs, removed)
    paragraphs = _strip_link_ctas(paragraphs, removed)
    if source in {SourceSite.TDN, SourceSite.TDN_FRANCE}:
        paragraphs = _drop_leading(paragraphs, _TDN_LEADING_RULES, removed)
        paragraphs = _truncate_tail(paragraphs, _TDN_TAIL_RULES, removed)
    elif source == SourceSite.SPORTING_LIFE:
        paragraphs = _truncate_tail(paragraphs, _SPORTING_LIFE_TAIL_RULES, removed)
        paragraphs = _remove_betting_promotions(paragraphs, removed)
        paragraphs = _strip_sporting_life_inline_noise(paragraphs, removed)
    elif source == SourceSite.SPONICHI:
        paragraphs = _remove_sponichi_promotions(paragraphs, removed)

    text = normalize_whitespace("\n\n".join(paragraphs))
    return ArticleContentCleanResult(
        text=text,
        status="ok" if text else "empty_after_cleaning",
        removed_rules=dict(sorted(removed.items())),
    )
