#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from historical_race_detail_http import controlled_http_get
from package_historical_race_detail_candidates import SOURCE_PROVIDERS, package_candidates
from prepare_cached_historical_race_details import (
    parse_equibase_yearbook,
    parse_jra_detail,
    parse_nsa_pdf,
)
from prepare_france_zeturf_race_detail_candidates import _parse_page as parse_zeturf_detail
from prepare_hkjc_race_detail_candidates import (
    _converter as hkjc_converter,
    _parse_local_result_page as parse_hkjc_detail,
)
from prepare_irishracing_race_detail_candidates import _parse_result_page as parse_irishracing_detail
from prepare_uk_sportinglife_race_detail_candidates import _parse_detail_page as parse_sportinglife_detail
from prepare_us_equibase_archived_race_detail_candidates import (
    _parse_chart_text as parse_equibase_chart_text,
    _pdf_text as read_equibase_chart_text,
)
from race_event_source_cache import ensure_source_cache_manifest, write_source_cache


STAGES = ("discover", "cache", "parse", "validate", "package")
REGION_SOURCES = {
    "japan": ("jra", "netkeiba"),
    "hong_kong": ("hkjc",),
    "united_kingdom": ("racing_post", "sporting_life", "irishracing"),
    "france": ("france_galop", "zeturf", "irishracing"),
    "united_states": ("equibase_chart", "equibase_archive", "horse_racing_nation"),
}
PARSE_CORES = {
    region: "historical_race_detail_adapters.parse_cached_sources"
    for region in REGION_SOURCES
}
PROVIDER_ALIASES = {
    "jra": "jra",
    "hkjc": "hkjc",
    "sporting_life": "sporting_life",
    "uk_sportinglife": "sporting_life",
    "irishracing": "irishracing",
    "uk_irishracing": "uk_irishracing",
    "france_irishracing": "france_irishracing",
    "zeturf": "zeturf",
    "equibase": "equibase",
    "equibase_chart": "equibase_chart",
    "equibase_archive": "equibase_chart",
    "nsa": "nsa",
}
DEFAULT_SOURCE_NAMES = {
    "jra": "jra_official_result_page",
    "hkjc": "hkjc_results_all_zh_hk",
    "sporting_life": "sporting_life",
    "uk_irishracing": "irishracing_uk",
    "france_irishracing": "irishracing_france",
    "zeturf": "zeturf",
    "equibase": "equibase_yearbook",
    "equibase_chart": "equibase_pdf_chart",
    "nsa": "nsa_official_result_pdf",
}
ADAPTER_SPECS = {
    (region, stage): {
        "region": region,
        "stage": stage,
        "sources": list(sources),
        "execution": "internal_callable",
        "callable": (
            "historical_race_detail_adapters.discover_sources"
            if stage == "discover"
            else "historical_race_detail_adapters.cache_sources"
            if stage == "cache"
            else PARSE_CORES[region]
            if stage == "parse"
            else "historical_race_detail_runner_v2.validate_complete_target"
            if stage == "validate"
            else "package_historical_race_detail_candidates.package_candidates"
        ),
    }
    for region, sources in REGION_SOURCES.items()
    for stage in STAGES
}


class DetailAdapterError(RuntimeError):
    pass


def get_adapter_spec(region: str, stage: str) -> dict:
    spec = ADAPTER_SPECS.get((region, stage))
    if spec is None:
        raise DetailAdapterError(f"unsupported detail adapter: {region}/{stage}")
    return json.loads(json.dumps(spec))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DetailAdapterError(f"adapter input is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DetailAdapterError(f"adapter input must be an object: {path}")
    return value


def _safe_file(path: Path, *, root: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise DetailAdapterError(f"adapter path is unsafe: {path}")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DetailAdapterError(f"adapter path escapes approved root: {path}") from exc
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise DetailAdapterError(f"adapter symlink path is forbidden: {current}")
        if not current.exists():
            raise DetailAdapterError(f"adapter path is missing: {current}")
    if not path.is_file():
        raise DetailAdapterError(f"adapter path is not a file: {path}")
    return path


def _file_identity(path: Path) -> dict:
    body = path.read_bytes()
    return {"path": str(path), "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def supported_parse_providers() -> tuple[str, ...]:
    return tuple(sorted(PROVIDER_ALIASES))


def _events_by_target(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = {}
    for row in rows:
        target_id = str(row.get("target_id") or "")
        if not target_id or target_id in result:
            raise DetailAdapterError("event adapter input has invalid target IDs")
        result[target_id] = row
    return result


def discover_sources(descriptor: dict, *, plan_root: Path) -> dict:
    inputs = descriptor["adapter_inputs"]
    event_path = _safe_file(Path(inputs["events_csv"]), root=plan_root)
    fragment_path = _safe_file(Path(inputs["source_fragment"]), root=plan_root)
    events = _events_by_target(event_path)
    fragment = _read_json(fragment_path)
    requests = fragment.get("requests")
    if not isinstance(requests, list) or not requests:
        raise DetailAdapterError("source fragment has no structured requests")
    target_sha = {str(row["target_id"]): row["target_sha256"] for row in descriptor["targets"]}
    normalized = []
    seen_urls: set[str] = set()
    for request in requests:
        if not isinstance(request, dict):
            raise DetailAdapterError("source request is invalid")
        target_id = str(request.get("target_id") or "")
        source_url = str(request.get("source_url") or "")
        provider = str(request.get("source_provider") or "")
        if (
            target_id not in events
            or target_sha.get(target_id) != request.get("target_sha256")
            or request.get("region") != descriptor["region"]
            or provider not in descriptor["recipe"]["source_chain"]
            or source_url in seen_urls
            or urlsplit(source_url).scheme != "https"
        ):
            raise DetailAdapterError("source request is outside the approved target/source mapping")
        seen_urls.add(source_url)
        normalized.append(json.loads(json.dumps(request)))
    return {
        "requests": normalized,
        "events_csv": str(event_path),
        "source_fragment_identity": _file_identity(fragment_path),
    }


def _fixture_body(request: dict, *, plan_root: Path) -> bytes | None:
    identity = request.get("fixture_identity")
    if identity is None:
        return None
    if not isinstance(identity, dict):
        raise DetailAdapterError("fixture identity is invalid")
    path = _safe_file(Path(str(identity.get("path") or "")), root=plan_root)
    body = path.read_bytes()
    if len(body) != identity.get("size") or hashlib.sha256(body).hexdigest() != identity.get("sha256"):
        raise DetailAdapterError("fixture source identity changed")
    return body


def cache_sources(
    descriptor: dict,
    *,
    discover_artifact: dict,
    plan_root: Path,
    run_root: Path,
) -> dict:
    cache_root = run_root / "source-cache"
    cache_root.mkdir(exist_ok=True)
    manifest_path = ensure_source_cache_manifest(cache_root / "placeholder.cache")
    identities = []
    for request in discover_artifact["requests"]:
        body = _fixture_body(request, plan_root=plan_root)
        if body is None:
            body = controlled_http_get(
                request["source_url"],
                policy=descriptor["request_policy"],
                shard_id=descriptor["shard_id"],
                shard_state_path=run_root / "request-budget.json",
                host_state_root=Path(descriptor["outputs"]["host_last_start"]).parent,
                timeout=int(descriptor.get("timeout_seconds") or 30),
                headers={"User-Agent": "UmaFansBot/1.0"},
            )
        suffix = Path(urlsplit(request["source_url"]).path).suffix or ".html"
        filename = hashlib.sha256(request["source_url"].encode()).hexdigest() + suffix
        identities.append(
            write_source_cache(cache_root / filename, body, source_url=request["source_url"])
        )
    return {
        "source_cache_manifest": str(manifest_path),
        "source_cache_identities": identities,
        "request_count": len(identities),
    }


def _cached_sources(manifest_path: Path) -> dict[str, Path]:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise DetailAdapterError("source cache manifest is unsafe or missing")
    manifest = _read_json(manifest_path)
    files = manifest.get("files")
    if manifest.get("schema_version") != "1.0" or not isinstance(files, dict):
        raise DetailAdapterError("source cache manifest is invalid")
    root = manifest_path.parent.resolve()
    cached = {}
    for identity in files.values():
        if not isinstance(identity, dict):
            raise DetailAdapterError("source cache identity is invalid")
        relative = Path(str(identity.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise DetailAdapterError("source cache path is unsafe")
        path = root / relative
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise DetailAdapterError("source cache symlink is forbidden")
        if not path.is_file():
            raise DetailAdapterError("source cache file is missing")
        body = path.read_bytes()
        if len(body) != identity.get("size") or hashlib.sha256(body).hexdigest() != identity.get("sha256"):
            raise DetailAdapterError("source cache identity changed")
        source_url = str(identity.get("source_url") or "")
        if not source_url or source_url in cached:
            raise DetailAdapterError("source cache URL identity is invalid")
        cached[source_url] = path
    return cached


def _provider_for_request(request: dict, *, region: str) -> str:
    raw = str(request.get("source_provider") or "")
    provider = PROVIDER_ALIASES.get(raw)
    if provider == "irishracing":
        provider = "uk_irishracing" if region == "united_kingdom" else "france_irishracing"
    if provider is None:
        raise DetailAdapterError(f"unsupported offline detail provider: {raw}")
    return provider


def _parse_cached_request(
    request: dict,
    *,
    event: dict,
    region: str,
    source_path: Path,
) -> tuple[list[dict], list[dict], dict, str]:
    provider = _provider_for_request(request, region=region)
    source_url = str(request["source_url"])
    if provider == "jra":
        runners, results, metadata = parse_jra_detail(source_path.read_bytes(), source_url=source_url)
    elif provider == "hkjc":
        race_no = str((parse_qs(urlsplit(source_url).query).get("RaceNo") or [""])[-1])
        race_no = race_no or str(request.get("race_no") or "")
        race_title = str(
            request.get("race_title_hant")
            or event.get("original_name")
            or event.get("slug")
            or "approved historical race"
        )
        if not race_no:
            raise DetailAdapterError("HKJC cached request has no race number")
        runners, results, metadata = parse_hkjc_detail(
            source_path.read_text(encoding="utf-8", errors="replace"),
            source_url=source_url,
            race_no=race_no,
            race_title_hant=race_title,
            converter=hkjc_converter(),
        )
    elif provider == "sporting_life":
        runners, results, metadata = parse_sportinglife_detail(
            source_path.read_text(encoding="utf-8", errors="replace"), source_url=source_url
        )
    elif provider in {"uk_irishracing", "france_irishracing"}:
        runners, results, metadata = parse_irishracing_detail(
            source_path.read_text(encoding="utf-8", errors="replace"), source_url=source_url
        )
    elif provider == "zeturf":
        runners, results, metadata = parse_zeturf_detail(
            source_path.read_text(encoding="utf-8", errors="replace"), source_url=source_url
        )
    elif provider == "equibase":
        runners, results, metadata = parse_equibase_yearbook(
            source_path.read_text(encoding="utf-8", errors="replace"), source_url=source_url
        )
    elif provider == "equibase_chart":
        runners, results, metadata = parse_equibase_chart_text(
            read_equibase_chart_text(source_path), source_url=source_url
        )
    else:
        runners, results, metadata = parse_nsa_pdf(source_path, source_url=source_url)
    if not runners or not results:
        raise DetailAdapterError(f"{provider} offline detail output is incomplete")
    source_name = str(request.get("source_name") or DEFAULT_SOURCE_NAMES[provider])
    return runners, results, metadata, source_name


def parse_cached_sources(
    descriptor: dict,
    *,
    cache_artifact: dict,
    run_root: Path,
) -> dict:
    inputs = descriptor["adapter_inputs"]
    events = _events_by_target(Path(inputs["events_csv"]))
    fragment = _read_json(Path(inputs["source_fragment"]))
    requests = fragment.get("requests")
    if not isinstance(requests, list) or not requests:
        raise DetailAdapterError("source fragment has no parse requests")
    cached = _cached_sources(Path(cache_artifact["source_cache_manifest"]))
    records = []
    gaps = []
    for request in requests:
        if not isinstance(request, dict):
            raise DetailAdapterError("source parse request is invalid")
        target_id = str(request.get("target_id") or "")
        source_url = str(request.get("source_url") or "")
        event = events.get(target_id)
        source_path = cached.get(source_url)
        if event is None or source_path is None:
            gaps.append(
                {
                    "target_id": target_id,
                    "target_sha256": str(request.get("target_sha256") or ""),
                    "reason_code": "source_not_cached" if source_path is None else "target_not_found",
                    "source_url": source_url,
                }
            )
            continue
        try:
            runners, results, metadata, source_name = _parse_cached_request(
                request,
                event=event,
                region=str(descriptor["region"]),
                source_path=source_path,
            )
        except Exception as exc:
            gaps.append(
                {
                    "target_id": target_id,
                    "target_sha256": str(request.get("target_sha256") or ""),
                    "reason_code": "parse_failed",
                    "provider": request.get("source_provider"),
                    "source_url": source_url,
                    "error": str(exc),
                }
            )
            continue
        records.append(
            {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": source_name,
                "source_url": source_url,
                "modules": {
                    "runners": {"is_complete": True, "items": runners},
                    "results": {"is_complete": True, "items": results},
                },
                "metadata": metadata,
            }
        )
    candidate_path = run_root / "parsed-candidates.jsonl"
    candidate_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in records),
        encoding="utf-8",
    )
    gap_path = run_root / "parse-gaps.json"
    gap_path.write_text(json.dumps(gaps, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "candidate_jsonl": str(candidate_path),
        "parse_gap_json": str(gap_path),
        "candidate_count": len(records),
        "runner_count": sum(len(row["modules"]["runners"]["items"]) for row in records),
        "result_count": sum(len(row["modules"]["results"]["items"]) for row in records),
    }


def read_candidates(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise DetailAdapterError("parsed candidate row is invalid")
                rows.append(value)
    return rows


def _plan_inventory_sha256(descriptor: dict, events: dict[str, dict]) -> str:
    plan_identities = [
        identity
        for identity in descriptor.get("identities") or []
        if isinstance(identity, dict) and identity.get("role") == "plan"
    ]
    if len(plan_identities) == 1:
        value = str(plan_identities[0].get("sha256") or "")
        if len(value) == 64 and all(character in "0123456789abcdef" for character in value.casefold()):
            return value
        raise DetailAdapterError("descriptor plan identity SHA-256 is invalid")
    if plan_identities:
        raise DetailAdapterError("descriptor must contain exactly one plan identity")

    # Direct helper tests predating descriptor identity wiring supply an already-bound event SHA.
    legacy_values = {str(row.get("inventory_artifact_sha256") or "") for row in events.values()}
    if len(legacy_values) == 1:
        value = next(iter(legacy_values))
        if len(value) == 64 and all(character in "0123456789abcdef" for character in value.casefold()):
            return value
    raise DetailAdapterError("descriptor plan identity is required for staged events")


def _stage_validated_events(
    descriptor: dict,
    *,
    candidate_jsonl: Path,
    run_root: Path,
) -> tuple[Path, dict[str, dict], dict[str, dict]]:
    event_path = Path(descriptor["adapter_inputs"]["events_csv"])
    with event_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    events = {}
    for row in rows:
        target_id = str(row.get("target_id") or "")
        if not target_id or target_id in events:
            raise DetailAdapterError("event adapter input has invalid target IDs")
        events[target_id] = row

    source_fragment_path = descriptor.get("adapter_inputs", {}).get("source_fragment")
    approved_requests: dict[str, list[dict]] = {}
    if source_fragment_path:
        fragment = _read_json(Path(source_fragment_path))
        requests = fragment.get("requests")
        if not isinstance(requests, list):
            raise DetailAdapterError("source fragment has no package requests")
        for request in requests:
            if not isinstance(request, dict):
                raise DetailAdapterError("source fragment package request is invalid")
            target_id = str(request.get("target_id") or "")
            if not target_id:
                raise DetailAdapterError("source fragment package target is invalid")
            approved_requests.setdefault(target_id, []).append(request)

    inventory_sha256 = _plan_inventory_sha256(descriptor, events)
    requires_validation_evidence = any(
        isinstance(identity, dict) and identity.get("role") == "plan"
        for identity in descriptor.get("identities") or []
    )
    validated_by_target: dict[str, dict] = {}
    approved_by_target: dict[str, dict] = {}
    for candidate in read_candidates(candidate_jsonl):
        key = (int(candidate.get("year") or 0), str(candidate.get("slug") or ""))
        event = next(
            (
                row
                for row in rows
                if (int(row.get("year") or 0), str(row.get("slug") or "")) == key
            ),
            None,
        )
        if event is None:
            raise DetailAdapterError(f"validated candidate is outside event input: {key}")
        target_id = str(event["target_id"])
        if target_id in validated_by_target:
            raise DetailAdapterError(f"duplicate validated candidate target: {target_id}")
        candidate_target_sha = str(candidate.get("target_sha256") or "")
        if candidate_target_sha and candidate_target_sha != event.get("target_sha256"):
            raise DetailAdapterError(f"validated candidate target SHA changed: {target_id}")
        validation = candidate.get("validation")
        if isinstance(validation, dict):
            if (
                validation.get("status") != "complete"
                or str(validation.get("target_id") or "") != target_id
            ):
                raise DetailAdapterError(f"validated candidate evidence is invalid: {target_id}")
            validation_event = validation.get("event")
            if not isinstance(validation_event, dict) or validation_event.get("source_url") != candidate.get(
                "source_url"
            ):
                raise DetailAdapterError(f"validated candidate source changed: {target_id}")
        elif requires_validation_evidence:
            raise DetailAdapterError(f"package candidate was not validated: {target_id}")
        requests = approved_requests.get(target_id, [])
        if requests:
            matches = [
                request
                for request in requests
                if request.get("source_url") == candidate.get("source_url")
                and request.get("source_name") == candidate.get("source_name")
                and str(request.get("target_sha256") or "")
                == str(event.get("target_sha256") or "")
            ]
            if len(matches) != 1:
                raise DetailAdapterError(
                    f"validated candidate differs from approved source: {target_id}"
                )
            approved_by_target[target_id] = matches[0]
        validated_by_target[target_id] = candidate

    for target_id, event in events.items():
        event["inventory_artifact_sha256"] = inventory_sha256
        candidate = validated_by_target.get(target_id)
        validation = (candidate or {}).get("validation")
        validation_event = (validation.get("event") or {}) if isinstance(validation, dict) else {}
        validated_distance = str(validation_event.get("distance") or "").strip()
        if "distance_text" in fieldnames and not str(event.get("distance_text") or "").strip():
            event["distance_text"] = validated_distance
        approved = approved_by_target.get(target_id)
        if approved is not None:
            package_provider = SOURCE_PROVIDERS.get(str(approved.get("source_name") or ""))
            if not package_provider:
                raise DetailAdapterError(f"approved package provider is unavailable: {target_id}")
            try:
                source_refs = json.loads(event.get("source_refs") or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise DetailAdapterError(f"event source refs are invalid: {target_id}") from exc
            if not isinstance(source_refs, dict):
                raise DetailAdapterError(f"event source refs are invalid: {target_id}")
            discovery = source_refs.setdefault("detail_discovery", {})
            if not isinstance(discovery, dict):
                raise DetailAdapterError(f"event detail discovery is invalid: {target_id}")
            urls = discovery.setdefault("urls", {})
            if not isinstance(urls, dict):
                raise DetailAdapterError(f"event detail discovery URLs are invalid: {target_id}")
            approved_result = {
                "url": approved["source_url"],
                "source_provider": package_provider,
            }
            existing_result = urls.get("result_url")
            if isinstance(existing_result, dict):
                for key, value in approved_result.items():
                    if existing_result.get(key) not in (None, "", value):
                        raise DetailAdapterError(f"event approved result URL conflicts: {target_id}")
                approved_result = {**existing_result, **approved_result}
            elif existing_result is not None:
                raise DetailAdapterError(f"event approved result URL is invalid: {target_id}")
            urls["result_url"] = approved_result
            discovery.setdefault("adapter_key", approved["source_provider"])
            event["source_refs"] = json.dumps(
                source_refs,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )

    staged_path = run_root / "staged-events.csv"
    with staged_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return staged_path, events, validated_by_target


def _read_gap_rows(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file():
        raise DetailAdapterError(f"gap artifact is unsafe or missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DetailAdapterError(f"gap artifact is unreadable: {path}") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise DetailAdapterError(f"gap artifact must contain an array of objects: {path}")
    return value


def _event_source_url(event: dict) -> str:
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    return str(
        ((((source_refs.get("detail_discovery") or {}).get("urls") or {}).get("result_url") or {}).get("url"))
        or ""
    )


def _normalize_package_gaps(
    *,
    result: dict,
    events: dict[str, dict],
    gap_artifacts: list[tuple[str, Path]],
    event_path: Path,
    cache_manifest: Path,
) -> list[dict]:
    event_identity = _file_identity(event_path)
    cache_identity = _file_identity(cache_manifest)
    record_targets = {str(record["target_id"]) for record in result["records"]}
    explicit_by_target: dict[str, dict] = {}
    artifact_identity_by_target: dict[str, tuple[str, dict]] = {}
    for artifact_name, path in gap_artifacts:
        artifact_identity = _file_identity(path)
        for row in _read_gap_rows(path):
            target_id = str(row.get("target_id") or "")
            if target_id not in events or target_id in explicit_by_target:
                raise DetailAdapterError("gap target is outside scope or duplicated")
            if target_id in record_targets:
                raise DetailAdapterError("target cannot be both packaged and a gap")
            explicit_by_target[target_id] = row
            artifact_identity_by_target[target_id] = (artifact_name, artifact_identity)

    normalized = []
    for default_gap in result["gaps"]:
        target_id = str(default_gap["target_id"])
        event = events[target_id]
        source = explicit_by_target.pop(target_id, default_gap)
        target_sha256 = str(event.get("target_sha256") or "")
        supplied_sha256 = str(source.get("target_sha256") or "")
        if supplied_sha256 and supplied_sha256 != target_sha256:
            raise DetailAdapterError(f"gap target SHA changed: {target_id}")
        reason_code = str(source.get("reason_code") or source.get("reason") or "missing_candidate")
        if not reason_code or reason_code == "source_exhausted":
            raise DetailAdapterError(f"recoverable package gap reason is invalid: {target_id}")
        source_url = str(source.get("source_url") or _event_source_url(event))
        if not source_url:
            raise DetailAdapterError(f"package gap source URL is missing: {target_id}")
        raw_error = source.get("error")
        error = (
            copy.deepcopy(raw_error)
            if isinstance(raw_error, dict)
            else {
                "type": "DetailAdapterError" if raw_error else "PackageGap",
                "message": str(raw_error or reason_code),
            }
        )
        error_identity = source.get("error_identity")
        if not isinstance(error_identity, dict) or len(str(error_identity.get("sha256") or "")) != 64:
            error_identity = {
                "sha256": hashlib.sha256(
                    json.dumps(error, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                ).hexdigest()
            }
        evidence_identities = copy.deepcopy(source.get("evidence_identities") or {})
        if not isinstance(evidence_identities, dict):
            raise DetailAdapterError(f"package gap evidence identities are invalid: {target_id}")
        artifact_entry = artifact_identity_by_target.get(target_id)
        if artifact_entry is not None:
            artifact_name, artifact_identity = artifact_entry
            evidence_identities.setdefault(artifact_name, artifact_identity)
        evidence_identities.setdefault("events_csv", event_identity)
        evidence_identities.setdefault("source_cache_manifest", cache_identity)
        normalized.append(
            {
                **{
                    key: copy.deepcopy(value)
                    for key, value in source.items()
                    if key not in {"reason", "reason_code", "target_id", "target_sha256", "source_url", "error", "error_identity", "evidence_identities"}
                },
                "target_id": int(target_id),
                "target_sha256": target_sha256,
                "year": int(event["year"]),
                "slug": str(event["slug"]),
                "reason_code": reason_code,
                "source_url": source_url,
                "error": error,
                "error_identity": error_identity,
                "evidence_identities": evidence_identities,
            }
        )
    if explicit_by_target:
        raise DetailAdapterError("gap targets are not missing from the validated package")
    accounted_targets = record_targets | {str(row["target_id"]) for row in normalized}
    if accounted_targets != set(events) or len(record_targets) + len(normalized) != len(events):
        raise DetailAdapterError("package target denominator was not conserved")
    return sorted(normalized, key=lambda row: row["target_id"])


def package_validated_sources(
    descriptor: dict,
    *,
    candidate_jsonl: Path,
    cache_manifest: Path,
    parse_gap_json: Path | None = None,
    validation_gap_json: Path | None = None,
    run_root: Path,
) -> dict:
    staged_event_csv, staged_events, validated_by_target = _stage_validated_events(
        descriptor,
        candidate_jsonl=candidate_jsonl,
        run_root=run_root,
    )
    result = package_candidates(
        event_csv_paths=[staged_event_csv],
        candidate_jsonl_paths=[candidate_jsonl],
        source_cache_manifest_paths=[cache_manifest],
    )
    for record in result["records"]:
        target_id = str(record["target_id"])
        candidate = validated_by_target[target_id]
        event = staged_events[target_id]
        validation_event = (candidate.get("validation") or {}).get("event") or {}
        distance_text = str(validation_event.get("distance") or event.get("distance_text") or "").strip()
        provenance = validation_event.get("distance_provenance")
        if distance_text and not isinstance(provenance, dict):
            provenance = {
                "source": "event_csv.distance_text",
                "original_text": distance_text,
                "source_url": record["source_url"],
            }
        if distance_text:
            record["distance_text"] = distance_text
            record["distance_provenance"] = provenance
    gap_artifacts = [
        (name, path)
        for name, path in (
            ("parse_gaps", parse_gap_json),
            ("validation_gaps", validation_gap_json),
        )
        if path is not None
    ]
    result["gaps"] = _normalize_package_gaps(
        result=result,
        events=staged_events,
        gap_artifacts=gap_artifacts,
        event_path=staged_event_csv,
        cache_manifest=cache_manifest,
    )
    scope_count = len(staged_events)
    record_count = len(result["records"])
    gap_count = len(result["gaps"])
    manifest_path = run_root / "package-manifest.json"
    manifest = {
        "schema_version": "2.0",
        "artifact_kind": "historical_race_detail_package",
        "scope_count": scope_count,
        "record_count": record_count,
        "gap_count": gap_count,
        "accounted_count": record_count + gap_count,
        "records": result["records"],
        "gaps": result["gaps"],
        "staged_event_identity": _file_identity(staged_event_csv),
        "candidate_identity": _file_identity(candidate_jsonl),
        "source_cache_manifest_identity": _file_identity(cache_manifest),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "package_manifest": str(manifest_path),
        "staged_event_csv": str(staged_event_csv),
        "scope_count": scope_count,
        "record_count": record_count,
        "gap_count": gap_count,
        "accounted_count": record_count + gap_count,
    }
