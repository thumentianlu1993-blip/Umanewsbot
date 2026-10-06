from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
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

_HRN_STRUCTURED_NOISE_SELECTORS = (
    "[role='dialog']",
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
    blocks: tuple[dict[str, object], ...] = ()
    before_text: str = ""
    body_html_sha256: str = ""

    @property
    def removed_count(self) -> int:
        return sum(self.removed_rules.values())

    def metadata(self) -> dict[str, object]:
        return {
            "removed_count": self.removed_count,
            "removed_rules": dict(self.removed_rules),
            "trace_version": 1,
            "body_html_sha256": self.body_html_sha256,
            "before_text": self.before_text,
            "after_text": self.text,
            "blocks": [dict(block, reasons=list(block["reasons"])) for block in self.blocks],
        }


def _source_value(source_site: SourceSite | str) -> str:
    return source_site.value if isinstance(source_site, SourceSite) else str(source_site)


def _block(source: str, locator: str, original: str, *, context_sha: str, reason: str = "") -> dict[str, object]:
    identity = json.dumps([source, context_sha, locator, original], ensure_ascii=False, separators=(",", ":"))
    return {
        "block_id": "body-" + hashlib.sha256(identity.encode()).hexdigest()[:20],
        "locator": locator,
        "original_text": original,
        "text": "" if reason else original,
        "decision": "removed" if reason else "kept",
        "reasons": [reason] if reason else ["article_text"],
    }


class _CleaningAudit:
    def __init__(self, node: Tag, source: str):
        self.source = source
        self.before_text = extract_article_text(node)
        self.body_html_sha256 = hashlib.sha256(str(node).encode()).hexdigest()
        self.noise: list[dict[str, object]] = []
        # Capture paths before decompose changes sibling positions. Compare by
        # identity so identical sibling markup still has distinct paths.
        self.paths: dict[int, str] = {id(node): "container"}
        for parent in (node, *node.find_all(True)):
            children = [child for child in parent.children if isinstance(child, Tag)]
            for index, child in enumerate(children):
                self.paths[id(child)] = self.paths[id(parent)] + f"/{child.name}[{index}]"

    def remove(self, matches: list[Tag], reason: str) -> None:
        for match in matches:
            original = extract_article_text(match)
            self.noise.append(_block(self.source, self.paths[id(match)], original, context_sha=self.body_html_sha256, reason=reason))


def _remove_structured_noise(node: Tag, removed: Counter[str], audit: _CleaningAudit) -> None:
    for selector in _STRUCTURED_NOISE_SELECTORS:
        matches = list(node.select(selector))
        audit.remove(matches, "structured_noise")
        for match in matches:
            match.decompose()
        if matches:
            removed["structured_noise"] += len(matches)


def _remove_source_structured_noise(node: Tag, source: str, removed: Counter[str], audit: _CleaningAudit) -> None:
    selectors = _HRN_STRUCTURED_NOISE_SELECTORS if source == SourceSite.HORSE_RACING_NATION else (
        _SPONICHI_STRUCTURED_NOISE_SELECTORS if source == SourceSite.SPONICHI else ()
    )
    reason = "hrn_structured_noise" if source == SourceSite.HORSE_RACING_NATION else "sponichi_structured_noise"
    for selector in selectors:
        matches = list(node.select(selector))
        audit.remove(matches, reason)
        for match in matches:
            match.decompose()
        if matches:
            removed[reason] += len(matches)


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


def _apply_local_rule(blocks: list[dict[str, object]], cleaner, removed: Counter[str]) -> None:
    # Existing local rules accept one paragraph and retain their original
    # counters/text behavior. Tracking travels with the occurrence, not text
    # matching, so duplicate paragraphs cannot steal each other's decisions.
    for block in blocks:
        if not block["text"]:
            continue
        before = Counter(removed)
        result = cleaner([block["text"]], removed)
        block["text"] = result[0] if result else ""
        reasons = sorted(name for name in removed if removed[name] > before[name])
        if reasons:
            block["reasons"] = [r for r in block["reasons"] if r != "article_text"] + reasons
            block["decision"] = "modified" if block["text"] else "removed"


def _apply_edge_rule(blocks: list[dict[str, object]], rules, removed: Counter[str], *, leading: bool) -> None:
    active = [block for block in blocks if block["text"]]
    texts = [block["text"] for block in active]
    result = _drop_leading(texts, rules, removed) if leading else _truncate_tail(texts, rules, removed)
    dropped = active[:len(active) - len(result)] if leading else active[len(result):]
    tail_reason = next((name for name, pattern in rules if dropped and pattern.search(dropped[0]["text"])), "")
    for block in dropped:
        reason = next(name for name, pattern in rules if pattern.search(block["text"])) if leading else tail_reason
        block["text"] = ""
        block["decision"] = "removed"
        block["reasons"] = [r for r in block["reasons"] if r != "article_text"] + [reason]


def clean_international_article_body(node: Tag, *, source_site: SourceSite | str) -> ArticleContentCleanResult:
    removed: Counter[str] = Counter()
    source = _source_value(source_site)
    audit = _CleaningAudit(node, source)
    _remove_structured_noise(node, removed, audit)
    _remove_source_structured_noise(node, source, removed, audit)
    blocks = [_block(source, f"paragraph[{index}]", paragraph, context_sha=audit.body_html_sha256) for index, paragraph in enumerate(_paragraphs(node))]
    _apply_local_rule(blocks, _remove_standalone_urls, removed)
    _apply_local_rule(blocks, _strip_link_ctas, removed)
    if source in {SourceSite.TDN, SourceSite.TDN_FRANCE}:
        _apply_edge_rule(blocks, _TDN_LEADING_RULES, removed, leading=True)
        _apply_edge_rule(blocks, _TDN_TAIL_RULES, removed, leading=False)
    elif source == SourceSite.SPORTING_LIFE:
        _apply_edge_rule(blocks, _SPORTING_LIFE_TAIL_RULES, removed, leading=False)
        _apply_local_rule(blocks, _remove_betting_promotions, removed)
        _apply_local_rule(blocks, _strip_sporting_life_inline_noise, removed)
    elif source == SourceSite.SPONICHI:
        _apply_local_rule(blocks, _remove_sponichi_promotions, removed)

    for block in blocks:
        block["text"] = normalize_whitespace(block["text"])
    text = normalize_whitespace("\n\n".join(block["text"] for block in blocks if block["text"]))
    return ArticleContentCleanResult(
        text=text,
        status="ok" if text else "empty_after_cleaning",
        removed_rules=dict(sorted(removed.items())),
        blocks=tuple(audit.noise + blocks),
        before_text=audit.before_text,
        body_html_sha256=audit.body_html_sha256,
    )
