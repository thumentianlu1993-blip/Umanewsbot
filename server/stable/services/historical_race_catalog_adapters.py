from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from stable.models import (
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    RaceEventSurface,
    RaceGrade,
    RaceSeriesStatus,
    RacingRegion,
)
from stable.services.historical_race_inventory import (
    InventoryValidationError,
    canonical_json,
    file_identity,
)


CATALOG_SCHEMA_VERSION = "1.0"
ADAPTER_PARSER_VERSION = "2026.07.1"
REQUIRED_COLUMNS = {
    "record_type",
    "year",
    "series_key",
    "original_name",
    "grade_text",
    "racecourse",
    "local_date",
    "distance_text",
    "surface",
    "expectation_status",
    "season_label",
    "source_scope",
    "discipline",
}


@dataclass(frozen=True)
class CatalogAdapterConfig:
    key: str
    region: str
    providers: frozenset[str]
    grade_patterns: tuple[tuple[re.Pattern[str], str], ...]


def _patterns(*items: tuple[str, str]) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(pattern, re.I), grade) for pattern, grade in items)


ADAPTER_CONFIGS = {
    "japan_official_catalog": CatalogAdapterConfig(
        key="japan_official_catalog",
        region=RacingRegion.JAPAN,
        providers=frozenset({"jra", "nar", "tjcis"}),
        grade_patterns=_patterns(
            (r"^(?:G1|GI|GⅠ)$", RaceGrade.G1),
            (r"^(?:G2|GII|GⅡ)$", RaceGrade.G2),
            (r"^(?:G3|GIII|GⅢ)$", RaceGrade.G3),
            (r"^(?:Jpn1|JpnI|JpnⅠ)$", RaceGrade.JPN1),
            (r"^(?:Jpn2|JpnII|JpnⅡ)$", RaceGrade.JPN2),
            (r"^(?:Jpn3|JpnIII|JpnⅢ)$", RaceGrade.JPN3),
            (r"^(?:J-G1|JG1|J[・.]GⅠ)$", RaceGrade.JG1),
            (r"^(?:J-G2|JG2|J[・.]GⅡ)$", RaceGrade.JG2),
            (r"^(?:J-G3|JG3|J[・.]GⅢ)$", RaceGrade.JG3),
            (r"地方重賞|重賞", RaceGrade.LOCAL_GRADE),
        ),
    ),
    "hkjc_official_catalog": CatalogAdapterConfig(
        key="hkjc_official_catalog",
        region=RacingRegion.HONG_KONG,
        providers=frozenset({"hkjc", "tjcis"}),
        grade_patterns=_patterns(
            (r"^(?:G1|Group 1|香港一級賽)$", RaceGrade.G1),
            (r"^(?:G2|Group 2|香港二級賽)$", RaceGrade.G2),
            (r"^(?:G3|Group 3|香港三級賽)$", RaceGrade.G3),
        ),
    ),
    "bha_pattern_catalog": CatalogAdapterConfig(
        key="bha_pattern_catalog",
        region=RacingRegion.UNITED_KINGDOM,
        providers=frozenset({"bha", "bhb", "jockey_club_archive", "tjcis"}),
        grade_patterns=_patterns(
            (r"^(?:Group|Grade)\s*1$", RaceGrade.G1),
            (r"^(?:Group|Grade)\s*2$", RaceGrade.G2),
            (r"^(?:Group|Grade)\s*3$", RaceGrade.G3),
        ),
    ),
    "france_galop_pattern_catalog": CatalogAdapterConfig(
        key="france_galop_pattern_catalog",
        region=RacingRegion.FRANCE,
        providers=frozenset({"france_galop", "tjcis"}),
        grade_patterns=_patterns(
            (r"^(?:Groupe|Group|Gr)\s*(?:I|1)$", RaceGrade.G1),
            (r"^(?:Groupe|Group|Gr)\s*(?:II|2)$", RaceGrade.G2),
            (r"^(?:Groupe|Group|Gr)\s*(?:III|3)$", RaceGrade.G3),
        ),
    ),
    "toba_graded_stakes_catalog": CatalogAdapterConfig(
        key="toba_graded_stakes_catalog",
        region=RacingRegion.UNITED_STATES,
        providers=frozenset({"toba", "agsc", "tjcis"}),
        grade_patterns=_patterns(
            (r"^(?:Grade|G)\s*(?:I|1)$", RaceGrade.G1),
            (r"^(?:Grade|G)\s*(?:II|2)$", RaceGrade.G2),
            (r"^(?:Grade|G)\s*(?:III|3)$", RaceGrade.G3),
        ),
    ),
}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_grade(config: CatalogAdapterConfig, grade_text: str, *, record_type: str) -> str:
    value = " ".join(str(grade_text or "").split())
    for pattern, grade in config.grade_patterns:
        if pattern.search(value):
            return grade
    if record_type == "timeline":
        timeline_grades = {
            "listed": RaceGrade.LISTED,
            "l": RaceGrade.LISTED,
            "open": RaceGrade.OPEN,
            "op": RaceGrade.OPEN,
            "ungraded": RaceGrade.OTHER,
            "not graded": RaceGrade.OTHER,
        }
        normalized = value.casefold()
        if normalized in timeline_grades:
            return timeline_grades[normalized]
    raise InventoryValidationError(f"{config.key} unsupported historical grade: {grade_text}")


def _surface(value: str, *, allow_blank: bool = False) -> str:
    normalized = str(value or "").strip().casefold()
    if not normalized and allow_blank:
        return ""
    aliases = {
        "turf": RaceEventSurface.TURF,
        "grass": RaceEventSurface.TURF,
        "芝": RaceEventSurface.TURF,
        "dirt": RaceEventSurface.DIRT,
        "泥地": RaceEventSurface.DIRT,
        "synthetic": RaceEventSurface.SYNTHETIC,
        "all-weather": RaceEventSurface.SYNTHETIC,
        "jumps": RaceEventSurface.JUMPS,
        "jump": RaceEventSurface.JUMPS,
        "障碍": RaceEventSurface.JUMPS,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise InventoryValidationError(f"unsupported historical surface: {value}") from exc


def _manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryValidationError(f"historical catalog manifest is unreadable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise InventoryValidationError("historical catalog manifest schema is unsupported")
    return payload


def _cache_path(manifest_path: Path, relative: str, *, adapter_key: str) -> Path:
    manifest_root = manifest_path.parent.resolve()
    candidate = (manifest_root / relative).resolve()
    try:
        candidate.relative_to(manifest_root)
    except ValueError as exc:
        raise InventoryValidationError(
            f"{adapter_key} cache path is outside manifest directory: {relative}"
        ) from exc
    return candidate


def _discipline(value: str, *, surface: str, adapter_key: str) -> str:
    discipline = str(value or "").strip().casefold()
    if discipline not in {"flat", "jumps"}:
        raise InventoryValidationError(f"{adapter_key} unsupported discipline: {value}")
    if (surface == RaceEventSurface.JUMPS) != (discipline == "jumps"):
        raise InventoryValidationError(
            f"{adapter_key} discipline and surface disagree: {discipline}/{surface}"
        )
    return discipline


def _season_label(value: str, *, region: str, year: int, adapter_key: str, location: str) -> str:
    label = str(value or "").strip()
    if region != RacingRegion.HONG_KONG:
        return label
    match = re.fullmatch(r"(\d{4})[/_-](\d{2}|\d{4})", label)
    if not match:
        raise InventoryValidationError(f"{adapter_key} invalid or missing season_label at {location}")
    start = int(match.group(1))
    raw_end = match.group(2)
    end = int(raw_end) if len(raw_end) == 4 else (start // 100) * 100 + int(raw_end)
    if end < start:
        end += 100
    if end != start + 1 or year not in {start, end}:
        raise InventoryValidationError(f"{adapter_key} season_label does not match year at {location}")
    return label


def _series_status(value: str, *, adapter_key: str, location: str) -> str:
    normalized = str(value or RaceSeriesStatus.UNKNOWN).strip().casefold()
    aliases = {
        "active": RaceSeriesStatus.ACTIVE,
        "discontinued": RaceSeriesStatus.DISCONTINUED,
        "ended": RaceSeriesStatus.DISCONTINUED,
        "unknown": RaceSeriesStatus.UNKNOWN,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise InventoryValidationError(f"{adapter_key} invalid series_status at {location}") from exc


def parse_historical_catalog_manifest(manifest_path: str | Path) -> list[dict[str, Any]]:
    path = Path(manifest_path)
    manifest = _manifest(path)
    adapter_key = str(manifest.get("adapter_key") or "")
    try:
        config = ADAPTER_CONFIGS[adapter_key]
    except KeyError as exc:
        raise InventoryValidationError(f"unknown historical catalog adapter: {adapter_key}") from exc
    provider = str(manifest.get("source_provider") or "")
    if provider not in config.providers:
        raise InventoryValidationError(f"{adapter_key} rejects source provider: {provider}")
    if manifest.get("parser_version") != ADAPTER_PARSER_VERSION:
        raise InventoryValidationError(f"{adapter_key} parser version mismatch")
    supported = manifest.get("supported_years")
    if not isinstance(supported, dict):
        raise InventoryValidationError(f"{adapter_key} supported_years is missing")
    try:
        start_year = int(supported.get("start") or 0)
        end_year = int(supported.get("end") or 0)
    except (TypeError, ValueError) as exc:
        raise InventoryValidationError(f"{adapter_key} supported year range is invalid") from exc
    if start_year <= 0 or end_year < start_year or end_year < 1984:
        raise InventoryValidationError(f"{adapter_key} supported year range is invalid")
    source_authority = str(manifest.get("source_authority") or "official_archive")
    if source_authority not in {"official", "official_current", "official_archive"}:
        raise InventoryValidationError(f"{adapter_key} source authority is invalid")
    cache_files = manifest.get("cache_files")
    if not isinstance(cache_files, list) or not cache_files:
        raise InventoryValidationError(f"{adapter_key} cache_files is empty")

    candidates = []
    for cache in cache_files:
        if not isinstance(cache, dict):
            raise InventoryValidationError(f"{adapter_key} cache provenance is incomplete")
        source_url = str(cache.get("source_url") or "").strip()
        relative = str(cache.get("path") or "").strip()
        expected_sha = str(cache.get("sha256") or "").strip()
        if not source_url.startswith(("https://", "http://")) or len(expected_sha) != 64:
            raise InventoryValidationError(f"{adapter_key} cache provenance is incomplete")
        cache_path = _cache_path(path, relative, adapter_key=adapter_key)
        if not cache_path.is_file() or _file_sha256(cache_path) != expected_sha:
            raise InventoryValidationError(f"{adapter_key} cache identity mismatch: {relative}")
        with cache_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise InventoryValidationError(
                    f"{adapter_key} cache columns missing: {', '.join(sorted(missing))}"
                )
            row_count = 0
            for line_number, row in enumerate(reader, start=2):
                row_count += 1
                try:
                    year = int(row["year"])
                except (TypeError, ValueError) as exc:
                    raise InventoryValidationError(f"{adapter_key} invalid year at {relative}:{line_number}") from exc
                if year < 1984 or not start_year <= year <= end_year:
                    raise InventoryValidationError(f"{adapter_key} year outside declared support: {year}")
                record_type = str(row["record_type"] or "").strip()
                if record_type not in {"catalog", "timeline"}:
                    raise InventoryValidationError(f"{adapter_key} invalid record_type: {record_type}")
                expectation = str(row["expectation_status"] or HistoricalRaceExpectationStatus.HELD)
                if expectation not in HistoricalRaceExpectationStatus.values:
                    raise InventoryValidationError(f"{adapter_key} invalid expectation: {expectation}")
                series_key = str(row["series_key"] or "").strip()
                original_name = str(row["original_name"] or "").strip()
                if not series_key or not original_name:
                    raise InventoryValidationError(f"{adapter_key} missing series identity at {relative}:{line_number}")
                surface = _surface(
                    row["surface"],
                    allow_blank=expectation != HistoricalRaceExpectationStatus.HELD,
                )
                discipline = _discipline(row["discipline"], surface=surface, adapter_key=adapter_key)
                location = f"{relative}:{line_number}"
                season_label = _season_label(
                    row.get("season_label"),
                    region=config.region,
                    year=year,
                    adapter_key=adapter_key,
                    location=location,
                )
                local_date = str(row["local_date"] or "").strip()
                if local_date:
                    try:
                        parsed_date = date.fromisoformat(local_date)
                    except ValueError as exc:
                        raise InventoryValidationError(
                            f"{adapter_key} invalid local_date at {location}"
                        ) from exc
                    if parsed_date.year != year:
                        raise InventoryValidationError(
                            f"{adapter_key} local_date does not match year at {location}"
                        )
                series_status = _series_status(
                    row.get("series_status"),
                    adapter_key=adapter_key,
                    location=location,
                )
                source_scope = str(row.get("source_scope") or "").strip()
                if not source_scope:
                    raise InventoryValidationError(
                        f"{adapter_key} missing source_scope at {relative}:{line_number}"
                    )
                raw_source_path = str(row.get("raw_source_cache_path") or "").strip()
                raw_source_sha = str(row.get("raw_source_cache_sha256") or "").strip()
                raw_source_url = str(row.get("raw_source_url") or "").strip()
                source_duplicate_count = str(row.get("source_duplicate_count") or "1").strip()
                if not source_duplicate_count.isdigit() or int(source_duplicate_count) < 1:
                    raise InventoryValidationError(
                        f"{adapter_key} source duplicate count is invalid at {location}"
                    )
                if any((raw_source_path, raw_source_sha, raw_source_url)) and not (
                    raw_source_path
                    and re.fullmatch(r"[0-9a-fA-F]{64}", raw_source_sha)
                    and raw_source_url.startswith(("https://", "http://"))
                ):
                    raise InventoryValidationError(
                        f"{adapter_key} raw source provenance is incomplete at {location}"
                    )
                candidates.append(
                    {
                        "record_type": record_type,
                        "series_key": series_key,
                        "country_region": config.region,
                        "year": year,
                        "canonical_name_original": str(row.get("canonical_name_original") or original_name).strip(),
                        "original_name": original_name,
                        "chinese_name": str(row.get("chinese_name") or "").strip(),
                        "grade_text": str(row["grade_text"] or "").strip(),
                        "normalized_grade": _normalized_grade(
                            config,
                            row["grade_text"],
                            record_type=record_type,
                        ),
                        "racecourse": str(row["racecourse"] or "").strip(),
                        "local_date": local_date,
                        "distance_text": str(row["distance_text"] or "").strip(),
                        "surface": surface,
                        "season_label": season_label,
                        "source_scope": source_scope,
                        "discipline": discipline,
                        "expectation_status": expectation,
                        "resolution_status": HistoricalRaceResolutionStatus.PENDING,
                        "founded_year": int(row["founded_year"]) if str(row.get("founded_year") or "").isdigit() else None,
                        "ended_year": int(row["ended_year"]) if str(row.get("ended_year") or "").isdigit() else None,
                        "series_status": series_status,
                        "source_refs": {
                            "source_provider": provider,
                            "source_authority": source_authority,
                            "source_url": source_url,
                            "source_cache_path": relative,
                            "source_cache_sha256": expected_sha,
                            "raw_source_cache_path": raw_source_path,
                            "raw_source_cache_sha256": raw_source_sha,
                            "raw_source_url": raw_source_url,
                            "source_duplicate_count": int(source_duplicate_count),
                            "parser_version": ADAPTER_PARSER_VERSION,
                            "manifest_path": str(path),
                            "season_label": season_label,
                            "source_scope": source_scope,
                            "discipline": discipline,
                        },
                    }
                )
            if row_count == 0:
                raise InventoryValidationError(f"{adapter_key} cache parsed zero rows: {relative}")
    return candidates


def discover_catalog_and_timeline(manifest_paths: Iterable[str | Path]) -> dict[str, list[dict[str, Any]]]:
    parsed = [row for path in manifest_paths for row in parse_historical_catalog_manifest(path)]
    catalog = [row for row in parsed if row["record_type"] == "catalog"]
    selected_series = {row["series_key"] for row in catalog}
    timeline = [
        row
        for row in parsed
        if row["record_type"] == "timeline" and row["series_key"] in selected_series
    ]
    excluded_timeline = [
        row
        for row in parsed
        if row["record_type"] == "timeline" and row["series_key"] not in selected_series
    ]
    if excluded_timeline:
        raise InventoryValidationError(
            "timeline contains series that never entered an approved graded/pattern catalog: "
            + ", ".join(sorted({row["series_key"] for row in excluded_timeline}))
        )
    return {"catalog": catalog, "timeline": timeline}


def build_catalog_candidate_artifact(
    *,
    manifest_paths: Iterable[str | Path],
    output_dir: str | Path,
) -> dict[str, Any]:
    manifests = tuple(Path(path) for path in manifest_paths)
    if not manifests:
        raise InventoryValidationError("at least one historical catalog source manifest is required")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise InventoryValidationError(f"historical catalog output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    discovered = discover_catalog_and_timeline(manifests)
    sort_key = lambda row: (row["country_region"], row["year"], row["series_key"])
    catalog = sorted(discovered["catalog"], key=sort_key)
    timeline = sorted(discovered["timeline"], key=sort_key)
    catalog_path = output / "catalog_candidate.jsonl"
    timeline_path = output / "series_timeline_candidate.jsonl"
    for path, rows in ((catalog_path, catalog), (timeline_path, timeline)):
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(canonical_json(row) + "\n")

    region_counts: dict[str, dict[str, int]] = {}
    for region in sorted({row["country_region"] for row in [*catalog, *timeline]}):
        region_counts[region] = {
            "catalog": sum(row["country_region"] == region for row in catalog),
            "timeline": sum(row["country_region"] == region for row in timeline),
        }
    summary = {
        "catalog_count": len(catalog),
        "timeline_count": len(timeline),
        "region_counts": region_counts,
        "parser_version": ADAPTER_PARSER_VERSION,
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts = {
        "catalog_candidate": catalog_path,
        "series_timeline_candidate": timeline_path,
        "summary": summary_path,
    }
    artifact_manifest = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "parser_version": ADAPTER_PARSER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": [file_identity(path).as_dict() for path in manifests],
        "artifacts": {
            key: file_identity(path, relative_to=output).as_dict()
            for key, path in artifacts.items()
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(artifact_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": str(output),
        "manifest": str(manifest_path),
        **summary,
    }
