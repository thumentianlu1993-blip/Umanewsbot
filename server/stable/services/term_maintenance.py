from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from stable.models import NewsArticle, SourceLanguage, TermAlias, TermAliasType, TermEntry, TermType, WorkflowStatus
from stable.services.term_admin import source_text_identity, sync_all_term_alias_active, upsert_term_source_alias
from stable.services.terms import source_term_matches_text, source_terms_by_entry


MERGE_NOTE_MARKER = "hkjc_ja_alias_merged_into_term_id"
MACHINE_TRANSLATION_FIELDS = ["translated_title_zh", "translated_body_zh", "translated_summary_zh", "base_translation_zh"]
PUBLISH_FIELDS = ["title_zh", "body_zh", "summary_zh", "push_summary_zh"]
BACKFILL_FIELDS = [*MACHINE_TRANSLATION_FIELDS, *PUBLISH_FIELDS]


def normalize_target_zh(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    return re.sub(r"\s+", "", normalized).casefold()


def _term_snapshot(term: TermEntry | None) -> dict:
    if term is None:
        return {}
    return {
        "term_id": term.pk,
        "source_language": term.source_language,
        "source_text": term.source_ja,
        "term_type": term.term_type,
        "target_zh": term.target_zh,
        "racing_region": term.racing_region,
        "is_active": term.is_active,
    }


def _active_source_owners(*, source_language: str, source_text: str) -> list[dict]:
    text = (source_text or "").strip()
    if not text:
        return []
    owners_by_key: dict[tuple[int, str], dict] = {}
    primary_terms = TermEntry.objects.filter(source_language=source_language, source_ja__iexact=text, is_active=True)
    for term in primary_terms.order_by("pk"):
        key = (term.pk, source_text_identity(term.source_ja))
        owners_by_key[key] = {"owner_kind": "primary", "term": term, "alias_id": None, "text": term.source_ja}
    aliases = TermAlias.objects.select_related("term").filter(
        source_language=source_language,
        text__iexact=text,
        is_active=True,
        term__is_active=True,
    )
    for alias in aliases.order_by("term_id", "pk"):
        key = (alias.term_id, source_text_identity(alias.text))
        if key in owners_by_key:
            continue
        owners_by_key[key] = {"owner_kind": "alias", "term": alias.term, "alias_id": alias.pk, "text": alias.text}
    return list(owners_by_key.values())


def _owner_to_dict(owner: dict) -> dict:
    term = owner["term"]
    return {
        "owner_kind": owner["owner_kind"],
        "owner_term_id": term.pk,
        "owner_alias_id": owner.get("alias_id"),
        "owner_term_type": term.term_type,
        "owner_source_language": term.source_language,
        "owner_source_text": owner.get("text") or term.source_ja,
        "owner_target_zh": term.target_zh,
        "owner_is_active": term.is_active,
    }


def _merge_row(
    *,
    action: str,
    reason: str,
    target: TermEntry | None,
    source_text: str,
    source_language: str,
    owner: dict | None = None,
    extra: dict | None = None,
) -> dict:
    owner_payload = _owner_to_dict(owner) if owner else {}
    payload = {
        "action": action,
        "reason": reason,
        "source_language": source_language,
        "source_text": (source_text or "").strip(),
        "source_text_key": source_text_identity(source_text or ""),
        "target": _term_snapshot(target),
        **owner_payload,
    }
    if extra:
        payload.update(extra)
    return payload


def _plan_single_alias_merge(*, target: TermEntry | None, source_text: str, source_language: str) -> dict:
    if target is None:
        return _merge_row(
            action="skipped",
            reason="target_missing",
            target=None,
            source_text=source_text,
            source_language=source_language,
        )
    if not target.is_active:
        return _merge_row(
            action="skipped",
            reason="target_inactive",
            target=target,
            source_text=source_text,
            source_language=source_language,
        )
    owners = _active_source_owners(source_language=source_language, source_text=source_text)
    target_owners = [owner for owner in owners if owner["term"].pk == target.pk]
    if target_owners:
        return _merge_row(
            action="skipped",
            reason="already_on_target",
            target=target,
            source_text=source_text,
            source_language=source_language,
            owner=target_owners[0],
        )
    if not owners:
        return _merge_row(
            action="skipped",
            reason="source_owner_missing",
            target=target,
            source_text=source_text,
            source_language=source_language,
        )
    primary_owners = [owner for owner in owners if owner["owner_kind"] == "primary"]
    if len(owners) > 1:
        return _merge_row(
            action="skipped",
            reason="multiple_active_owners",
            target=target,
            source_text=source_text,
            source_language=source_language,
            owner=owners[0],
            extra={"owners": [_owner_to_dict(owner) for owner in owners]},
        )
    if not primary_owners:
        return _merge_row(
            action="skipped",
            reason="active_alias_owner",
            target=target,
            source_text=source_text,
            source_language=source_language,
            owner=owners[0],
        )
    owner = primary_owners[0]
    source_term = owner["term"]
    if source_term.term_type != target.term_type:
        return _merge_row(
            action="skipped",
            reason="term_type_mismatch",
            target=target,
            source_text=source_text,
            source_language=source_language,
            owner=owner,
        )
    if normalize_target_zh(source_term.target_zh) != normalize_target_zh(target.target_zh):
        return _merge_row(
            action="skipped",
            reason="target_zh_conflict",
            target=target,
            source_text=source_text,
            source_language=source_language,
            owner=owner,
            extra={
                "target_target_zh_normalized": normalize_target_zh(target.target_zh),
                "owner_target_zh_normalized": normalize_target_zh(source_term.target_zh),
            },
        )
    return _merge_row(
        action="candidate",
        reason="same_target_primary_owner",
        target=target,
        source_text=source_text,
        source_language=source_language,
        owner=owner,
    )


def _merge_targets(
    *,
    term_type: str,
    target_source_language: str,
    racing_region: str | None,
    target_term_ids: Iterable[int] | None,
) -> list[TermEntry]:
    queryset = TermEntry.objects.filter(
        is_active=True,
        term_type=term_type,
        source_language=target_source_language,
    ).order_by("pk")
    if racing_region is not None:
        queryset = queryset.filter(racing_region=racing_region)
    if target_term_ids:
        queryset = queryset.filter(pk__in=list(target_term_ids))
    return list(queryset)


def plan_hkjc_ja_alias_merge(
    *,
    term_type: str = TermType.HORSE,
    target_source_language: str = SourceLanguage.ENGLISH,
    alias_source_language: str = SourceLanguage.JAPANESE,
    racing_region: str | None = None,
    target_term_ids: Iterable[int] | None = None,
    candidate_rows: Iterable[dict] | None = None,
    limit: int | None = None,
) -> dict:
    rows: list[dict] = []
    seen: set[tuple[int | None, str]] = set()
    targets = _merge_targets(
        term_type=term_type,
        target_source_language=target_source_language,
        racing_region=racing_region,
        target_term_ids=target_term_ids,
    )
    targets_by_id = {target.pk: target for target in targets}
    targets_by_source = {source_text_identity(target.source_ja): target for target in targets}
    if candidate_rows is not None:
        for candidate in candidate_rows:
            target = None
            raw_target_id = candidate.get("target_term_id") or candidate.get("term_id")
            if raw_target_id:
                target = targets_by_id.get(int(raw_target_id)) or TermEntry.objects.filter(pk=int(raw_target_id)).first()
            if target is None:
                raw_target_source = candidate.get("target_source_text") or candidate.get("target_source_ja") or candidate.get("target")
                if raw_target_source:
                    target = targets_by_source.get(source_text_identity(raw_target_source))
            source_text = candidate.get("source_text") or candidate.get("alias_text") or candidate.get("source_ja") or ""
            key = (target.pk if target else None, source_text_identity(source_text))
            if key in seen:
                continue
            seen.add(key)
            rows.append(_plan_single_alias_merge(target=target, source_text=source_text, source_language=alias_source_language))
            if limit and len(rows) >= limit:
                break
    else:
        source_terms = list(
            TermEntry.objects.filter(is_active=True, source_language=alias_source_language, term_type=term_type).order_by("pk")
        )
        for target in targets:
            target_key = normalize_target_zh(target.target_zh)
            for source_term in source_terms:
                if source_term.pk == target.pk or normalize_target_zh(source_term.target_zh) != target_key:
                    continue
                key = (target.pk, source_text_identity(source_term.source_ja))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    _plan_single_alias_merge(
                        target=target,
                        source_text=source_term.source_ja,
                        source_language=alias_source_language,
                    )
                )
                if limit and len(rows) >= limit:
                    break
            if limit and len(rows) >= limit:
                break
    return {"summary": _merge_summary(rows), "rows": rows}


def _merge_summary(rows: list[dict]) -> dict:
    counts = Counter(row["action"] for row in rows)
    reasons = Counter(row["reason"] for row in rows)
    return {
        "scanned": len(rows),
        "candidate_count": counts.get("candidate", 0),
        "skipped_count": counts.get("skipped", 0),
        "applied_count": counts.get("applied", 0),
        "unchanged_count": counts.get("unchanged", 0),
        "reason_counts": dict(sorted(reasons.items())),
    }


def _append_merge_note(source_term: TermEntry, target: TermEntry) -> str:
    now = timezone.localtime(timezone.now()).isoformat()
    note = f"{MERGE_NOTE_MARKER}={target.pk}; merged_at={now}; target_source={target.source_ja}"
    existing = (source_term.notes or "").strip()
    if note in existing:
        return existing
    return f"{existing}\n{note}".strip() if existing else note


def apply_hkjc_ja_alias_merge(plan_rows: Iterable[dict]) -> dict:
    result_rows: list[dict] = []
    for row in plan_rows:
        if row.get("action") != "candidate":
            skipped = {**row, "action": "skipped", "apply_reason": "not_candidate"}
            result_rows.append(skipped)
            continue
        target_id = (row.get("target") or {}).get("term_id") or row.get("target_term_id")
        source_text = row.get("source_text") or ""
        source_language = row.get("source_language") or SourceLanguage.JAPANESE
        target = TermEntry.objects.filter(pk=target_id).first()
        rechecked = _plan_single_alias_merge(target=target, source_text=source_text, source_language=source_language)
        if rechecked["action"] != "candidate":
            result_rows.append({**rechecked, "apply_reason": "recheck_failed"})
            continue
        source_term = TermEntry.objects.filter(pk=rechecked.get("owner_term_id")).first()
        if source_term is None or target is None:
            result_rows.append({**rechecked, "action": "skipped", "apply_reason": "missing_rechecked_term"})
            continue
        with transaction.atomic():
            alias = upsert_term_source_alias(
                target,
                source_language=source_language,
                text=source_text,
                alias_type=TermAliasType.ALIAS,
                is_active=True,
            )
            source_term.is_active = False
            source_term.notes = _append_merge_note(source_term, target)
            source_term.save(update_fields=["is_active", "notes", "updated_at"])
            sync_all_term_alias_active(source_term)
        result_rows.append(
            {
                **rechecked,
                "action": "applied",
                "alias_id": alias.pk if alias else None,
                "deactivated_source_term_id": source_term.pk,
                "apply_reason": "merged",
            }
        )
    return {"summary": _merge_summary(result_rows), "rows": result_rows}


def _matches_for_source_terms(
    text: str,
    term: TermEntry,
    source_language: str,
    source_terms: Iterable[str],
) -> list[dict]:
    matches: list[dict] = []
    for source_text in source_terms:
        if source_term_matches_text(text or "", source_text, source_language):
            matches.append(
                {
                    "term_id": term.pk,
                    "source_text": source_text,
                    "target_zh": term.target_zh,
                    "replacement_count": _replacement_count(text or "", source_text, source_language),
                }
            )
    return matches


def _replace_source_term(text: str, source_text: str, target: str, source_language: str) -> str:
    if not source_text:
        return text
    if source_language == SourceLanguage.ENGLISH:
        pattern = re.compile(r"(?<![0-9A-Za-z])" + re.escape(source_text) + r"(?![0-9A-Za-z])", re.IGNORECASE)
        return pattern.sub(target, text)
    return text.replace(source_text, target)


def _apply_term_mapping_for_source_terms(
    text: str,
    term: TermEntry,
    source_language: str,
    source_terms: Iterable[str],
) -> str:
    mapped = text
    for source_text in sorted(source_terms, key=len, reverse=True):
        mapped = _replace_source_term(mapped, source_text, term.target_zh, source_language)
    return mapped


def _field_contains_any_source_term(text: str, source_language: str, source_terms: Iterable[str]) -> bool:
    value = text or ""
    for source_text in source_terms:
        if source_term_matches_text(value, source_text, source_language):
            return True
    return False


def _replacement_count(text: str, source_text: str, source_language: str) -> int:
    if not source_text:
        return 0
    if source_language == SourceLanguage.ENGLISH:
        pattern = re.compile(r"(?<![0-9A-Za-z])" + re.escape(source_text) + r"(?![0-9A-Za-z])", re.IGNORECASE)
        return len(pattern.findall(text or ""))
    return (text or "").count(source_text)


def _article_queryset(
    *,
    article_ids: Iterable[int] | None = None,
    source_language: str | None = None,
    published_from: date | datetime | None = None,
    published_to: date | datetime | None = None,
    published_only: bool = True,
):
    queryset = NewsArticle.objects.order_by("pk")
    if published_only:
        queryset = queryset.filter(workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at__isnull=False)
    if article_ids:
        queryset = queryset.filter(pk__in=list(article_ids))
    if source_language:
        queryset = queryset.filter(source_language=source_language)
    if published_from:
        queryset = queryset.filter(published_to_web_at__gte=published_from)
    if published_to:
        queryset = queryset.filter(published_to_web_at__lte=published_to)
    return queryset


def plan_article_term_backfill(
    *,
    term_ids: Iterable[int],
    article_ids: Iterable[int] | None = None,
    source_language: str | None = None,
    published_from: date | datetime | None = None,
    published_to: date | datetime | None = None,
    limit: int | None = None,
    published_only: bool = True,
) -> dict:
    term_id_list = [int(term_id) for term_id in term_ids if term_id]
    terms = list(TermEntry.objects.filter(pk__in=term_id_list, is_active=True).order_by("-priority", "source_ja"))
    terms_by_source_language: dict[str, dict[int, list[str]]] = {}
    flat_source_terms_by_language: dict[str, list[str]] = {}
    articles = _article_queryset(
        article_ids=article_ids,
        source_language=source_language,
        published_from=published_from,
        published_to=published_to,
        published_only=published_only,
    )
    if limit:
        articles = articles[:limit]
    rows: list[dict] = []
    scanned_articles = 0
    unchanged_fields = 0
    for article in articles:
        scanned_articles += 1
        article_language = article.source_language or SourceLanguage.JAPANESE
        if article_language not in terms_by_source_language:
            language_terms = source_terms_by_entry(terms, article_language)
            terms_by_source_language[article_language] = language_terms
            flat_source_terms_by_language[article_language] = [
                source_text for source_terms in language_terms.values() for source_text in source_terms
            ]
        language_terms = terms_by_source_language[article_language]
        flat_source_terms = flat_source_terms_by_language[article_language]
        manual_fields = set(article.manually_edited_fields or [])
        for field_name in BACKFILL_FIELDS:
            before = getattr(article, field_name, "") or ""
            if not before:
                unchanged_fields += 1
                continue
            if not _field_contains_any_source_term(before, article_language, flat_source_terms):
                unchanged_fields += 1
                continue
            after = before
            matches: list[dict] = []
            for term in terms:
                source_terms = language_terms.get(term.pk, [])
                if not source_terms:
                    continue
                term_matches = _matches_for_source_terms(after, term, article_language, source_terms)
                if not term_matches:
                    continue
                next_after = _apply_term_mapping_for_source_terms(after, term, article_language, source_terms)
                if next_after != after:
                    matches.extend(term_matches)
                    after = next_after
            if after == before:
                unchanged_fields += 1
                continue
            is_manual_skip = field_name in PUBLISH_FIELDS and field_name in manual_fields
            rows.append(
                {
                    "action": "skipped" if is_manual_skip else "planned",
                    "reason": "manual_field" if is_manual_skip else "matched",
                    "article_id": article.pk,
                    "field": field_name,
                    "source_language": article_language,
                    "matches": matches,
                    "term_ids": sorted({match["term_id"] for match in matches}),
                    "source_texts": [match["source_text"] for match in matches],
                    "target_values": sorted({match["target_zh"] for match in matches}),
                    "replacement_count": sum(match["replacement_count"] for match in matches),
                    "before": before,
                    "after": after,
                    "before_excerpt": _excerpt(before),
                    "after_excerpt": _excerpt(after),
                }
            )
    return {"summary": _backfill_summary(rows, scanned_articles=scanned_articles, unchanged_fields=unchanged_fields), "rows": rows}


def _excerpt(value: str, size: int = 120) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= size:
        return text
    return f"{text[:size]}..."


def _backfill_summary(rows: list[dict], *, scanned_articles: int | None = None, unchanged_fields: int = 0) -> dict:
    counts = Counter(row["action"] for row in rows)
    article_ids = {row.get("article_id") for row in rows if row.get("article_id")}
    return {
        "scanned_articles": scanned_articles if scanned_articles is not None else len(article_ids),
        "matched_articles": len(article_ids),
        "planned_fields": counts.get("planned", 0),
        "updated_fields": counts.get("applied", 0),
        "skipped_fields": counts.get("skipped", 0),
        "unchanged_fields": counts.get("unchanged", 0) + unchanged_fields,
        "stale_fields": counts.get("stale", 0),
        "replacement_count": sum(int(row.get("replacement_count") or 0) for row in rows if row.get("action") in {"planned", "applied"}),
    }


def apply_article_term_backfill(diff_rows: Iterable[dict]) -> dict:
    result_rows: list[dict] = []
    for row in diff_rows:
        if row.get("action") != "planned":
            result_rows.append({**row, "action": "skipped", "apply_reason": row.get("reason") or "not_planned"})
            continue
        article = NewsArticle.objects.filter(pk=row.get("article_id")).first()
        if article is None:
            result_rows.append({**row, "action": "skipped", "apply_reason": "article_missing"})
            continue
        field_name = row.get("field")
        if field_name not in BACKFILL_FIELDS:
            result_rows.append({**row, "action": "skipped", "apply_reason": "invalid_field"})
            continue
        if field_name in PUBLISH_FIELDS and field_name in set(article.manually_edited_fields or []):
            result_rows.append({**row, "action": "skipped", "apply_reason": "manual_field"})
            continue
        current_value = getattr(article, field_name, "") or ""
        if current_value != (row.get("before") or ""):
            result_rows.append({**row, "action": "stale", "apply_reason": "stale_field_value"})
            continue
        after = row.get("after") or ""
        if current_value == after:
            result_rows.append({**row, "action": "unchanged", "apply_reason": "already_applied"})
            continue
        setattr(article, field_name, after)
        article.save(update_fields=[field_name, "updated_at"])
        result_rows.append({**row, "action": "applied", "apply_reason": "updated"})
    return {"summary": _backfill_summary(result_rows), "rows": result_rows}


def merge_term_ids_from_rows(rows: Iterable[dict], *, include_candidates: bool = True) -> list[int]:
    term_ids: set[int] = set()
    for row in rows:
        action = row.get("action")
        if action == "applied" or (include_candidates and action == "candidate"):
            target_id = (row.get("target") or {}).get("term_id") or row.get("target_term_id")
            if target_id:
                term_ids.add(int(target_id))
    return sorted(term_ids)


def load_rows_from_json(path: str | Path) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get("rows")
        if isinstance(rows, list):
            return rows
    raise ValueError(f"Artifact does not contain rows: {path}")


def load_candidate_rows(path: str | Path) -> list[dict]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        return load_rows_from_json(source)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_json_artifact(path: str | Path, payload: dict) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def write_csv_artifact(path: str | Path, rows: list[dict], fieldnames: list[str]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            csv_row = {}
            for field in fieldnames:
                value = row.get(field, "")
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                csv_row[field] = value
            writer.writerow(csv_row)
    return output
