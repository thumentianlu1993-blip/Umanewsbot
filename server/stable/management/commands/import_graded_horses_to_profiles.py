#!/usr/bin/env python3
"""Import graded-race horses from theracingapi.* tables into canonical HorseProfile + TermEntry.

Reads the dataset produced by fetch_uk_graded_race_horses_pro.py (already loaded into the
production PostgreSQL `theracingapi` schema) and creates:

- One TermEntry per horse
- One HorseProfile per TermEntry, linked to the term
- HorseRaceRecord rows for every career start

The command is idempotent: re-running it updates existing profiles/records by horse_id.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from stable.models import (
    HorseProfile,
    HorseProfileCompleteness,
    HorseProfileStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRaceStartStatus,
    RaceEvent,
    RaceGrade,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermTranslationStatus,
    TermType,
)


# Map The Racing API region codes to the project's RacingRegion choices.
REGION_MAP: dict[str, str] = {
    "gb": RacingRegion.UNITED_KINGDOM,
    "ire": RacingRegion.UNITED_KINGDOM,
    "fr": RacingRegion.FRANCE,
    "usa": RacingRegion.UNITED_STATES,
    "ger": RacingRegion.OTHER,
    "aus": RacingRegion.OTHER,
    "uae": RacingRegion.OTHER,
    "ksa": RacingRegion.OTHER,
    "qa": RacingRegion.OTHER,
    "bhr": RacingRegion.OTHER,
}

# Country code parsed from names like "Qirat (GB)".
COUNTRY_RE = re.compile(r"\(([A-Z]{2,3})\)$")


def _parse_country(horse_name: str) -> str:
    match = COUNTRY_RE.search(horse_name)
    return match.group(1) if match else ""


def _strip_country(horse_name: str) -> str:
    return COUNTRY_RE.sub("", horse_name).strip()


def _map_sex(sex: str) -> str:
    return sex.strip() if sex else ""


def _map_region(region: str) -> str:
    return REGION_MAP.get(region.strip().lower(), RacingRegion.OTHER)


def _result_status(position: str) -> str:
    """Derive HorseRaceResultStatus from finish position string."""
    pos = position.strip() if position else ""
    if not pos:
        return HorseRaceResultStatus.UNKNOWN
    # Normalize common non-numeric codes.
    if pos.upper() in {"F", "PU", "UR", "BD", "SU", "R", "DSQ", "RO"}:
        return HorseRaceResultStatus.DID_NOT_FINISH
    if pos.upper() in {"SCR", "NS", "W"}:
        return HorseRaceResultStatus.SCRATCHED
    # Extract leading digits.
    digits = ""
    for ch in pos:
        if ch.isdigit():
            digits += ch
        else:
            break
    if not digits:
        return HorseRaceResultStatus.UNKNOWN
    if digits == "1":
        return HorseRaceResultStatus.WON
    if digits in {"2", "3"}:
        return HorseRaceResultStatus.PLACED
    return HorseRaceResultStatus.UNPLACED


def _normalized_grade(grade_text: str) -> str:
    """Map API grade text to RaceGrade choices."""
    g = (grade_text or "").strip().upper()
    if "G1" in g or "GROUP 1" in g or "GRADE 1" in g:
        return RaceGrade.G1
    if "G2" in g or "GROUP 2" in g or "GRADE 2" in g:
        return RaceGrade.G2
    if "G3" in g or "GROUP 3" in g or "GRADE 3" in g:
        return RaceGrade.G3
    return ""


def _is_major_win(grade_text: str, position: str) -> bool:
    return _normalized_grade(grade_text) == RaceGrade.G1 and _result_status(position) == HorseRaceResultStatus.WON


def _load_horse_profiles() -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT horse_id, name, sex, sire, dam, damsire, raw_payload
            FROM theracingapi.horse_profile
            ORDER BY horse_id
            """
        )
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _load_horse_results() -> dict[str, list[dict[str, Any]]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT horse_id, race_id, race_date, region, course, race_name, pattern, position, raw_payload
            FROM theracingapi.horse_result
            ORDER BY horse_id, race_date
            """
        )
        columns = [col[0] for col in cursor.description]
        results: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in cursor.fetchall():
            rec = dict(zip(columns, row))
            results[rec["horse_id"]].append(rec)
        return results


class Command(BaseCommand):
    help = "Import theracingapi graded-race horses into canonical HorseProfile + TermEntry + HorseRaceRecord."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB.")
        parser.add_argument("--skip-records", action="store_true", help="Skip creating HorseRaceRecord rows.")
        parser.add_argument("--limit", type=int, help="Limit number of horses to process.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        skip_records = options["skip_records"]
        limit = options.get("limit")

        self.stdout.write("[info] loading horse profiles from theracingapi.horse_profile ...")
        raw_horses = _load_horse_profiles()
        if limit:
            raw_horses = raw_horses[:limit]
        self.stdout.write(f"[info] {len(raw_horses)} horses loaded")

        if not dry_run:
            self.stdout.write("[info] loading career results from theracingapi.horse_result ...")
            results_by_horse = _load_horse_results()
            self.stdout.write(f"[info] {sum(len(v) for v in results_by_horse.values())} results loaded")
        else:
            results_by_horse = {}

        term_created = term_existing = profile_created = profile_existing = record_created = 0

        # Idempotency: build map of existing profiles keyed by theracingapi horse_id stored in source_refs.
        existing_profiles: dict[str, HorseProfile] = {}
        for profile in HorseProfile.objects.filter(source_refs__has_key="theracingapi_horse_id"):
            horse_id = profile.source_refs.get("theracingapi_horse_id")
            if horse_id:
                existing_profiles[horse_id] = profile

        # Existing TermEntry lookup by source_ja + term_type.
        existing_terms: dict[tuple[str, str], TermEntry] = {
            (t.source_ja, t.racing_region): t
            for t in TermEntry.objects.filter(term_type=TermType.HORSE, is_active=True)
        }

        with transaction.atomic():
            for raw in raw_horses:
                horse_id = raw["horse_id"]
                full_name = raw["name"] or ""
                country = _parse_country(full_name)
                base_name = _strip_country(full_name)

                # Load raw payload to get the original region if available.
                payload = raw.get("raw_payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                api_region = payload.get("region", "")
                racing_region = _map_region(api_region)

                # 1. TermEntry
                term_key = (base_name, racing_region)
                term = existing_terms.get(term_key)
                if not term:
                    term = TermEntry.objects.create(
                        term_type=TermType.HORSE,
                        source_language=SourceLanguage.ENGLISH,
                        racing_region=racing_region,
                        source_ja=base_name,
                        target_zh="",
                        translation_status=TermTranslationStatus.PENDING,
                        is_active=True,
                    )
                    existing_terms[term_key] = term
                    term_created += 1
                else:
                    term_existing += 1

                # 2. HorseProfile
                profile = existing_profiles.get(horse_id)
                profile_defaults = {
                    "primary_term": term,
                    "english_name": full_name,
                    "original_name": full_name,
                    "sex": _map_sex(raw.get("sex") or ""),
                    "country": country,
                    "sire_text": raw.get("sire") or "",
                    "dam_text": raw.get("dam") or "",
                    "dam_sire_text": raw.get("damsire") or "",
                    "racing_region": racing_region,
                    "review_status": HorseProfileStatus.PUBLISHED,
                    "completeness_status": HorseProfileCompleteness.PROFILE_ONLY,
                    "published_at": timezone.now(),
                    "source_refs": {"theracingapi_horse_id": horse_id, "theracingapi_payload": payload},
                }
                if not profile:
                    profile = HorseProfile.objects.create(**profile_defaults)
                    existing_profiles[horse_id] = profile
                    profile_created += 1
                else:
                    for key, value in profile_defaults.items():
                        setattr(profile, key, value)
                    profile.save(update_fields=list(profile_defaults.keys()))
                    profile_existing += 1

                if dry_run or skip_records:
                    continue

                # 3. HorseRaceRecord
                existing_records = {
                    r.source_refs.get("theracingapi_race_id"): r
                    for r in profile.race_records.filter(source_refs__has_key="theracingapi_race_id")
                }
                new_records = []
                for rec in results_by_horse.get(horse_id, []):
                    race_id = rec.get("race_id") or ""
                    if race_id in existing_records:
                        continue
                    race_date = rec.get("race_date")
                    if isinstance(race_date, str):
                        try:
                            race_date = datetime.strptime(race_date, "%Y-%m-%d").date()
                        except ValueError:
                            race_date = None
                    position = rec.get("position") or ""
                    grade_text = rec.get("pattern") or ""
                    result_status = _result_status(position)

                    # Try to link to an existing RaceEvent by race_id.
                    event = None
                    if race_id:
                        try:
                            event = RaceEvent.objects.get(external_race_id=race_id)
                        except RaceEvent.DoesNotExist:
                            event = None

                    raw_payload = rec.get("raw_payload") or {}
                    if isinstance(raw_payload, str):
                        try:
                            raw_payload = json.loads(raw_payload)
                        except Exception:
                            raw_payload = {}

                    new_records.append(
                        HorseRaceRecord(
                            horse_profile=profile,
                            event=event,
                            race_name=rec.get("race_name") or "",
                            race_year=race_date.year if race_date else None,
                            race_date=race_date,
                            race_date_precision=HorseRaceDatePrecision.EXACT if race_date else HorseRaceDatePrecision.UNKNOWN,
                            race_region=_map_region(rec.get("region") or ""),
                            grade_text=grade_text,
                            normalized_grade=_normalized_grade(grade_text),
                            racecourse=rec.get("course") or "",
                            finish_position=position,
                            result_status=result_status,
                            start_status=HorseRaceStartStatus.STARTED,
                            is_major_win=_is_major_win(grade_text, position),
                            source_name="The Racing API",
                            source_refs={"theracingapi_race_id": race_id},
                            raw_payload=raw_payload,
                        )
                    )
                if new_records:
                    HorseRaceRecord.objects.bulk_create(new_records, ignore_conflicts=True)
                    record_created += len(new_records)

            if dry_run:
                raise transaction.Rollback()

        self.stdout.write(
            self.style.SUCCESS(
                f"terms_created={term_created} terms_existing={term_existing} "
                f"profiles_created={profile_created} profiles_existing={profile_existing} "
                f"records_created={record_created}"
            )
        )
