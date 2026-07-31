#!/usr/bin/env python3
"""Import graded-race horses from theracingapi.* tables into canonical HorseProfile + TermEntry.

Reads the dataset produced by fetch_uk_graded_race_horses_pro.py (already loaded into the
production PostgreSQL `theracingapi` schema) and creates:

- One TermEntry per horse
- One HorseProfile per TermEntry, linked to the term
- HorseRaceRecord rows for every career start

The command is idempotent: re-running it updates existing profiles/records by horse_id.
Processing is batched to keep memory usage low (the result table can contain 50k+ rows
with large JSON payloads).
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
    HorseRaceDatePrecision,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRaceStartStatus,
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

BATCH_SIZE = 500


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


def _load_horse_profile_batch(offset: int, limit: int) -> list[dict[str, Any]]:
    """Load a batch of horse profiles."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT horse_id, name, sex, sire, dam, damsire
            FROM theracingapi.horse_profile
            ORDER BY horse_id
            LIMIT %s OFFSET %s
            """,
            [limit, offset],
        )
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _derive_region(results: list[dict[str, Any]]) -> str:
    """Derive a horse's racing region from its career results (most common region)."""
    if not results:
        return RacingRegion.OTHER
    counts: dict[str, int] = defaultdict(int)
    for rec in results:
        counts[(rec.get("region") or "").strip().lower()] += 1
    # Prefer any non-empty region; fall back to OTHER only when everything is blank.
    best = max(counts, key=lambda k: (counts[k], k != ""))
    return _map_region(best) if best else RacingRegion.OTHER


def _load_results_for_horses(horse_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Load results for a specific list of horse IDs (no raw_payload to save memory)."""
    if not horse_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT horse_id, race_id, race_date, region, course, race_name, pattern, position
            FROM theracingapi.horse_result
            WHERE horse_id = ANY(%s)
            ORDER BY horse_id, race_date
            """,
            [horse_ids],
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
        parser.add_argument("--limit", type=int, help="Limit total number of horses to process.")
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Horses per batch.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        skip_records = options["skip_records"]
        limit = options.get("limit")
        batch_size = options["batch_size"]

        # Pre-load existing TermEntry keys to avoid collisions when generating
        # disambiguated source_ja values.
        used_term_keys: set[tuple[str, str]] = {
            (t.source_ja, t.racing_region)
            for t in TermEntry.objects.filter(term_type=TermType.HORSE, is_active=True)
        }

        term_created = term_existing = profile_created = profile_existing = record_created = 0
        total_horses_processed = 0
        offset = 0

        while True:
            raw_horses = _load_horse_profile_batch(offset, batch_size)
            if not raw_horses:
                break

            if limit and total_horses_processed + len(raw_horses) > limit:
                raw_horses = raw_horses[: limit - total_horses_processed]

            total_horses_processed += len(raw_horses)
            horse_ids = [raw["horse_id"] for raw in raw_horses]

            results_by_horse: dict[str, list[dict[str, Any]]] = {}
            if not dry_run and not skip_records:
                results_by_horse = _load_results_for_horses(horse_ids)

            # Idempotency: fetch existing profiles for this batch.
            existing_profiles: dict[str, HorseProfile] = {
                profile.source_refs.get("theracingapi_horse_id"): profile
                for profile in HorseProfile.objects.filter(
                    source_refs__has_key="theracingapi_horse_id",
                    source_refs__theracingapi_horse_id__in=horse_ids,
                )
                if profile.source_refs.get("theracingapi_horse_id")
            }

            with transaction.atomic():
                for raw in raw_horses:
                    horse_id = raw["horse_id"]
                    full_name = raw["name"] or ""
                    country = _parse_country(full_name)
                    base_name = _strip_country(full_name)
                    horse_results = results_by_horse.get(horse_id, [])
                    racing_region = _derive_region(horse_results)

                    # 2. HorseProfile (look up first to decide whether to create a new TermEntry)
                    profile = existing_profiles.get(horse_id)
                    if profile:
                        # Re-use the existing TermEntry for this horse.
                        term = profile.primary_term
                        term_existing += 1
                    else:
                        # Create a dedicated TermEntry per horse.  Prefer the clean base
                        # name; only add a disambiguating suffix when the same base name
                        # already exists for this region.
                        candidates = [base_name]
                        if country:
                            candidates.append(f"{base_name} ({country})")
                        candidates.append(f"{base_name} ({horse_id})")

                        source_ja = base_name
                        for candidate in candidates:
                            if (candidate, racing_region) not in used_term_keys:
                                source_ja = candidate
                                break

                        term = TermEntry.objects.create(
                            term_type=TermType.HORSE,
                            source_language=SourceLanguage.ENGLISH,
                            racing_region=racing_region,
                            source_ja=source_ja,
                            target_zh="",
                            translation_status=TermTranslationStatus.PENDING,
                            is_active=True,
                        )
                        used_term_keys.add((source_ja, racing_region))
                        term_created += 1

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
                        "source_refs": {"theracingapi_horse_id": horse_id},
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
                        elif isinstance(race_date, datetime):
                            race_date = race_date.date()
                        position = rec.get("position") or ""
                        grade_text = rec.get("pattern") or ""
                        result_status = _result_status(position)

                        new_records.append(
                            HorseRaceRecord(
                                horse_profile=profile,
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
                            )
                        )
                    if new_records:
                        HorseRaceRecord.objects.bulk_create(new_records, ignore_conflicts=True)
                        record_created += len(new_records)

                if dry_run:
                    transaction.set_rollback(True)

            self.stdout.write(
                f"[batch] offset={offset} processed={total_horses_processed} "
                f"terms_created={term_created} terms_existing={term_existing} "
                f"profiles_created={profile_created} profiles_existing={profile_existing} "
                f"records_created={record_created}"
            )

            if limit and total_horses_processed >= limit:
                break
            offset += batch_size

        self.stdout.write(
            self.style.SUCCESS(
                f"terms_created={term_created} terms_existing={term_existing} "
                f"profiles_created={profile_created} profiles_existing={profile_existing} "
                f"records_created={record_created}"
            )
        )
