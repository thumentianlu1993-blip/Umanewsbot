#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pdfplumber

from discover_historical_race_band_sources import (
    build_calendar_event_input_rows,
    build_jra_provider_rows,
    build_toba_provider_rows,
    match_official_schedule_targets,
    parse_bha_flat_schedule_text,
    parse_bha_jump_schedule_text,
    parse_france_galop_flat_schedule_text,
    parse_france_galop_flat_program_text,
    parse_france_galop_obstacle_group_summary_text,
    parse_france_galop_obstacle_schedule_text,
    parse_hkjc_pattern_schedule_text,
    write_calendar_event_inputs,
)
from historical_race_calendar_common import (
    CalendarArtifactError,
    SHA256_RE,
    atomic_publish_directory,
    canonical_bytes,
    file_identity,
    load_catalog,
    load_selection,
    sha256_file,
    valid_timestamp,
)


class CalendarPrepareError(CalendarArtifactError):
    pass


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise CalendarPrepareError(
                        f"request ledger row is not an object: {line_number}"
                    )
                rows.append(row)
    except (OSError, json.JSONDecodeError) as exc:
        raise CalendarPrepareError("request ledger is unreadable") from exc
    return rows


def _safe_cached_file(root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative == Path(".") or relative.is_absolute() or ".." in relative.parts:
        raise CalendarPrepareError("source cache path is unsafe")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise CalendarPrepareError("source cache path contains a symlink")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CalendarPrepareError("source cache path escapes the declared root") from exc
    return resolved


def _verified_cache(
    *,
    root: Path,
    manifest_path: Path,
    ledger_path: Path,
    sources: list[dict],
    catalog_sources: list[dict],
    catalog_targets: dict[int, dict],
) -> tuple[dict[str, tuple[dict, Path]], dict[str, dict], dict]:
    if root.is_symlink() or not root.is_dir():
        raise CalendarPrepareError("source cache root is invalid")
    root = root.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalendarPrepareError("source cache manifest is unreadable") from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if manifest.get("schema_version") != "1.0" or not isinstance(files, dict):
        raise CalendarPrepareError("source cache manifest schema is invalid")
    ledger_rows = _read_jsonl(ledger_path)
    expected_targets_by_request: dict[tuple[str, str], set[int]] = defaultdict(set)
    for source in catalog_sources:
        key = (source["adapter_key"], source["url"])
        expected_targets_by_request[key].update(
            target_id
            for target_id, target in catalog_targets.items()
            if target["country_region"] == source["country_region"]
            and target["year"] == source["edition_year"]
        )
    ledger_by_request: dict[tuple[str, str], dict] = {}
    for row in ledger_rows:
        adapter = str(row.get("adapter_key") or "")
        url = str(row.get("source_url") or "")
        status = row.get("status")
        key = (adapter, url)
        if not adapter or not url or status not in {"succeeded", "failed"} or key in ledger_by_request:
            raise CalendarPrepareError("request ledger identity is invalid or duplicated")
        references = row.get("target_references")
        if not isinstance(references, list):
            raise CalendarPrepareError("request ledger target references are invalid")
        normalized_references = {}
        for reference in references:
            if not isinstance(reference, dict):
                raise CalendarPrepareError("request ledger target references are invalid")
            target_id = reference.get("target_id")
            edition_year = reference.get("edition_year")
            if (
                not isinstance(target_id, int)
                or isinstance(target_id, bool)
                or not isinstance(edition_year, int)
                or isinstance(edition_year, bool)
                or target_id in normalized_references
            ):
                raise CalendarPrepareError("request ledger target references are invalid")
            normalized_references[target_id] = reference
        if (
            len(normalized_references) != len(references)
            or set(normalized_references) != expected_targets_by_request.get(key, set())
            or any(
                str(reference.get("target_sha256") or "")
                != catalog_targets[target_id]["target_sha256"]
                or str(reference.get("series_key") or "")
                != catalog_targets[target_id]["series_key"]
                or reference.get("edition_year") != catalog_targets[target_id]["year"]
                or reference.get("role") != "calendar_source"
                for target_id, reference in normalized_references.items()
            )
        ):
            raise CalendarPrepareError("request ledger does not bind the complete parser scope")
        ledger_by_request[key] = row

    expected_requests = set(expected_targets_by_request)
    if set(ledger_by_request) != expected_requests:
        raise CalendarPrepareError("request ledger scope does not match the source catalog")

    verified: dict[str, tuple[dict, Path]] = {}
    for source in sources:
        key = (source["adapter_key"], source["url"])
        entry = ledger_by_request.get(key)
        if entry is None:
            raise CalendarPrepareError(f"calendar source is absent from request ledger: {source['id']}")
        if entry["status"] == "failed":
            continue
        identity = entry.get("source_cache_identity")
        if not isinstance(identity, dict):
            raise CalendarPrepareError("successful request has no source cache identity")
        manifest_relative = str(identity.get("path") or "")
        cache_relative = str(
            entry.get("source_cache_relative_path") or manifest_relative
        )
        manifest_identity = files.get(manifest_relative)
        expected_size = identity.get("size")
        expected_sha = str(identity.get("sha256") or "")
        if (
            not isinstance(manifest_identity, dict)
            or manifest_identity.get("source_url") != source["url"]
            or identity.get("source_url") != source["url"]
            or manifest_identity.get("size") != expected_size
            or manifest_identity.get("sha256") != expected_sha
            or not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or expected_size < 0
            or not SHA256_RE.fullmatch(expected_sha)
        ):
            raise CalendarPrepareError("source cache manifest and ledger identities disagree")
        manifest_parts = Path(manifest_relative).parts
        cache_parts = Path(cache_relative).parts
        if (
            not cache_parts
            or len(cache_parts) > len(manifest_parts)
            or manifest_parts[-len(cache_parts) :] != cache_parts
        ):
            raise CalendarPrepareError(
                "source cache copied path does not match manifest identity"
            )
        cached = _safe_cached_file(root, cache_relative)
        if (
            not cached.is_file()
            or cached.stat().st_size != expected_size
            or sha256_file(cached) != expected_sha
        ):
            raise CalendarPrepareError("source cache file identity drifted")
        verified[source["id"]] = (identity, cached)
    return verified, ledger_by_request, file_identity(ledger_path)


def _source_text(source: dict, path: Path) -> str:
    content_format = source["content_format"]
    if content_format == "pdf":
        try:
            with pdfplumber.open(path) as pdf:
                preserve_layout = source["parser"] == "france_obstacle_summary"
                text = "\n".join(
                    (page.extract_text(layout=preserve_layout) or "")
                    for page in pdf.pages
                )
        except Exception as exc:
            raise CalendarPrepareError(f"calendar PDF is unreadable: {source['id']}") from exc
    else:
        body = path.read_bytes()
        if content_format == "json":
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise CalendarPrepareError(f"calendar JSON is invalid: {source['id']}") from exc
            text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        else:
            text = body.decode("utf-8", errors="replace")
    if not text.strip():
        raise CalendarPrepareError(f"calendar source has no extractable text: {source['id']}")
    return text


def _decorate_schedule_rows(rows: list[dict], source: dict) -> list[dict]:
    return [
        {
            **row,
            "calendar_source_url": source["url"],
            "calendar_source_provider": source["adapter_key"],
            "calendar_source_authority": source["source_authority"],
            "calendar_source_parser": source["parser"],
            "annual_surface": source["options"].get("surface", ""),
            "annual_discipline": source["options"].get("discipline", ""),
        }
        for row in rows
    ]


def _bind_parser_issues(
    issues: list[dict], targets_by_identity: dict[tuple[str, int], dict]
) -> list[dict]:
    bound = []
    for issue in issues:
        normalized = dict(issue)
        if normalized.get("target_id") in (None, ""):
            try:
                target = targets_by_identity[
                    (
                        str(normalized["series_key"]),
                        int(normalized["edition_year"]),
                    )
                ]
            except (KeyError, TypeError, ValueError):
                pass
            else:
                normalized["target_id"] = target["target_id"]
        bound.append(normalized)
    return bound


def _direct_provider_matches(
    provider_rows: list[dict], targets_by_identity: dict[tuple[str, int], dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    candidates: dict[int, list[tuple[dict, dict]]] = defaultdict(list)
    for row in provider_rows:
        identity_key = (str(row.get("series_key") or ""), int(row.get("edition_year") or 0))
        target = targets_by_identity.get(identity_key)
        if target is None:
            raise CalendarPrepareError("direct provider target is outside parser scope")
        target_id = target["target_id"]
        result_url = (((row.get("urls") or {}).get("result_url") or {}).get("url"))
        if not isinstance(result_url, str) or not result_url.startswith("https://"):
            raise CalendarPrepareError(
                f"direct provider has no HTTPS result URL: {target_id}"
            )
        normalized = {
            **row,
            "target_id": target_id,
            "target_sha256": target["target_sha256"],
            "inventory_artifact_sha256": target["inventory_artifact_sha256"],
        }
        match = {
            "target_id": target_id,
            "series_key": target["series_key"],
            "edition_year": target["year"],
            "local_date": row.get("local_date"),
            "racecourse": target.get("racecourse") or "",
            "race_name": target.get("original_name") or "",
            "distance_text": row.get("distance_text") or target.get("distance_text") or "",
            "normalized_grade": target.get("normalized_grade") or "",
            "source_url": result_url,
            "source_provider": row.get("adapter_key") or "",
            "source_authority": (((row.get("urls") or {}).get("result_url") or {}).get("source_authority")) or "",
        }
        candidates[target_id].append((match, normalized))

    matches = []
    normalized_rows = []
    issues = []
    for target_id, rows in sorted(candidates.items()):
        distinct = {
            canonical_bytes(match): (match, normalized)
            for match, normalized in rows
        }
        if len(distinct) > 1:
            issues.append(
                {
                    "target_id": target_id,
                    "code": "direct_provider_conflict",
                    "candidate_urls": sorted(
                        str(match.get("source_url") or "")
                        for match, _normalized in distinct.values()
                    ),
                }
            )
            continue
        match, normalized = next(iter(distinct.values()))
        matches.append(match)
        normalized_rows.append(normalized)
    return matches, normalized_rows, issues


def prepare_calendar_inputs(
    *,
    selection_path: Path,
    catalog_path: Path,
    source_cache_root: Path,
    source_cache_manifest_path: Path,
    request_ledger_path: Path,
    country_region: str,
    year: int,
    recorded_at: str,
    output_dir: Path,
) -> dict:
    if not valid_timestamp(recorded_at):
        raise CalendarPrepareError("recorded_at must be a timezone-aware ISO timestamp")
    try:
        _selection, all_targets = load_selection(selection_path)
        _catalog, all_sources = load_catalog(catalog_path)
    except CalendarArtifactError as exc:
        raise CalendarPrepareError(str(exc)) from exc
    targets = [
        target
        for target in all_targets
        if target["country_region"] == country_region and target["year"] == year
    ]
    sources = [
        source
        for source in all_sources
        if source["country_region"] == country_region and source["edition_year"] == year
    ]
    if not targets or not sources:
        raise CalendarPrepareError("calendar parser region/year scope is empty")
    scope_ids = {target["target_id"] for target in targets}
    targets_by_identity = {
        (target["series_key"], target["year"]): target for target in targets
    }
    verified, ledger_by_request, ledger_identity = _verified_cache(
        root=source_cache_root,
        manifest_path=source_cache_manifest_path,
        ledger_path=request_ledger_path,
        sources=sources,
        catalog_sources=all_sources,
        catalog_targets={target["target_id"]: target for target in all_targets},
    )

    schedule_rows = []
    provider_rows = []
    parser_errors: list[dict] = []
    jra_sources: dict[str, tuple[dict, Path]] = {}
    for source in sources:
        cached = verified.get(source["id"])
        if cached is None:
            continue
        _identity, path = cached
        parser_name = source["parser"]
        if parser_name in {"jra_schedule", "jra_history"}:
            if parser_name in jra_sources:
                raise CalendarPrepareError(
                    f"JRA calendar parser source is duplicated: {parser_name}"
                )
            jra_sources[parser_name] = (source, path)
            continue
        try:
            text = _source_text(source, path)
            if parser_name == "toba_yearbook":
                result = build_toba_provider_rows(targets=targets, year=year, body=text)
                provider_rows.extend(result["rows"])
                parser_errors.extend(
                    _bind_parser_issues(result["issues"], targets_by_identity)
                )
            elif parser_name == "hkjc_pattern":
                season_end_year = int(source["options"]["season_end_year"])
                natural_year_rows = [
                    {**row, "edition_year": year}
                    for row in parse_hkjc_pattern_schedule_text(
                        text, edition_year=season_end_year
                    )
                    if str(row.get("local_date") or "").startswith(f"{year}-")
                ]
                schedule_rows.extend(
                    _decorate_schedule_rows(
                        natural_year_rows, source
                    )
                )
            elif parser_name == "bha_flat":
                schedule_rows.extend(
                    _decorate_schedule_rows(parse_bha_flat_schedule_text(text, year=year), source)
                )
            elif parser_name == "bha_jump":
                schedule_rows.extend(
                    _decorate_schedule_rows(
                        parse_bha_jump_schedule_text(
                            text,
                            season_start_year=int(source["options"]["season_start_year"]),
                        ),
                        source,
                    )
                )
            elif parser_name == "france_flat":
                schedule_rows.extend(
                    _decorate_schedule_rows(
                        parse_france_galop_flat_schedule_text(text, year=year), source
                    )
                )
            elif parser_name == "france_flat_program":
                schedule_rows.extend(
                    _decorate_schedule_rows(
                        parse_france_galop_flat_program_text(text, year=year), source
                    )
                )
            elif parser_name == "france_obstacle":
                schedule_rows.extend(
                    _decorate_schedule_rows(
                        parse_france_galop_obstacle_schedule_text(
                            text,
                            year=year,
                            date_start=str(source["options"]["date_start"]),
                            date_end=str(source["options"]["date_end"]),
                        ),
                        source,
                    )
                )
            elif parser_name == "france_obstacle_summary":
                schedule_rows.extend(
                    _decorate_schedule_rows(
                        parse_france_galop_obstacle_group_summary_text(
                            text,
                            year=year,
                        ),
                        source,
                    )
                )
            else:
                raise CalendarPrepareError(f"calendar parser is unsupported: {parser_name}")
        except (CalendarPrepareError, OSError, ValueError) as exc:
            parser_errors.append(
                {"source_id": source["id"], "code": "source_parse_failed", "error": str(exc)}
            )

    if jra_sources:
        if set(jra_sources) != {"jra_schedule", "jra_history"}:
            parser_errors.append(
                {"source_id": "jra", "code": "source_parse_failed", "error": "JRA source pair is incomplete"}
            )
        else:
            try:
                result = build_jra_provider_rows(
                    targets=targets,
                    year=year,
                    english_schedule_body=jra_sources["jra_schedule"][1].read_bytes(),
                    history_body=jra_sources["jra_history"][1].read_bytes(),
                )
                provider_rows.extend(result["rows"])
                parser_errors.extend(
                    _bind_parser_issues(result["issues"], targets_by_identity)
                )
            except Exception as exc:
                parser_errors.append(
                    {"source_id": "jra", "code": "source_parse_failed", "error": str(exc)}
                )

    direct_matches, normalized_providers, direct_issues = _direct_provider_matches(
        provider_rows, targets_by_identity
    )
    direct_ids = {match["target_id"] for match in direct_matches}
    remaining_targets = [target for target in targets if target["target_id"] not in direct_ids]
    schedule_result = match_official_schedule_targets(remaining_targets, schedule_rows)
    matches = sorted(
        [*direct_matches, *schedule_result["matches"]], key=lambda row: row["target_id"]
    )
    matched_ids = {match["target_id"] for match in matches}
    issues_by_target: dict[int, list[dict]] = defaultdict(list)
    for issue in [*parser_errors, *direct_issues, *schedule_result["issues"]]:
        target_id = issue.get("target_id")
        if target_id not in (None, ""):
            issues_by_target[int(target_id)].append(issue)

    failed_sources = [
        source
        for source in sources
        if ledger_by_request[(source["adapter_key"], source["url"])]["status"] == "failed"
    ]
    gaps = []
    for target in targets:
        if target["target_id"] in matched_ids:
            continue
        issues = issues_by_target.get(target["target_id"], [])
        if not issues:
            issues = [
                issue
                for issue in parser_errors
                if issue.get("target_id") in (None, "")
            ]
        decisive_issues = [
            issue
            for issue in issues
            if issue.get("code") != "official_schedule_match_missing"
        ]
        if decisive_issues:
            reason_code = str(
                decisive_issues[0].get("code") or "calendar_match_failed"
            )
        elif failed_sources:
            reason_code = "source_request_failed"
        elif issues:
            reason_code = str(issues[0].get("code") or "calendar_match_failed")
        elif parser_errors:
            reason_code = "source_parse_failed"
        else:
            reason_code = "official_schedule_match_missing"
        gaps.append(
            {
                "target_id": target["target_id"],
                "target_sha256": target["target_sha256"],
                "inventory_artifact_sha256": target["inventory_artifact_sha256"],
                "series_key": target["series_key"],
                "edition_year": target["year"],
                "reason_code": reason_code,
                "recorded_at": recorded_at,
                "source_url": (failed_sources[0]["url"] if failed_sources else sources[0]["url"]),
                "evidence_identity": {
                    **ledger_identity,
                    "path": request_ledger_path.name,
                },
                "source_evidence": [
                    {
                        "source_id": source["id"],
                        "source_url": source["url"],
                        "status": ledger_by_request[(source["adapter_key"], source["url"])]["status"],
                        "cache_identity": ledger_by_request[(source["adapter_key"], source["url"])].get(
                            "source_cache_identity"
                        ),
                    }
                    for source in sources
                ],
                "issues": issues,
            }
        )
    if matched_ids | {gap["target_id"] for gap in gaps} != scope_ids:
        raise CalendarPrepareError("calendar parser did not account for the complete scope")

    event_rows = build_calendar_event_input_rows(targets, matches)
    summary = {
        "schema_version": "1.0",
        "country_region": country_region,
        "edition_year": year,
        "scope_count": len(targets),
        "complete_count": len(event_rows),
        "gap_count": len(gaps),
        "accounted_count": len(event_rows) + len(gaps),
        "provider_row_count": len(normalized_providers),
        "accounted_rate": 1.0,
        "data_complete_rate": round(len(event_rows) / len(targets), 8),
        "recorded_at": recorded_at,
    }
    result = dict(summary)

    def write(temporary: Path) -> None:
        providers_path = temporary / "provider_rows.jsonl"
        providers_path.write_bytes(
            b"".join(canonical_bytes(row) for row in sorted(normalized_providers, key=lambda row: row["target_id"]))
        )
        gaps_path = temporary / "gaps.jsonl"
        gaps_path.write_bytes(
            b"".join(canonical_bytes(row) for row in sorted(gaps, key=lambda row: row["target_id"]))
        )
        event_files = write_calendar_event_inputs(event_rows, temporary)
        summary_path = temporary / "summary.json"
        summary_path.write_bytes(canonical_bytes(summary))
        artifacts = {
            "provider_rows": file_identity(providers_path, relative_to=temporary),
            "gaps": file_identity(gaps_path, relative_to=temporary),
            "summary": file_identity(summary_path, relative_to=temporary),
        }
        for region, event_path in sorted(event_files.items()):
            artifacts[f"events_{region}"] = file_identity(
                Path(event_path), relative_to=temporary
            )
        manifest = {
            "schema_version": "1.0",
            "selection": file_identity(selection_path),
            "source_catalog": file_identity(catalog_path),
            "request_ledger": file_identity(request_ledger_path),
            "source_cache_manifest": file_identity(source_cache_manifest_path),
            "artifacts": artifacts,
        }
        (temporary / "manifest.json").write_bytes(canonical_bytes(manifest))

    try:
        atomic_publish_directory(output_dir, write)
    except CalendarArtifactError as exc:
        raise CalendarPrepareError(str(exc)) from exc
    result["output_dir"] = str(output_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从冻结 source cache 离线生成历史赛事年度赛历输入。"
    )
    parser.add_argument("--selection-snapshot", required=True, type=Path)
    parser.add_argument("--source-catalog", required=True, type=Path)
    parser.add_argument("--source-cache-root", required=True, type=Path)
    parser.add_argument("--source-cache-manifest", required=True, type=Path)
    parser.add_argument("--request-ledger", required=True, type=Path)
    parser.add_argument("--country-region", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare_calendar_inputs(
            selection_path=args.selection_snapshot,
            catalog_path=args.source_catalog,
            source_cache_root=args.source_cache_root,
            source_cache_manifest_path=args.source_cache_manifest,
            request_ledger_path=args.request_ledger,
            country_region=args.country_region,
            year=args.year,
            recorded_at=args.recorded_at,
            output_dir=args.output_dir,
        )
    except (CalendarPrepareError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
