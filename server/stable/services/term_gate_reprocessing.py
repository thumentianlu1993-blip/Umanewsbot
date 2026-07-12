from __future__ import annotations

import base64
import hashlib
import json
import re
import resource
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from typing import Any, Callable

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    ArticleRaceLinkStatus,
    AutomationStatus,
    NewsArticle,
    ReviewMode,
    RaceEventResult,
    RaceEventRunner,
    SourceLanguage,
    TermAlias,
    TermEntry,
    TermGateReprocessLock,
    TermGateReprocessRun,
    TermGateReprocessStatus,
    TermType,
    WorkflowStatus,
)
from stable.services.terms import _comparable_horse_name, recognize_horse_names_batch
from stable.services.validation import (
    ValidationBatchContext,
    apply_validation_outcome,
    validate_rewrite,
    _visible_source_parts,
)


LOCK_KEY = "term-gate-reprocess"
RULE_VERSION = "english-term-context-v2"
TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.PUBLISHED,
    WorkflowStatus.REJECTED,
    WorkflowStatus.WITHDRAWN,
    WorkflowStatus.DUPLICATE,
    WorkflowStatus.ARCHIVED,
    WorkflowStatus.IGNORED,
}


class ReprocessLeaseActive(RuntimeError):
    pass


class ReprocessSnapshotDrift(RuntimeError):
    pass


class ReprocessDeadlineReached(RuntimeError):
    pass


@dataclass(frozen=True)
class ReprocessCursor:
    first_seen_at: datetime
    article_id: int
    window_start: datetime
    window_end: datetime
    selector_sha256: str = ""


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, execute, sql, params, many, context):
        self.count += 1
        return execute(sql, params, many, context)


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _evaluate_queryset_with_count(queryset, category: str, query_counts: dict[str, int]):
    counter = _QueryCounter()
    with connection.execute_wrapper(counter):
        rows = list(queryset)
    query_counts[category] = query_counts.get(category, 0) + counter.count
    return rows


def _lock_term_snapshot_tables() -> None:
    if connection.vendor != "postgresql":
        return
    term_table = connection.ops.quote_name(TermEntry._meta.db_table)
    alias_table = connection.ops.quote_name(TermAlias._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f"LOCK TABLE {term_table}, {alias_table} IN SHARE MODE")


def encode_reprocess_cursor(
    *,
    first_seen_at: datetime,
    article_id: int,
    window_start: datetime,
    window_end: datetime,
    selector_sha256: str = "",
) -> str:
    payload = {
        "first_seen_at": first_seen_at.isoformat(),
        "article_id": article_id,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "selector_sha256": selector_sha256,
    }
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_reprocess_cursor(value: str) -> ReprocessCursor:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return ReprocessCursor(
            first_seen_at=datetime.fromisoformat(payload["first_seen_at"]),
            article_id=int(payload["article_id"]),
            window_start=datetime.fromisoformat(payload["window_start"]),
            window_end=datetime.fromisoformat(payload["window_end"]),
            selector_sha256=str(payload.get("selector_sha256") or ""),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("无效 continuation cursor") from exc


_TERM_SNAPSHOT_FIELDS = (
    "id", "term_type", "source_language", "racing_region", "source_ja", "target_zh",
    "aliases_ja", "aliases_zh", "priority", "is_active",
)
_ALIAS_SNAPSHOT_FIELDS = ("id", "term_id", "source_language", "text", "alias_type", "is_active")


def _snapshot_row(instance_or_dict, fields: tuple[str, ...]) -> dict:
    if isinstance(instance_or_dict, dict):
        return {field: instance_or_dict[field] for field in fields}
    return {field: getattr(instance_or_dict, field) for field in fields}


def _term_snapshot_sha256_from_loaded(entries, aliases) -> str:
    entry_rows = [_snapshot_row(entry, _TERM_SNAPSHOT_FIELDS) for entry in entries]
    alias_rows = [_snapshot_row(alias, _ALIAS_SNAPSHOT_FIELDS) for alias in aliases]
    return _canonical_sha(
        {
            "entries": sorted(entry_rows, key=lambda item: item["id"]),
            "aliases": sorted(alias_rows, key=lambda item: item["id"]),
        }
    )


def build_term_snapshot_sha256(*, progress_callback: Callable[[], None] | None = None) -> str:
    if progress_callback:
        progress_callback()
    entries = list(
        TermEntry.objects.filter(
            is_active=True,
            term_type__in=[TermType.HORSE, TermType.RACE, TermType.JOCKEY, TermType.TRAINER],
        )
    )
    if progress_callback:
        progress_callback()
    aliases = list(
        TermAlias.objects.filter(term_id__in=[entry.id for entry in entries])
    )
    if progress_callback:
        progress_callback()
    snapshot = _term_snapshot_sha256_from_loaded(entries, aliases)
    if progress_callback:
        progress_callback()
    return snapshot


def build_settings_sha256() -> str:
    return _canonical_sha(
        {
            "mode": getattr(settings, "ENGLISH_TERM_CONTEXT_MODE", "off"),
            "common": getattr(settings, "MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS", []),
            "ambiguous": getattr(settings, "MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS", []),
            "ignored": getattr(settings, "MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS", []),
            "duplicate_high": getattr(settings, "AUTO_DUPLICATE_HIGH_THRESHOLD", 0.86),
            "duplicate_review": getattr(settings, "AUTO_DUPLICATE_REVIEW_THRESHOLD", 0.72),
            "duplicate_lookback_days": getattr(settings, "AUTO_DUPLICATE_LOOKBACK_DAYS", 7),
            "auto_rewrite_enabled": getattr(settings, "AUTO_REWRITE_ENABLED", False),
            "publish_content_source": getattr(settings, "AUTO_PUBLISH_CONTENT_SOURCE", "base_translation"),
            "rewrite_confidence_min": getattr(settings, "REWRITE_CONFIDENCE_MIN", 60),
        }
    )


def article_input_fingerprint(article: NewsArticle) -> str:
    return _canonical_sha(
        {
            "id": article.id,
            "source": [article.title_ja, article.body_ja_normalized, article.body_ja_raw],
            "publish": [article.title_zh, article.translated_title_zh, article.body_zh, article.translated_body_zh],
            "state": [article.workflow_status, article.automation_status, article.gate_issues],
            "published_to_web_at": article.published_to_web_at,
            "updated_at": article.updated_at,
        }
    )


def claim_reprocess_lease(
    run: TermGateReprocessRun,
    *,
    owner_token: str,
    now: datetime | None = None,
    lease_minutes: int | None = None,
) -> TermGateReprocessLock:
    now = now or timezone.now()
    lease_minutes = lease_minutes or int(getattr(settings, "TERM_GATE_REPROCESS_LEASE_MINUTES", 30))
    with transaction.atomic():
        lock, _ = TermGateReprocessLock.objects.get_or_create(key=LOCK_KEY)
        lock = TermGateReprocessLock.objects.select_for_update().get(pk=lock.pk)
        if lock.locked_by_run_id and lock.lease_expires_at and lock.lease_expires_at > now:
            raise ReprocessLeaseActive(f"run={lock.locked_by_run_id} lease_expires_at={lock.lease_expires_at.isoformat()}")
        lock.locked_by_run = run
        lock.owner_token = owner_token
        lock.heartbeat_at = now
        lock.lease_expires_at = now + timedelta(minutes=lease_minutes)
        lock.save(update_fields=["locked_by_run", "owner_token", "heartbeat_at", "lease_expires_at", "updated_at"])
        return lock


def renew_reprocess_lease(*, owner_token: str, now: datetime | None = None) -> bool:
    now = now or timezone.now()
    with transaction.atomic():
        lock = TermGateReprocessLock.objects.select_for_update().filter(key=LOCK_KEY).first()
        if not lock or lock.owner_token != owner_token:
            return False
        lock.heartbeat_at = now
        lock.lease_expires_at = now + timedelta(minutes=int(getattr(settings, "TERM_GATE_REPROCESS_LEASE_MINUTES", 30)))
        lock.save(update_fields=["heartbeat_at", "lease_expires_at", "updated_at"])
        return True


def release_reprocess_lease(*, owner_token: str) -> bool:
    with transaction.atomic():
        lock = TermGateReprocessLock.objects.select_for_update().filter(key=LOCK_KEY).first()
        if not lock or lock.owner_token != owner_token:
            return False
        lock.locked_by_run = None
        lock.owner_token = ""
        lock.lease_expires_at = None
        lock.heartbeat_at = None
        lock.save(update_fields=["locked_by_run", "owner_token", "lease_expires_at", "heartbeat_at", "updated_at"])
        return True


_ENGLISH_BUCKET_TOKEN_RE = re.compile(r"[0-9A-Za-z]+(?:['’.-][0-9A-Za-z]+)*")
_FALLBACK_BUCKET = "__fallback__"


def _term_bucket_key(value: str, language: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    if language == SourceLanguage.ENGLISH:
        match = _ENGLISH_BUCKET_TOKEN_RE.search(normalized)
        return match.group(0).casefold() if match else _FALLBACK_BUCKET
    return next((character for character in normalized if not character.isspace()), _FALLBACK_BUCKET)


def _source_bucket_keys(source: str, language: str) -> set[str]:
    if language == SourceLanguage.ENGLISH:
        return {match.group(0).casefold() for match in _ENGLISH_BUCKET_TOKEN_RE.finditer(source)}
    return {character for character in source if not character.isspace()}


def build_validation_batch_context(
    articles: list[NewsArticle],
    *,
    progress_callback: Callable[[], None] | None = None,
    lock_terms: bool = False,
) -> ValidationBatchContext:
    query_counts = {
        "term_entry_prefetch_count": 0,
        "term_alias_prefetch_count": 0,
        "race_entity_prefetch_count": 0,
        "horse_alias_prefetch_count": 0,
        "horse_term_prefetch_count": 0,
        "duplicate_corpus_prefetch_count": 0,
    }
    if progress_callback:
        progress_callback()
    entry_queryset = TermEntry.objects.filter(
            is_active=True,
            term_type__in=[TermType.HORSE, TermType.RACE, TermType.JOCKEY, TermType.TRAINER],
        )
    if lock_terms:
        entry_queryset = entry_queryset.select_for_update()
    entries = _evaluate_queryset_with_count(entry_queryset, "term_entry_prefetch_count", query_counts)
    if progress_callback:
        progress_callback()
    alias_queryset = TermAlias.objects.filter(term_id__in=[entry.id for entry in entries])
    if lock_terms:
        alias_queryset = alias_queryset.select_for_update()
    all_aliases = _evaluate_queryset_with_count(alias_queryset, "term_alias_prefetch_count", query_counts)
    aliases = [alias for alias in all_aliases if alias.is_active]
    aliases_by_term_language: dict[tuple[int, str], list[str]] = {}
    for alias in aliases:
        aliases_by_term_language.setdefault((alias.term_id, alias.source_language), []).append(alias.text)
    languages = {article.source_language or SourceLanguage.JAPANESE for article in articles}
    terms_by_language: dict[str, dict[int, list[str]]] = {}
    for language in languages:
        mapping: dict[int, list[str]] = {}
        for entry in entries:
            values = []
            if entry.source_language == language:
                values.extend(entry.all_japanese_terms())
            values.extend(aliases_by_term_language.get((entry.id, language), []))
            mapping[entry.id] = list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
        terms_by_language[language] = mapping
    known_horse_terms_by_language = {
        language: {
            _comparable_horse_name(value, language)
            for entry in entries
            if entry.term_type == TermType.HORSE
            for value in terms_by_language[language].get(entry.id, [])
            if _comparable_horse_name(value, language)
        }
        for language in languages
    }
    compiled_by_language: dict[str, dict[str, list[tuple[int, re.Pattern]]]] = {}
    for language, mapping in terms_by_language.items():
        compiled: dict[str, list[tuple[int, re.Pattern]]] = {}
        for index, (term_id, values) in enumerate(mapping.items(), start=1):
            if progress_callback and index % 100 == 1:
                progress_callback()
            for value in values:
                normalized = unicodedata.normalize("NFKC", value)
                if language == SourceLanguage.ENGLISH:
                    pattern = re.compile(r"(?<![0-9A-Za-z])" + re.escape(normalized) + r"(?![0-9A-Za-z])", re.IGNORECASE)
                else:
                    pattern = re.compile(re.escape(normalized))
                compiled.setdefault(_term_bucket_key(normalized, language), []).append((term_id, pattern))
        compiled_by_language[language] = compiled
    term_entry_ids_by_article: dict[int, set[int]] = {}
    term_pattern_check_count = 0
    for article_index, article in enumerate(articles, start=1):
        if progress_callback and article_index % 10 == 1:
            progress_callback()
        language = article.source_language or SourceLanguage.JAPANESE
        title, body = _visible_source_parts(article)
        source = unicodedata.normalize("NFKC", f"{title}\n{body}")
        buckets = compiled_by_language.get(language, {})
        candidate_patterns = list(buckets.get(_FALLBACK_BUCKET, []))
        for key in _source_bucket_keys(source, language):
            candidate_patterns.extend(buckets.get(key, []))
        matched_ids: set[int] = set()
        seen_patterns: set[tuple[int, str, int]] = set()
        for term_id, pattern in candidate_patterns:
            pattern_key = (term_id, pattern.pattern, pattern.flags)
            if pattern_key in seen_patterns:
                continue
            seen_patterns.add(pattern_key)
            term_pattern_check_count += 1
            if progress_callback and term_pattern_check_count % 250 == 1:
                progress_callback()
            if pattern.search(source):
                matched_ids.add(term_id)
        term_entry_ids_by_article[article.id] = matched_ids
    article_ids = [article.id for article in articles]
    structured_entities_by_article: dict[int, dict[str, list[str]]] = {article_id: {} for article_id in article_ids}
    effective_links = Q(
        event__article_links__status__in=[ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL],
        event__article_links__removed_at__isnull=True,
    )
    runner_rows = _evaluate_queryset_with_count(
        RaceEventRunner.objects.filter(
            effective_links,
            event__article_links__article_id__in=article_ids,
        ).values(
            "id", "event_id", "event__article_links__article_id", "horse_name", "jockey_name", "trainer_name"
        ).distinct(),
        "race_entity_prefetch_count",
        query_counts,
    )
    result_rows = _evaluate_queryset_with_count(
        RaceEventResult.objects.filter(
            effective_links,
            event__article_links__article_id__in=article_ids,
        ).values(
            "id", "event_id", "event__article_links__article_id", "horse_name", "jockey_name", "trainer_name"
        ).distinct(),
        "race_entity_prefetch_count",
        query_counts,
    )
    if progress_callback:
        progress_callback()
    for kind, rows in (("runner", runner_rows), ("result", result_rows)):
        for row in rows:
            names = structured_entities_by_article.setdefault(row["event__article_links__article_id"], {})
            for field in ("horse_name", "jockey_name", "trainer_name"):
                if row.get(field):
                    key = unicodedata.normalize("NFKC", row[field]).casefold()
                    names.setdefault(key, []).append(f"race_{kind}:{row['id']}:event:{row['event_id']}:{field}")
    earliest = min((article.published_at or timezone.now() for article in articles), default=timezone.now()) - timedelta(
        days=int(getattr(settings, "AUTO_DUPLICATE_LOOKBACK_DAYS", 7))
    )
    duplicate_candidates = (
        _evaluate_queryset_with_count(
            NewsArticle.objects.filter(
                Q(workflow_status=WorkflowStatus.PUBLISHED)
                | Q(review_mode=ReviewMode.AUTO, automation_status=AutomationStatus.PUBLISH_READY),
                published_at__gte=earliest,
            ).order_by("-published_at", "-id")[:500],
            "duplicate_corpus_prefetch_count",
            query_counts,
        )
        if articles
        else []
    )
    if progress_callback:
        progress_callback()
    def count_query(category: str, amount: int) -> None:
        query_counts[category] = query_counts.get(category, 0) + amount

    recognized_horses = recognize_horse_names_batch(
        articles,
        progress_callback=progress_callback,
        known_horse_terms_by_language=known_horse_terms_by_language,
        query_count_callback=count_query,
    )
    if progress_callback:
        progress_callback()
    term_snapshot_sha256 = _term_snapshot_sha256_from_loaded(entries, all_aliases)
    if progress_callback:
        progress_callback()
    entity_prefetch_count = (
        query_counts["race_entity_prefetch_count"]
        + query_counts["horse_alias_prefetch_count"]
        + query_counts["horse_term_prefetch_count"]
    )
    return ValidationBatchContext(
        term_entries=entries,
        terms_by_language=terms_by_language,
        recognized_horses_by_article=recognized_horses,
        duplicate_candidates=duplicate_candidates,
        term_entry_ids_by_article=term_entry_ids_by_article,
        structured_entities_by_article=structured_entities_by_article,
        term_snapshot_sha256=term_snapshot_sha256,
        entity_prefetch_count=entity_prefetch_count,
        race_entity_prefetch_count=query_counts["race_entity_prefetch_count"],
        horse_alias_prefetch_count=query_counts["horse_alias_prefetch_count"],
        horse_term_prefetch_count=query_counts["horse_term_prefetch_count"],
        term_entry_prefetch_count=query_counts["term_entry_prefetch_count"],
        term_alias_prefetch_count=query_counts["term_alias_prefetch_count"],
        duplicate_corpus_prefetch_count=query_counts["duplicate_corpus_prefetch_count"],
        term_pattern_check_count=term_pattern_check_count,
    )


def _has_core_blocker(article: NewsArticle) -> bool:
    return any(issue.get("code") == "core_term_missing" and issue.get("severity") == "blocker" for issue in (article.gate_issues or []))


def _count_core_blockers(queryset) -> int:
    table = connection.ops.quote_name(NewsArticle._meta.db_table)
    if connection.vendor == "postgresql":
        where = (
            f"EXISTS (SELECT 1 FROM jsonb_array_elements({table}.gate_issues) AS issue "
            "WHERE issue->>'code' = %s AND issue->>'severity' = %s)"
        )
        return queryset.extra(where=[where], params=["core_term_missing", "blocker"]).count()
    if connection.vendor == "sqlite":
        where = (
            f"EXISTS (SELECT 1 FROM json_each({table}.gate_issues) AS issue "
            "WHERE json_extract(issue.value, '$.code') = %s "
            "AND json_extract(issue.value, '$.severity') = %s)"
        )
        return queryset.extra(where=[where], params=["core_term_missing", "blocker"]).count()
    return sum(
        any(issue.get("code") == "core_term_missing" and issue.get("severity") == "blocker" for issue in issues or [])
        for issues in queryset.values_list("gate_issues", flat=True).iterator(chunk_size=1000)
    )


def _serialize_outcome(article: NewsArticle, outcome) -> dict:
    blockers = [issue for issue in outcome.issues if issue.get("severity") == "blocker"]
    classifications = list(outcome.details.get("english_term_classifications") or [])
    uncertain = [item for item in classifications if item.get("term_semantic_classification") == "uncertain"]
    return {
        "article_id": article.id,
        "passed": outcome.passed,
        "reason": outcome.reason,
        "blockers": blockers,
        "warnings": [issue for issue in outcome.issues if issue.get("severity") == "warning"],
        "english_term_classifications": classifications,
        "common_word_count": sum(item.get("term_semantic_classification") == "common_word" for item in classifications),
        "uncertain_match_count": len(uncertain),
        "uncertain_core_match_count": sum(item.get("position") == "core" for item in uncertain),
        "uncertain_background_match_count": sum(item.get("position") == "background" for item in uncertain),
        "proper_term_blocker_count": sum(
            issue.get("code") == "core_term_missing"
            and (issue.get("payload") or {}).get("term_semantic_classification") == "proper_noun"
            for issue in blockers
        ),
    }


def _run_reprocess_dry_run(
    *,
    region: str,
    hours: int,
    limit: int,
    max_seconds: float,
    source_filters: set[str] | None = None,
    cursor_value: str = "",
    owner_token: str,
) -> dict:
    cursor = decode_reprocess_cursor(cursor_value) if cursor_value else None
    window_end = cursor.window_end if cursor else timezone.now()
    window_start = cursor.window_start if cursor else window_end - timedelta(hours=hours)
    if window_start >= window_end:
        raise ValueError("cursor 时间窗口无效")
    selectors = {
        "region": region,
        "hours": hours,
        "limit": limit,
        "sources": sorted(source_filters or []),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }
    selector_sha = _canonical_sha(selectors)
    if cursor and cursor.selector_sha256 and cursor.selector_sha256 != selector_sha:
        raise ValueError("cursor 与当前选择器不一致")
    run = TermGateReprocessRun.objects.create(mode="dry_run", selectors=selectors, status=TermGateReprocessStatus.PENDING)
    lease_claimed = False
    try:
        claim_reprocess_lease(run, owner_token=owner_token)
        lease_claimed = True
    except ReprocessLeaseActive as exc:
        run.status = TermGateReprocessStatus.REJECTED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        raise
    run.status = TermGateReprocessStatus.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at", "updated_at"])
    started = monotonic()
    deadline = started + max_seconds
    heartbeat_interval = timedelta(
        seconds=max(1, min(60, int(getattr(settings, "TERM_GATE_REPROCESS_LEASE_MINUTES", 30)) * 20))
    )
    last_heartbeat_at = timezone.now()

    def renew_if_due() -> None:
        nonlocal last_heartbeat_at
        now = timezone.now()
        if now - last_heartbeat_at < heartbeat_interval:
            return
        if not renew_reprocess_lease(owner_token=owner_token, now=now):
            raise ReprocessLeaseActive("重跑任务执行期间失去全局租约")
        last_heartbeat_at = now

    def check_progress() -> None:
        renew_if_due()
        if monotonic() >= deadline:
            raise ReprocessDeadlineReached

    try:
        queryset = NewsArticle.objects.filter(
            racing_region=region,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            source_language=SourceLanguage.ENGLISH,
            first_seen_at__gte=window_start,
            first_seen_at__lt=window_end,
        ).order_by("first_seen_at", "id")
        if cursor:
            queryset = queryset.filter(Q(first_seen_at__gt=cursor.first_seen_at) | Q(first_seen_at=cursor.first_seen_at, id__gt=cursor.article_id))
        row_queryset = queryset.values(
            "id", "first_seen_at", "gate_issues", "workflow_status",
            "source_site", "source_mode", "source_config_id",
        )
        skipped = {"manual_terminal_state": [], "no_core_term_blocker": [], "source_not_selected": []}
        outside_lookback_queryset = NewsArticle.objects.filter(
            racing_region=region,
            automation_status=AutomationStatus.MANUAL_REVIEW_REQUIRED,
            source_language=SourceLanguage.ENGLISH,
            first_seen_at__lt=window_start,
        ).exclude(workflow_status__in=TERMINAL_WORKFLOW_STATUSES)
        outside_lookback_count = _count_core_blockers(outside_lookback_queryset)
        selected_ids: list[int] = []
        stop_reason = "completed"
        scanned_count = 0
        scan_batch_size = max(50, min(500, limit * 2))
        scan_limit = max(200, min(5000, limit * 20))
        scan_cursor = cursor
        start_cursor = cursor or ReprocessCursor(window_start, 0, window_start, window_end, selector_sha)
        resume_before_first_selected = start_cursor
        scan_exhausted = False
        last_scanned_row: dict | None = None
        while len(selected_ids) < limit and not scan_exhausted and scanned_count < scan_limit:
            try:
                check_progress()
            except ReprocessDeadlineReached:
                stop_reason = "max_seconds"
                break
            batch_queryset = row_queryset
            if scan_cursor:
                batch_queryset = batch_queryset.filter(
                    Q(first_seen_at__gt=scan_cursor.first_seen_at)
                    | Q(first_seen_at=scan_cursor.first_seen_at, id__gt=scan_cursor.article_id)
                )
            rows = list(batch_queryset[:scan_batch_size])
            if not rows:
                scan_exhausted = True
                break
            for row in rows:
                if scanned_count >= scan_limit:
                    stop_reason = "scan_limit"
                    break
                previous_cursor = scan_cursor or start_cursor
                scanned_count += 1
                last_scanned_row = row
                scan_cursor = ReprocessCursor(
                    row["first_seen_at"],
                    row["id"],
                    window_start,
                    window_end,
                    selector_sha,
                )
                if row["workflow_status"] in TERMINAL_WORKFLOW_STATUSES:
                    skipped["manual_terminal_state"].append(row["id"])
                    continue
                if not any(
                    issue.get("code") == "core_term_missing" and issue.get("severity") == "blocker"
                    for issue in (row["gate_issues"] or [])
                ):
                    skipped["no_core_term_blocker"].append(row["id"])
                    continue
                key = f"{row['source_site']}:{row['source_mode']}"
                if source_filters and key not in source_filters and str(row["source_config_id"] or "") not in source_filters:
                    skipped["source_not_selected"].append(row["id"])
                    continue
                selected_ids.append(row["id"])
                if len(selected_ids) == 1:
                    resume_before_first_selected = previous_cursor
                if len(selected_ids) >= limit:
                    stop_reason = "limit"
                    break
            scan_exhausted = len(rows) < scan_batch_size
            try:
                check_progress()
            except ReprocessDeadlineReached:
                stop_reason = "max_seconds"
                break
            if scanned_count >= scan_limit and len(selected_ids) < limit:
                stop_reason = "scan_limit"
            if stop_reason == "scan_limit":
                break
        selected_map = {
            article.id: article
            for article in NewsArticle.objects.filter(id__in=selected_ids).prefetch_related("related_region_links")
        }
        selected = [selected_map[article_id] for article_id in selected_ids]
        context: ValidationBatchContext | None = None
        try:
            context = build_validation_batch_context(selected, progress_callback=check_progress)
        except ReprocessDeadlineReached:
            stop_reason = "max_seconds"
        outcomes: list[dict] = []
        completed_articles: list[NewsArticle] = []
        for article in selected if context is not None else []:
            try:
                check_progress()
                outcome = validate_rewrite(
                    article,
                    batch_context=context,
                    progress_callback=check_progress,
                )
            except ReprocessDeadlineReached:
                stop_reason = "max_seconds"
                break
            outcomes.append(_serialize_outcome(article, outcome))
            completed_articles.append(article)
        candidate_payload = [
            {"article_id": article.id, "input_sha256": article_input_fingerprint(article), "first_seen_at": article.first_seen_at.isoformat()}
            for article in completed_articles
        ]
        next_cursor = ""
        if stop_reason == "max_seconds":
            last_cursor = (
                ReprocessCursor(
                    completed_articles[-1].first_seen_at,
                    completed_articles[-1].id,
                    window_start,
                    window_end,
                    selector_sha,
                )
                if completed_articles
                else resume_before_first_selected
            )
            next_cursor = encode_reprocess_cursor(
                first_seen_at=last_cursor.first_seen_at,
                article_id=last_cursor.article_id,
                window_start=window_start,
                window_end=window_end,
                selector_sha256=selector_sha,
            )
        elif stop_reason in {"limit", "scan_limit"} and last_scanned_row:
            next_cursor = encode_reprocess_cursor(
                first_seen_at=last_scanned_row["first_seen_at"],
                article_id=last_scanned_row["id"],
                window_start=window_start,
                window_end=window_end,
                selector_sha256=selector_sha,
            )
        summary = {
            "candidate_count": len(completed_articles),
            "completed_count": len(outcomes),
            "revalidated_to_publish_ready_count": sum(item["passed"] for item in outcomes),
            "still_blocked_count": sum(not item["passed"] for item in outcomes),
            "common_word_downgraded_count": sum(item["common_word_count"] for item in outcomes),
            "proper_term_blocker_count": sum(item["proper_term_blocker_count"] for item in outcomes),
            "uncertain_match_count": sum(item["uncertain_match_count"] for item in outcomes),
            "uncertain_article_count": sum(item["uncertain_match_count"] > 0 for item in outcomes),
            "uncertain_core_article_count": sum(item["uncertain_core_match_count"] > 0 for item in outcomes),
            "uncertain_background_article_count": sum(
                item["uncertain_background_match_count"] > 0 for item in outcomes
            ),
        }
        performance = {
            "term_index_build_count": context.term_index_build_count if context else 0,
            "entity_prefetch_count": context.entity_prefetch_count if context else 0,
            "race_entity_prefetch_count": context.race_entity_prefetch_count if context else 0,
            "horse_alias_prefetch_count": context.horse_alias_prefetch_count if context else 0,
            "horse_term_prefetch_count": context.horse_term_prefetch_count if context else 0,
            "term_entry_prefetch_count": context.term_entry_prefetch_count if context else 0,
            "term_alias_prefetch_count": context.term_alias_prefetch_count if context else 0,
            "duplicate_corpus_prefetch_count": context.duplicate_corpus_prefetch_count if context else 0,
            "term_pattern_check_count": context.term_pattern_check_count if context else 0,
            "elapsed_seconds": monotonic() - started,
        }
        manifest_body = {
            "selectors": selectors,
            "rule_version": RULE_VERSION,
            "settings_sha256": build_settings_sha256(),
            "term_snapshot_sha256": context.term_snapshot_sha256 if context else "",
            "candidate_payload": candidate_payload,
            "outcomes": outcomes,
        }
        manifest_sha = _canonical_sha(manifest_body)
        result = {
            "run_id": run.id,
            "manifest_sha256": manifest_sha,
            "candidate_ids": [article.id for article in completed_articles],
            "revalidated_to_publish_ready_ids": [item["article_id"] for item in outcomes if item["passed"]],
            "outcomes": outcomes,
            "summary": summary,
            "summary_by_region": {region: summary.copy()},
            "skipped": skipped,
            "outside_lookback_count": outside_lookback_count,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "scanned_count": scanned_count,
            "stop_reason": stop_reason,
            "next_cursor": next_cursor,
            "performance": performance,
        }
        run.status = TermGateReprocessStatus.SUCCEEDED
        run.cursor = next_cursor
        run.rule_version = RULE_VERSION
        run.settings_sha256 = manifest_body["settings_sha256"]
        run.term_snapshot_sha256 = context.term_snapshot_sha256 if context else ""
        run.candidate_payload = candidate_payload
        run.result_payload = result
        run.manifest_sha256 = manifest_sha
        run.statistics = performance
        run.finished_at = timezone.now()
        run.save()
        return result
    except Exception as exc:
        run.status = TermGateReprocessStatus.FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        raise
    finally:
        if lease_claimed:
            release_reprocess_lease(owner_token=owner_token)


def run_reprocess_dry_run(
    *,
    region: str,
    hours: int,
    limit: int,
    max_seconds: float,
    source_filters: set[str] | None = None,
    cursor_value: str = "",
    owner_token: str,
) -> dict:
    query_counter = _QueryCounter()
    rss_before = _max_rss_bytes()
    with connection.execute_wrapper(query_counter):
        result = _run_reprocess_dry_run(
            region=region,
            hours=hours,
            limit=limit,
            max_seconds=max_seconds,
            source_filters=source_filters,
            cursor_value=cursor_value,
            owner_token=owner_token,
        )
        performance = {
            **result["performance"],
            "peak_rss_delta_bytes": max(0, _max_rss_bytes() - rss_before),
            "sql_query_count": query_counter.count + 1,
        }
        result["performance"] = performance
        TermGateReprocessRun.objects.filter(pk=result["run_id"]).update(
            statistics=performance,
            result_payload=result,
        )
    return result


def commit_reprocess_run(*, dry_run_id: int, manifest_sha256: str) -> dict:
    run = TermGateReprocessRun.objects.get(pk=dry_run_id, mode="dry_run")
    if run.status == TermGateReprocessStatus.COMMITTED:
        return {"status": "already_committed", "restored_candidate_ids": run.result_payload.get("committed_candidate_ids", [])}
    if run.manifest_sha256 != manifest_sha256:
        raise ValueError("manifest SHA-256 不匹配")
    if run.rule_version != RULE_VERSION or run.settings_sha256 != build_settings_sha256() or run.term_snapshot_sha256 != build_term_snapshot_sha256():
        TermGateReprocessRun.objects.filter(pk=run.pk).update(
            status=TermGateReprocessStatus.REJECTED,
            error_message="global_snapshot_drift",
            finished_at=timezone.now(),
        )
        return {"status": "rejected", "reason": "global_snapshot_drift", "restored_candidate_ids": []}
    expected = {item["article_id"]: item for item in run.candidate_payload}
    restored: list[int] = []
    skipped: list[int] = []
    skipped_reasons: dict[str, str] = {}
    owner_token = uuid.uuid4().hex
    claim_reprocess_lease(run, owner_token=owner_token)
    heartbeat_interval = timedelta(
        seconds=max(1, min(60, int(getattr(settings, "TERM_GATE_REPROCESS_LEASE_MINUTES", 30)) * 20))
    )
    last_heartbeat_at = timezone.now()

    def commit_progress() -> None:
        nonlocal last_heartbeat_at
        heartbeat_now = timezone.now()
        if heartbeat_now - last_heartbeat_at < heartbeat_interval:
            return
        if not renew_reprocess_lease(owner_token=owner_token, now=heartbeat_now):
            raise ReprocessLeaseActive("提交任务执行期间失去全局租约")
        last_heartbeat_at = heartbeat_now

    try:
        with transaction.atomic():
            locked_run = TermGateReprocessRun.objects.select_for_update().get(pk=run.pk)
            _lock_term_snapshot_tables()
            articles = list(NewsArticle.objects.select_for_update().filter(id__in=expected).order_by("id"))
            stable_articles = []
            for article in articles:
                if article_input_fingerprint(article) != expected[article.id]["input_sha256"]:
                    skipped.append(article.id)
                    skipped_reasons[str(article.id)] = "article_input_drift"
                else:
                    stable_articles.append(article)
            context = build_validation_batch_context(
                stable_articles,
                progress_callback=commit_progress,
                lock_terms=True,
            )
            current_settings_sha256 = build_settings_sha256()
            if (
                locked_run.rule_version != RULE_VERSION
                or locked_run.settings_sha256 != current_settings_sha256
                or locked_run.term_snapshot_sha256 != context.term_snapshot_sha256
            ):
                raise ReprocessSnapshotDrift(
                    json.dumps(
                        {
                            "stage": "before_article_writes",
                            "expected_settings_sha256": locked_run.settings_sha256,
                            "actual_settings_sha256": current_settings_sha256,
                            "expected_term_snapshot_sha256": locked_run.term_snapshot_sha256,
                            "actual_term_snapshot_sha256": context.term_snapshot_sha256,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            expected_outcomes = {
                item["article_id"]: item for item in run.result_payload.get("outcomes", [])
            }
            for article in stable_articles:
                outcome = validate_rewrite(
                    article,
                    batch_context=context,
                    progress_callback=commit_progress,
                )
                serialized = _serialize_outcome(article, outcome)
                if _canonical_sha(serialized) != _canonical_sha(expected_outcomes.get(article.id, {})):
                    skipped.append(article.id)
                    skipped_reasons[str(article.id)] = "validation_result_drift"
                    continue
                if not outcome.passed:
                    skipped.append(article.id)
                    skipped_reasons[str(article.id)] = "still_blocked"
                    continue
                apply_validation_outcome(article, outcome)
                now = timezone.now()
                NewsArticle.objects.filter(pk=article.pk).update(ranked_revived_at=now, updated_at=now)
                restored.append(article.id)
            final_settings_sha256 = build_settings_sha256()
            final_term_snapshot_sha256 = build_term_snapshot_sha256(progress_callback=commit_progress)
            if (
                locked_run.rule_version != RULE_VERSION
                or locked_run.settings_sha256 != final_settings_sha256
                or locked_run.term_snapshot_sha256 != final_term_snapshot_sha256
            ):
                raise ReprocessSnapshotDrift(
                    json.dumps(
                        {
                            "stage": "before_transaction_commit",
                            "expected_settings_sha256": locked_run.settings_sha256,
                            "actual_settings_sha256": final_settings_sha256,
                            "expected_term_snapshot_sha256": locked_run.term_snapshot_sha256,
                            "actual_term_snapshot_sha256": final_term_snapshot_sha256,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            locked_run.status = TermGateReprocessStatus.COMMITTED
            locked_run.result_payload = {**locked_run.result_payload, "committed_candidate_ids": restored, "skipped_article_ids": skipped}
            locked_run.finished_at = timezone.now()
            locked_run.save(update_fields=["status", "result_payload", "finished_at", "updated_at"])
    except ReprocessSnapshotDrift as exc:
        TermGateReprocessRun.objects.filter(pk=run.pk).update(
            status=TermGateReprocessStatus.REJECTED,
            error_message=str(exc),
            finished_at=timezone.now(),
        )
        return {
            "status": "rejected",
            "reason": "global_snapshot_drift",
            "restored_candidate_ids": [],
            "snapshot_drift": str(exc),
        }
    except Exception as exc:
        TermGateReprocessRun.objects.filter(pk=run.pk).update(status=TermGateReprocessStatus.FAILED, error_message=str(exc), finished_at=timezone.now())
        raise
    finally:
        release_reprocess_lease(owner_token=owner_token)
    return {
        "status": "committed",
        "restored_candidate_ids": restored,
        "skipped_article_ids": skipped,
        "skipped_reasons": skipped_reasons,
    }
