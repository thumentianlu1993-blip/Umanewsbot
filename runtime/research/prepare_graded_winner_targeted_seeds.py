#!/usr/bin/env python3
"""Freeze 2005-2025 winner anchors as targeted-horse seed v2 rows.

The builder is offline and fail-closed.  It preserves every TOBA physical
occurrence (including same-day divisions), then fills non-US targets from the
already-frozen history ledgers and the bounded Wikipedia capture.  Missing
winner rows remain explicit semantic gaps; they never become guessed seeds.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlsplit


SCHEMA_VERSION = "graded-winner-targeted-seed-artifact.v1"
SEED_SCHEMA_VERSION = "targeted-horse-seed.v2"
TARGET_SCHEMA_VERSION = "graded-horse-target-ledger.v1"
PLAN_SCHEMA_VERSION = "graded-winner-source-events.v1"
REGIONS = frozenset({"france", "ireland", "united_kingdom", "united_states"})
SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return resolved


def _require_sha(path: Path, expected: str, *, label: str) -> Path:
    resolved = _regular(path, label=label)
    if not SHA256_RE.fullmatch(str(expected or "")) or sha256_path(resolved) != expected:
        raise ValueError(f"{label} SHA-256 mismatch")
    return resolved


def _json(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(_regular(path, label=label).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _jsonl(path: Path, *, label: str) -> list[dict]:
    rows: list[dict] = []
    try:
        for ordinal, line in enumerate(
            _regular(path, label=label).read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{label} row {ordinal} is not an object")
            rows.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSONL") from exc
    return rows


def _csv(path: Path, *, label: str) -> list[dict]:
    try:
        with _regular(path, label=label).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"{label} is invalid CSV") from exc


def _identity(path: Path, *, rows: int | None = None) -> dict:
    result = {
        "path": path.name,
        "sha256": sha256_path(path),
        "size": path.stat().st_size,
    }
    if rows is not None:
        result["rows"] = rows
    return result


def _atomic_write(path: Path, body: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _cache_name(prefix: str, value: str, suffix: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return f"{prefix}_{key[-120:]}.{suffix}"


def _https_url(value: object, *, wikipedia: bool = False) -> str:
    parsed = urlsplit(str(value or ""))
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("source URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or (wikipedia and parsed.hostname != "en.wikipedia.org")
    ):
        raise ValueError("source URL is invalid")
    return parsed.geturl()


def _history_map(records: Iterable[dict], *, region: str) -> dict[tuple[str, str, int], dict]:
    result: dict[tuple[str, str, int], dict] = {}
    for record in records:
        slug = str(record.get("slug") or "")
        url = _https_url(record.get("source_url"), wikipedia=True)
        modules = record.get("modules")
        items = (
            ((modules.get("history_winners") or {}).get("items") or [])
            if isinstance(modules, Mapping)
            else []
        )
        if not slug or not isinstance(items, list):
            raise ValueError("history record contract drift")
        for item in items:
            if not isinstance(item, Mapping):
                raise ValueError("history winner item contract drift")
            year = int(item.get("winner_year") or 0)
            horse = str(item.get("horse_name") or "").strip()
            key = (region, slug, year)
            if not horse or key in result:
                raise ValueError("history winner identity drift")
            result[key] = {"horse_name": horse, "source_url": url}
    return result


def _load_plan(root: Path, expected_sha: str) -> tuple[dict, Path]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("event plan root must be a regular directory")
    manifest_path = _require_sha(
        resolved / "event-manifest.json", expected_sha, label="event plan manifest"
    )
    if (resolved / "PREPARED").read_text(encoding="ascii").strip() != expected_sha:
        raise ValueError("event plan PREPARED marker drift")
    manifest = _json(manifest_path, label="event plan manifest")
    if (
        manifest.get("schema_version") != PLAN_SCHEMA_VERSION
        or manifest.get("status") != "PREPARED_NOT_APPROVED"
        or manifest.get("network_requests") != 0
        or manifest.get("database_writes") != 0
    ):
        raise ValueError("event plan contract drift")
    return manifest, resolved


def _load_capture(
    root: Path,
    *,
    candidates_sha: str,
    summary_sha: str,
    review_sha: str,
    unmatched_sha: str,
    budget_sha: str,
    source_manifest_sha: str,
    expected_event_slugs: set[str],
) -> tuple[dict[tuple[str, str, int], dict], dict]:
    resolved = root.resolve(strict=True)
    output = resolved / "output"
    paths = {
        "candidates": _require_sha(
            output / "france_wikipedia_history_winner_candidates_2026.jsonl",
            candidates_sha,
            label="capture candidates",
        ),
        "summary": _require_sha(output / "summary.json", summary_sha, label="capture summary"),
        "review": _require_sha(
            output / "france_wikipedia_history_winner_review_2026.csv",
            review_sha,
            label="capture review",
        ),
        "unmatched": _require_sha(
            output / "france_wikipedia_history_winner_unmatched_2026.csv",
            unmatched_sha,
            label="capture unmatched",
        ),
        "budget": _require_sha(resolved / "request-budget.json", budget_sha, label="capture budget"),
        "sources": _require_sha(
            output / "sources" / "source_cache_manifest.json",
            source_manifest_sha,
            label="capture source manifest",
        ),
    }
    summary = _json(paths["summary"], label="capture summary")
    budget = _json(paths["budget"], label="capture budget")
    source_manifest = _json(paths["sources"], label="capture source manifest")
    records = _jsonl(paths["candidates"], label="capture candidates")
    review = _csv(paths["review"], label="capture review")
    unmatched = _csv(paths["unmatched"], label="capture unmatched")
    record_slugs = [str(row.get("slug") or "") for row in records]
    review_slugs = [str(row.get("slug") or "") for row in review]
    unmatched_slugs = [str(row.get("slug") or "") for row in unmatched]
    requests = budget.get("requests")
    source_files = source_manifest.get("files")
    if (
        summary.get("source") != "wikipedia_winners_table"
        or summary.get("events_requested") != len(expected_event_slugs)
        or summary.get("events") != len(records)
        or summary.get("events_without_history") != len(unmatched)
        or int(summary.get("events_skipped_partial") or 0) != 0
        or len(records) + len(unmatched) != len(expected_event_slugs)
        or len(review) != len(records)
        or not all(record_slugs)
        or len(record_slugs) != len(set(record_slugs))
        or set(review_slugs) != set(record_slugs)
        or set(record_slugs) & set(unmatched_slugs)
        or set(record_slugs) | set(unmatched_slugs) != expected_event_slugs
        or budget.get("status") != "active"
        or budget.get("request_count") != len(requests or [])
        or int(budget.get("request_count") or 0) > int(budget.get("max_requests") or 0)
        or float(budget.get("request_interval_seconds") or 0) < 1
        or not isinstance(requests, list)
        or not isinstance(source_files, Mapping)
        or source_manifest.get("schema_version") != "1.0"
    ):
        raise ValueError("bounded capture contract drift")
    history: dict[tuple[str, str, int], dict] = {}
    regions: set[str] = set()
    for record in records:
        slug = str(record.get("slug") or "")
        region = slug.split("-", 1)[0]
        region = {
            "france": "france",
            "ireland": "ireland",
            "united": "",
        }.get(region, region)
        # Slugs for UK/US contain the full region prefix and cannot be inferred
        # from the first token alone.  They are rebound to the plan target below.
        metadata = record.get("metadata")
        title = str((metadata or {}).get("wiki_title") or "")
        source_url = _https_url(record.get("source_url"), wikipedia=True)
        page_name = _cache_name("source_wiki_page", title, "html")
        identity = source_files.get(page_name)
        page_path = output / "sources" / page_name
        if (
            not slug
            or not title
            or not isinstance(identity, Mapping)
            or identity.get("path") != page_name
            or identity.get("source_url") != source_url
            or not page_path.is_file()
            or page_path.is_symlink()
            or sha256_path(page_path) != identity.get("sha256")
            or page_path.stat().st_size != identity.get("size")
        ):
            raise ValueError("capture source page identity drift")
        modules = record.get("modules")
        items = (
            ((modules.get("history_winners") or {}).get("items") or [])
            if isinstance(modules, Mapping)
            else []
        )
        if not isinstance(items, list):
            raise ValueError("capture history items drift")
        for item in items:
            year = int(item.get("winner_year") or 0)
            horse = str(item.get("horse_name") or "").strip()
            if not horse:
                raise ValueError("capture winner name is empty")
            # Region is intentionally filled later from the exact target row.
            key = ("", slug, year)
            if key in history:
                raise ValueError("capture winner identity is duplicated")
            history[key] = {
                "horse_name": horse,
                "source_url": source_url,
                "source_payload_sha256": identity["sha256"],
            }
        regions.add(region)
    return history, {
        "root": str(resolved),
        "candidates": _identity(paths["candidates"], rows=len(records)),
        "summary": _identity(paths["summary"]),
        "review": _identity(paths["review"], rows=len(review)),
        "unmatched": _identity(paths["unmatched"], rows=len(unmatched)),
        "request_budget": _identity(paths["budget"]),
        "source_manifest": _identity(paths["sources"]),
        "network_requests": int(budget["request_count"]),
        "errors": len(summary.get("errors") or []),
    }


def _seed(
    *,
    target: Mapping[str, object],
    occurrence_id: str,
    horse_name: str,
    source_authority: str,
    source_url: str,
    source_payload_sha256: str,
    local_date: str = "",
    race_name: str = "",
    racecourse_alias: str = "",
) -> dict:
    target_key = str(target["target_key"])
    aliases = list(
        dict.fromkeys(
            value
            for value in (
                str(target.get("original_name") or "").strip(),
                str(target.get("canonical_name_original") or "").strip(),
                race_name.strip(),
            )
            if value
        )
    )
    course = str(target.get("racecourse") or "").strip()
    course_aliases = list(dict.fromkeys(value for value in (course, racecourse_alias.strip()) if value))
    year = int(target["year"])
    return {
        "schema_version": SEED_SCHEMA_VERSION,
        "seed_id": "graded-winner-" + hashlib.sha256(occurrence_id.encode("utf-8")).hexdigest()[:20],
        "name": horse_name,
        "expected_finish_position": "1",
        "source_authority": source_authority,
        "source_url": source_url,
        "source_payload_sha256": source_payload_sha256,
        "allow_profile_only_if_target_missing": True,
        "source_occurrence_id": occurrence_id,
        "target": {
            "year": year,
            "edition_year": year,
            "country_region": target["country_region"],
            "local_date": local_date or str(target.get("local_date") or ""),
            "canonical_name_original": target["canonical_name_original"],
            "race_name_aliases": aliases,
            "racecourse": course,
            "racecourse_aliases": course_aliases,
            "grade_text": target["grade_text"],
            "discipline": target["discipline"],
            "target_key": target_key,
        },
    }


def build(
    *,
    event_plan_root: Path,
    expected_event_manifest_sha256: str,
    capture_root: Path,
    capture_hashes: Mapping[str, str],
    output_dir: Path,
) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output directory must not already exist")
    plan, plan_root = _load_plan(event_plan_root, expected_event_manifest_sha256)
    target_identity = plan.get("target_ledger") or {}
    target_path = _require_sha(
        Path(str(target_identity.get("path") or "")),
        str(target_identity.get("sha256") or ""),
        label="target ledger",
    )
    target_rows = [
        row
        for row in _jsonl(target_path, label="target ledger")
        if 2005 <= int(row.get("year") or 0) <= 2025
    ]
    targets: dict[str, dict] = {}
    occurrence_keys: set[tuple[str, str, int]] = set()
    for row in target_rows:
        key = str(row.get("target_key") or "")
        occurrence = (
            str(row.get("country_region") or ""),
            str(row.get("series_key") or ""),
            int(row.get("year") or 0),
        )
        if (
            row.get("schema_version") != TARGET_SCHEMA_VERSION
            or not key
            or key in targets
            or occurrence in occurrence_keys
            or occurrence[0] not in REGIONS
        ):
            raise ValueError("target ledger contract drift")
        targets[key] = row
        occurrence_keys.add(occurrence)
    if len(targets) != int((plan.get("counts") or {}).get("target_occurrences_2005_2025") or -1):
        raise ValueError("target denominator drift")

    toba_identity = plan.get("toba_bindings") or {}
    toba_path = _require_sha(
        Path(str(toba_identity.get("path") or "")),
        str(toba_identity.get("sha256") or ""),
        label="TOBA bindings",
    )
    toba_by_target: dict[str, list[dict]] = defaultdict(list)
    seen_physical: set[str] = set()
    for row in _jsonl(toba_path, label="TOBA bindings"):
        target_key = str(row.get("target_key") or "")
        occurrence_key = str(row.get("occurrence_key") or "")
        if target_key not in targets:
            continue
        if (
            row.get("calendar_source_provider") != "toba"
            or row.get("adapter_key") not in {"toba", "equibase"}
            or not occurrence_key
            or occurrence_key in seen_physical
            or not str(row.get("anchor_horse_name") or "").strip()
        ):
            raise ValueError("TOBA occurrence contract drift")
        seen_physical.add(occurrence_key)
        toba_by_target[target_key].append(row)

    frozen: dict[tuple[str, str, int], dict] = {}
    frozen_identities = []
    for identity in plan.get("frozen_histories") or []:
        region = str(identity.get("region") or "")
        history_path = _require_sha(
            Path(str(identity.get("path") or "")),
            str(identity.get("sha256") or ""),
            label=f"{region} frozen history",
        )
        local = _history_map(_jsonl(history_path, label=f"{region} frozen history"), region=region)
        overlap = set(frozen) & set(local)
        if overlap:
            raise ValueError("frozen history occurrence overlap")
        frozen.update(local)
        frozen_identities.append({**dict(identity), "size": history_path.stat().st_size})

    events_identity = (plan.get("outputs") or {}).get("events.csv") or {}
    events_path = _require_sha(
        plan_root / str(events_identity.get("path") or ""),
        str(events_identity.get("sha256") or ""),
        label="source events",
    )
    events = _csv(events_path, label="source events")
    event_slugs = [str(row.get("slug") or "") for row in events]
    if not events or not all(event_slugs) or len(event_slugs) != len(set(event_slugs)):
        raise ValueError("source event identity drift")
    capture, capture_identity = _load_capture(
        capture_root,
        candidates_sha=capture_hashes["candidates"],
        summary_sha=capture_hashes["summary"],
        review_sha=capture_hashes["review"],
        unmatched_sha=capture_hashes["unmatched"],
        budget_sha=capture_hashes["budget"],
        source_manifest_sha=capture_hashes["sources"],
        expected_event_slugs=set(event_slugs),
    )

    seeds: list[dict] = []
    gaps: list[dict] = []
    source_counts: Counter[str] = Counter()
    target_occurrence_seed_counts: Counter[str] = Counter()
    for target_key, target in sorted(targets.items()):
        toba_rows = sorted(
            toba_by_target.get(target_key, []), key=lambda row: str(row["occurrence_key"])
        )
        if toba_rows:
            for row in toba_rows:
                seeds.append(
                    _seed(
                        target=target,
                        occurrence_id=str(row["occurrence_key"]),
                        horse_name=str(row["anchor_horse_name"]).strip(),
                        source_authority="grading_authority",
                        source_url=_https_url(row["calendar_source_url"]),
                        source_payload_sha256=str(toba_identity["sha256"]),
                        local_date=str(row.get("local_date") or ""),
                        race_name=str(row.get("race_name") or ""),
                        racecourse_alias=str(row.get("racecourse") or ""),
                    )
                )
                source_counts["toba"] += 1
                target_occurrence_seed_counts[target_key] += 1
            continue
        occurrence = (
            str(target["country_region"]),
            str(target["series_key"]),
            int(target["year"]),
        )
        winner = frozen.get(occurrence)
        source_name = "frozen_history"
        payload_sha = next(
            (
                str(row["sha256"])
                for row in plan.get("frozen_histories") or []
                if row.get("region") == occurrence[0]
            ),
            "",
        )
        if winner is None:
            winner = capture.get(("", occurrence[1], occurrence[2]))
            source_name = "bounded_wikipedia_capture"
            payload_sha = str((winner or {}).get("source_payload_sha256") or "")
        if winner is None:
            gaps.append(
                {
                    "schema_version": "graded-winner-anchor-gap.v1",
                    "target_key": target_key,
                    "country_region": occurrence[0],
                    "year": occurrence[2],
                    "series_key": occurrence[1],
                    "reason": "winner_anchor_not_found",
                }
            )
            continue
        seeds.append(
            _seed(
                target=target,
                occurrence_id=f"{source_name}:{target_key}",
                horse_name=str(winner["horse_name"]),
                source_authority="human_reviewed_reference",
                source_url=str(winner["source_url"]),
                source_payload_sha256=payload_sha,
            )
        )
        source_counts[source_name] += 1
        target_occurrence_seed_counts[target_key] += 1

    if any(not SHA256_RE.fullmatch(str(seed["source_payload_sha256"])) for seed in seeds):
        raise ValueError("seed source payload identity drift")
    if len({seed["seed_id"] for seed in seeds}) != len(seeds):
        raise ValueError("seed ID collision")
    covered_targets = set(target_occurrence_seed_counts)
    gap_targets = {row["target_key"] for row in gaps}
    if covered_targets & gap_targets or covered_targets | gap_targets != set(targets):
        raise ValueError("target seed/gap conservation drift")

    seeds.sort(key=lambda row: (str(row["target"]["target_key"]), str(row["seed_id"])))
    gaps.sort(key=lambda row: str(row["target_key"]))
    output_dir.mkdir(parents=True, mode=0o700)
    seed_path = output_dir / "targeted-horse-seeds.jsonl"
    gap_path = output_dir / "semantic-gaps.jsonl"
    _atomic_write(seed_path, "".join(canonical_json(row) + "\n" for row in seeds).encode("utf-8"))
    _atomic_write(gap_path, "".join(canonical_json(row) + "\n" for row in gaps).encode("utf-8"))
    manifest = {
        "schema_version": "targeted-horse-seed-ledger.v1",
        "artifact_schema_version": SCHEMA_VERSION,
        "status": "complete",
        "coverage_status": "complete" if not gaps else "complete_with_gaps",
        "completion_marker": "COMPLETE",
        "execution_ready_for_complete_members": bool(seeds),
        "network_requests": 0,
        "database_writes": 0,
        "event_plan": {
            "root": str(plan_root),
            "manifest_sha256": expected_event_manifest_sha256,
        },
        "target_ledger": {
            "path": str(target_path),
            "sha256": target_identity["sha256"],
            "rows": len(targets),
        },
        "target_manifest_sha256": expected_event_manifest_sha256,
        "target_ledger_sha256": target_identity["sha256"],
        "seed_count": len(seeds),
        "seed_ledger": _identity(seed_path, rows=len(seeds)),
        "toba_bindings": {
            "path": str(toba_path),
            "sha256": toba_identity["sha256"],
            "physical_occurrences": len(seen_physical),
            "selected_occurrences": sum(len(value) for value in toba_by_target.values()),
            "selected_targets": len(toba_by_target),
        },
        "frozen_histories": frozen_identities,
        "bounded_capture": capture_identity,
        "counts": {
            "target_occurrences": len(targets),
            "covered_target_occurrences": len(covered_targets),
            "physical_winner_seeds": len(seeds),
            "duplicate_physical_occurrence_seeds": len(seeds) - len(covered_targets),
            "semantic_gaps": len(gaps),
            "by_source": dict(sorted(source_counts.items())),
            "by_region": dict(
                sorted(Counter(seed["target"]["country_region"] for seed in seeds).items())
            ),
        },
        "outputs": {
            seed_path.name: _identity(seed_path, rows=len(seeds)),
            gap_path.name: _identity(gap_path, rows=len(gaps)),
        },
    }
    manifest_path = output_dir / "seed-ledger-manifest.json"
    _atomic_write(manifest_path, (canonical_json(manifest) + "\n").encode("utf-8"))
    manifest_sha = sha256_path(manifest_path)
    _atomic_write(output_dir / "COMPLETE", (manifest_sha + "\n").encode("ascii"))
    return {**manifest, "seed_artifact_manifest_sha256": manifest_sha}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-plan-root", required=True, type=Path)
    parser.add_argument("--expected-event-manifest-sha256", required=True)
    parser.add_argument("--capture-root", required=True, type=Path)
    for name in ("candidates", "summary", "review", "unmatched", "budget", "sources"):
        parser.add_argument(f"--expected-capture-{name}-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture_hashes = {
        name: getattr(args, f"expected_capture_{name}_sha256")
        for name in ("candidates", "summary", "review", "unmatched", "budget", "sources")
    }
    result = build(
        event_plan_root=args.event_plan_root,
        expected_event_manifest_sha256=args.expected_event_manifest_sha256,
        capture_root=args.capture_root,
        capture_hashes=capture_hashes,
        output_dir=args.output_dir,
    )
    print(canonical_json({"status": result["coverage_status"], "counts": result["counts"], "manifest_sha256": result["seed_artifact_manifest_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
