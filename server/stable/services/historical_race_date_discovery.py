from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RacingRegion,
)
from stable.services.historical_race_batches import (
    materialize_historical_event,
    target_identity,
)
from stable.services.historical_race_inventory import (
    InventoryValidationError,
    canonical_json,
    file_identity,
)


DATE_SOURCE_DISCOVERY_SCHEMA_VERSION = "1.0"
DIRECT_URL_KEYS = {
    "declared_runners_url",
    "actual_runners_url",
    "non_runner_url",
    "result_url",
    "cancellation_url",
}
DISCOVERY_ADAPTER_ALLOWED_HOSTS = {
    "jra": ("jra.go.jp",),
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
    "zeturf": ("zeturf.fr",),
    "france_irishracing": ("irishracing.com",),
    "equibase": ("equibase.com",),
    "brisnet": ("brisnet.com",),
    "drf": ("drf.com",),
    "bloodhorse": ("bloodhorse.com",),
    "nsa": ("nationalsteeplechase.com",),
    "us_hrn": ("horseracingnation.com",),
}
DISCOVERY_ADAPTER_ALLOWED_AUTHORITIES = {
    "jra": {"official"},
    "netkeiba": {"third_party_high_access"},
    "jbis": {"third_party_high_access"},
    "hkjc": {"official"},
    "uk_racingpost": {"third_party_high_access"},
    "uk_skysports": {"third_party_high_access", "reference"},
    "uk_sportinglife": {"third_party_high_access"},
    "uk_irishracing": {"third_party_high_access"},
    "uk_bha": {"official"},
    "france_galop": {"official"},
    "pmu": {"third_party_high_access"},
    "zeturf": {"third_party_high_access"},
    "france_irishracing": {"third_party_high_access"},
    "equibase": {"third_party"},
    "brisnet": {"third_party"},
    "drf": {"third_party_high_access"},
    "bloodhorse": {"third_party"},
    "nsa": {"official"},
    "us_hrn": {"third_party_high_access"},
}
DISCOVERY_ADAPTER_REGIONS = {
    "jra": RacingRegion.JAPAN,
    "netkeiba": RacingRegion.JAPAN,
    "jbis": RacingRegion.JAPAN,
    "hkjc": RacingRegion.HONG_KONG,
    "uk_racingpost": RacingRegion.UNITED_KINGDOM,
    "uk_skysports": RacingRegion.UNITED_KINGDOM,
    "uk_sportinglife": RacingRegion.UNITED_KINGDOM,
    "uk_irishracing": RacingRegion.UNITED_KINGDOM,
    "uk_bha": RacingRegion.UNITED_KINGDOM,
    "france_galop": RacingRegion.FRANCE,
    "pmu": RacingRegion.FRANCE,
    "zeturf": RacingRegion.FRANCE,
    "france_irishracing": RacingRegion.FRANCE,
    "equibase": RacingRegion.UNITED_STATES,
    "brisnet": RacingRegion.UNITED_STATES,
    "drf": RacingRegion.UNITED_STATES,
    "bloodhorse": RacingRegion.UNITED_STATES,
    "nsa": RacingRegion.UNITED_STATES,
    "us_hrn": RacingRegion.UNITED_STATES,
}
PRIMARY_RESULT_PROVIDERS = {
    RacingRegion.JAPAN: {"jra", "netkeiba"},
    RacingRegion.HONG_KONG: {"hkjc"},
    RacingRegion.UNITED_KINGDOM: {"uk_racingpost", "uk_skysports", "uk_sportinglife", "uk_irishracing", "uk_bha"},
    RacingRegion.FRANCE: {"france_galop", "pmu", "zeturf", "france_irishracing"},
    RacingRegion.UNITED_STATES: {"equibase", "brisnet", "drf", "nsa", "us_hrn"},
}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise InventoryValidationError(f"date discovery row must be an object: {path}:{line_number}")
            rows.append(payload)
    return rows


def _artifact_path(root: Path, relative: Any, *, label: str) -> Path:
    text = str(relative or "").strip()
    path = (root / text).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise InventoryValidationError(f"{label} is outside artifact directory: {text}") from exc
    return path


def _validate_https_url(url: str, *, allowed_hosts: tuple[str, ...], redirect: bool) -> None:
    parsed = urlparse(url)
    label = "redirect URL" if redirect else "direct source URL"
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise InventoryValidationError(f"{label} must be an unauthenticated HTTPS URL")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "metadata.google.internal"} or hostname.endswith((".local", ".internal")):
        raise InventoryValidationError(f"{label} uses a private or internal host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise InventoryValidationError(f"{label} uses a non-public IP address")
    if not any(hostname == allowed or hostname.endswith(f".{allowed}") for allowed in allowed_hosts):
        raise InventoryValidationError(f"{label} host is outside the adapter allowlist: {hostname}")


def validate_direct_source_urls(adapter_key: str, urls: dict[str, Any]) -> dict[str, Any]:
    if adapter_key not in DISCOVERY_ADAPTER_ALLOWED_HOSTS:
        raise InventoryValidationError(f"unsupported date discovery adapter: {adapter_key}")
    if not isinstance(urls, dict) or not urls:
        raise InventoryValidationError("date discovery candidate is missing direct URLs")
    normalized: dict[str, Any] = {}
    for key, evidence in urls.items():
        if key not in DIRECT_URL_KEYS or not isinstance(evidence, dict):
            raise InventoryValidationError(f"unsupported direct source URL field: {key}")
        provider = str(evidence.get("source_provider") or adapter_key).strip()
        if provider not in DISCOVERY_ADAPTER_ALLOWED_HOSTS:
            raise InventoryValidationError(f"unsupported direct source provider: {provider}")
        url = str(evidence.get("url") or "").strip()
        authority = str(evidence.get("source_authority") or "").strip()
        if not authority:
            raise InventoryValidationError(f"direct source URL is missing source authority: {key}")
        if authority not in DISCOVERY_ADAPTER_ALLOWED_AUTHORITIES[provider]:
            raise InventoryValidationError(
                f"direct source authority is invalid for {provider}: {authority}"
            )
        _validate_https_url(url, allowed_hosts=DISCOVERY_ADAPTER_ALLOWED_HOSTS[provider], redirect=False)
        redirects = evidence.get("redirect_chain") or []
        if not isinstance(redirects, list):
            raise InventoryValidationError(f"redirect chain must be a list: {key}")
        for redirect_url in redirects:
            _validate_https_url(
                str(redirect_url or "").strip(),
                allowed_hosts=DISCOVERY_ADAPTER_ALLOWED_HOSTS[provider],
                redirect=True,
            )
        normalized[key] = {
            "url": url,
            "source_provider": provider,
            "source_authority": authority,
            "redirect_chain": [str(item) for item in redirects],
        }
    return normalized


def _number(value: str) -> int | float:
    if "/" in value:
        whole, fraction = (value.split(maxsplit=1) if " " in value else ("0", value))
        numerator, denominator = fraction.split("/", 1)
        result = float(whole) + (float(numerator) / float(denominator))
    else:
        result = float(value)
    return int(result) if result.is_integer() else result


def parse_distance_evidence(distance_text: str, country_region: str) -> dict[str, Any]:
    raw = " ".join(str(distance_text or "").split())
    if not raw:
        return {"distance_text": "", "measurement_system": "unknown", "components": []}
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        raise InventoryValidationError("distance requires an explicit unit")

    imperial_regions = {RacingRegion.UNITED_KINGDOM, RacingRegion.UNITED_STATES}
    if country_region in imperial_regions:
        unit_map = {
            "m": "mile",
            "mi": "mile",
            "mile": "mile",
            "miles": "mile",
            "f": "furlong",
            "fur": "furlong",
            "furlong": "furlong",
            "furlongs": "furlong",
            "y": "yard",
            "yd": "yard",
            "yard": "yard",
            "yards": "yard",
        }
        token_pattern = re.compile(
            r"(\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+)\s*"
            r"(miles?|mi|m|furlongs?|fur|f|yards?|yd|y)\b",
            re.IGNORECASE,
        )
        matches = list(token_pattern.finditer(raw))
        remainder = token_pattern.sub("", raw).strip(" ,+")
        if not matches or remainder:
            raise InventoryValidationError(f"unsupported imperial distance format: {raw}")
        components = [
            {"value": _number(match.group(1)), "unit": unit_map[match.group(2).lower()]}
            for match in matches
        ]
        metres = sum(
            float(item["value"]) * {"mile": 1609.344, "furlong": 201.168, "yard": 0.9144}[item["unit"]]
            for item in components
        )
        return {
            "distance_text": raw,
            "measurement_system": "imperial_racing",
            "components": components,
            "derived_metres": round(metres, 3),
            "conversion_formula": "mile=1609.344m; furlong=201.168m; yard=0.9144m",
        }

    metric = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|metres?|meters?|km|kilometres?|kilometers?)", raw, re.I)
    if not metric:
        raise InventoryValidationError(f"unsupported metric distance format: {raw}")
    value = _number(metric.group(1))
    token = metric.group(2).lower()
    unit = "kilometre" if token.startswith(("k", "kil")) else "metre"
    metres = float(value) * (1000 if unit == "kilometre" else 1)
    return {
        "distance_text": raw,
        "measurement_system": "metric",
        "components": [{"value": value, "unit": unit}],
        "derived_metres": int(metres) if metres.is_integer() else metres,
        "conversion_formula": "kilometre=1000m" if unit == "kilometre" else "source metres",
    }


def _candidate_issues(row: dict[str, Any], target: HistoricalRaceEventTarget) -> tuple[list[str], dict[str, Any] | None]:
    issues: list[str] = []
    try:
        parsed_date = date.fromisoformat(str(row.get("local_date") or ""))
    except ValueError:
        parsed_date = None
        issues.append("missing_date" if not row.get("local_date") else "invalid_date")
    actual_year = row.get("actual_year")
    if parsed_date:
        if parsed_date.year != target.year and actual_year in (None, ""):
            issues.append("actual_year_missing")
        try:
            actual_year = int(actual_year) if actual_year not in (None, "") else parsed_date.year
        except (TypeError, ValueError):
            issues.append("actual_year_invalid")
        else:
            if actual_year != parsed_date.year:
                issues.append("actual_year_date_mismatch")
            if parsed_date.year != target.year and not str(row.get("cross_year_reason") or "").strip():
                issues.append("cross_year_reason_missing")
            if abs(parsed_date.year - target.year) > 1:
                issues.append("cross_year_out_of_range")
    adapter_key = str(row.get("adapter_key") or "")
    try:
        urls = validate_direct_source_urls(adapter_key, row.get("urls") or {})
    except InventoryValidationError as exc:
        urls = None
        issues.append(f"direct_url_invalid:{exc}")
    if urls is not None:
        if DISCOVERY_ADAPTER_REGIONS.get(adapter_key) != target.country_region:
            issues.append("adapter_region_mismatch")
        if any(
            DISCOVERY_ADAPTER_REGIONS.get(evidence["source_provider"]) != target.country_region
            for evidence in urls.values()
        ):
            issues.append("url_provider_region_mismatch")
        if target.expectation_status == HistoricalRaceExpectationStatus.HELD:
            result_evidence = urls.get("result_url")
            if result_evidence is None:
                issues.append("held_direct_result_missing")
            elif result_evidence["source_provider"] not in PRIMARY_RESULT_PROVIDERS[target.country_region]:
                issues.append("held_primary_result_provider_missing")
        if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED and "cancellation_url" not in urls:
            issues.append("cancelled_evidence_missing")
    try:
        distance_evidence = parse_distance_evidence(
            str(row.get("distance_text") or target.distance_text or ""), target.country_region
        )
    except InventoryValidationError as exc:
        distance_evidence = None
        issues.append(f"distance_unit_invalid:{exc}")
    normalized = None
    if not issues and parsed_date and urls is not None and distance_evidence is not None:
        normalized = {
            "target_id": target.pk,
            "expected_target_sha256": str(row.get("expected_target_sha256") or ""),
            "inventory_manifest_sha256": str(row.get("inventory_manifest_sha256") or ""),
            "adapter_key": adapter_key,
            "local_date": parsed_date.isoformat(),
            "actual_year": actual_year,
            "cross_year_reason": str(row.get("cross_year_reason") or "").strip(),
            "urls": urls,
            "distance_evidence": distance_evidence,
        }
    return issues, normalized


def _read_selection_snapshot(
    path: str | Path,
    *,
    inventory_manifest_sha256: str,
) -> tuple[bytes, dict[str, Any], dict[int, dict[str, Any]]]:
    source = Path(path)
    try:
        selection_bytes = source.read_bytes()
        selection = json.loads(selection_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryValidationError("date discovery selection snapshot is unreadable") from exc
    if not isinstance(selection, dict) or selection.get("inventory_manifest_sha256") != inventory_manifest_sha256:
        raise InventoryValidationError("date discovery selection snapshot inventory mismatch")
    claimed_snapshot_sha = str(selection.get("snapshot_sha256") or "")
    snapshot_payload = dict(selection)
    snapshot_payload.pop("snapshot_sha256", None)
    actual_snapshot_sha = hashlib.sha256(canonical_json(snapshot_payload).encode("utf-8")).hexdigest()
    if claimed_snapshot_sha != actual_snapshot_sha:
        raise InventoryValidationError("date discovery selection snapshot SHA is invalid")
    selection_rows = selection.get("targets")
    if not isinstance(selection_rows, list) or not selection_rows:
        raise InventoryValidationError("date discovery selection snapshot has no targets")
    selection_by_id: dict[int, dict[str, Any]] = {}
    for row in selection_rows:
        try:
            target_id = int(row["target_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InventoryValidationError("date discovery selection has invalid target id") from exc
        if target_id in selection_by_id or not str(row.get("target_sha256") or "").strip():
            raise InventoryValidationError("date discovery selection target identities are invalid")
        selection_by_id[target_id] = row
    if int(selection.get("target_count", -1)) != len(selection_by_id):
        raise InventoryValidationError("date discovery selection target count is inconsistent")
    return selection_bytes, selection, selection_by_id


def build_provider_discovery_candidates(
    *,
    provider_rows: Iterable[dict[str, Any]],
    selection_snapshot_path: str | Path,
    inventory_manifest_sha256: str,
) -> dict[str, Any]:
    """Map source-specific edition records onto the immutable target selection."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(inventory_manifest_sha256 or "")):
        raise InventoryValidationError("date discovery inventory manifest SHA is invalid")
    _selection_bytes, _selection, selection_by_id = _read_selection_snapshot(
        selection_snapshot_path,
        inventory_manifest_sha256=inventory_manifest_sha256,
    )
    selection_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    for selected in selection_by_id.values():
        try:
            identity = (str(selected["series_key"]), int(selected["year"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise InventoryValidationError("date discovery selection target identity is incomplete") from exc
        if identity in selection_by_identity:
            raise InventoryValidationError("date discovery selection has duplicate series/year identity")
        selection_by_identity[identity] = selected

    candidates: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(provider_rows, start=1):
        if not isinstance(raw, dict):
            issues.append({"row_number": index, "code": "provider_row_not_object"})
            continue
        adapter_key = str(raw.get("adapter_key") or "").strip()
        try:
            edition_year = int(raw.get("edition_year"))
        except (TypeError, ValueError):
            issues.append({"row_number": index, "code": "edition_year_invalid"})
            continue
        series_key = str(raw.get("series_key") or "").strip()
        selected = selection_by_identity.get((series_key, edition_year))
        if selected is None:
            issues.append(
                {
                    "row_number": index,
                    "code": "target_not_in_selection",
                    "series_key": series_key,
                    "edition_year": edition_year,
                }
            )
            continue
        selected_region = str(selected.get("country_region") or "")
        if DISCOVERY_ADAPTER_REGIONS.get(adapter_key) != selected_region:
            issues.append(
                {
                    "row_number": index,
                    "code": "adapter_region_mismatch",
                    "series_key": series_key,
                    "edition_year": edition_year,
                    "adapter_key": adapter_key,
                    "country_region": selected_region,
                }
            )
            continue
        candidate = {
            "target_id": int(selected["target_id"]),
            "expected_target_sha256": str(selected["target_sha256"]),
            "inventory_manifest_sha256": inventory_manifest_sha256,
            "adapter_key": adapter_key,
            "local_date": str(raw.get("local_date") or "").strip(),
            "urls": raw.get("urls") if isinstance(raw.get("urls"), dict) else {},
            "distance_text": str(raw.get("distance_text") or "").strip(),
        }
        if raw.get("actual_year") not in (None, ""):
            candidate["actual_year"] = raw["actual_year"]
        if str(raw.get("cross_year_reason") or "").strip():
            candidate["cross_year_reason"] = str(raw["cross_year_reason"]).strip()
        candidates.append(candidate)
    return {"candidate_rows": candidates, "issues": issues}


def _successful_cached_source_urls(source_cache_bytes: bytes, request_ledger_bytes: bytes) -> set[str]:
    try:
        source_cache = json.loads(source_cache_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryValidationError("date discovery source cache manifest is invalid") from exc
    files = source_cache.get("files") if isinstance(source_cache, dict) else None
    if not isinstance(source_cache, dict) or source_cache.get("schema_version") != "1.0" or not isinstance(files, dict):
        raise InventoryValidationError("date discovery source cache manifest is invalid")
    successful: set[str] = set()
    try:
        lines = request_ledger_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise InventoryValidationError("date discovery request ledger is invalid") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InventoryValidationError(
                f"date discovery request ledger is invalid at line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise InventoryValidationError(
                f"date discovery request ledger row must be an object at line {line_number}"
            )
        if row.get("status") != "succeeded":
            continue
        identity = row.get("source_cache_identity")
        source_url = str(row.get("source_url") or "").strip()
        if not isinstance(identity, dict) or not source_url:
            raise InventoryValidationError("successful date discovery request is missing cache identity")
        path = str(identity.get("path") or "")
        if files.get(path) != identity or str(identity.get("source_url") or "").strip() != source_url:
            raise InventoryValidationError("date discovery request cache identity does not match manifest")
        successful.add(source_url)
    return successful


def build_date_source_discovery_artifact(
    *,
    candidate_rows: Iterable[dict[str, Any]],
    selection_snapshot_path: str | Path,
    output_dir: str | Path,
    inventory_manifest_sha256: str,
    source_cache_manifest_path: str | Path,
    request_ledger_path: str | Path,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", str(inventory_manifest_sha256 or "")):
        raise InventoryValidationError("date discovery inventory manifest SHA is invalid")
    source_cache_source = Path(source_cache_manifest_path)
    request_ledger_source = Path(request_ledger_path)
    try:
        source_cache_bytes = source_cache_source.read_bytes()
        request_ledger_bytes = request_ledger_source.read_bytes()
    except OSError as exc:
        raise InventoryValidationError("date discovery evidence inputs are unreadable") from exc
    selection_bytes, _selection, selection_by_id = _read_selection_snapshot(
        selection_snapshot_path,
        inventory_manifest_sha256=inventory_manifest_sha256,
    )
    successful_source_urls = _successful_cached_source_urls(source_cache_bytes, request_ledger_bytes)

    rows = list(candidate_rows)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            raise InventoryValidationError("date discovery candidate row must be an object")
        try:
            target_id = int(row.get("target_id"))
        except (TypeError, ValueError) as exc:
            raise InventoryValidationError("date discovery candidate has invalid target_id") from exc
        grouped[target_id].append(row)
    outside = sorted(set(grouped) - set(selection_by_id))
    if outside:
        raise InventoryValidationError(f"date discovery candidate is outside selection snapshot: {outside[0]}")
    targets = HistoricalRaceEventTarget.objects.select_related("race_series", "event").in_bulk(selection_by_id)
    ready_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    for target_id in sorted(selection_by_id):
        candidates = grouped.get(target_id) or []
        target = targets.get(target_id)
        issues: list[str] = []
        normalized = None
        if target is None:
            issues.append("target_missing")
        elif not candidates:
            issues.append("missing_candidate")
        elif len(candidates) != 1:
            issues.append("multiple_candidates")
        else:
            row = candidates[0]
            if target.artifact_sha256 != inventory_manifest_sha256 or str(
                row.get("inventory_manifest_sha256") or ""
            ) != inventory_manifest_sha256:
                issues.append("inventory_manifest_mismatch")
            actual_target_sha = target_identity(target)["target_sha256"]
            if selection_by_id[target_id]["target_sha256"] != actual_target_sha:
                issues.append("target_changed_after_selection")
            if str(row.get("expected_target_sha256") or "") != actual_target_sha:
                issues.append("target_changed_before_discovery")
            if target.resolution_status != HistoricalRaceResolutionStatus.PENDING or target.event_id:
                issues.append("target_not_pending_unmaterialized")
            candidate_issues, normalized = _candidate_issues(row, target)
            issues.extend(candidate_issues)
            if normalized:
                for role, evidence in normalized["urls"].items():
                    if evidence["url"] not in successful_source_urls:
                        issues.append(f"source_fetch_not_succeeded:{role}")
                if issues:
                    normalized = None
        status = "ready" if not issues and normalized else "gap"
        if normalized and status == "ready":
            ready_rows.append(normalized)
        review = {
            "target_id": target_id,
            "series_key": target.race_series.key if target else "",
            "year": target.year if target else "",
            "country_region": target.country_region if target else "",
            "status": status,
            "issues": "|".join(issues),
            "local_date": normalized["local_date"] if normalized else str(candidates[0].get("local_date") or "") if candidates else "",
            "operator_decision": "",
            "operator_notes": "",
        }
        review_rows.append(review)
        if status == "gap":
            gap_rows.append({key: review[key] for key in ("target_id", "series_key", "year", "country_region", "issues")})

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    candidates_path = root / "date_source_candidates.jsonl"
    review_path = root / "date_source_review.csv"
    gaps_path = root / "gap_ledger.csv"
    selection_path = root / "selection_snapshot.json"
    source_cache_path = root / "source_cache_manifest.json"
    request_ledger_copy_path = root / "request_ledger.jsonl"
    selection_path.write_bytes(selection_bytes)
    source_cache_path.write_bytes(source_cache_bytes)
    request_ledger_copy_path.write_bytes(request_ledger_bytes)
    _write_jsonl(candidates_path, ready_rows)
    _write_csv(
        review_path,
        review_rows,
        [
            "target_id",
            "series_key",
            "year",
            "country_region",
            "status",
            "issues",
            "local_date",
            "operator_decision",
            "operator_notes",
        ],
    )
    _write_csv(gaps_path, gap_rows, ["target_id", "series_key", "year", "country_region", "issues"])
    artifacts = {
        "selection_snapshot": file_identity(selection_path, relative_to=root).as_dict(),
        "source_cache_manifest": file_identity(source_cache_path, relative_to=root).as_dict(),
        "request_ledger": file_identity(request_ledger_copy_path, relative_to=root).as_dict(),
        "date_source_candidates": file_identity(candidates_path, relative_to=root).as_dict(),
        "date_source_review": file_identity(review_path, relative_to=root).as_dict(),
        "gap_ledger": file_identity(gaps_path, relative_to=root).as_dict(),
    }
    manifest = {
        "schema_version": DATE_SOURCE_DISCOVERY_SCHEMA_VERSION,
        "inventory_manifest_sha256": inventory_manifest_sha256,
        "source_cache_manifest_identity": artifacts["source_cache_manifest"],
        "request_ledger_identity": artifacts["request_ledger"],
        "selection_snapshot_identity": artifacts["selection_snapshot"],
        "input_target_count": len(selection_by_id),
        "candidate_count": len(ready_rows),
        "gap_count": len(gap_rows),
        "artifacts": artifacts,
    }
    _write_json(root / "manifest.json", manifest)
    _write_json(
        root / "approval.json",
        {
            "status": "pending",
            "manifest_identity": file_identity(root / "manifest.json", relative_to=root).as_dict(),
            "approved_by": "",
            "approved_at": "",
            "approved_target_ids": [],
        },
    )
    return {
        "output_dir": str(root),
        "candidate_count": len(ready_rows),
        "gap_count": len(gap_rows),
        "manifest": str(root / "manifest.json"),
        "approval": str(root / "approval.json"),
    }


def validate_date_source_discovery_artifact(
    artifact_dir: str | Path, approval_path: str | Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(artifact_dir)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise InventoryValidationError("date discovery manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != DATE_SOURCE_DISCOVERY_SCHEMA_VERSION:
        raise InventoryValidationError("date discovery manifest schema is unsupported")
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    required = {
        "selection_snapshot",
        "source_cache_manifest",
        "request_ledger",
        "date_source_candidates",
        "date_source_review",
        "gap_ledger",
    }
    if required - set(artifacts):
        raise InventoryValidationError("date discovery manifest is incomplete")
    for name, expected in artifacts.items():
        if not isinstance(expected, dict):
            raise InventoryValidationError(f"date discovery artifact identity is invalid: {name}")
        path = _artifact_path(root, expected.get("path"), label=f"date discovery artifact {name}")
        if not path.is_file() or file_identity(path, relative_to=root).as_dict() != expected:
            raise InventoryValidationError(f"date discovery artifact changed after manifest: {name}")
    approval = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    if approval.get("manifest_identity") != file_identity(manifest_path, relative_to=root).as_dict():
        raise InventoryValidationError("date discovery approval does not match manifest")
    if approval.get("status") != "approved" or not str(approval.get("approved_by") or "").strip() or not str(
        approval.get("approved_at") or ""
    ).strip():
        raise InventoryValidationError("date discovery artifact is not approved")
    candidate_path = _artifact_path(
        root,
        artifacts["date_source_candidates"]["path"],
        label="date discovery candidates",
    )
    candidate_ids = [int(row["target_id"]) for row in _read_jsonl(candidate_path)]
    if len(candidate_ids) != int(manifest.get("candidate_count", -1)):
        raise InventoryValidationError("date discovery manifest candidate count is inconsistent")
    gap_path = _artifact_path(root, artifacts["gap_ledger"]["path"], label="date discovery gaps")
    with gap_path.open(encoding="utf-8-sig", newline="") as handle:
        gap_count = sum(1 for _row in csv.DictReader(handle))
    if gap_count != int(manifest.get("gap_count", -1)):
        raise InventoryValidationError("date discovery manifest gap count is inconsistent")
    if len(candidate_ids) + gap_count != int(manifest.get("input_target_count", -1)):
        raise InventoryValidationError("date discovery manifest input target count is inconsistent")
    approved_ids = approval.get("approved_target_ids")
    if not isinstance(approved_ids, list) or not all(isinstance(value, int) for value in approved_ids) or len(
        approved_ids
    ) != len(set(approved_ids)):
        raise InventoryValidationError("date discovery approval target ids are invalid")
    if not approved_ids:
        raise InventoryValidationError("date discovery approval has no targets")
    if not set(approved_ids).issubset(candidate_ids):
        raise InventoryValidationError("date discovery approval includes gap or unknown targets")
    return manifest, approval


def _locked_date_discovery_targets(target_ids: Iterable[int]):
    # PostgreSQL rejects FOR UPDATE on the nullable side of an outer join.
    # event_id is available without joining the optional event relation.
    return (
        HistoricalRaceEventTarget.objects.select_for_update()
        .select_related("race_series")
        .filter(pk__in=target_ids)
    )


def apply_date_source_discovery_artifact(
    *, artifact_dir: str | Path, approval_path: str | Path
) -> dict[str, Any]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("historical race backfill is disabled")
    root = Path(artifact_dir)
    manifest, approval = validate_date_source_discovery_artifact(root, approval_path)
    actor = get_user_model().objects.filter(username=str(approval["approved_by"])).first()
    if actor is None:
        raise InventoryValidationError("date discovery approval operator does not exist")
    candidates_path = _artifact_path(
        root,
        manifest["artifacts"]["date_source_candidates"]["path"],
        label="date discovery candidates",
    )
    approved_ids = {int(value) for value in approval["approved_target_ids"]}
    candidates = [row for row in _read_jsonl(candidates_path) if int(row["target_id"]) in approved_ids]
    if len(candidates) != len(approved_ids):
        raise InventoryValidationError("date discovery approved candidates are incomplete")
    manifest_sha = file_identity(root / "manifest.json", relative_to=root).sha256
    changes: list[dict[str, Any]] = []
    with transaction.atomic():
        targets = {target.pk: target for target in _locked_date_discovery_targets(approved_ids)}
        if set(targets) != approved_ids:
            raise InventoryValidationError("date discovery target disappeared after approval")
        for candidate in candidates:
            target = targets[int(candidate["target_id"])]
            if target_identity(target)["target_sha256"] != candidate["expected_target_sha256"]:
                raise InventoryValidationError(f"date discovery target changed after approval: {target.pk}")
            if target.artifact_sha256 != manifest["inventory_manifest_sha256"]:
                raise InventoryValidationError(f"date discovery inventory changed after approval: {target.pk}")
            if target.resolution_status != HistoricalRaceResolutionStatus.PENDING or target.event_id:
                raise InventoryValidationError(f"date discovery target is no longer pending/unmaterialized: {target.pk}")
        for candidate in candidates:
            target = targets[int(candidate["target_id"])]
            before = target_identity(target)["target_sha256"]
            refs = dict(target.source_refs or {})
            for key, evidence in candidate["urls"].items():
                refs[key] = evidence["url"]
            refs["detail_discovery"] = {
                "schema_version": DATE_SOURCE_DISCOVERY_SCHEMA_VERSION,
                "manifest_sha256": manifest_sha,
                "source_cache_manifest_identity": manifest["source_cache_manifest_identity"],
                "request_ledger_identity": manifest["request_ledger_identity"],
                "adapter_key": candidate["adapter_key"],
                "actual_year": candidate["actual_year"],
                "cross_year_reason": candidate["cross_year_reason"],
                "urls": candidate["urls"],
                "distance_evidence": candidate["distance_evidence"],
            }
            target.local_date = date.fromisoformat(candidate["local_date"])
            target.source_refs = refs
            target.resolution_status = HistoricalRaceResolutionStatus.READY
            target.save(update_fields={"local_date", "source_refs", "resolution_status"})
            materialize_historical_event(target, actor=actor)
            target.refresh_from_db()
            changes.append(
                {
                    "target_id": target.pk,
                    "before": before,
                    "after": target_identity(target)["target_sha256"],
                }
            )
        OperationLog.objects.create(
            admin=actor,
            action_type="historical_race_date_source_applied",
            target_type="date_source_discovery_artifact",
            target_id=manifest_sha,
            detail=canonical_json(
                {
                    "manifest_sha256": manifest_sha,
                    "inventory_manifest_sha256": manifest["inventory_manifest_sha256"],
                    "target_sha256_changes": changes,
                }
            ),
        )
    return {
        "manifest_sha256": manifest_sha,
        "applied_count": len(changes),
        "target_sha256_changes": changes,
    }
