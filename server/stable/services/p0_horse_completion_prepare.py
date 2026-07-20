"""Rolling P0 horse batch prepare stage: checkpointed fetching + artifact publish.

Consumes an approved batch manifest (fail-closed SHA binding), executes the
five-region completion adapters per candidate with BatchRunState checkpoint
semantics, streams per-candidate payloads to staging, and atomically
publishes the reviewable artifact set. All network access goes through the
persistent per-region budget ledger; budget exhaustion aborts the run in a
resumable ``prepare_failed`` state.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from django.conf import settings

from stable.services.p0_horse_completion_adapters import (
    P0HorseCompletionRequest,
    REVIEWED_CANDIDATE_REQUEST_BUDGETS,
    _blocked_candidate_payload,
    _PerCandidateSourceClient,
    p0_horse_completion_cache_path,
    run_p0_horse_completion_adapter,
)
from stable.services.p0_horse_completion_batch import (
    BatchRunState,
    P0HorseBatchError,
    P0_HORSE_BATCH_REGIONS,
    _utcnow_iso,
    _write_json_atomically,
    append_resume_history,
    invalidate_downstream_stages,
    plan_candidate_resume,
    record_candidate_failure,
    record_candidate_success,
    validate_approved_batch_manifest,
)
from stable.services.p0_horse_completion_budget import (
    before_p0_horse_source_request,
    load_race_event_request_budget_module,
)


def _candidate_external_id(candidate: dict[str, Any]) -> str:
    namespace = str(candidate.get("source_namespace") or "").strip()
    if not namespace:
        return ""
    prefix = f"{namespace}:"
    for key in candidate.get("identity_keys") or []:
        text = str(key or "").strip()
        if text.startswith(prefix):
            return text[len(prefix) :]
    return ""


def _candidate_primary_url(candidate: dict[str, Any]) -> str:
    for value in candidate.get("source_urls") or []:
        text = str(value or "").strip()
        if text.startswith("https://") or text.startswith("http://"):
            return text
    return ""


def _interleave_by_region(horses: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_region: dict[str, list[dict[str, Any]]] = {
        region: [] for region in P0_HORSE_BATCH_REGIONS
    }
    for horse in horses:
        by_region.setdefault(horse["region"], []).append(horse)
    interleaved: list[dict[str, Any]] = []
    index = 0
    while True:
        added = False
        for region in P0_HORSE_BATCH_REGIONS:
            rows = by_region.get(region) or []
            if index < len(rows):
                interleaved.append(rows[index])
                added = True
        if not added:
            return interleaved
        index += 1


def _staging_path(run_dir: Path, candidate_key: str) -> Path:
    digest = hashlib.sha256(candidate_key.encode("utf-8")).hexdigest()[:16]
    return run_dir / "staging" / f"{digest}.json"


def _default_source_client_factory(
    region: str,
    *,
    budget_dir: str | Path | None,
    host_interval_dir: str | Path | None,
    max_requests: int | None,
):
    import requests

    from stable.services.p0_horse_completion_source_clients import (
        build_p0_horse_completion_source_client,
    )

    return build_p0_horse_completion_source_client(
        region,
        transport=requests.Session(),
        budget_hook=lambda url: before_p0_horse_source_request(
            url,
            region=region,
            budget_dir=budget_dir,
            max_requests=max_requests,
            host_interval_dir=host_interval_dir,
        ),
    )


def _region_run_request_limit(region: str, horse_count: int) -> int:
    """Derived per-run request cap: per-candidate budget x2 (retry allowance)."""
    override = int(getattr(settings, "HORSE_PROFILE_COMPLETION_MAX_REQUESTS", 0))
    if override > 0:
        return override
    per_candidate = REVIEWED_CANDIDATE_REQUEST_BUDGETS[region]
    return max(1, horse_count) * per_candidate * 2


def _request_from_candidate(
    candidate: dict[str, Any],
    *,
    cache_dir: str | Path,
    allow_network: bool,
    request_interval_seconds: float,
) -> P0HorseCompletionRequest:
    region = candidate["region"]
    cache_path = p0_horse_completion_cache_path(cache_dir, candidate["candidate_key"])
    return P0HorseCompletionRequest(
        candidate_key=candidate["candidate_key"],
        region=region,
        horse_name=candidate["horse_name"],
        source_url=_candidate_primary_url(candidate),
        external_horse_id=_candidate_external_id(candidate),
        candidate_source_name=str(candidate.get("source_namespace") or "").strip(),
        expected_sire_name=str(candidate.get("expected_sire_name") or "").strip(),
        expected_dam_name=str(candidate.get("expected_dam_name") or "").strip(),
        expected_birth_year=candidate.get("expected_birth_year"),
        cache_path=str(cache_path),
        allow_network=allow_network,
        request_interval_seconds=request_interval_seconds,
        request_budget=REVIEWED_CANDIDATE_REQUEST_BUDGETS[region],
        batch_limit=int(
            getattr(settings, "HORSE_PROFILE_COMPLETION_REGION_BATCH_LIMIT", 100)
        ),
    )


def _payload_summary_row(payload: dict[str, Any]) -> dict[str, Any]:
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    career = (
        payload.get("career_history")
        if isinstance(payload.get("career_history"), dict)
        else {}
    )
    evidence = [
        item.get("source_url", "")
        for item in payload.get("source_evidence", [])
        if isinstance(item, dict)
    ]
    return {
        "candidate_key": payload.get("candidate_key", ""),
        "region": payload.get("region", ""),
        "horse_name": payload.get("horse_name", ""),
        "external_horse_id": payload.get("external_horse_id", ""),
        "basic_profile_complete": bool(coverage.get("basic_profile", {}).get("complete")),
        "pedigree_complete": bool(coverage.get("pedigree", {}).get("complete")),
        "career_history_complete": bool(coverage.get("career_history", {}).get("complete")),
        "source_evidence_complete": bool(coverage.get("source_evidence", {}).get("complete")),
        "official_or_source_start_count": career.get("official_or_source_start_count", ""),
        "collected_start_count": career.get("collected_start_count", ""),
        "career_history_gap_count": career.get("gap_count", ""),
        "failure_reason": ";".join(payload.get("failure_reason") or []),
        "source_urls": ";".join(evidence),
    }


def _publish_batch_artifacts(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    staging_paths: list[Path],
    generated_at: str,
) -> dict[str, Any]:
    """Atomically publish the artifact set, streaming one payload at a time.

    Peak memory is one candidate payload, never the whole batch — a hard
    requirement on the 4 GiB production host.
    """
    staging_dir = run_dir / "artifact.tmp"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    failure_counts: dict[str, int] = {}
    region_counts: dict[str, dict[str, int]] = {}
    blocked = 0
    network_requests = 0
    cache_hits = 0
    total = 0
    blocked_entries: list[dict[str, Any]] = []
    profile_id_by_key = {
        horse["candidate_key"]: horse.get("profile_id")
        for horse in manifest.get("horses") or []
    }

    combined_path = staging_dir / "combined_candidates.jsonl"
    review_path = staging_dir / "batch_review.csv"
    evidence_path = staging_dir / "source_evidence_manifest.jsonl"
    with combined_path.open("w", encoding="utf-8") as combined, evidence_path.open(
        "w", encoding="utf-8"
    ) as evidence, review_path.open("w", encoding="utf-8", newline="") as csv_handle:
        writer: csv.DictWriter | None = None
        for staging_path in staging_paths:
            try:
                payload = json.loads(staging_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise P0HorseBatchError(
                    f"candidate staging payload missing or unreadable: {staging_path}"
                ) from exc
            combined.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            combined.flush()
            row = _payload_summary_row(payload)
            if writer is None:
                writer = csv.DictWriter(csv_handle, fieldnames=list(row.keys()))
                writer.writeheader()
            writer.writerow(row)
            evidence.write(
                json.dumps(
                    {
                        "candidate_key": payload.get("candidate_key", ""),
                        "source_evidence": payload.get("source_evidence") or [],
                        "retrieval": payload.get("retrieval") or {},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            total += 1
            region = str(payload.get("region") or "")
            bucket = region_counts.setdefault(region, {"horses": 0, "blocked": 0})
            bucket["horses"] += 1
            reasons = payload.get("failure_reason") or []
            if reasons:
                blocked += 1
                bucket["blocked"] += 1
                blocked_entries.append(
                    {
                        "profile_id": profile_id_by_key.get(payload.get("candidate_key")),
                        "candidate_key": payload.get("candidate_key", ""),
                        "horse_name": payload.get("horse_name", ""),
                        "region": region,
                        "reason": "blocked_at_prepare",
                        "failure_reason": list(reasons),
                        "batch_id": manifest["batch_id"],
                        "recorded_at": generated_at,
                    }
                )
            for reason in reasons:
                failure_counts[reason] = failure_counts.get(reason, 0) + 1
            retrieval = payload.get("retrieval") if isinstance(payload.get("retrieval"), dict) else {}
            network_requests += int(retrieval.get("network_request_count") or 0)
            cache_hits += int(bool(retrieval.get("cache_hit")))
            del payload
        if writer is None:
            csv.DictWriter(csv_handle, fieldnames=["candidate_key"]).writeheader()

    summary: dict[str, Any] = {
        "schema_version": "p0-horse-completion-batch-summary.v1",
        "batch_id": manifest["batch_id"],
        "batch_manifest_sha256": manifest["batch_sha256"],
        "generated_at": generated_at,
        "totals": {
            "horses": total,
            "succeeded": total - blocked,
            "blocked": blocked,
        },
        "region_counts": region_counts,
        "failure_reason_counts": failure_counts,
        "network": {
            "network_request_count": network_requests,
            "cache_hit_count": cache_hits,
        },
        "artifacts": {},
    }
    summary_path = staging_dir / "summary.json"
    for artifact_path in sorted(staging_dir.iterdir()):
        if artifact_path.is_file() and artifact_path.name != "summary.json":
            summary["artifacts"][artifact_path.name] = hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest()
    _write_json_atomically(summary_path, summary)

    artifact_dir = run_dir / "artifact"
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    os.replace(staging_dir, artifact_dir)
    if blocked_entries:
        from stable.services.p0_horse_completion_batch import (
            append_blocker_pool_entries,
        )

        append_blocker_pool_entries(
            run_dir,
            blocked_entries,
            replace_batch_id=manifest["batch_id"],
            replace_reason="blocked_at_prepare",
        )
    return summary


def prepare_p0_horse_batch(
    manifest_path: str | Path,
    *,
    expected_sha256: str | None = None,
    allow_network: bool = False,
    cache_dir: str | Path | None = None,
    budget_dir: str | Path | None = None,
    source_client_factory: Callable[[str], Any] | None = None,
    request_interval_seconds: float | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    manifest = validate_approved_batch_manifest(
        manifest_path,
        expected_sha256=expected_sha256,
    )
    run_dir = Path(manifest_path).parent
    state_path = run_dir / "state.json"
    if state_path.exists():
        state = BatchRunState.read(run_dir)
    else:
        state = BatchRunState.create(batch_id=manifest["batch_id"], run_dir=run_dir)
    if state.stage == "abandoned":
        raise P0HorseBatchError("batch run was abandoned; start a new batch")

    effective_cache_dir = Path(
        cache_dir
        or getattr(
            settings,
            "HORSE_PROFILE_COMPLETION_CACHE_DIR",
            "runtime/horse_profile_completion/cache",
        )
    )
    interval = (
        float(request_interval_seconds)
        if request_interval_seconds is not None
        else float(
            getattr(settings, "HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS", 8.0)
        )
    )
    candidates = list(manifest.get("horses") or [])
    decisions = plan_candidate_resume(state, candidates)
    decision_counts: dict[str, int] = {}
    for decision in decisions.values():
        action = decision["action"]
        decision_counts[action] = decision_counts.get(action, 0) + 1
    if state.candidate_states:
        append_resume_history(
            state,
            from_stage=state.stage,
            decisions=decision_counts,
        )
    state.stage = "preparing"
    state.write()

    budget_error = load_race_event_request_budget_module().RequestBudgetExceeded
    budget_root = Path(
        budget_dir
        or getattr(
            settings,
            "HORSE_PROFILE_COMPLETION_BUDGET_DIR",
            "runtime/horse_profile_completion/budget",
        )
    )
    run_budget_dir = budget_root / "runs" / manifest["batch_id"]
    host_interval_dir = budget_root / "host-interval"
    region_horse_counts: dict[str, int] = {}
    for candidate in candidates:
        region_horse_counts[candidate["region"]] = (
            region_horse_counts.get(candidate["region"], 0) + 1
        )

    if source_client_factory is None:
        factory = lambda region: _default_source_client_factory(  # noqa: E731
            region,
            budget_dir=run_budget_dir,
            host_interval_dir=host_interval_dir,
            max_requests=_region_run_request_limit(
                region,
                region_horse_counts.get(region, 0),
            ),
        )
    else:
        factory = source_client_factory
    region_clients: dict[str, Any] = {}
    reran = False
    for candidate in _interleave_by_region(candidates):
        key = candidate["candidate_key"]
        if decisions[key]["action"] == "skipped_unchanged":
            continue
        reran = True
        region = candidate["region"]
        request = _request_from_candidate(
            candidate,
            cache_dir=effective_cache_dir,
            allow_network=allow_network,
            request_interval_seconds=interval,
        )
        if region not in region_clients:
            region_clients[region] = factory(region)
        delegate = region_clients.get(region)
        source_client = _PerCandidateSourceClient(delegate) if delegate is not None else None
        try:
            payload = run_p0_horse_completion_adapter(
                request,
                source_client=source_client,
            )
        except budget_error as exc:
            record_candidate_failure(state, candidate, error=str(exc))
            state.stage = "prepare_failed"
            state.write()
            raise P0HorseBatchError(
                f"request budget exhausted during batch prepare: {exc}"
            ) from exc
        except Exception as exc:
            from stable.services.p0_horse_completion_source_clients import (
                P0HorseSourceBlocked,
            )

            if isinstance(exc, P0HorseSourceBlocked):
                failure_reason = "source_cache_or_adapter_error"
            elif exc.__class__.__name__ == "P0HorseCompletionNetworkDisabled":
                failure_reason = "network_disabled_cache_missing"
            else:
                failure_reason = "unexpected_adapter_error"
            payload = _blocked_candidate_payload(
                candidate,
                failure_reason=failure_reason,
                request=request,
                network_request_count=int(
                    getattr(source_client, "last_request_count", 0) or 0
                ),
                error=exc,
            )
        staging_path = _staging_path(run_dir, key)
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomically(staging_path, payload)
        record_candidate_success(state, candidate, outputs={"payload": staging_path})

    invalidate_downstream_stages(state, reran=reran)

    staging_paths = [
        _staging_path(run_dir, candidate["candidate_key"]) for candidate in candidates
    ]
    try:
        summary = _publish_batch_artifacts(
            run_dir=run_dir,
            manifest=manifest,
            staging_paths=staging_paths,
            generated_at=generated_at or _utcnow_iso(),
        )
    except Exception:
        state.stage = "prepare_failed"
        state.write()
        raise
    summary["resume"] = decision_counts
    for stage in ("prepare", "artifact"):
        if stage not in state.completed_stages:
            state.completed_stages.append(stage)
    state.stage = "prepared"
    state.artifacts["artifact_dir"] = str(run_dir / "artifact")
    state.write()
    return summary
