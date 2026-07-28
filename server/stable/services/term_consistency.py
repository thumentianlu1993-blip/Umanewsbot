"""
Multilingual term consistency service for racing news.

Provides occurrence-level term resolution, canonical consistency gates for
new articles, and CAS-based historical repair for published articles.

See docs/changes/unify-public-racing-terms/ for full spec and design.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    NewsArticle,
    RaceEventRunner,
    SourceLanguage,
    TermAlias,
    TermConsistencyManifest,
    TermConsistencyManifestStatus,
    TermEntry,
    TermMappingEvidence,
    TermType,
    WorkflowStatus,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESOLVER_VERSION = "1.0.0"

# Public Chinese fields that should use canonical term display names.
CANONICAL_FIELDS = frozenset({
    "title_zh",
    "summary_zh",
    "body_zh",
    "push_summary_zh",
    "tags_json",
})

# Source-language fields that must never be modified.
CONSERVED_FIELDS = frozenset({
    "body_ja_raw",
    "body_ja_normalized",
    "title_ja",
    "public_slug",
    "published_at",
    "workflow_status",
})

# Rewrite-specific fields also gated by consistency checks.
REWRITE_CANONICAL_FIELDS = frozenset({
    "rewrite_title_zh",
    "rewrite_summary_zh",
    "rewrite_body_zh",
})

# Known common English words that should not be replaced as horse names
# without strong racing-runner evidence.
_COMMON_ENGLISH_TERMS: set[str] = {
    # From validation.py ENGLISH_COMMON_WORD_TERM_SEEDS
    "ace", "agenda", "brilliant", "class", "classic", "contact", "excellent",
    "fantastic", "fast track", "good job", "hopeful", "incredible", "live",
    "number", "reputation", "something", "soon", "step forward", "threat",
    "title", "tuesday", "versatile", "were", "wonderful",
    # Additional common racing-adjacent words
    "amazing", "better", "bold", "brave", "clear", "close", "common",
    "cool", "dear", "deep", "fair", "fast", "fine", "firm", "first",
    "free", "full", "glad", "gold", "good", "grand", "great", "happy",
    "hard", "heavy", "high", "hot", "just", "keen", "last", "late",
    "light", "like", "lucky", "mere", "more", "much", "near", "neat",
    "next", "nice", "noble", "open", "past", "perfect", "pure", "quick",
    "rare", "real", "rich", "right", "ripe", "rose", "royal", "safe",
    "same", "sane", "saved", "sharp", "short", "sick", "slim", "slow",
    "small", "smart", "smooth", "soft", "solid", "some", "soon", "sore",
    "sound", "sour", "star", "steady", "still", "strong", "sure", "sweet",
    "swift", "tall", "tame", "that", "thin", "this", "tight", "tough",
    "true", "trust", "vast", "very", "warm", "weak", "well", "wide",
    "wild", "wise", "young",
}

# Race name markers (from validation.py).
_RACE_NAME_MARKERS = {
    "classic", "cup", "derby", "futurity", "guineas", "handicap",
    "invitational", "oaks", "prix", "stakes",
}

# Field order for conserve validation
_SOURCE_FIELDS = frozenset({
    "body_ja_raw", "body_ja_normalized", "title_ja",
    "public_slug", "published_at", "workflow_status",
})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Occurrence:
    """A single occurrence of a term-alias surface in text."""
    surface: str
    start: int
    end: int
    term_id: int | None = None
    alias_id: int | None = None
    target_zh: str = ""
    source_language: str = ""
    status: str = "uncertain"  # confirmed | uncertain | conflict
    evidence: list[dict] = field(default_factory=list)
    resolver_version: str = RESOLVER_VERSION
    entity_evidence: list[str] = field(default_factory=list)


@dataclass
class OccurrenceResult:
    """Result of resolving term occurrences in text."""
    occurrences: list[Occurrence] = field(default_factory=list)
    suggested_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    """Result of applying the consistency gate to an article."""
    issues: list[dict] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)
    suggested_tags: list[str] = field(default_factory=list)
    passed: bool = True
    blockers: list[dict] = field(default_factory=list)


@dataclass
class DryRunManifest:
    """Manifest for a dry-run consistency repair."""
    run_id: str
    manifest_sha256: str
    diffs: list[dict]
    term_snapshot_sha256: str
    settings_sha256: str
    resolver_version: str = RESOLVER_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommitResult:
    """Result of committing a dry-run manifest."""
    success: bool
    applied_articles: int
    total_fields: int
    skipped_articles: int
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Alias index (module-level cache)
# ---------------------------------------------------------------------------

_SETTINGS_SHA_CACHE: str = ""


def _settings_sha256() -> str:
    """Compute a SHA256 of relevant settings (no caching — detects overrides)."""
    payload = {
        "TERM_CONSISTENCY_ENABLED": getattr(settings, "TERM_CONSISTENCY_ENABLED", False),
        "TERM_CONSISTENCY_ENFORCE": getattr(settings, "TERM_CONSISTENCY_ENFORCE", False),
        "AUTO_REWRITE_ENABLED": getattr(settings, "AUTO_REWRITE_ENABLED", False),
        "AUTO_PUBLISH_CONTENT_SOURCE": getattr(settings, "AUTO_PUBLISH_CONTENT_SOURCE", "base_translation"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def _build_surface_index() -> dict[str, list[dict]]:
    """Build a fresh in-memory surface -> [entry, ...] index.

    Uses values() for performance with large alias counts.
    Each entry has:
      term_id, alias_id, source_language, target_zh, term_type,
      racing_region, is_active
    """
    # Fetch alias and entry data as dicts (avoids ORM object overhead)
    alias_data = list(
        TermAlias.objects.filter(is_active=True).values(
            "id", "term_id", "source_language", "text", "alias_type", "is_active"
        )
    )
    entry_data = list(
        TermEntry.objects.filter(is_active=True).values(
            "id", "source_ja", "target_zh", "source_language",
            "term_type", "racing_region", "is_active"
        )
    )

    # Build entry lookup
    entries_by_id: dict[int, dict] = {e["id"]: e for e in entry_data}

    index: dict[str, list[dict]] = {}

    def _add(surface: str, entry: dict) -> None:
        key = _nfkc(surface).casefold()
        if not key:
            return
        if key not in index:
            index[key] = []
        for existing in index[key]:
            if existing["term_id"] == entry["term_id"] and existing.get("alias_id") == entry.get("alias_id"):
                return
        index[key].append(entry)

    for alias in alias_data:
        term = entries_by_id.get(alias["term_id"])
        if not term or not term.get("is_active"):
            continue
        if alias["source_language"] in {SourceLanguage.CHINESE, SourceLanguage.CHINESE_TRADITIONAL}:
            continue
        _add(alias["text"], {
            "term_id": term["id"],
            "alias_id": alias["id"],
            "source_language": alias["source_language"],
            "target_zh": term["target_zh"],
            "term_type": term["term_type"],
            "racing_region": term.get("racing_region") or "",
            "is_active": term.get("is_active", True) and alias.get("is_active", True),
        })

    for eid, term in entries_by_id.items():
        surface = _nfkc(term.get("source_ja", ""))
        if surface:
            key = surface.casefold()
            if key not in index or not any(
                item["term_id"] == term["id"] and item.get("alias_id") is None
                for item in index[key]
            ):
                _add(surface, {
                    "term_id": term["id"],
                    "alias_id": None,
                    "source_language": term["source_language"],
                    "target_zh": term["target_zh"],
                    "term_type": term["term_type"],
                    "racing_region": term.get("racing_region") or "",
                    "is_active": term.get("is_active", True),
                })

    return index


def _entries_for_surface(surface: str, source_language: str) -> list[dict]:
    """Get all active term entries for a given surface and language."""
    index = _build_surface_index()
    key = _nfkc(surface).casefold()
    entries = index.get(key, [])
    return [
        e for e in entries
        if e.get("is_active") and e["source_language"] == source_language
    ]


def _build_evidence_cache() -> set[tuple[int, int | None]]:
    """Preload all approved evidence pairs into a set for O(1) lookup.

    Returns a set of (term_id, alias_id_or_None) tuples for approved evidence.
    """
    rows = TermMappingEvidence.objects.filter(
        review_status="approved"
    ).values_list("term_id", "alias_id")
    return {(tid, aid) for tid, aid in rows}


def _has_approved_evidence(
    term_id: int,
    alias_id: int | None,
    evidence_cache: set[tuple[int, int | None]] | None = None,
) -> bool:
    """Check if approved evidence exists for a term/alias pair.

    When evidence_cache is provided (preferred for batch operations), uses
    O(1) set lookup instead of a per-occurrence DB query.
    """
    key = (term_id, alias_id) if alias_id is not None else (term_id, None)
    if evidence_cache is not None:
        return key in evidence_cache
    query = Q(term_id=term_id, review_status="approved")
    if alias_id is not None:
        query = query & Q(alias_id=alias_id)
    else:
        query = query & Q(alias_id__isnull=True)
    return TermMappingEvidence.objects.filter(query).exists()


def _article_runner_names(article: NewsArticle) -> set[str]:
    """Get set of normalized runner horse names from confirmed article race links."""
    names: set[str] = set()
    links = ArticleRaceLink.objects.filter(
        article=article,
        status__in=[ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL],
    ).select_related("event")
    for link in links:
        runners = RaceEventRunner.objects.filter(event=link.event)
        for r in runners:
            n = _nfkc(r.horse_name).casefold()
            if n:
                names.add(n)
    return names


def _looks_like_race_name(text: str) -> bool:
    normalized = (text or "").strip().casefold()
    if not normalized:
        return False
    tokens = re.findall(r"[a-z0-9']+", normalized)
    return any(t in _RACE_NAME_MARKERS for t in tokens)


def _is_common_english_word(surface: str) -> bool:
    """Check if a surface is a known common English word."""
    cleaned = re.sub(r"[^a-z]", "", surface.casefold())
    return cleaned in _COMMON_ENGLISH_TERMS


def _content_source() -> str:
    if not getattr(settings, "AUTO_REWRITE_ENABLED", False):
        return "base_translation"
    source = getattr(settings, "AUTO_PUBLISH_CONTENT_SOURCE", "base_translation") or "base_translation"
    return source if source in {"base_translation", "rewrite"} else "base_translation"


def _is_manually_edited(article: NewsArticle, field: str) -> bool:
    edited = article.manually_edited_fields or []
    return field in edited


# ---------------------------------------------------------------------------
# Occurrence Resolver
# ---------------------------------------------------------------------------

def resolve_term_occurrences(
    text: str,
    source_language: str,
    article: NewsArticle | None = None,
    surface_index: dict[str, list[dict]] | None = None,
    runner_names: set[str] | None = None,
    evidence_cache: set[tuple[int, int | None]] | None = None,
) -> OccurrenceResult:
    """Resolve term alias occurrences in the given text.

    Args:
        text: The text to scan for occurrences.
        source_language: Source language code.
        article: Optional article for structured entity evidence.
        surface_index: Optional pre-built alias index (for batch operations).
        runner_names: Optional pre-fetched runner names set.
        evidence_cache: Optional pre-built approved evidence cache.

    Returns an OccurrenceResult with classified Occurrences.
    """
    result = OccurrenceResult()
    if not text:
        return result

    # Build alias index if not provided
    if surface_index is None:
        surface_index = _build_surface_index()
    if not surface_index:
        return result

    # Build approved evidence cache once (avoids per-occurrence DB queries)
    if evidence_cache is None:
        evidence_cache = _build_evidence_cache()

    # Get structured entity evidence if article provided
    if runner_names is None:
        runner_names = _article_runner_names(article) if article else set()

    normalized_text = _nfkc(text)
    # Collect all aliases for the given source language, sorted by length desc
    lang_entries: dict[str, list[dict]] = {}
    for key, entries in surface_index.items():
        matching = [e for e in entries if e["source_language"] == source_language and e.get("is_active")]
        if matching:
            lang_entries[key] = matching

    seen_spans: set[tuple[int, int]] = set()
    suggested_tags: set[str] = set()

    # Pre-compute text for fast substring check (avoids regex when surface not present)
    normalized_lower = normalized_text.casefold()

    # Sort by length desc so longer matches take priority
    for surface_cf, entries in sorted(lang_entries.items(), key=lambda x: -len(x[0])):
        # Fast path: skip surfaces not present in text
        if surface_cf not in normalized_lower:
            continue
        # Find all occurrences in text
        for match in re.finditer(re.escape(surface_cf), normalized_text, re.IGNORECASE):
            start, end = match.start(), match.end()
            # Skip if overlapping with already-processed span
            if any(s <= start < e or s < end <= e for s, e in seen_spans):
                continue
            seen_spans.add((start, end))

            surface_found = normalized_text[start:end]

            # -- Conflict detection: only if multiple distinct term_ids --
            distinct_term_ids = {e["term_id"] for e in entries}
            if len(distinct_term_ids) > 1:
                # Multiple active terms share this surface -> conflict
                result.occurrences.append(Occurrence(
                    surface=surface_found,
                    start=start,
                    end=end,
                    term_id=None,
                    source_language=source_language,
                    status="conflict",
                    target_zh=None,
                    evidence=[{
                        "reason": "multiple_active_terms",
                        "term_ids": sorted(distinct_term_ids),
                    }],
                ))
                continue

            entry = entries[0]
            # Prefer the term's own registry (source_ja) entry when the same
            # surface is registered both as an alias and as the term's
            # source_ja: the registry entry is the trusted mapping, so the
            # occurrence resolves through it rather than through an
            # unreviewed alias that merely duplicates the source surface.
            for candidate in entries:
                if candidate.get("alias_id") is None:
                    entry = candidate
                    break
            term_id = entry["term_id"]
            alias_id = entry.get("alias_id")
            target_zh = entry.get("target_zh", "") or ""
            term_type = entry.get("term_type", "")
            surface_lower = surface_found.casefold()

            # Check approved evidence (uses pre-built cache for batch operations)
            has_evidence = _has_approved_evidence(term_id, alias_id, evidence_cache=evidence_cache)

            # English common word gating
            is_common_word = (
                source_language == SourceLanguage.ENGLISH
                and _is_common_english_word(surface_found)
            )

            # Runner evidence
            in_runner_names = surface_lower in runner_names

            # Race name context
            is_race_context = (
                term_type == TermType.RACE
                and _looks_like_race_name(surface_found)
            ) if source_language == SourceLanguage.ENGLISH else True

            # Determine status
            if is_common_word and not in_runner_names and not has_evidence:
                # Common English word without strong evidence -> uncertain
                status = "uncertain"
            elif has_evidence or in_runner_names:
                status = "confirmed"
            elif alias_id is not None:
                # Unreviewed alias — of ANY term type and ANY source
                # language — without approved evidence (or runner evidence)
                # cannot be trusted for automatic replacement.  Japanese
                # aliases must not bypass the gate via the race-context
                # rule, and non-HORSE (e.g. RACE) aliases are held to the
                # same standard.  Surfaces matching the term's own
                # source_ja resolve through the registry entry above
                # (alias_id is None), not through the alias.
                status = "uncertain"
            elif is_race_context:
                status = "confirmed"
            elif term_type == TermType.HORSE and source_language == SourceLanguage.ENGLISH and is_common_word:
                status = "uncertain"
            else:
                # Registry (source_ja) entry for an active term — trust the
                # curated termbase.
                status = "confirmed"

            # Build evidence
            evidence_list: list[dict] = []
            if has_evidence:
                evidence_list.append({"kind": "approved_evidence", "term_id": term_id})
            if in_runner_names:
                evidence_list.append({"kind": "race_runner"})

            result.occurrences.append(Occurrence(
                surface=surface_found,
                start=start,
                end=end,
                term_id=term_id if status != "conflict" else None,
                alias_id=alias_id,
                target_zh=target_zh if status == "confirmed" else "",
                source_language=source_language,
                status=status,
                evidence=evidence_list,
                entity_evidence=list(runner_names) if in_runner_names else [],
            ))

            if status == "confirmed" and target_zh:
                suggested_tags.add(target_zh)

    result.suggested_tags = sorted(suggested_tags)
    result.metadata = {"resolver_version": RESOLVER_VERSION, "surface_count": len(lang_entries)}
    return result


def resolve_occurrences(
    text: str,
    source_language: str,
    article: NewsArticle | None = None,
) -> OccurrenceResult:
    """Public API: resolve term alias occurrences."""
    return resolve_term_occurrences(text, source_language, article=article)


# ---------------------------------------------------------------------------
# Mapping Evidence Management
# ---------------------------------------------------------------------------

def create_mapping_evidence(
    term: TermEntry,
    alias: TermAlias | None = None,
    evidence_kind: str = "manual_review",
    source_url: str = "",
    source_digest: str = "",
    identity_payload: dict | None = None,
) -> TermMappingEvidence:
    identity_payload = identity_payload or {}
    return TermMappingEvidence.objects.create(
        term=term,
        alias=alias,
        evidence_kind=evidence_kind,
        source_url=source_url,
        source_digest=source_digest,
        review_status="pending",
        identity_payload=identity_payload,
        identity_sha256=hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True).encode("utf-8")
        ).hexdigest() if identity_payload else "",
    )


def approve_evidence(evidence_id: int, reviewed_by: str) -> TermMappingEvidence:
    evidence = TermMappingEvidence.objects.get(id=evidence_id)
    evidence.review_status = "approved"
    evidence.reviewed_by = reviewed_by
    evidence.reviewed_at = timezone.now()
    evidence.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "updated_at"])
    return evidence


def get_approved_evidence_for_term(term_id: int) -> list[TermMappingEvidence]:
    return list(
        TermMappingEvidence.objects.filter(term_id=term_id, review_status="approved")
        .select_related("alias")
    )


# ---------------------------------------------------------------------------
# New Article Consistency Gate
# ---------------------------------------------------------------------------

def _fields_to_validate(article: NewsArticle, content_source: str) -> list[tuple[str, Any]]:
    fields: list[tuple[str, Any]] = []
    for f in CANONICAL_FIELDS:
        val = getattr(article, f, None)
        if val is not None:
            fields.append((f, val))
    # Always check rewrite fields if they have values, regardless of content source
    for f in REWRITE_CANONICAL_FIELDS:
        val = getattr(article, f, None)
        if val is not None:
            fields.append((f, val))
    return fields


def validate_canonical_consistency(
    article: NewsArticle,
    surface_index: dict[str, list[dict]] | None = None,
    evidence_cache: set[tuple[int, int | None]] | None = None,
) -> list[dict]:
    """Check all public Chinese fields for canonical term consistency.

    Args:
        article: The article to validate.
        surface_index: Optional pre-built surface index for batch efficiency.
        evidence_cache: Optional pre-built approved evidence cache.

    Returns a list of issue dicts with {field, term_id, expected_zh,
    actual_text, occurrence_status, evidence}.
    """
    issues: list[dict] = []
    content_source = _content_source()
    fields_to_check = _fields_to_validate(article, content_source)
    article_lang = article.source_language or SourceLanguage.ENGLISH

    # Preload runner names once for this article
    article_runner_names = _article_runner_names(article)

    for field_name, field_value in fields_to_check:
        if not field_value:
            continue
        if _is_manually_edited(article, field_name):
            continue

        if field_name == "tags_json":
            # Tags are a JSON list — check each tag text
            if isinstance(field_value, list):
                tag_text = " ".join(str(t) for t in field_value if t)
                resolved = resolve_term_occurrences(
                    tag_text, article_lang, article=article,
                    surface_index=surface_index,
                    runner_names=article_runner_names,
                    evidence_cache=evidence_cache,
                )
                for occ in resolved.occurrences:
                    if occ.status == "confirmed" and occ.target_zh:
                        # Check if any tag matches this surface
                        for tag in field_value:
                            tag_str = str(tag) if not isinstance(tag, str) else tag
                            if _nfkc(tag_str).casefold() == occ.surface.casefold():
                                issues.append({
                                    "field": field_name,
                                    "severity": "warning",
                                    "message": f"Tag '{tag_str}' should be '{occ.target_zh}'",
                                    "term_id": occ.term_id,
                                    "expected_zh": occ.target_zh,
                                    "actual_text": tag_str,
                                    "occurrence_status": occ.status,
                                    "evidence": occ.evidence,
                                })
        else:
            resolved = resolve_term_occurrences(
                str(field_value), article_lang, article=article,
                surface_index=surface_index,
                runner_names=article_runner_names,
                evidence_cache=evidence_cache,
            )
            for occ in resolved.occurrences:
                if occ.status == "conflict":
                    issues.append({
                        "field": field_name,
                        "severity": "blocker",
                        "message": f"Conflict for '{occ.surface}': multiple active terms",
                        "term_id": None,
                        "expected_zh": "",
                        "actual_text": occ.surface,
                        "occurrence_status": "conflict",
                        "evidence": occ.evidence,
                    })
                elif occ.target_zh and occ.surface.casefold() != occ.target_zh.casefold():
                    _enforce = getattr(settings, "TERM_CONSISTENCY_ENFORCE", False)
                    if occ.status == "conflict" or (_enforce and occ.status == "confirmed"):
                        severity = "blocker"
                    elif occ.status == "confirmed":
                        severity = "warning"
                    else:
                        severity = "info"
                    issues.append({
                        "field": field_name,
                        "severity": severity,
                        "message": f"'{occ.surface}' should be '{occ.target_zh}' (status={occ.status})",
                        "term_id": occ.term_id,
                        "expected_zh": occ.target_zh,
                        "actual_text": occ.surface,
                        "occurrence_status": occ.status,
                        "evidence": occ.evidence,
                    })

    return issues


def apply_consistency_gate(article: NewsArticle) -> GateResult:
    """Apply canonical consistency gate to an article.

    Returns a GateResult with issues, occurrences, and a pass/block decision.
    """
    article_lang = article.source_language or SourceLanguage.ENGLISH
    surface_index = _build_surface_index()

    # Resolve occurrences in source text
    source_text = (
        (article.title_ja or "") + " "
        + (article.body_ja_normalized or article.body_ja_raw or "")
    ).strip()
    article_runner_names: set[str] = _article_runner_names(article) if article and not hasattr(article, 'runner_cache') else (article.runner_cache if article and hasattr(article, 'runner_cache') else set())
    resolved = resolve_term_occurrences(
        source_text, article_lang, article=article, surface_index=surface_index,
        runner_names=article_runner_names,
    )

    # Also resolve occurrences in Chinese public fields
    all_public_text_parts: list[str] = []
    for f in CANONICAL_FIELDS:
        val = getattr(article, f, None)
        if val:
            all_public_text_parts.append(str(val))
    public_text = " ".join(all_public_text_parts)
    if public_text.strip():
        public_resolved = resolve_term_occurrences(
            public_text, article_lang, article=article, surface_index=surface_index,
            runner_names=article_runner_names,
        )
        # Track (surface, start, end) triples already found in source to avoid duplicates
        source_spans = {(o.surface.casefold(), o.start, o.end) for o in resolved.occurrences}
        for o in public_resolved.occurrences:
            key = (o.surface.casefold(), o.start, o.end)
            if key not in source_spans:
                resolved.occurrences.append(o)

    # Build shared caches once — validate_canonical_consistency reuses them
    # across all fields, avoiding per-field index rebuild and per-occurrence
    # evidence queries.
    evidence_cache = _build_evidence_cache()

    # Check canonical consistency on publish fields (reuses surface_index + evidence_cache)
    issue_dicts = validate_canonical_consistency(
        article, surface_index=surface_index, evidence_cache=evidence_cache,
    )

    gate_issues: list[dict] = []
    blockers: list[dict] = []
    for issue in issue_dicts:
        gate_issues.append(issue)
        if issue.get("severity") == "blocker":
            blockers.append(issue)

    passed = len(blockers) == 0

    return GateResult(
        issues=gate_issues,
        occurrences=resolved.occurrences,
        suggested_tags=resolved.suggested_tags,
        passed=passed,
        blockers=blockers,
    )


def apply_canonical_consistency(
    article: NewsArticle,
    dry_run: bool = False,
    surface_index: dict[str, list[dict]] | None = None,
    evidence_cache: set[tuple[int, int | None]] | None = None,
) -> list[dict]:
    """Apply canonical consistency fixes to an article.

    When dry_run=True, returns diffs without modifying anything.
    When dry_run=False, applies fixes for confirmed occurrences.

    Args:
        article: Article to check.
        dry_run: If True, only generate diffs without modifying.
        surface_index: Optional pre-built alias index for batch efficiency.
        evidence_cache: Optional pre-built approved evidence cache.
    """
    diffs: list[dict] = []
    content_source = _content_source()
    fields_to_check = _fields_to_validate(article, content_source)
    article_lang = article.source_language or SourceLanguage.ENGLISH

    # Preload runner names once per article to avoid per-field DB queries
    article_runner_names: set[str] = _article_runner_names(article) if not hasattr(article, 'runner_cache') else article.runner_cache

    for field_name, field_value in fields_to_check:
        if not field_value:
            continue
        if _is_manually_edited(article, field_name):
            continue

        if field_name == "tags_json":
            new_tags = _normalize_tags(field_value, article, surface_index=surface_index, evidence_cache=evidence_cache)
            if new_tags != field_value:
                before_sha = hashlib.sha256(
                    json.dumps(field_value, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if not dry_run:
                    setattr(article, field_name, new_tags)
                diffs.append({
                    "article_id": article.id,
                    "field": field_name,
                    "before_sha256": before_sha,
                    "before_value": field_value,
                    "after_value": new_tags,
                    "applied": not dry_run,
                    "occurrences": [],
                    "target_zh": "",
                })
        else:
            text_val = str(field_value)
            resolved = resolve_term_occurrences(text_val, article_lang, article=article, surface_index=surface_index, runner_names=article_runner_names, evidence_cache=evidence_cache)
            new_value = _apply_occurrence_replacements(text_val, resolved)
            if new_value != text_val:
                before_sha = hashlib.sha256(text_val.encode("utf-8")).hexdigest()
                occ_details = [
                    {"surface": o.surface, "start": o.start, "end": o.end, "status": o.status}
                    for o in resolved.occurrences if o.status == "confirmed" and o.target_zh
                ]
                target_zh = next(
                    (o.target_zh for o in resolved.occurrences if o.target_zh), ""
                )
                if not dry_run:
                    setattr(article, field_name, new_value)
                diffs.append({
                    "article_id": article.id,
                    "field": field_name,
                    "before_sha256": before_sha,
                    "before_value": text_val,
                    "after_value": new_value,
                    "applied": not dry_run,
                    "occurrences": occ_details,
                    "target_zh": target_zh,
                })

    if not dry_run and diffs:
        update_fields = ["updated_at"]
        for d in diffs:
            if d.get("applied") and d.get("field"):
                update_fields.append(d["field"])
        article.save(update_fields=update_fields)

    return diffs


def _nfkc_offset_map(text: str) -> tuple[str | None, list[tuple[int, int]] | None]:
    """Map offsets in ``_nfkc(text)`` space back to original text offsets.

    Returns ``(normalized, char_map)`` where ``normalized == _nfkc(text)``
    and ``char_map[i] = (orig_start, orig_end)`` gives the original span of
    the i-th normalized character.  Returns ``(None, None)`` when per-char
    normalization cannot reproduce whole-string NFKC (e.g. cross-character
    composition), in which case offsets cannot be mapped safely.
    """
    if not text:
        return "", []
    normalized_chars: list[tuple[str, int, int]] = []
    for i, ch in enumerate(text):
        for nc in unicodedata.normalize("NFKC", ch):
            normalized_chars.append((nc, i, i + 1))
    normalized_full = "".join(c for c, _, _ in normalized_chars)
    if normalized_full != unicodedata.normalize("NFKC", text):
        return None, None
    # Replicate the strip() applied by _nfkc so offsets line up with the
    # resolver's coordinate space.
    stripped = normalized_full.strip()
    lead = len(normalized_full) - len(normalized_full.lstrip())
    char_map = [(s, e) for _, s, e in normalized_chars[lead:lead + len(stripped)]]
    return stripped, char_map


def _apply_occurrence_replacements(text: str, resolved: OccurrenceResult) -> str:
    """Replace confirmed occurrences in text with their target_zh values.

    Occurrence offsets are computed against the NFKC-normalized (and
    stripped) text.  When normalization changed the text (e.g. full-width
    forms) or leading whitespace was stripped, absolute offsets no longer
    line up with the original string; the NFKC offset map is then used to
    translate each occurrence back to its original span, so replacements
    still land instead of being silently skipped.  A case-insensitive
    surface search remains as a last-resort fallback.
    """
    if not text or not resolved.occurrences:
        return text
    confirmed = [
        o for o in resolved.occurrences
        if o.status == "confirmed" and o.target_zh
        and o.surface.casefold() != o.target_zh.casefold()
    ]
    if not confirmed:
        return text

    # Sort descending by start position.  Processing right-to-left keeps
    # the original coordinates of all not-yet-processed spans valid.
    confirmed.sort(key=lambda o: -o.start)
    result = text
    # Lazily computed NFKC -> original offset map (None when unmappable).
    offset_map: list[tuple[int, int]] | None | bool = False
    # Spans (in current `result` coordinates) already replaced via the
    # search fallback; later fallback matches must not overlap them.
    fallback_spans: list[tuple[int, int]] = []
    for occ in confirmed:
        if occ.start < occ.end <= len(result) and result[occ.start:occ.end].casefold() == occ.surface.casefold():
            result = result[:occ.start] + occ.target_zh + result[occ.end:]
            continue
        # Offsets are in NFKC space: translate back to original coordinates.
        if offset_map is False:
            _norm, offset_map = _nfkc_offset_map(text)
        if offset_map and occ.end <= len(offset_map):
            orig_start = offset_map[occ.start][0]
            orig_end = offset_map[occ.end - 1][1]
            segment = result[orig_start:orig_end]
            if _nfkc(segment).casefold() == occ.surface.casefold():
                result = result[:orig_start] + occ.target_zh + result[orig_end:]
                continue
        # Last resort: case-insensitive surface search, rightmost first,
        # skipping spans already replaced by an earlier fallback.
        pattern = re.compile(re.escape(occ.surface), re.IGNORECASE)
        for match in sorted(pattern.finditer(result), key=lambda m: -m.start()):
            span = match.span()
            if any(s <= span[0] < e or s < span[1] <= e for s, e in fallback_spans):
                continue
            result = result[:span[0]] + occ.target_zh + result[span[1]:]
            # Record the span of the *replacement* text (lengths differ) so
            # later fallback matches do not overlap what we just wrote.
            fallback_spans.append((span[0], span[0] + len(occ.target_zh)))
            break

    return result


def _normalize_tags(tags: Any, article: NewsArticle, surface_index: dict[str, list[dict]] | None = None, evidence_cache: set[tuple[int, int | None]] | None = None) -> Any:
    """Normalize tags to use canonical Chinese names."""
    if not tags or not isinstance(tags, list):
        return tags

    resolved = resolve_term_occurrences(
        " ".join(str(t) for t in tags),
        article.source_language or SourceLanguage.ENGLISH,
        article=article,
        surface_index=surface_index,
        evidence_cache=evidence_cache,
    )
    replacement_map: dict[str, str] = {}
    for occ in resolved.occurrences:
        if occ.status == "confirmed" and occ.target_zh:
            replacement_map[occ.surface.casefold()] = occ.target_zh

    new_tags = list(tags)
    for i, tag in enumerate(new_tags):
        tag_str = str(tag) if not isinstance(tag, str) else tag
        if tag_str.casefold() in replacement_map:
            new_tags[i] = replacement_map[tag_str.casefold()]
    return new_tags


# ---------------------------------------------------------------------------
# Historical Repair — Dry-run / Manifest
# ---------------------------------------------------------------------------

def _term_snapshot_sha256(version: str | None = None) -> str:
    """Compute a SHA256 of the term registry for drift detection.

    Covers not only term entries but also alias surfaces and mapping-evidence
    content AND review states, so that re-activating an alias, editing
    evidence, or approving evidence between dry-run and commit invalidates
    the manifest.  Datetime fields are excluded (not JSON-stable); every
    text content field is included.
    """
    terms = list(
        TermEntry.objects.filter(is_active=True)
        .values("id", "target_zh", "source_ja", "is_active", "term_type", "racing_region")
        .order_by("id")
    )
    aliases = list(
        TermAlias.objects.filter(is_active=True)
        .values("id", "term_id", "text", "source_language", "alias_type", "is_active")
        .order_by("id")
    )
    evidence = list(
        TermMappingEvidence.objects.all()
        .values(
            "id", "term_id", "alias_id", "evidence_kind",
            "source_url", "source_digest", "identity_payload", "identity_sha256",
            "review_status", "reviewed_by",
        )
        .order_by("id")
    )
    snapshot = {
        "terms": terms,
        "aliases": aliases,
        "evidence": evidence,
        "version": version or "1.0",
    }
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()


def _build_manifest_from_articles(
    articles: list[NewsArticle],
    term_version: str | None = None,
    run_id_suffix: str = "",
) -> DryRunManifest:
    """Shared helper: build a dry-run manifest from a list of articles.

    Both ``build_dry_run_manifest`` and ``generate_canonical_consistency_dry_run``
    delegate to this function to avoid duplicated logic.
    """
    run_id = hashlib.sha256(
        (str(timezone.now().timestamp()) + run_id_suffix).encode("utf-8")
    ).hexdigest()[:16]

    term_snapshot_sha = _term_snapshot_sha256(term_version)
    settings_hash = _settings_sha256()

    # Build alias index once for all articles in the batch
    surface_index = _build_surface_index()
    evidence_cache = _build_evidence_cache()

    # Preload runner names for all articles in batch
    runner_names_by_article: dict[int, set[str]] = {}
    if articles:
        runner_names_by_article = preload_runner_names(articles)

    diffs: list[dict] = []
    for article in articles:
        article.runner_cache = runner_names_by_article.get(article.id, set())
        article_diffs = apply_canonical_consistency(article, dry_run=True, surface_index=surface_index, evidence_cache=evidence_cache)
        diffs.extend(article_diffs)

    manifest_content = {
        "run_id": run_id,
        "term_snapshot_sha256": term_snapshot_sha,
        "settings_sha256": settings_hash,
        "resolver_version": RESOLVER_VERSION,
        "diffs": diffs,
    }
    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest_content, sort_keys=True).encode("utf-8")
    ).hexdigest()

    # Persist the manifest so a dry-run produced by one worker can be
    # committed (or rolled back) by another — process restarts must not
    # lose it.
    TermConsistencyManifest.objects.update_or_create(
        run_id=run_id,
        defaults={
            "manifest_sha256": manifest_sha256,
            "term_snapshot_sha256": term_snapshot_sha,
            "settings_sha256": settings_hash,
            "resolver_version": RESOLVER_VERSION,
            "diffs": diffs,
            "status": TermConsistencyManifestStatus.PENDING,
        },
    )

    return DryRunManifest(
        run_id=run_id,
        manifest_sha256=manifest_sha256,
        diffs=diffs,
        term_snapshot_sha256=term_snapshot_sha,
        settings_sha256=settings_hash,
    )


def build_dry_run_manifest(
    region: str | None = None,
    term_version: str | None = None,
) -> DryRunManifest:
    """Build a dry-run manifest for published articles needing consistency fixes."""
    filters = Q(workflow_status=WorkflowStatus.PUBLISHED)
    if region:
        filters = filters & Q(racing_region=region)

    articles = list(
        NewsArticle.objects.filter(filters).order_by("-published_at")
    )
    return _build_manifest_from_articles(
        articles, term_version=term_version, run_id_suffix="__dry_run"
    )


def generate_canonical_consistency_dry_run(
    article_ids: list[int] | None = None,
    term_version: str | None = None,
) -> DryRunManifest:
    """Generate a dry-run manifest for specific article IDs."""
    filters = Q(workflow_status=WorkflowStatus.PUBLISHED)
    if article_ids:
        filters = filters & Q(id__in=article_ids)

    articles = list(
        NewsArticle.objects.filter(filters).order_by("-published_at")
    )
    return _build_manifest_from_articles(
        articles, term_version=term_version, run_id_suffix="__gentle_dry"
    )


# ---------------------------------------------------------------------------
# Historical Repair — Commit / CAS Apply
# ---------------------------------------------------------------------------

def _field_value_sha256(field: str, value: Any) -> str:
    """Hash a field value using the same serialization as the dry-run diff."""
    if field == "tags_json":
        return hashlib.sha256(
            json.dumps(value, sort_keys=True).encode("utf-8")
        ).hexdigest()
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def commit_dry_run(
    run_id: str,
    manifest_sha256: str,
    approved_by: str | None = None,
) -> CommitResult:
    """Apply a dry-run manifest with CAS semantics.

    The ENTIRE batch — manifest row lock, per-article row locks, CAS checks,
    field writes, and the manifest status flip — runs in a single database
    transaction.  Any failure (drift, DB error, fault injection) rolls the
    whole batch back: partial application is impossible.
    """
    from stable.signals import suppress_qq_push

    applied_articles: set[int] = set()
    total_fields = 0

    with transaction.atomic():
        # Lock the manifest row for the duration of the batch so a
        # concurrent commit/rollback cannot interleave.
        try:
            stored = TermConsistencyManifest.objects.select_for_update().get(run_id=run_id)
        except TermConsistencyManifest.DoesNotExist:
            raise ValueError(f"Manifest with run_id={run_id} not found in store")

        if stored.status != TermConsistencyManifestStatus.PENDING:
            raise ValueError(
                f"Manifest {run_id} is already {stored.status}; refusing to re-commit"
            )

        # Validate manifest SHA
        if stored.manifest_sha256 != manifest_sha256:
            raise ValueError(
                f"Manifest SHA mismatch: expected {manifest_sha256}, got {stored.manifest_sha256}"
            )

        # Validate settings haven't drifted
        current_settings_sha = _settings_sha256()
        if stored.settings_sha256 != current_settings_sha:
            raise ValueError(
                f"Settings drift: expected {current_settings_sha}, got {stored.settings_sha256}"
            )

        # Verify term snapshot hasn't drifted
        current_term_sha = _term_snapshot_sha256()
        if stored.term_snapshot_sha256 != current_term_sha:
            raise ValueError(
                f"Term snapshot drift: expected {current_term_sha}, got {stored.term_snapshot_sha256}"
            )

        # Apply each diff with before-SHA verification.  Each article row is
        # locked (select_for_update) before its CAS check and write, so a
        # concurrent editor cannot slip a change between check and save.
        article_changes: dict[int, tuple[NewsArticle, set[str]]] = {}
        with suppress_qq_push():
            for diff in stored.diffs or []:
                article_id = diff.get("article_id")
                field = diff.get("field")
                if not article_id or not field:
                    continue
                if diff.get("skipped"):
                    continue

                # Lock and fetch article lazily — only once per article_id
                if article_id not in article_changes:
                    try:
                        article_obj = NewsArticle.objects.select_for_update().get(id=article_id)
                    except NewsArticle.DoesNotExist:
                        continue
                    article_changes[article_id] = (article_obj, set())
                article_obj, modified_fields = article_changes[article_id]

                if _is_manually_edited(article_obj, field):
                    continue

                current_value = getattr(article_obj, field, None)
                if current_value is None:
                    continue

                before_sha_expected = diff.get("before_sha256", "")
                current_sha = _field_value_sha256(field, current_value)

                if current_sha != before_sha_expected:
                    raise ValueError(
                        f"Before SHA drift: article={article_id} field={field} "
                        f"expected={before_sha_expected} got={current_sha}"
                    )

                new_value = diff.get("after_value")
                setattr(article_obj, field, new_value)
                total_fields += 1
                applied_articles.add(article_id)
                modified_fields.add(field)

            # Save each article once with all its modified fields.  A failure
            # here raises out of the atomic block and rolls back every
            # previously saved article in this batch.
            for article_id, (article_obj, modified_fields) in article_changes.items():
                if modified_fields:
                    update_list = list(modified_fields | {"updated_at"})
                    article_obj.save(update_fields=update_list)

        stored.status = TermConsistencyManifestStatus.COMMITTED
        stored.approved_by = approved_by or ""
        stored.committed_at = timezone.now()
        stored.save(update_fields=["status", "approved_by", "committed_at", "updated_at"])

    return CommitResult(
        success=True,
        applied_articles=len(applied_articles),
        total_fields=total_fields,
        skipped_articles=0,
    )


def apply_canonical_consistency_manifest(
    manifest: DryRunManifest,
    approved_by: str,
) -> CommitResult:
    return commit_dry_run(manifest.run_id, manifest.manifest_sha256, approved_by=approved_by)


def rollback_canonical_consistency(manifest_id: str) -> CommitResult:
    """Roll back a previously committed consistency manifest.

    Restores each diff's ``before_value`` with CAS semantics: the current
    field value must hash to the committed ``after_value``; any drift aborts
    the whole rollback before anything is written (fail-closed).  Fields
    flagged as manually edited at rollback time are left untouched.

    The ENTIRE batch — manifest row lock, per-article row locks, CAS checks,
    restores, and the manifest status flip — runs in a single database
    transaction: a mid-batch failure cannot produce a partial rollback.
    """
    from stable.signals import suppress_qq_push

    with transaction.atomic():
        # Lock the manifest row for the duration of the batch.
        try:
            stored = TermConsistencyManifest.objects.select_for_update().get(run_id=manifest_id)
        except TermConsistencyManifest.DoesNotExist:
            return CommitResult(
                success=False, applied_articles=0, total_fields=0, skipped_articles=0,
                errors=[f"Manifest {manifest_id} not found"],
            )
        if stored.status != TermConsistencyManifestStatus.COMMITTED:
            return CommitResult(
                success=False, applied_articles=0, total_fields=0, skipped_articles=0,
                errors=[
                    f"Manifest {manifest_id} is {stored.status}; "
                    "only committed manifests can be rolled back"
                ],
            )

        # Phase 1: lock articles and validate CAS for every diff BEFORE writing.
        article_cache: dict[int, NewsArticle] = {}
        eligible_diffs: list[dict] = []
        errors: list[str] = []
        for diff in stored.diffs or []:
            article_id = diff.get("article_id")
            field = diff.get("field")
            if not article_id or not field or diff.get("skipped"):
                continue
            if article_id not in article_cache:
                try:
                    article_cache[article_id] = NewsArticle.objects.select_for_update().get(id=article_id)
                except NewsArticle.DoesNotExist:
                    errors.append(f"article {article_id} not found")
                    continue
            article_obj = article_cache[article_id]
            if _is_manually_edited(article_obj, field):
                # Human owns this field now — nothing to restore, do not fail.
                continue
            current_value = getattr(article_obj, field, None)
            if current_value is None:
                continue
            after_sha = _field_value_sha256(field, diff.get("after_value"))
            current_sha = _field_value_sha256(field, current_value)
            if current_sha != after_sha:
                errors.append(
                    f"After-value drift: article={article_id} field={field} "
                    f"expected={after_sha} got={current_sha}"
                )
                continue
            eligible_diffs.append(diff)

        if errors:
            # No writes have been made; the transaction commits empty.
            return CommitResult(
                success=False, applied_articles=0, total_fields=0, skipped_articles=0,
                errors=errors,
            )

        # Phase 2: restore before_value, batching per article.  A failure
        # here raises out of the atomic block and rolls back every restore.
        applied_articles: set[int] = set()
        total_fields = 0
        article_changes: dict[int, tuple[NewsArticle, set[str]]] = {}
        for diff in eligible_diffs:
            article_id = diff["article_id"]
            field = diff["field"]
            article_obj = article_cache[article_id]
            if article_id not in article_changes:
                article_changes[article_id] = (article_obj, set())
            _, modified_fields = article_changes[article_id]
            setattr(article_obj, field, diff.get("before_value"))
            modified_fields.add(field)
            applied_articles.add(article_id)
            total_fields += 1

        with suppress_qq_push():
            for article_id, (article_obj, modified_fields) in article_changes.items():
                if modified_fields:
                    update_list = list(modified_fields | {"updated_at"})
                    article_obj.save(update_fields=update_list)

        stored.status = TermConsistencyManifestStatus.ROLLED_BACK
        stored.rolled_back_at = timezone.now()
        stored.save(update_fields=["status", "rolled_back_at", "updated_at"])

    return CommitResult(
        success=True,
        applied_articles=len(applied_articles),
        total_fields=total_fields,
        skipped_articles=0,
    )


# ---------------------------------------------------------------------------
# Performance helpers
# ---------------------------------------------------------------------------

def preload_runner_names(articles: list[NewsArticle]) -> dict[int, set[str]]:
    """Preload runner names for a batch of articles using constant queries."""
    article_ids = [a.id for a in articles]
    links = ArticleRaceLink.objects.filter(
        article_id__in=article_ids,
        status__in=[ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL],
    ).select_related("event")

    event_ids = set()
    article_event_map: dict[int, list[int]] = {}
    for link in links:
        event_ids.add(link.event_id)
        article_event_map.setdefault(link.article_id, []).append(link.event_id)

    runners = RaceEventRunner.objects.filter(event_id__in=event_ids)
    event_runner_map: dict[int, set[str]] = {}
    for runner in runners:
        event_runner_map.setdefault(runner.event_id, set()).add(
            _nfkc(runner.horse_name).casefold()
        )

    result: dict[int, set[str]] = {}
    for aid, eids in article_event_map.items():
        names: set[str] = set()
        for eid in eids:
            names.update(event_runner_map.get(eid, set()))
        result[aid] = names
    return result


# Export for test cache reset
def reset_index_cache() -> None:
    """Reset caches (useful for testing)."""
    global _SETTINGS_SHA_CACHE
    _SETTINGS_SHA_CACHE = ""
