#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


ADAPTER_ALLOWED_HOSTS = {
    "jra": ("jra.go.jp", "japanracing.jp"),
    "netkeiba": ("netkeiba.com",),
    "jbis": ("jbis.or.jp",),
    "hkjc": ("hkjc.com",),
    "uk_racingpost": ("racingpost.com",),
    "uk_skysports": ("skysports.com",),
    "uk_sportinglife": ("sportinglife.com",),
    "uk_irishracing": ("irishracing.com",),
    "uk_bha": ("britishhorseracing.com",),
    "france_galop": ("france-galop.com",),
    "pmu": ("pmu.fr",),
    "france_irishracing": ("irishracing.com",),
    "equibase": ("equibase.com",),
    "brisnet": ("brisnet.com",),
    "drf": ("drf.com",),
    "bloodhorse": ("bloodhorse.com",),
    "nsa": ("nationalsteeplechase.com",),
    "us_hrn": ("horseracingnation.com",),
    "toba": ("toba.org",),
}

PARSER_ADAPTERS = {
    "jra_schedule": {"jra"},
    "jra_history": {"jra"},
    "toba_yearbook": {"toba"},
    "hkjc_pattern": {"hkjc"},
    "bha_flat": {"uk_bha"},
    "bha_jump": {"uk_bha"},
    "france_flat": {"france_galop"},
    "france_flat_program": {"france_galop"},
    "france_obstacle": {"france_galop"},
    "france_obstacle_summary": {"france_galop"},
}

CONTENT_FORMATS = {"html", "json", "pdf", "text"}
SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class CalendarArtifactError(RuntimeError):
    pass


def canonical_bytes(payload) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path, *, relative_to: Path | None = None) -> dict:
    if path.is_symlink() or not path.is_file():
        raise CalendarArtifactError(f"artifact is not a regular file: {path}")
    rendered = path.name if relative_to is None else path.relative_to(relative_to).as_posix()
    return {
        "path": rendered,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _host_allowed(hostname: str, allowed: tuple[str, ...]) -> bool:
    hostname = hostname.rstrip(".").casefold()
    return any(
        hostname == item.casefold() or hostname.endswith("." + item.casefold())
        for item in allowed
    )


def validate_source_url(url: str, adapter_key: str) -> None:
    parsed = urlparse(str(url or ""))
    try:
        port = parsed.port
    except ValueError as exc:
        raise CalendarArtifactError(
            f"calendar source URL has an invalid port: {adapter_key}/{url}"
        ) from exc
    if (
        adapter_key not in ADAPTER_ALLOWED_HOSTS
        or parsed.scheme != "https"
        or not parsed.hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or not _host_allowed(parsed.hostname, ADAPTER_ALLOWED_HOSTS[adapter_key])
    ):
        raise CalendarArtifactError(
            f"calendar source URL is outside adapter allowlist: {adapter_key}/{url}"
        )


def load_selection(path: Path) -> tuple[dict, list[dict]]:
    if path.is_symlink() or not path.is_file():
        raise CalendarArtifactError("selection snapshot is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalendarArtifactError("selection snapshot is unreadable") from exc
    targets = payload.get("targets") if isinstance(payload, dict) else None
    if payload.get("schema_version") != "1.0" or not isinstance(targets, list) or not targets:
        raise CalendarArtifactError("selection snapshot schema is invalid")
    seen_ids: set[int] = set()
    seen_identity: set[tuple[str, int]] = set()
    normalized = []
    for row in targets:
        if not isinstance(row, dict):
            raise CalendarArtifactError("selection target identity is invalid")
        raw_target_id = row.get("target_id")
        raw_year = row.get("year")
        if (
            not isinstance(raw_target_id, int)
            or isinstance(raw_target_id, bool)
            or not isinstance(raw_year, int)
            or isinstance(raw_year, bool)
        ):
            raise CalendarArtifactError("selection target identity is invalid")
        try:
            target_id = raw_target_id
            year = raw_year
            series_key = str(row["series_key"])
            region = str(row["country_region"])
            target_sha = str(row["target_sha256"])
            inventory_sha = str(
                row.get("inventory_artifact_sha256") or row.get("artifact_sha256")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarArtifactError("selection target identity is invalid") from exc
        if (
            target_id <= 0
            or not 1800 <= year <= 2200
            or target_id in seen_ids
            or (series_key, year) in seen_identity
            or not series_key.strip()
            or not region
            or not SHA256_RE.fullmatch(target_sha)
            or not SHA256_RE.fullmatch(inventory_sha)
        ):
            raise CalendarArtifactError("selection target identity is invalid or duplicated")
        seen_ids.add(target_id)
        seen_identity.add((series_key, year))
        normalized.append(
            {
                **row,
                "target_id": target_id,
                "year": year,
                "series_key": series_key,
                "country_region": region,
                "target_sha256": target_sha,
                "inventory_artifact_sha256": inventory_sha,
            }
        )
    return payload, sorted(normalized, key=lambda row: row["target_id"])


def hkjc_coverage_policy(
    sources: list[dict], *, hkjc_cutoff_date: date | None = None
) -> dict | None:
    hkjc_sources = [source for source in sources if source["parser"] == "hkjc_pattern"]
    if hkjc_cutoff_date is None:
        hkjc_seasons: dict[int, set[int]] = {}
        for source in hkjc_sources:
            hkjc_seasons.setdefault(source["edition_year"], set()).add(
                source["options"]["season_end_year"]
            )
        for edition_year, season_end_years in sorted(hkjc_seasons.items()):
            expected = {edition_year, edition_year + 1}
            if season_end_years != expected:
                raise CalendarArtifactError(
                    "HKJC pattern sources must cover both seasons for natural year "
                    f"{edition_year}: expected {sorted(expected)}"
                )
        return None

    if not isinstance(hkjc_cutoff_date, date):
        raise CalendarArtifactError("HKJC cutoff date is invalid")
    if not sources or len(hkjc_sources) != len(sources):
        raise CalendarArtifactError(
            "HKJC partial coverage only supports official HKJC pattern sources"
        )
    if any(
        source["adapter_key"] != "hkjc"
        or source["source_authority"] != "official"
        for source in sources
    ):
        raise CalendarArtifactError(
            "HKJC partial coverage only supports official HKJC pattern sources"
        )
    edition_years = {source["edition_year"] for source in sources}
    if len(edition_years) != 1:
        raise CalendarArtifactError(
            "HKJC partial coverage requires a single edition year catalog"
        )
    edition_year = next(iter(edition_years))
    if hkjc_cutoff_date.year != edition_year:
        raise CalendarArtifactError(
            "HKJC cutoff date must match the catalog edition year"
        )
    included = {source["options"]["season_end_year"] for source in sources}
    expected = {edition_year, edition_year + 1}
    if included != {edition_year}:
        raise CalendarArtifactError(
            "HKJC partial coverage must include the current season and may only "
            "omit the next season"
        )

    coverage_values = set()
    for source in sources:
        options = source["options"]
        try:
            coverage_start = date.fromisoformat(str(options["coverage_start_date"]))
            coverage_end = date.fromisoformat(str(options["coverage_end_date"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarArtifactError(
                "HKJC partial coverage requires valid coverage date boundaries"
            ) from exc
        reason = str(options.get("partial_coverage_reason") or "").strip()
        if (
            coverage_start >= coverage_end
            or not coverage_start <= hkjc_cutoff_date <= coverage_end
            or coverage_start.year not in {edition_year - 1, edition_year}
            or coverage_end.year != edition_year
            or not reason
        ):
            raise CalendarArtifactError(
                "HKJC partial coverage boundaries are invalid"
            )
        coverage_values.add((coverage_start, coverage_end, reason))
    if len(coverage_values) != 1:
        raise CalendarArtifactError(
            "HKJC partial coverage boundaries must be identical across sources"
        )
    coverage_start, coverage_end, reason = next(iter(coverage_values))
    return {
        "coverage_mode": "cutoff_bounded_partial_natural_year",
        "cutoff_date": hkjc_cutoff_date.isoformat(),
        "coverage_start_date": coverage_start.isoformat(),
        "coverage_end_date": coverage_end.isoformat(),
        "included_season_end_years": sorted(included),
        "omitted_season_end_years": sorted(expected - included),
        "expected_full_season_end_years": sorted(expected),
        "partial_coverage_reason": reason,
    }


def load_catalog(
    path: Path, *, hkjc_cutoff_date: date | None = None
) -> tuple[dict, list[dict]]:
    if path.is_symlink() or not path.is_file():
        raise CalendarArtifactError("calendar source catalog is not a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalendarArtifactError("calendar source catalog is unreadable") from exc
    sources = payload.get("sources") if isinstance(payload, dict) else None
    if payload.get("schema_version") != "1.0" or not isinstance(sources, list):
        raise CalendarArtifactError("calendar source catalog schema is invalid")
    seen_ids: set[str] = set()
    normalized = []
    for row in sources:
        if not isinstance(row, dict):
            raise CalendarArtifactError("calendar source must be an object")
        source_id = str(row.get("id") or "")
        region = str(row.get("country_region") or "")
        adapter = str(row.get("adapter_key") or "")
        parser = str(row.get("parser") or "")
        content_format = str(row.get("content_format") or "")
        authority = str(row.get("source_authority") or "")
        options = row.get("options", {})
        raw_year = row.get("edition_year")
        if not isinstance(raw_year, int) or isinstance(raw_year, bool):
            raise CalendarArtifactError(f"calendar source year is invalid: {source_id}")
        year = raw_year
        if (
            not SOURCE_ID_RE.fullmatch(source_id)
            or source_id in seen_ids
            or not region
            or year < 1800
            or year > 2200
            or parser not in PARSER_ADAPTERS
            or adapter not in PARSER_ADAPTERS[parser]
            or content_format not in CONTENT_FORMATS
            or not authority
            or not isinstance(options, dict)
        ):
            raise CalendarArtifactError(f"calendar source definition is invalid: {source_id}")
        validate_source_url(str(row.get("url") or ""), adapter)
        if parser == "bha_jump" and (
            not isinstance(options.get("season_start_year"), int)
            or isinstance(options.get("season_start_year"), bool)
        ):
            raise CalendarArtifactError(
                f"BHA jump source requires season_start_year: {source_id}"
            )
        if parser == "hkjc_pattern" and (
            not isinstance(options.get("season_end_year"), int)
            or isinstance(options.get("season_end_year"), bool)
        ):
            raise CalendarArtifactError(
                f"HKJC pattern source requires season_end_year: {source_id}"
            )
        if parser == "france_obstacle":
            try:
                date_start = date.fromisoformat(str(options["date_start"]))
                date_end = date.fromisoformat(str(options["date_end"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise CalendarArtifactError(
                    f"France obstacle source requires bounded date window: {source_id}"
                ) from exc
            if (
                date_start > date_end
                or (date_end - date_start).days > 370
                or not date_start.year <= year <= date_end.year
            ):
                raise CalendarArtifactError(
                    f"France obstacle source requires bounded date window: {source_id}"
                )
        seen_ids.add(source_id)
        normalized.append(
            {
                **row,
                "id": source_id,
                "country_region": region,
                "edition_year": year,
                "adapter_key": adapter,
                "parser": parser,
                "content_format": content_format,
                "source_authority": authority,
                "options": options,
            }
        )
    normalized = sorted(normalized, key=lambda row: row["id"])
    hkjc_coverage_policy(normalized, hkjc_cutoff_date=hkjc_cutoff_date)
    return payload, normalized


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    directories = [root, *[path for path in root.rglob("*") if path.is_dir()]]
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def atomic_publish_directory(output_dir: Path, writer) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise CalendarArtifactError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent)
    )
    published = False
    try:
        writer(temporary)
        _fsync_tree(temporary)
        temporary.rename(output_dir)
        published = True
        descriptor = os.open(output_dir.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        shutil.rmtree(output_dir if published else temporary, ignore_errors=True)
        raise
