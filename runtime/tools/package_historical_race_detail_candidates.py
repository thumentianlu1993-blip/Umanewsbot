#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlparse


SOURCE_PROVIDERS = {
    "jra_official_result_page": "jra",
    "netkeiba": "netkeiba",
    "hkjc_results_all_zh_hk": "hkjc",
    "sporting_life": "uk_sportinglife",
    "irishracing_uk": "uk_irishracing",
    "irishracing_france": "france_irishracing",
    "horse_racing_nation": "us_hrn",
    "equibase_pdf_chart": "equibase",
    "equibase_yearbook": "equibase",
    "nsa_official_result_pdf": "nsa",
    "zeturf": "zeturf",
}


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.lower())


def _approved_supplemental_source(event: dict, *, provider: str | None, source_url: str) -> dict | None:
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    discovery = source_refs.get("detail_discovery") or {}
    for supplemental in discovery.get("approved_detail_sources") or []:
        if (
            isinstance(supplemental, dict)
            and supplemental.get("url") == source_url
            and supplemental.get("source_provider") == provider
            and _is_sha256(supplemental.get("artifact_manifest_sha256"))
            and _is_sha256((supplemental.get("source_cache_identity") or {}).get("sha256"))
        ):
            return supplemental
    return None


def source_matches_event(event: dict, *, source_name: str, source_url: str) -> bool:
    try:
        source_refs = json.loads(event.get("source_refs") or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    discovery = source_refs.get("detail_discovery") or {}
    evidence = ((discovery.get("urls") or {}).get("result_url") or {})
    provider = SOURCE_PROVIDERS.get(source_name)
    if _approved_supplemental_source(event, provider=provider, source_url=source_url):
        return True
    if evidence.get("source_provider") != provider:
        return False
    approved_url = str(evidence.get("url") or "")
    if source_url == approved_url:
        return True
    if provider != "hkjc":
        return False
    approved = urlparse(approved_url)
    actual = urlparse(source_url)
    approved_query = {key.casefold(): values[-1] for key, values in parse_qs(approved.query).items()}
    actual_query = {key.casefold(): values[-1] for key, values in parse_qs(actual.query).items()}
    keys = {"racedate", "racecourse", "raceno"}
    return (
        approved.scheme == actual.scheme == "https"
        and approved.hostname == actual.hostname
        and approved.path.endswith("/local/information/localresults")
        and actual.path.endswith("/local/information/localresults")
        and {key: approved_query.get(key) for key in keys} == {key: actual_query.get(key) for key in keys}
    )


def _read_event_rows(paths: Iterable[Path]) -> dict[tuple[int, str], dict]:
    rows: dict[tuple[int, str], dict] = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (int(row["year"]), str(row["slug"]))
                if key in rows:
                    raise RuntimeError(f"duplicate event input: {key}")
                if len(str(row.get("target_sha256") or "")) != 64 or len(
                    str(row.get("inventory_artifact_sha256") or "")
                ) != 64:
                    raise RuntimeError(f"event input identity is incomplete: {key}")
                rows[key] = row
    return rows


def _read_cache_identities(paths: Iterable[Path]) -> dict[str, dict]:
    identities: dict[str, dict] = {}
    for manifest_path in paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0" or not isinstance(files, dict):
            raise RuntimeError(f"source cache manifest is invalid: {manifest_path}")
        root = manifest_path.parent.resolve()
        for identity in files.values():
            if not isinstance(identity, dict):
                raise RuntimeError(f"source cache identity is invalid: {manifest_path}")
            source_url = str(identity.get("source_url") or "")
            source = (root / str(identity.get("path") or "")).resolve()
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(f"source cache path escapes manifest directory: {source}") from exc
            if not source.is_file():
                raise RuntimeError(f"source cache file is missing: {source}")
            body = source.read_bytes()
            if len(body) != int(identity.get("size") or -1) or hashlib.sha256(body).hexdigest() != identity.get(
                "sha256"
            ):
                raise RuntimeError(f"source cache identity changed: {source}")
            existing = identities.get(source_url)
            if existing is None or str(identity.get("cached_at") or "") > str(existing.get("cached_at") or ""):
                identities[source_url] = identity
            elif str(identity.get("cached_at") or "") == str(existing.get("cached_at") or "") and existing != identity:
                raise RuntimeError(f"source URL has ambiguous cache identities: {source_url}")
    return identities


def _read_candidates(paths: Iterable[Path]) -> list[dict]:
    records = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise RuntimeError(f"candidate row must be an object: {path}:{line_number}")
                records.append(record)
    return records


def package_candidates(
    *,
    event_csv_paths: Iterable[Path],
    candidate_jsonl_paths: Iterable[Path],
    source_cache_manifest_paths: Iterable[Path],
) -> dict:
    events = _read_event_rows(event_csv_paths)
    cache_identities = _read_cache_identities(source_cache_manifest_paths)
    packaged: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for candidate in _read_candidates(candidate_jsonl_paths):
        key = (int(candidate.get("year") or 0), str(candidate.get("slug") or ""))
        event = events.get(key)
        if event is None:
            raise RuntimeError(f"candidate is outside event input: {key}")
        if key in seen:
            raise RuntimeError(f"duplicate detail candidate: {key}")
        source_url = str(candidate.get("source_url") or "")
        source_name = str(candidate.get("source_name") or "")
        if not source_matches_event(event, source_name=source_name, source_url=source_url):
            raise RuntimeError(f"candidate source URL was not approved for event: {key}")
        cache_identity = cache_identities.get(source_url)
        if cache_identity is None:
            raise RuntimeError(f"candidate source URL has no verified cache identity: {source_url}")
        supplemental = _approved_supplemental_source(
            event,
            provider=SOURCE_PROVIDERS.get(source_name),
            source_url=source_url,
        )
        if supplemental:
            approved_cache = supplemental["source_cache_identity"]
            if any(
                approved_cache.get(field) != cache_identity.get(field)
                for field in ("source_url", "size", "sha256")
            ):
                raise RuntimeError(f"candidate source cache differs from approved capture: {source_url}")
        modules = candidate.get("modules")
        if not isinstance(modules, dict) or set(modules) != {"runners", "results"}:
            raise RuntimeError(f"candidate modules are incomplete: {key}")
        normalized_modules = {}
        for module_name in ("runners", "results"):
            payload = modules[module_name]
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list) or not items:
                raise RuntimeError(f"candidate module has no rows: {key}/{module_name}")
            normalized_items = []
            for item in items:
                if not isinstance(item, dict):
                    raise RuntimeError(f"candidate item is invalid: {key}/{module_name}")
                refs = dict(item.get("source_refs") or {})
                refs["source_cache_identity"] = cache_identity
                normalized_items.append({**item, "source_refs": refs})
            normalized_modules[module_name] = {
                "items": normalized_items,
                "is_complete": True,
                "source_cache_identity": cache_identity,
            }
        packaged.append(
            {
                "target_id": int(event["target_id"]),
                "target_sha256": event["target_sha256"],
                "inventory_artifact_sha256": event["inventory_artifact_sha256"],
                "source_name": source_name,
                "source_url": source_url,
                "modules": normalized_modules,
            }
        )
        seen.add(key)
    gaps = [
        {"target_id": int(event["target_id"]), "year": key[0], "slug": key[1], "reason": "missing_candidate"}
        for key, event in sorted(events.items())
        if key not in seen
    ]
    return {"records": sorted(packaged, key=lambda row: row["target_id"]), "gaps": gaps}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind parsed historical detail rows to targets and verified source cache.")
    parser.add_argument("--events-csv", action="append", required=True, type=Path)
    parser.add_argument("--candidate-jsonl", action="append", required=True, type=Path)
    parser.add_argument("--source-cache-manifest", action="append", required=True, type=Path)
    parser.add_argument("--output-jsonl", required=True, type=Path)
    parser.add_argument("--gap-json", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    result = package_candidates(
        event_csv_paths=args.events_csv,
        candidate_jsonl_paths=args.candidate_jsonl,
        source_cache_manifest_paths=args.source_cache_manifest,
    )
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.output_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in result["records"]),
        encoding="utf-8",
    )
    args.gap_json.parent.mkdir(parents=True, exist_ok=True)
    args.gap_json.write_text(json.dumps(result["gaps"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "event_input_count": len(result["records"]) + len(result["gaps"]),
        "candidate_count": len(result["records"]),
        "gap_count": len(result["gaps"]),
        "candidate_sha256": hashlib.sha256(args.output_jsonl.read_bytes()).hexdigest(),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
