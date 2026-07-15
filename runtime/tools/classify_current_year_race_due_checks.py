#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile

from historical_race_calendar_common import CalendarArtifactError, load_selection


class DueCheckError(RuntimeError):
    pass


EVENT_FIELDS = [
    "target_id",
    "target_sha256",
    "inventory_artifact_sha256",
    "year",
    "slug",
    "original_name",
    "chinese_name",
    "country_region",
    "racecourse",
    "grade_text",
    "normalized_grade",
    "surface",
    "distance_text",
    "status",
    "local_date",
    "source_refs",
]


def canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def require_unique_target_ids(rows: list[dict], *, label: str) -> None:
    seen = set()
    for row in rows:
        target_id = row.get("target_id") if isinstance(row, dict) else None
        if target_id in seen:
            raise DueCheckError(f"duplicate {label} target_id: {target_id}")
        seen.add(target_id)


def identity(path: Path, *, root: Path) -> dict:
    body = path.read_bytes()
    return {
        "path": os.path.relpath(path, root),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size": len(body),
    }


def same_content_identity(first: dict | None, second: dict) -> bool:
    return isinstance(first, dict) and all(
        first.get(key) == second.get(key) for key in ("size", "sha256")
    )


def load_manifest(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DueCheckError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise DueCheckError(f"{label} schema is invalid")
    return payload


def write_event_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            payload = {field: row.get(field, "") for field in EVENT_FIELDS}
            source_refs = payload.get("source_refs")
            if isinstance(source_refs, (dict, list)):
                payload["source_refs"] = json.dumps(
                    source_refs,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            writer.writerow(payload)


def classify_due_checks(
    *,
    selection_path: Path,
    source_catalog_path: Path,
    request_manifest_path: Path,
    parse_manifest_path: Path,
    date_matches_path: Path,
    gaps_path: Path,
    cutoff: date,
    output_dir: Path,
) -> dict:
    selection = json.loads(selection_path.read_text())
    raw_targets = selection.get("targets") if isinstance(selection, dict) else None
    if not isinstance(raw_targets, list) or not raw_targets:
        raise DueCheckError("selection has no targets")
    require_unique_target_ids(raw_targets, label="selection")
    try:
        _selection, targets = load_selection(selection_path)
    except CalendarArtifactError as exc:
        raise DueCheckError(str(exc)) from exc
    target_by_id = {row["target_id"]: row for row in targets}
    selection_identity = identity(selection_path, root=output_dir)
    catalog_identity = identity(source_catalog_path, root=output_dir)
    request_identity = identity(request_manifest_path, root=output_dir)
    parse_identity = identity(parse_manifest_path, root=output_dir)
    request_manifest = load_manifest(
        request_manifest_path, label="request manifest"
    )
    parse_manifest = load_manifest(parse_manifest_path, label="parse manifest")
    if (
        not same_content_identity(request_manifest.get("selection"), selection_identity)
        or not same_content_identity(
            request_manifest.get("source_catalog"), catalog_identity
        )
        or not same_content_identity(parse_manifest.get("selection"), selection_identity)
        or not same_content_identity(
            parse_manifest.get("source_catalog"), catalog_identity
        )
        or not same_content_identity(
            parse_manifest.get("request_manifest"), request_identity
        )
    ):
        raise DueCheckError("current-year upstream manifest identity drifted")
    date_matches = read_jsonl(date_matches_path)
    gaps = read_jsonl(gaps_path)
    date_matches_identity = identity(date_matches_path, root=output_dir)
    gaps_identity = identity(gaps_path, root=output_dir)
    parse_artifacts = parse_manifest.get("artifacts")
    if (
        not isinstance(parse_artifacts, dict)
        or not same_content_identity(
            parse_artifacts.get("date_matches"), date_matches_identity
        )
        or not same_content_identity(parse_artifacts.get("gaps"), gaps_identity)
    ):
        raise DueCheckError("parse manifest date ledger identity drifted")
    require_unique_target_ids(date_matches, label="date matches")
    require_unique_target_ids(gaps, label="gaps")
    date_match_ids = {row["target_id"] for row in date_matches}
    gap_ids = {row["target_id"] for row in gaps}
    if date_match_ids & gap_ids:
        raise DueCheckError("date matches and gaps overlap")
    if date_match_ids | gap_ids != set(target_by_id):
        raise DueCheckError("date matches and gaps do not account for selection")

    due_rows = []
    not_due_rows = []
    for row in date_matches:
        target = target_by_id[row["target_id"]]
        try:
            local_date = date.fromisoformat(row["local_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DueCheckError(f"invalid date match local_date for target {row.get('target_id')}") from exc
        region = str(row.get("country_region") or target["country_region"])
        if region != target["country_region"]:
            raise DueCheckError(
                f"date match region differs from selection for target {row.get('target_id')}"
            )
        decorated = {**row, "due_check_cutoff": cutoff.isoformat()}
        if local_date <= cutoff:
            due_rows.append(
                {
                    **decorated,
                    "country_region": region,
                    "status": "finished",
                    "due_state": "due_event",
                }
            )
        else:
            not_due_rows.append(
                {
                    **decorated,
                    "country_region": region,
                    "status": "scheduled",
                    "due_state": "not_due",
                }
            )

    due_gaps = [
        {
            **row,
            "due_check_cutoff": cutoff.isoformat(),
            "due_state": "due_check_pending",
            "original_reason_code": row.get("reason_code"),
        }
        for row in gaps
    ]
    if output_dir.exists():
        raise DueCheckError(f"output already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        audit_files = {
            "not_due": temporary / "not_due.jsonl",
            "due_gaps": temporary / "due_gaps.jsonl",
        }
        audit_files["not_due"].write_bytes(
            b"".join(canonical(row) for row in sorted(not_due_rows, key=lambda row: row["target_id"]))
        )
        audit_files["due_gaps"].write_bytes(
            b"".join(canonical(row) for row in sorted(due_gaps, key=lambda row: row["target_id"]))
        )
        apply_paths = {}
        for region in sorted({row["country_region"] for row in due_rows}):
            path = temporary / f"events_{region}.csv"
            write_event_csv(
                path,
                sorted(
                    [row for row in due_rows if row["country_region"] == region],
                    key=lambda row: row["target_id"],
                ),
            )
            apply_paths[f"events_{region}"] = path
        summary = {
            "schema_version": "1.0",
            "scope_count": len(targets),
            "due_event_count": len(due_rows),
            "not_due_count": len(not_due_rows),
            "due_check_pending_count": len(due_gaps),
            "accounted_count": len(due_rows) + len(not_due_rows) + len(due_gaps),
            "cutoff_date": cutoff.isoformat(),
            "future_policy": "not_due_never_fabricate_result",
        }
        summary_path = temporary / "summary.json"
        summary_path.write_bytes(canonical(summary))
        apply_artifacts = {
            name: identity(path, root=temporary)
            for name, path in sorted(apply_paths.items())
        }
        descriptor_path = temporary / "apply_descriptor.json"
        manifest = {
            **summary,
            "inputs": {
                "selection": selection_identity,
                "source_catalog": catalog_identity,
                "request_manifest": request_identity,
                "parse_manifest": parse_identity,
                "date_matches": date_matches_identity,
                "gaps": gaps_identity,
            },
            "apply_artifacts": apply_artifacts,
            "audit_artifacts": {
                name: identity(path, root=temporary)
                for name, path in sorted(audit_files.items())
            },
            "summary": identity(summary_path, root=temporary),
        }
        manifest_path = temporary / "manifest.json"
        manifest_path.write_bytes(canonical(manifest))
        descriptor = {
            "schema_version": "1.0",
            "artifact_kind": "due_only",
            "cutoff_date": cutoff.isoformat(),
            "scope_count": len(targets),
            "due_event_count": len(due_rows),
            "classified_manifest": identity(manifest_path, root=temporary),
            "selection": selection_identity,
            "source_catalog": catalog_identity,
            "request_manifest": request_identity,
            "parse_manifest": parse_identity,
            "apply_artifacts": apply_artifacts,
        }
        descriptor_path.write_bytes(canonical(descriptor))
        temporary.replace(output_dir)
    except Exception:
        for path in sorted(temporary.glob("*"), reverse=True):
            path.unlink(missing_ok=True)
        temporary.rmdir()
        raise
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="按截止日分类当前年度赛事目标。")
    parser.add_argument("--selection-snapshot", required=True, type=Path)
    parser.add_argument("--source-catalog", required=True, type=Path)
    parser.add_argument("--request-manifest", required=True, type=Path)
    parser.add_argument("--parse-manifest", required=True, type=Path)
    parser.add_argument("--date-matches", required=True, type=Path)
    parser.add_argument("--gaps", required=True, type=Path)
    parser.add_argument("--cutoff-date", required=True, type=date.fromisoformat)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = classify_due_checks(
            selection_path=args.selection_snapshot,
            source_catalog_path=args.source_catalog,
            request_manifest_path=args.request_manifest,
            parse_manifest_path=args.parse_manifest,
            date_matches_path=args.date_matches,
            gaps_path=args.gaps,
            cutoff=args.cutoff_date,
            output_dir=args.output_dir,
        )
    except (DueCheckError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
