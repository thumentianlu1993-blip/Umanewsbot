from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from django.db import connection, transaction
from django.db.models import Prefetch

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceResolutionStatus,
    RaceEventCandidateStatus,
    RaceEventDataCandidate,
    RaceEventVisibility,
)
from stable.services.historical_batch_pipeline import HistoricalBatchPipelineError


STAGES = {"date", "detail-source", "final"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise HistoricalBatchPipelineError(f"{label} is not a regular file")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalBatchPipelineError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise HistoricalBatchPipelineError(f"{label} must be an object")
    return payload


def _read_jsonl(path: Path, *, label: str) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise HistoricalBatchPipelineError(f"{label} is not a regular file")
    rows = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise HistoricalBatchPipelineError(f"{label} row is not an object: {line_number}")
            rows.append(row)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalBatchPipelineError(f"{label} is unreadable") from exc
    return rows


def _manifest_file(root: Path, identity: Any, *, label: str) -> Path:
    if not isinstance(identity, dict):
        raise HistoricalBatchPipelineError(f"manifest {label} identity is invalid")
    relative = Path(str(identity.get("path") or ""))
    expected = str(identity.get("sha256") or "")
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not re.fullmatch(r"[0-9a-f]{64}", expected)
    ):
        raise HistoricalBatchPipelineError(f"manifest {label} identity is invalid")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise HistoricalBatchPipelineError(f"manifest {label} uses a symlink")
    path = candidate.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise HistoricalBatchPipelineError(f"manifest {label} escapes artifact root") from exc
    if path.is_symlink() or not path.is_file() or _sha256_file(path) != expected:
        raise HistoricalBatchPipelineError(f"manifest {label} SHA mismatch")
    return path


def _source_urls(refs: Any) -> set[str]:
    if not isinstance(refs, dict):
        return set()
    discovery = refs.get("detail_discovery")
    if not isinstance(discovery, dict):
        return set()
    sources = discovery.get("approved_detail_sources")
    if not isinstance(sources, list):
        return set()
    return {
        str(source.get("url"))
        for source in sources
        if isinstance(source, dict) and str(source.get("url") or "")
    }


def _candidate_source_url(row: dict[str, Any]) -> str:
    source_url = str(row.get("source_url") or "")
    if source_url:
        return source_url
    urls = row.get("urls")
    if isinstance(urls, dict):
        result = urls.get("result_url")
        if isinstance(result, dict):
            return str(result.get("url") or "")
    return ""


def _module_count(row: dict[str, Any], module: str) -> int | None:
    modules = row.get("modules")
    if not isinstance(modules, dict):
        return None
    payload = modules.get(module)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    return len(payload["items"])


def verify_historical_batch_stage(*, stage: str, artifact_dir: str | Path) -> dict[str, Any]:
    if stage not in STAGES:
        raise HistoricalBatchPipelineError(f"unsupported verification stage: {stage}")
    root = Path(artifact_dir).resolve()
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path, label="manifest")
    if manifest.get("schema_version") != "1.0":
        raise HistoricalBatchPipelineError("manifest schema is invalid")
    selection_path = _manifest_file(root, manifest.get("selection"), label="selection")
    complete_path = _manifest_file(root, manifest.get("complete"), label="complete")
    gaps_path = _manifest_file(root, manifest.get("gaps"), label="gaps")
    selection = _read_json(selection_path, label="selection")
    targets_in_scope = selection.get("targets")
    if selection.get("schema_version") != "1.0" or not isinstance(targets_in_scope, list):
        raise HistoricalBatchPipelineError("selection targets are invalid")
    try:
        scope_by_id = {
            int(row["target_id"]): row
            for row in targets_in_scope
            if isinstance(row, dict) and not isinstance(row.get("target_id"), bool)
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalBatchPipelineError("selection target IDs are invalid") from exc
    if len(scope_by_id) != len(targets_in_scope):
        raise HistoricalBatchPipelineError("selection target IDs are duplicated")
    complete_rows = _read_jsonl(complete_path, label="complete")
    gap_rows = _read_jsonl(gaps_path, label="gaps")
    try:
        complete_by_id = {
            int(row["target_id"]): row
            for row in complete_rows
            if not isinstance(row.get("target_id"), bool)
        }
        gaps_by_id = {
            int(row["target_id"]): row
            for row in gap_rows
            if not isinstance(row.get("target_id"), bool)
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalBatchPipelineError("complete/gap target IDs are invalid") from exc
    gap_ids = set(gaps_by_id)
    if (
        len(complete_by_id) != len(complete_rows)
        or len(gap_ids) != len(gap_rows)
        or set(complete_by_id) & gap_ids
        or set(complete_by_id) | gap_ids != set(scope_by_id)
    ):
        raise HistoricalBatchPipelineError("complete/gap coverage does not equal selection")

    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
        applied_candidates = RaceEventDataCandidate.objects.filter(
            status=RaceEventCandidateStatus.APPLIED
        ).order_by("event_id", "module", "-applied_at", "-id")
        queryset = (
            HistoricalRaceEventTarget.objects.filter(pk__in=scope_by_id)
            .select_related("race_series", "event")
            .prefetch_related("event__runners", "event__results")
            .prefetch_related(
                Prefetch("event__data_candidates", queryset=applied_candidates, to_attr="verified_applied_candidates")
            )
        )
        targets = {target.pk: target for target in queryset}
        errors: list[dict[str, Any]] = []
        region_counts: dict[str, dict[str, int]] = {}
        published_count = 0
        runner_count = 0
        result_count = 0
        gap_pending_count = 0
        for target_id, expected in sorted(scope_by_id.items()):
            target = targets.get(target_id)
            if target is None:
                errors.append({"target_id": target_id, "code": "target_missing"})
                continue
            region = target.country_region
            region_counts.setdefault(region, {"targets": 0, "complete": 0, "gaps": 0, "runners": 0, "results": 0})
            region_counts[region]["targets"] += 1
            event = target.event
            if event is not None and event.visibility_status == RaceEventVisibility.PUBLISHED:
                published_count += 1
                errors.append({"target_id": target_id, "code": "historical_event_published"})
            if target_id in gap_ids:
                region_counts[region]["gaps"] += 1
                gap = gaps_by_id[target_id]
                if gap.get("target_sha256") != expected.get("target_sha256"):
                    errors.append(
                        {
                            "target_id": target_id,
                            "code": "gap_selection_identity_mismatch",
                            "selection": expected.get("target_sha256"),
                            "gap": gap.get("target_sha256"),
                        }
                    )
                if stage == "final":
                    if target.resolution_status == HistoricalRaceResolutionStatus.IMPORTED:
                        errors.append(
                            {
                                "target_id": target_id,
                                "code": "gap_target_already_imported",
                            }
                        )
                    else:
                        gap_pending_count += 1
                continue
            region_counts[region]["complete"] += 1
            row = complete_by_id[target_id]
            if event is None:
                errors.append({"target_id": target_id, "code": "event_missing"})
                continue
            if row.get("target_sha256") != expected.get("target_sha256"):
                errors.append(
                    {
                        "target_id": target_id,
                        "code": "candidate_selection_identity_mismatch",
                        "selection": expected.get("target_sha256"),
                        "candidate": row.get("target_sha256"),
                    }
                )
            inventory_sha = str(
                row.get("inventory_artifact_sha256")
                or expected.get("inventory_artifact_sha256")
                or selection.get("inventory_manifest_sha256")
                or ""
            )
            if target.artifact_sha256 != inventory_sha:
                errors.append(
                    {
                        "target_id": target_id,
                        "code": "inventory_identity_mismatch",
                        "expected": inventory_sha,
                        "actual": target.artifact_sha256,
                    }
                )
            expected_date = str(row.get("local_date") or "")
            actual_event_date = event.local_date.isoformat() if event.local_date else ""
            actual_target_date = target.local_date.isoformat() if target.local_date else ""
            if expected_date and (
                actual_event_date != expected_date or actual_target_date != expected_date
            ):
                errors.append(
                    {
                        "target_id": target_id,
                        "code": "date_mismatch",
                        "expected": expected_date,
                        "event": actual_event_date,
                        "target": actual_target_date,
                    }
                )
            if stage in {"detail-source", "final"}:
                expected_source = _candidate_source_url(row)
                if not expected_source:
                    errors.append({"target_id": target_id, "code": "source_missing_from_artifact"})
                else:
                    target_sources = _source_urls(target.source_refs)
                    event_sources = _source_urls(event.source_refs)
                    if expected_source not in target_sources or expected_source not in event_sources:
                        errors.append(
                            {
                                "target_id": target_id,
                                "code": "approved_source_mismatch",
                                "expected": expected_source,
                                "target_sources": sorted(target_sources),
                                "event_sources": sorted(event_sources),
                            }
                        )
            if stage == "final":
                if target.resolution_status != HistoricalRaceResolutionStatus.IMPORTED:
                    errors.append(
                        {
                            "target_id": target_id,
                            "code": "resolution_not_imported",
                            "actual": target.resolution_status,
                        }
                    )
                for module in ("runners", "results"):
                    if (target.module_statuses or {}).get(module) != "complete":
                        errors.append(
                            {
                                "target_id": target_id,
                                "code": "module_status_incomplete",
                                "module": module,
                            }
                        )
                expected_runners = _module_count(row, "runners")
                expected_results = _module_count(row, "results")
                actual_runners = len(event.runners.all())
                actual_results = len(event.results.all())
                runner_count += actual_runners
                result_count += actual_results
                region_counts[region]["runners"] += actual_runners
                region_counts[region]["results"] += actual_results
                if expected_runners != actual_runners:
                    errors.append(
                        {
                            "target_id": target_id,
                            "code": "runner_count_mismatch",
                            "expected": expected_runners,
                            "actual": actual_runners,
                        }
                    )
                if expected_results != actual_results:
                    errors.append(
                        {
                            "target_id": target_id,
                            "code": "result_count_mismatch",
                            "expected": expected_results,
                            "actual": actual_results,
                        }
                    )
                expected_source = _candidate_source_url(row)
                applied_by_module: dict[str, RaceEventDataCandidate] = {}
                for candidate in event.verified_applied_candidates:
                    if candidate.module in {"runners", "results"}:
                        applied_by_module.setdefault(candidate.module, candidate)
                if set(applied_by_module) != {"runners", "results"}:
                    errors.append(
                        {
                            "target_id": target_id,
                            "code": "applied_candidate_modules_missing",
                            "actual": sorted(applied_by_module),
                        }
                    )
                candidate_sources = {
                    candidate.source_url for candidate in applied_by_module.values()
                }
                if candidate_sources != {expected_source}:
                    errors.append(
                        {
                            "target_id": target_id,
                            "code": "applied_candidate_source_mismatch",
                            "expected": expected_source,
                            "actual": sorted(candidate_sources),
                        }
                    )
                for module, candidate in applied_by_module.items():
                    raw_payload = candidate.raw_payload or {}
                    if (
                        raw_payload.get("historical_target_id") != target_id
                        or raw_payload.get("target_sha256") != row.get("target_sha256")
                        or raw_payload.get("inventory_artifact_sha256") != inventory_sha
                    ):
                        errors.append(
                            {
                                "target_id": target_id,
                                "code": "applied_candidate_provenance_mismatch",
                                "module": module,
                            }
                        )
        report = {
            "schema_version": "1.0",
            "stage": stage,
            "artifact_manifest_sha256": _sha256_file(manifest_path),
            "scope_count": len(scope_by_id),
            "complete_count": len(complete_by_id),
            "gap_count": len(gap_ids),
            "gap_pending_count": gap_pending_count,
            "published_count": published_count,
            "runner_count": runner_count,
            "result_count": result_count,
            "region_counts": region_counts,
            "error_count": len(errors),
            "errors": errors,
        }
    return report


def write_verification_report(path: str | Path, report: dict[str, Any]) -> None:
    destination = Path(path)
    if destination.exists() or destination.is_symlink():
        raise HistoricalBatchPipelineError(f"verification report already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise HistoricalBatchPipelineError(
                f"verification report already exists: {destination}"
            ) from exc
        temporary.unlink()
        parent_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
