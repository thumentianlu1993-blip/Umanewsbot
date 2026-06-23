from __future__ import annotations

import hashlib
import json
import random
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable.models import (
    ExternalDataImportError,
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalHorseHistory,
    ExternalImportStatus,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceOdds,
    ExternalRaceResult,
)


class ExternalHorseDataError(Exception):
    pass


class ExternalHorseDataDependencyError(ExternalHorseDataError):
    pass


class ExternalHorseDataNetworkDisabled(ExternalHorseDataError):
    pass


class ExternalHorseDataAlreadyRunning(ExternalHorseDataError):
    pass


@dataclass(frozen=True)
class ImportOptions:
    source: str = ExternalDataSource.NETKEIBA
    dry_run: bool = False
    allow_network: bool = False
    lookback_months: int = 24
    request_interval_seconds: float = 5
    jitter_seconds: float = 2
    max_races: int = 30
    max_horses: int = 100
    fetch_odds: bool = False
    fetch_horse_detail: bool = True

    @classmethod
    def from_settings(cls, **overrides: Any) -> "ImportOptions":
        values = {
            "allow_network": getattr(settings, "EXTERNAL_HORSE_DATA_ALLOW_NETWORK", False),
            "lookback_months": getattr(settings, "EXTERNAL_HORSE_DATA_LOOKBACK_MONTHS", 24),
            "request_interval_seconds": getattr(settings, "EXTERNAL_HORSE_DATA_REQUEST_INTERVAL_SECONDS", 5),
            "jitter_seconds": getattr(settings, "EXTERNAL_HORSE_DATA_JITTER_SECONDS", 2),
            "max_races": getattr(settings, "EXTERNAL_HORSE_DATA_MAX_RACES_PER_RUN", 30),
            "max_horses": getattr(settings, "EXTERNAL_HORSE_DATA_MAX_HORSES_PER_RUN", 100),
            "fetch_odds": getattr(settings, "EXTERNAL_HORSE_DATA_FETCH_ODDS", False),
            "fetch_horse_detail": getattr(settings, "EXTERNAL_HORSE_DATA_FETCH_HORSE_DETAIL", True),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)


def ensure_keibascraper_available() -> str:
    try:
        import keibascraper  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on runtime environment
        raise ExternalHorseDataDependencyError(f"keibascraper import failed: {exc}") from exc
    return getattr(keibascraper, "__version__", "unknown")


def normalize_horse_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict())
        except Exception:
            pass
    return str(value)


def _as_payload(value: Any) -> Any:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        try:
            return _json_safe(value.to_dict("records"))
        except TypeError:
            return _json_safe(value.to_dict())
    return _json_safe(value)


def _rows(value: Any) -> list[dict[str, Any]]:
    payload = _as_payload(value)
    if isinstance(payload, list):
        return [row if isinstance(row, dict) else {"value": row} for row in payload]
    if isinstance(payload, dict):
        if payload and all(isinstance(item, list) for item in payload.values()):
            keys = list(payload.keys())
            length = max(len(payload[key]) for key in keys)
            return [{key: payload[key][idx] if idx < len(payload[key]) else None for key in keys} for idx in range(length)]
        return [payload]
    return [{"value": payload}]


def _first(row: dict[str, Any], keys: Iterable[str]) -> str:
    normalized = {unicodedata.normalize("NFKC", str(key)).lower(): value for key, value in row.items()}
    for key in keys:
        candidates = {key, key.lower(), unicodedata.normalize("NFKC", key).lower()}
        for candidate in candidates:
            if candidate in normalized and _string(normalized[candidate]):
                return _string(normalized[candidate])
    return ""


def _parse_date(value: Any) -> date | None:
    raw = _string(value)
    if not raw:
        return None
    raw = raw.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return None


def _stable_key(*parts: Any) -> str:
    raw = "|".join(_string(part) for part in parts if _string(part))
    if raw:
        return raw[:128]
    digest = hashlib.sha1(json.dumps(_json_safe(parts), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return digest[:32]


class KeibaScraperAdapter:
    def __init__(self, options: ImportOptions):
        self.options = options
        self._last_request_at: float | None = None

    def _guard_network(self) -> None:
        if not getattr(settings, "EXTERNAL_HORSE_DATA_IMPORT_ENABLED", False):
            raise ExternalHorseDataNetworkDisabled("external horse data import is disabled")
        if not self.options.allow_network:
            raise ExternalHorseDataNetworkDisabled("external horse data network access is disabled")

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            wait_seconds = max(0.0, float(self.options.request_interval_seconds) - elapsed)
            if self.options.jitter_seconds > 0:
                wait_seconds += random.uniform(0, float(self.options.jitter_seconds))
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        self._last_request_at = time.monotonic()

    def _keibascraper(self):
        self._guard_network()
        ensure_keibascraper_available()
        import keibascraper  # type: ignore

        return keibascraper

    def race_list(self, year: int, month: int) -> list[str]:
        self._throttle()
        race_ids = self._keibascraper().race_list(year, month)
        return [_string(race_id) for race_id in race_ids if _string(race_id)]

    def load(self, data_type: str, external_id: str):
        self._throttle()
        return self._keibascraper().load(data_type, external_id)

    def fetch_race(self, race_id: str, *, fetch_odds: bool = False) -> dict[str, Any]:
        race_payload, entry_payload = self.load("entry", race_id)
        result_race_payload, result_payload = self.load("result", race_id)
        odds_payload = []
        if fetch_odds:
            odds_payload = self.load("odds", race_id)
        return {
            "race": _as_payload(race_payload) or _as_payload(result_race_payload),
            "entry": _rows(entry_payload),
            "result": _rows(result_payload),
            "odds": _rows(odds_payload) if fetch_odds else [],
            "raw": {
                "entry": _as_payload(entry_payload),
                "result": _as_payload(result_payload),
                "odds": _as_payload(odds_payload) if fetch_odds else [],
            },
        }

    def fetch_horse(self, horse_id: str) -> dict[str, Any]:
        horse_payload, history_payload = self.load("horse", horse_id)
        return {
            "horse": _as_payload(horse_payload),
            "history": _rows(history_payload),
        }


class ExternalHorseDataImporter:
    def __init__(self, options: ImportOptions | None = None, adapter: Any | None = None):
        self.options = options or ImportOptions.from_settings()
        self.adapter = adapter or KeibaScraperAdapter(self.options)

    def _month_targets(self) -> list[tuple[int, int]]:
        local_today = timezone.localdate()
        year = local_today.year
        month = local_today.month
        targets: list[tuple[int, int]] = []
        for _ in range(max(1, int(self.options.lookback_months))):
            targets.append((year, month))
            month -= 1
            if month == 0:
                year -= 1
                month = 12
        return targets

    def _start_run(self, target_type: str, **payload: Any) -> ExternalDataImportRun:
        if not self.options.allow_network:
            raise ExternalHorseDataNetworkDisabled("real import requires allow_network=true")
        if not getattr(settings, "EXTERNAL_HORSE_DATA_IMPORT_ENABLED", False):
            raise ExternalHorseDataNetworkDisabled("external horse data import is disabled")
        with transaction.atomic():
            lock, _ = ExternalDataImportLock.objects.select_for_update().get_or_create(source=self.options.source)
            if lock.locked_by_run and lock.locked_by_run.status == ExternalImportStatus.STARTED:
                raise ExternalHorseDataAlreadyRunning(f"{self.options.source} import is already running")
            run = ExternalDataImportRun.objects.create(
                source=self.options.source,
                target_type=target_type,
                target_year=payload.get("year"),
                target_month=payload.get("month"),
                race_id=payload.get("race_id", ""),
                horse_id=payload.get("horse_id", ""),
                dry_run=False,
                parameters={
                    "lookback_months": self.options.lookback_months,
                    "request_interval_seconds": self.options.request_interval_seconds,
                    "jitter_seconds": self.options.jitter_seconds,
                    "max_races": self.options.max_races,
                    "max_horses": self.options.max_horses,
                    "fetch_odds": self.options.fetch_odds,
                    "fetch_horse_detail": self.options.fetch_horse_detail,
                    **{key: value for key, value in payload.items() if value is not None},
                },
            )
            lock.locked_by_run = run
            lock.acquired_at = timezone.now()
            lock.save(update_fields=["locked_by_run", "acquired_at", "updated_at"])
        return run

    def _finish_run(self, run: ExternalDataImportRun, status: str) -> None:
        run.status = status
        run.finished_at = timezone.now()
        run.coverage_stats = self.coverage_stats()
        run.save(update_fields=["status", "finished_at", "coverage_stats", "updated_at"])
        ExternalDataImportLock.objects.filter(source=run.source, locked_by_run=run).update(locked_by_run=None, acquired_at=None)

    def _set_current(self, run: ExternalDataImportRun, target_type: str, target_id: str) -> None:
        run.current_target_type = target_type
        run.current_target_id = target_id
        run.save(update_fields=["current_target_type", "current_target_id", "updated_at"])

    def _record_error(self, run: ExternalDataImportRun, target_type: str, target_id: str, exc: Exception, raw_payload: Any = None) -> None:
        run.failure_count += 1
        run.save(update_fields=["failure_count", "updated_at"])
        ExternalDataImportError.objects.create(
            run=run,
            source=self.options.source,
            target_type=target_type,
            target_id=target_id,
            error_type=exc.__class__.__name__,
            message=str(exc),
            raw_payload=_as_payload(raw_payload),
        )

    def dry_run(self, target_type: str, **payload: Any) -> dict[str, Any]:
        months = self._month_targets() if target_type == "default" else []
        expected_requests = 0
        if target_type == "race":
            expected_requests = 2 + int(bool(self.options.fetch_odds))
        elif target_type == "horse":
            expected_requests = 1
        elif target_type == "month":
            expected_requests = self.options.max_races * (2 + int(bool(self.options.fetch_odds)))
        elif target_type == "default":
            expected_requests = len(months) + self.options.max_races * (2 + int(bool(self.options.fetch_odds)))
        expected_seconds = expected_requests * (self.options.request_interval_seconds + self.options.jitter_seconds / 2)
        return {
            "dry_run": True,
            "source": self.options.source,
            "target_type": target_type,
            "target": payload,
            "months": months,
            "max_races": self.options.max_races,
            "max_horses": self.options.max_horses,
            "expected_requests": expected_requests,
            "estimated_seconds": round(expected_seconds, 1),
            "coverage_stats": self.coverage_stats(),
        }

    def import_default(self) -> dict[str, Any]:
        if self.options.dry_run:
            return self.dry_run("default")
        run = self._start_run("default")
        try:
            for year, month in self._month_targets():
                self._import_month_into_run(run, year, month)
            status = ExternalImportStatus.PARTIAL if run.failure_count else ExternalImportStatus.SUCCESS
            self._finish_run(run, status)
            return self.run_summary(run)
        except Exception as exc:
            self._record_error(run, "default", "default", exc)
            self._finish_run(run, ExternalImportStatus.FAILED)
            raise

    def import_month(self, year: int, month: int) -> dict[str, Any]:
        if self.options.dry_run:
            return self.dry_run("month", year=year, month=month)
        run = self._start_run("month", year=year, month=month)
        try:
            self._import_month_into_run(run, year, month)
            status = ExternalImportStatus.PAUSED if run.skipped_count else ExternalImportStatus.PARTIAL if run.failure_count else ExternalImportStatus.SUCCESS
            self._finish_run(run, status)
            return self.run_summary(run)
        except Exception as exc:
            self._record_error(run, "month", f"{year}-{month:02d}", exc)
            self._finish_run(run, ExternalImportStatus.FAILED)
            raise

    def _import_month_into_run(self, run: ExternalDataImportRun, year: int, month: int) -> None:
        self._set_current(run, "month", f"{year}-{month:02d}")
        race_ids = self.adapter.race_list(year, month)
        for race_id in race_ids[: self.options.max_races]:
            try:
                self._import_race_into_run(run, race_id)
            except Exception as exc:
                self._record_error(run, "race", race_id, exc)
        if len(race_ids) > self.options.max_races:
            run.skipped_count += len(race_ids) - self.options.max_races
            run.save(update_fields=["skipped_count", "updated_at"])

    def import_race(self, race_id: str) -> dict[str, Any]:
        if self.options.dry_run:
            return self.dry_run("race", race_id=race_id)
        run = self._start_run("race", race_id=race_id)
        try:
            self._import_race_into_run(run, race_id)
            status = ExternalImportStatus.PARTIAL if run.failure_count else ExternalImportStatus.SUCCESS
            self._finish_run(run, status)
            return self.run_summary(run)
        except Exception as exc:
            self._record_error(run, "race", race_id, exc)
            self._finish_run(run, ExternalImportStatus.FAILED)
            raise

    def _import_race_into_run(self, run: ExternalDataImportRun, race_id: str) -> set[str]:
        self._set_current(run, "race", race_id)
        bundle = self.adapter.fetch_race(race_id, fetch_odds=self.options.fetch_odds)
        horse_ids = self.save_race_bundle(race_id, bundle)
        run.success_count += 1
        run.coverage_stats = self.coverage_stats()
        run.save(update_fields=["success_count", "coverage_stats", "updated_at"])
        if self.options.fetch_horse_detail:
            for horse_id in sorted(horse_ids)[: self.options.max_horses]:
                try:
                    self._import_horse_into_run(run, horse_id)
                except Exception as exc:
                    self._record_error(run, "horse", horse_id, exc)
        return horse_ids

    def import_horse(self, horse_id: str, *, horse_name: str = "") -> dict[str, Any]:
        if self.options.dry_run:
            return self.dry_run("horse", horse_id=horse_id, horse_name=horse_name)
        run = self._start_run("horse", horse_id=horse_id, horse_name=horse_name)
        try:
            self._import_horse_into_run(run, horse_id, horse_name=horse_name)
            status = ExternalImportStatus.PARTIAL if run.failure_count else ExternalImportStatus.SUCCESS
            self._finish_run(run, status)
            return self.run_summary(run)
        except Exception as exc:
            self._record_error(run, "horse", horse_id, exc)
            self._finish_run(run, ExternalImportStatus.FAILED)
            raise

    def _import_horse_into_run(self, run: ExternalDataImportRun, horse_id: str, *, horse_name: str = "") -> None:
        self._set_current(run, "horse", horse_id)
        bundle = self.adapter.fetch_horse(horse_id)
        self.save_horse_bundle(horse_id, bundle, horse_name=horse_name)
        run.success_count += 1
        run.coverage_stats = self.coverage_stats()
        run.save(update_fields=["success_count", "coverage_stats", "updated_at"])

    def save_race_bundle(self, race_id: str, bundle: dict[str, Any]) -> set[str]:
        now = timezone.now()
        race_payload = bundle.get("race") or {}
        race_row = race_payload[0] if isinstance(race_payload, list) and race_payload else race_payload if isinstance(race_payload, dict) else {}
        race, _ = ExternalRace.objects.update_or_create(
            source=self.options.source,
            race_id=race_id,
            defaults={
                "race_name": _first(race_row, ["race_name", "レース名", "name", "title"]),
                "race_date": _parse_date(_first(race_row, ["race_date", "date", "日付", "開催日"])),
                "course": _first(race_row, ["course", "racecourse", "競馬場", "場所"]),
                "surface": _first(race_row, ["surface", "track", "馬場", "コース"]),
                "distance": _first(race_row, ["distance", "距離"]),
                "weather": _first(race_row, ["weather", "天候"]),
                "raw_payload": _as_payload(race_payload),
                "fetched_at": now,
                "last_seen_at": now,
            },
        )
        horse_ids: set[str] = set()
        for row in bundle.get("entry") or []:
            horse_id = _first(row, ["horse_id", "horseId", "馬ID", "id_horse"])
            horse_name = _first(row, ["horse_name", "馬名", "name", "horse"])
            horse_number = _first(row, ["horse_number", "馬番", "umaban", "number"])
            if horse_id:
                horse_ids.add(horse_id)
            entry_key = _stable_key(horse_number, horse_id, row)
            ExternalRaceEntry.objects.update_or_create(
                source=self.options.source,
                external_race_id=race_id,
                entry_key=entry_key,
                defaults={
                    "race": race,
                    "horse_id": horse_id,
                    "horse_name": horse_name,
                    "normalized_horse_name": normalize_horse_name(horse_name),
                    "horse_number": horse_number,
                    "frame_number": _first(row, ["frame_number", "枠番", "wakuban"]),
                    "jockey_name": _first(row, ["jockey_name", "騎手", "jockey"]),
                    "trainer_name": _first(row, ["trainer_name", "調教師", "trainer"]),
                    "raw_payload": _as_payload(row),
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
            self._upsert_alias(horse_id=horse_id, horse_name=horse_name, alias_source="entry", now=now)
        for row in bundle.get("result") or []:
            horse_id = _first(row, ["horse_id", "horseId", "馬ID", "id_horse"])
            horse_name = _first(row, ["horse_name", "馬名", "name", "horse"])
            horse_number = _first(row, ["horse_number", "馬番", "umaban", "number"])
            if horse_id:
                horse_ids.add(horse_id)
            result_key = _stable_key(horse_number, horse_id, _first(row, ["finish_position", "着順", "rank", "position"]), row)
            ExternalRaceResult.objects.update_or_create(
                source=self.options.source,
                external_race_id=race_id,
                result_key=result_key,
                defaults={
                    "race": race,
                    "horse_id": horse_id,
                    "horse_name": horse_name,
                    "normalized_horse_name": normalize_horse_name(horse_name),
                    "horse_number": horse_number,
                    "finish_position": _first(row, ["finish_position", "着順", "rank", "position"]),
                    "jockey_name": _first(row, ["jockey_name", "騎手", "jockey"]),
                    "trainer_name": _first(row, ["trainer_name", "調教師", "trainer"]),
                    "raw_payload": _as_payload(row),
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
            self._upsert_alias(horse_id=horse_id, horse_name=horse_name, alias_source="result", now=now)
        for row in bundle.get("odds") or []:
            odds_type = _first(row, ["odds_type", "type", "式別"]) or "default"
            horse_number = _first(row, ["horse_number", "馬番", "umaban", "number"])
            odds_key = _stable_key(odds_type, horse_number, _first(row, ["combination", "買い目"]), row)
            ExternalRaceOdds.objects.update_or_create(
                source=self.options.source,
                external_race_id=race_id,
                odds_type=odds_type,
                odds_key=odds_key,
                defaults={
                    "race": race,
                    "horse_number": horse_number,
                    "odds_value": _first(row, ["odds", "odds_value", "オッズ"]),
                    "raw_payload": _as_payload(row),
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
        return horse_ids

    def save_horse_bundle(self, horse_id: str, bundle: dict[str, Any], *, horse_name: str = "") -> ExternalHorse:
        now = timezone.now()
        horse_payload = bundle.get("horse") or {}
        horse_row = horse_payload[0] if isinstance(horse_payload, list) and horse_payload else horse_payload if isinstance(horse_payload, dict) else {}
        resolved_name = horse_name or _first(horse_row, ["horse_name", "馬名", "name"])
        horse, _ = ExternalHorse.objects.update_or_create(
            source=self.options.source,
            horse_id=horse_id,
            defaults={
                "horse_name": resolved_name,
                "normalized_horse_name": normalize_horse_name(resolved_name),
                "sex": _first(horse_row, ["sex", "性", "性別"]),
                "birth_date": _parse_date(_first(horse_row, ["birth_date", "birthday", "生年月日"]),
                ),
                "father_name": _first(horse_row, ["father_name", "父", "sire"]),
                "mother_name": _first(horse_row, ["mother_name", "母", "dam"]),
                "raw_payload": _as_payload(horse_payload),
                "fetched_at": now,
                "last_seen_at": now,
            },
        )
        self._upsert_alias(horse_id=horse_id, horse_name=resolved_name, horse=horse, alias_source="horse", now=now)
        for row in bundle.get("history") or []:
            race_id = _first(row, ["race_id", "raceId", "レースID", "id_race"])
            history_key = _stable_key(race_id, _first(row, ["horse_number", "馬番"]), _first(row, ["date", "日付"]), row)
            ExternalHorseHistory.objects.update_or_create(
                source=self.options.source,
                external_horse_id=horse_id,
                history_key=history_key,
                defaults={
                    "horse": horse,
                    "external_race_id": race_id,
                    "race_name": _first(row, ["race_name", "レース名", "name"]),
                    "raced_at": _parse_date(_first(row, ["race_date", "date", "日付", "開催日"])),
                    "horse_number": _first(row, ["horse_number", "馬番", "umaban", "number"]),
                    "finish_position": _first(row, ["finish_position", "着順", "rank", "position"]),
                    "raw_payload": _as_payload(row),
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
        return horse

    def _upsert_alias(
        self,
        *,
        horse_id: str,
        horse_name: str,
        alias_source: str,
        now: datetime,
        horse: ExternalHorse | None = None,
    ) -> ExternalHorseAlias | None:
        normalized = normalize_horse_name(horse_name)
        if not horse_id or not normalized:
            return None
        if horse is None:
            horse, _ = ExternalHorse.objects.get_or_create(
                source=self.options.source,
                horse_id=horse_id,
                defaults={
                    "horse_name": horse_name,
                    "normalized_horse_name": normalized,
                    "raw_payload": {},
                    "fetched_at": now,
                    "last_seen_at": now,
                },
            )
        alias, created = ExternalHorseAlias.objects.get_or_create(
            source=self.options.source,
            external_horse_id=horse_id,
            normalized_name=normalized,
            defaults={
                "horse": horse,
                "name_ja": horse_name,
                "confidence": 100,
                "alias_source": alias_source,
                "first_seen_at": now,
                "last_seen_at": now,
            },
        )
        if not created:
            alias.horse = alias.horse or horse
            alias.name_ja = horse_name
            alias.alias_source = alias.alias_source or alias_source
            alias.last_seen_at = now
            alias.save(update_fields=["horse", "name_ja", "alias_source", "last_seen_at", "updated_at"])
        return alias

    def lookup_alias(self, name_ja: str) -> list[ExternalHorseAlias]:
        normalized = normalize_horse_name(name_ja)
        if not normalized:
            return []
        return list(ExternalHorseAlias.objects.filter(source=self.options.source, normalized_name=normalized).order_by("-confidence", "-last_seen_at"))

    def coverage_stats(self) -> dict[str, int]:
        source = self.options.source
        entry_missing = ExternalRaceEntry.objects.filter(source=source).filter(horse_id="").count() + ExternalRaceEntry.objects.filter(source=source).filter(horse_name="").count()
        result_missing = ExternalRaceResult.objects.filter(source=source).filter(horse_id="").count() + ExternalRaceResult.objects.filter(source=source).filter(horse_name="").count()
        return {
            "race_count": ExternalRace.objects.filter(source=source).count(),
            "entry_count": ExternalRaceEntry.objects.filter(source=source).count(),
            "result_count": ExternalRaceResult.objects.filter(source=source).count(),
            "odds_count": ExternalRaceOdds.objects.filter(source=source).count(),
            "horse_count": ExternalHorse.objects.filter(source=source).count(),
            "history_count": ExternalHorseHistory.objects.filter(source=source).count(),
            "unique_horse_id_count": ExternalHorseAlias.objects.filter(source=source).values("external_horse_id").distinct().count(),
            "unique_horse_name_count": ExternalHorseAlias.objects.filter(source=source).values("normalized_name").distinct().count(),
            "missing_horse_id_or_name_count": entry_missing + result_missing,
        }

    def run_summary(self, run: ExternalDataImportRun) -> dict[str, Any]:
        run.refresh_from_db()
        return {
            "run_id": run.id,
            "source": run.source,
            "target_type": run.target_type,
            "status": run.status,
            "success_count": run.success_count,
            "skipped_count": run.skipped_count,
            "failure_count": run.failure_count,
            "coverage_stats": run.coverage_stats,
            "error_count": run.errors.count(),
        }
