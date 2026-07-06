from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

import django

django.setup()

from django.db import transaction

from stable.models import SourceLanguage, TermAlias, TermAliasType, TermEntry, TermType
from stable.services.term_admin import (
    commit_term_import,
    preview_term_import,
    source_text_identity,
    split_aliases,
    sync_term_source_aliases,
    upsert_term_source_alias,
)


COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,4}\)\s*$")
YEAR_MARKER_RE = re.compile(
    r"\(\s*(?:(?:~|-)\s*)?\d{4}(?:\s*[,~\-]\s*(?:\d{2,4})?)*\s*\)"
    r"|\(\s*(?:Reg\.|Ex\.|Replaced)\s*\)",
    re.I,
)


class DryRunRollback(Exception):
    pass


def norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def clean_horse_source(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", norm_text(value)).strip()


def clean_year_markers(value: str) -> str:
    return re.sub(r"\s+", " ", YEAR_MARKER_RE.sub("", norm_text(value))).strip()


def split_after_year_markers(value: str) -> list[str]:
    value = norm_text(value)
    matches = list(YEAR_MARKER_RE.finditer(value))
    if not matches:
        cleaned = clean_year_markers(value)
        return [cleaned] if cleaned else []
    parts: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        part = clean_year_markers(value[start:end])
        if part:
            parts.append(part)
    return parts


def split_year_marked_pair(source: str, target: str) -> list[tuple[str, str]]:
    source = norm_text(source)
    target = norm_text(target)
    if not YEAR_MARKER_RE.search(source) and not YEAR_MARKER_RE.search(target):
        return [(source, target)]
    source_parts = split_after_year_markers(source)
    target_parts = split_after_year_markers(target)
    if len(source_parts) == len(target_parts) and source_parts:
        return [(s, t) for s, t in zip(source_parts, target_parts) if s and t]
    return [(clean_year_markers(source), clean_year_markers(target))]


def append_note(notes: str, addition: str) -> str:
    notes = norm_text(notes)
    return f"{notes}; {addition}" if notes and addition not in notes else (notes or addition)


def repair_horse_country_suffix() -> Counter:
    stats: Counter = Counter()
    terms = TermEntry.objects.filter(term_type=TermType.HORSE, source_language=SourceLanguage.ENGLISH)
    for term in terms.iterator():
        original = term.source_ja
        cleaned = clean_horse_source(original)
        if not cleaned or cleaned == original:
            continue
        duplicate = (
            TermEntry.objects.filter(
                term_type=term.term_type,
                source_language=term.source_language,
                source_ja__iexact=cleaned,
            )
            .exclude(pk=term.pk)
            .first()
        )
        if duplicate:
            term.is_active = False
            term.notes = append_note(term.notes, f"deactivated_dirty_country_suffix_duplicate={original}; clean_term_id={duplicate.pk}")
            term.save(update_fields=["is_active", "notes", "updated_at"])
            stats["horse_suffix_deactivated_duplicates"] += 1
            continue
        term.source_ja = cleaned
        term.aliases_ja = [alias for alias in split_aliases(term.aliases_ja) if source_text_identity(alias) != source_text_identity(original)]
        term.notes = append_note(term.notes, f"cleaned_country_suffix_from={original}")
        term.save(update_fields=["source_ja", "aliases_ja", "notes", "updated_at"])
        sync_term_source_aliases(term, term.source_language)
        stats["horse_suffix_cleaned"] += 1
    return stats


def repair_year_marked_races() -> Counter:
    stats: Counter = Counter()
    terms = list(TermEntry.objects.filter(term_type=TermType.RACE, source_language=SourceLanguage.ENGLISH))
    for term in terms:
        if not YEAR_MARKER_RE.search(term.source_ja or "") and not YEAR_MARKER_RE.search(term.target_zh or ""):
            continue
        pieces = split_year_marked_pair(term.source_ja, term.target_zh)
        if not pieces:
            continue
        first_source, first_target = pieces[0]
        if not first_source or not first_target:
            continue
        duplicate = (
            TermEntry.objects.filter(
                term_type=term.term_type,
                source_language=term.source_language,
                source_ja__iexact=first_source,
            )
            .exclude(pk=term.pk)
            .first()
        )
        if duplicate:
            term.is_active = False
            term.notes = append_note(term.notes, f"deactivated_dirty_year_marker_duplicate={term.source_ja}; clean_term_id={duplicate.pk}")
            term.save(update_fields=["is_active", "notes", "updated_at"])
            stats["race_year_deactivated_duplicates"] += 1
        else:
            original_source = term.source_ja
            original_target = term.target_zh
            term.source_ja = first_source
            term.target_zh = first_target
            term.aliases_ja = []
            term.notes = append_note(term.notes, f"cleaned_year_markers_from={original_source}=>{original_target}")
            term.save(update_fields=["source_ja", "target_zh", "aliases_ja", "notes", "updated_at"])
            sync_term_source_aliases(term, term.source_language)
            stats["race_year_cleaned_primary"] += 1
        for source_text, target_text in pieces[1:]:
            if not source_text or not target_text:
                continue
            existing = TermEntry.objects.filter(
                term_type=term.term_type,
                source_language=term.source_language,
                source_ja__iexact=source_text,
            ).first()
            if existing:
                stats["race_year_split_existing"] += 1
                continue
            created = TermEntry.objects.create(
                term_type=term.term_type,
                source_language=term.source_language,
                racing_region=term.racing_region,
                source_ja=source_text,
                target_zh=target_text,
                aliases_ja=[],
                aliases_zh=[],
                race_grade=term.race_grade,
                notes=append_note(term.notes, f"split_from_dirty_term_id={term.pk}"),
                is_active=term.is_active,
                priority=term.priority,
            )
            sync_term_source_aliases(created, created.source_language)
            stats["race_year_split_created"] += 1
    return stats


def read_alias_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def apply_alias_rows(path: Path) -> tuple[Counter, list[dict[str, str]]]:
    stats: Counter = Counter()
    failures: list[dict[str, str]] = []
    for row in read_alias_rows(path):
        term_type = row.get("term_type", "").strip()
        primary_language = row.get("primary_source_language", "").strip() or SourceLanguage.ENGLISH
        primary_source = row.get("primary_source_ja", "").strip()
        alias_language = row.get("alias_language", "").strip() or SourceLanguage.JAPANESE
        alias_text = row.get("alias_text", "").strip()
        if not term_type or not primary_source or not alias_text:
            failures.append({**row, "error": "missing required alias fields"})
            stats["alias_failed"] += 1
            continue
        term = (
            TermEntry.objects.filter(
                term_type=term_type,
                source_language=primary_language,
                source_ja__iexact=primary_source,
                is_active=True,
            )
            .order_by("-priority", "pk")
            .first()
        )
        if term is None:
            failures.append({**row, "error": "primary term not found"})
            stats["alias_failed"] += 1
            continue
        same_language_entry = (
            TermEntry.objects.filter(
                term_type=term_type,
                source_language=alias_language,
                source_ja__iexact=alias_text,
                is_active=True,
            )
            .exclude(pk=term.pk)
            .first()
        )
        if same_language_entry:
            if term_type != TermType.HORSE:
                stats["alias_skipped_existing_same_language_entry"] += 1
                continue
            if same_language_entry.target_zh == term.target_zh or "source_tier=community" in (same_language_entry.notes or ""):
                same_language_entry.is_active = False
                same_language_entry.notes = append_note(
                    same_language_entry.notes,
                    f"deactivated_after_alias_link_to_term_id={term.pk}",
                )
                same_language_entry.save(update_fields=["is_active", "notes", "updated_at"])
                stats["alias_deactivated_duplicate_ja_entries"] += 1
            else:
                stats["alias_skipped_conflicting_same_language_entry"] += 1
                continue
        existing_alias = (
            TermAlias.objects.filter(
                source_language=alias_language,
                text__iexact=alias_text,
                is_active=True,
            )
            .exclude(term=term)
            .first()
        )
        if existing_alias:
            stats["alias_skipped_existing_alias_owner"] += 1
            continue
        upsert_term_source_alias(
            term,
            source_language=alias_language,
            text=alias_text,
            alias_type=TermAliasType.ALIAS,
            is_active=term.is_active,
        )
        stats["alias_upserted"] += 1
    return stats, failures


def verify_quality() -> dict[str, int]:
    active_terms = TermEntry.objects.filter(is_active=True)
    horse_suffix = sum(1 for term in active_terms.filter(term_type=TermType.HORSE, source_language=SourceLanguage.ENGLISH) if COUNTRY_SUFFIX_RE.search(term.source_ja or ""))
    year_markers = sum(
        1
        for term in active_terms.filter(term_type=TermType.RACE, source_language=SourceLanguage.ENGLISH)
        if YEAR_MARKER_RE.search(term.source_ja or "") or YEAR_MARKER_RE.search(term.target_zh or "")
    )
    return {
        "active_horse_country_suffix_terms": horse_suffix,
        "active_race_year_marker_terms": year_markers,
        "term_entries": TermEntry.objects.count(),
        "term_aliases": TermAlias.objects.count(),
    }


def run(args: argparse.Namespace) -> dict:
    csv_path = Path(args.csv)
    alias_path = Path(args.aliases)
    report: dict = {"dry_run": args.dry_run}
    try:
        with transaction.atomic():
            repair_stats = repair_horse_country_suffix() + repair_year_marked_races()
            preview = preview_term_import(csv_text=csv_path.read_text(encoding="utf-8-sig"), import_mode="upsert")
            report["preview_summary"] = preview["summary"]
            if preview["summary"]["error_count"]:
                report["preview_errors"] = [
                    {"line_no": row["line_no"], "errors": row["errors"]}
                    for row in preview["rows"]
                    if row["errors"]
                ][:50]
                raise RuntimeError("term import preview failed")
            import_result = commit_term_import(preview["rows"], "upsert")
            alias_stats, alias_failures = apply_alias_rows(alias_path)
            report.update(
                {
                    "repair_stats": dict(repair_stats),
                    "import_result": import_result,
                    "alias_stats": dict(alias_stats),
                    "alias_failures": alias_failures[:50],
                    "quality": verify_quality(),
                }
            )
            if alias_failures:
                raise RuntimeError(json.dumps({"error": "alias application had failures", **report}, ensure_ascii=False))
            if args.dry_run:
                raise DryRunRollback()
    except DryRunRollback:
        report["rolled_back"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--aliases", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
