from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import dateparse, timezone

from stable.models import (
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceResult,
    ExternalImportStatus,
    RacingRegion,
    SourceLanguage,
)


class HKJCImportError(Exception):
    pass


@dataclass(frozen=True)
class HKJCImportOptions:
    dry_run: bool = True
    allow_network: bool = False
    request_interval_seconds: float = 8
    max_races: int = 20
    max_horses: int = 80

    @classmethod
    def from_settings(cls, **overrides: Any) -> "HKJCImportOptions":
        values = {
            "request_interval_seconds": getattr(settings, "HKJC_IMPORT_REQUEST_INTERVAL_SECONDS", 8),
            "max_races": getattr(settings, "HKJC_IMPORT_MAX_RACES_PER_RUN", 20),
            "max_horses": getattr(settings, "HKJC_IMPORT_MAX_HORSES_PER_RUN", 80),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def _horse_identity(payload: dict) -> str:
    horse_id = _string(payload.get("horse_id") or payload.get("horseCode") or payload.get("id"))
    if horse_id:
        return f"id:{horse_id}"
    for field_name in (
        "horse_name_en",
        "english_name",
        "horse_name_zh_hant",
        "chinese_name",
        "horse_name",
        "name",
    ):
        normalized = _normalize_name(_string(payload.get(field_name)))
        if normalized:
            return f"name:{normalized.casefold()}"
    return ""


def _parse_date(value: Any):
    raw = _string(value)
    if not raw:
        return None
    return dateparse.parse_date(raw.replace("/", "-"))


def _parse_datetime(value: Any):
    raw = _string(value)
    if not raw:
        return None
    parsed = dateparse.parse_datetime(raw)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _load_json_file(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise HKJCImportError("HKJC payload file must contain a JSON object")
    return payload


class HKJCExternalDataImporter:
    source = ExternalDataSource.HKJC
    racing_region = RacingRegion.HONG_KONG
    source_language = SourceLanguage.ENGLISH

    def __init__(self, options: HKJCImportOptions | None = None):
        self.options = options or HKJCImportOptions.from_settings()

    def import_race_date(self, race_date: str, *, payload_file: str = "") -> dict:
        payload = _load_json_file(payload_file) if payload_file else {"races": [], "race_date": race_date}
        return self._import_payload("race_date", race_date, payload, has_payload_file=bool(payload_file))

    def import_race(self, race_id: str, *, payload_file: str = "") -> dict:
        payload = _load_json_file(payload_file) if payload_file else {"race": {"race_id": race_id}}
        return self._import_payload("race", race_id, payload, has_payload_file=bool(payload_file))

    def import_horse(self, horse_id: str, *, payload_file: str = "") -> dict:
        payload = _load_json_file(payload_file) if payload_file else {"horses": [{"horse_id": horse_id}]}
        return self._import_payload("horse", horse_id, payload, has_payload_file=bool(payload_file))

    def _import_payload(self, target_type: str, target_id: str, payload: dict, *, has_payload_file: bool) -> dict:
        stats = self._payload_stats(payload)
        if self.options.dry_run:
            return {
                "source": self.source,
                "target_type": target_type,
                "target_id": target_id,
                "dry_run": True,
                "coverage_stats": stats,
                "would_write_formal_tables": False,
            }
        if not has_payload_file:
            raise HKJCImportError("HKJC commit import requires --payload-file until network import is implemented")
        self._validate_payload_limits(stats)
        with transaction.atomic():
            lock, _ = ExternalDataImportLock.objects.select_for_update().get_or_create(
                source=self.source,
                defaults={"racing_region": self.racing_region},
            )
            if lock.locked_by_run and lock.locked_by_run.status == ExternalImportStatus.STARTED:
                raise HKJCImportError(f"{self.source} import is already running")
            run = ExternalDataImportRun.objects.create(
                source=self.source,
                racing_region=self.racing_region,
                source_language=self.source_language,
                target_type=target_type,
                parameters={"target_id": target_id},
                dry_run=False,
                status=ExternalImportStatus.STARTED,
            )
            lock.locked_by_run = run
            lock.acquired_at = timezone.now()
            lock.racing_region = self.racing_region
            lock.save(update_fields=["locked_by_run", "acquired_at", "racing_region", "updated_at"])
            try:
                written = self._upsert_payload(payload)
                run.success_count = written
                run.coverage_stats = stats
                run.status = ExternalImportStatus.SUCCESS
                run.finished_at = timezone.now()
                run.save()
            finally:
                ExternalDataImportLock.objects.filter(source=self.source, locked_by_run=run).update(
                    locked_by_run=None,
                    acquired_at=None,
                )
        return {
            "run_id": run.id,
            "source": self.source,
            "target_type": target_type,
            "target_id": target_id,
            "dry_run": False,
            "success_count": run.success_count,
            "coverage_stats": stats,
        }

    def _payload_stats(self, payload: dict) -> dict:
        races = self._races(payload)
        horses = self._horses(payload)
        entries = 0
        results = 0
        horse_identities: set[str] = set()
        for horse in horses:
            identity = _horse_identity(horse)
            if identity:
                horse_identities.add(identity)
        for race in races:
            race_entries = [item for item in race.get("entries") or [] if isinstance(item, dict)]
            race_results = [item for item in race.get("results") or [] if isinstance(item, dict)]
            entries += len(race_entries)
            results += len(race_results)
            for horse_payload in [*race_entries, *race_results]:
                identity = _horse_identity(horse_payload)
                if identity:
                    horse_identities.add(identity)
        return {"races": len(races), "entries": entries, "results": results, "horses": len(horse_identities)}

    def _validate_payload_limits(self, stats: dict) -> None:
        if stats["races"] > self.options.max_races:
            raise HKJCImportError(f"HKJC payload has {stats['races']} races; max_races is {self.options.max_races}")
        if stats["horses"] > self.options.max_horses:
            raise HKJCImportError(f"HKJC payload has {stats['horses']} horses; max_horses is {self.options.max_horses}")

    def _races(self, payload: dict) -> list[dict]:
        if isinstance(payload.get("races"), list):
            return [item for item in payload["races"] if isinstance(item, dict)]
        race = payload.get("race")
        return [race] if isinstance(race, dict) else []

    def _horses(self, payload: dict) -> list[dict]:
        if isinstance(payload.get("horses"), list):
            return [item for item in payload["horses"] if isinstance(item, dict)]
        horse = payload.get("horse")
        return [horse] if isinstance(horse, dict) else []

    def _upsert_payload(self, payload: dict) -> int:
        written = 0
        for race_payload in self._races(payload):
            race = self._upsert_race(race_payload)
            written += 1
            for entry_payload in race_payload.get("entries") or []:
                if isinstance(entry_payload, dict):
                    self._upsert_entry(race, entry_payload)
                    written += 1
                    self._upsert_alias_from_payload(entry_payload)
            for result_payload in race_payload.get("results") or []:
                if isinstance(result_payload, dict):
                    self._upsert_result(race, result_payload)
                    written += 1
                    self._upsert_alias_from_payload(result_payload)
        for horse_payload in self._horses(payload):
            self._upsert_horse(horse_payload)
            written += 1
            self._upsert_alias_from_payload(horse_payload)
        return written

    def _upsert_race(self, payload: dict) -> ExternalRace:
        race_id = _string(payload.get("race_id") or payload.get("raceNo") or payload.get("id"))
        if not race_id:
            raise HKJCImportError("HKJC race payload missing race_id")
        scheduled_start_at = _parse_datetime(payload.get("scheduled_start_at") or payload.get("start_time"))
        race, _ = ExternalRace.objects.update_or_create(
            source=self.source,
            race_id=race_id,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race_name": _string(payload.get("race_name") or payload.get("name")),
                "race_date": _parse_date(payload.get("race_date") or payload.get("date")),
                "course": _string(payload.get("course")),
                "venue": _string(payload.get("venue") or payload.get("racecourse")),
                "race_number": _string(payload.get("race_number") or payload.get("raceNo")),
                "race_grade": _string(payload.get("grade")),
                "race_class": _string(payload.get("class")),
                "surface": _string(payload.get("surface")),
                "track": _string(payload.get("track")),
                "distance": _string(payload.get("distance")),
                "weather": _string(payload.get("weather")),
                "going": _string(payload.get("going") or payload.get("track_condition")),
                "prize_money": _string(payload.get("prize_money") or payload.get("stakes")),
                "scheduled_start_at": scheduled_start_at,
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )
        return race

    def _upsert_entry(self, race: ExternalRace, payload: dict) -> None:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode"))
        entry_key = _string(payload.get("entry_key") or payload.get("horse_number") or horse_id or payload.get("horse_name"))
        ExternalRaceEntry.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            entry_key=entry_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": _string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name")),
                "normalized_horse_name": _normalize_name(_string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name"))),
                "horse_number": _string(payload.get("horse_number") or payload.get("no")),
                "frame_number": _string(payload.get("frame_number")),
                "barrier": _string(payload.get("barrier") or payload.get("draw")),
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
                "carried_weight": _string(payload.get("weight") or payload.get("carried_weight")),
                "equipment": _string(payload.get("equipment")),
                "rating": _string(payload.get("rating")),
                "owner_name": _string(payload.get("owner")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )

    def _upsert_result(self, race: ExternalRace, payload: dict) -> None:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode"))
        result_key = _string(payload.get("result_key") or payload.get("finish_position") or horse_id or payload.get("horse_name"))
        ExternalRaceResult.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            result_key=result_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": _string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name")),
                "normalized_horse_name": _normalize_name(_string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name"))),
                "horse_number": _string(payload.get("horse_number") or payload.get("no")),
                "finish_position": _string(payload.get("finish_position") or payload.get("position")),
                "finish_time": _string(payload.get("finish_time") or payload.get("time")),
                "margin": _string(payload.get("margin")),
                "odds_value": _string(payload.get("odds")),
                "running_position": _string(payload.get("running_position")),
                "sectional_time": _string(payload.get("sectional_time")),
                "barrier": _string(payload.get("barrier") or payload.get("draw")),
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )

    def _upsert_horse(self, payload: dict) -> ExternalHorse:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode") or payload.get("id"))
        if not horse_id:
            raise HKJCImportError("HKJC horse payload missing horse_id")
        horse_name_en = _string(payload.get("horse_name_en") or payload.get("english_name") or payload.get("name"))
        horse_name_zh_hant = _string(payload.get("horse_name_zh_hant") or payload.get("chinese_name"))
        horse_name = horse_name_en or horse_name_zh_hant
        horse, _ = ExternalHorse.objects.update_or_create(
            source=self.source,
            horse_id=horse_id,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "horse_name": horse_name,
                "horse_name_en": horse_name_en,
                "horse_name_zh_hant": horse_name_zh_hant,
                "normalized_horse_name": _normalize_name(horse_name),
                "sex": _string(payload.get("sex")),
                "birth_date": _parse_date(payload.get("birth_date") or payload.get("date_of_birth")),
                "country": _string(payload.get("country")),
                "color": _string(payload.get("color") or payload.get("colour")),
                "father_name": _string(payload.get("sire") or payload.get("father_name")),
                "mother_name": _string(payload.get("dam") or payload.get("mother_name")),
                "owner_name": _string(payload.get("owner")),
                "trainer_name": _string(payload.get("trainer")),
                "record_summary": _string(payload.get("record_summary") or payload.get("career_record")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )
        return horse

    def _upsert_alias_from_payload(self, payload: dict) -> None:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode") or payload.get("id"))
        if not horse_id:
            return
        horse = ExternalHorse.objects.filter(source=self.source, horse_id=horse_id).first()
        names = [
            (_string(payload.get("horse_name_en") or payload.get("english_name") or payload.get("horse_name") or payload.get("name")), SourceLanguage.ENGLISH),
            (_string(payload.get("horse_name_zh_hant") or payload.get("chinese_name")), SourceLanguage.CHINESE_TRADITIONAL),
        ]
        for name, language in names:
            if not name:
                continue
            ExternalHorseAlias.objects.update_or_create(
                source=self.source,
                external_horse_id=horse_id,
                normalized_name=_normalize_name(name),
                defaults={
                    "horse": horse,
                    "racing_region": self.racing_region,
                    "source_language": language,
                    "name_ja": name,
                    "name_en": name if language == SourceLanguage.ENGLISH else "",
                    "name_zh_hant": name if language == SourceLanguage.CHINESE_TRADITIONAL else "",
                    "confidence": 100,
                    "alias_source": "hkjc",
                    "last_seen_at": timezone.now(),
                },
            )

    def lookup_alias(self, name: str) -> list[ExternalHorseAlias]:
        normalized = _normalize_name(name)
        return list(
            ExternalHorseAlias.objects.filter(source=self.source, normalized_name=normalized)
            .order_by("-confidence", "-last_seen_at", "external_horse_id")
        )
