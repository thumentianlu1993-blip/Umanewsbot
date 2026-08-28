"""Fail-closed scheduled race-result review preparation and reviewed apply."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
from io import StringIO
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management import call_command
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from stable import models


SELECTOR_VERSION = "scheduled-race-result-review-v1"
REVIEW_PAYLOAD_VERSION = "race-result-review-payload-v1"
REVIEW_CSV_FIELDS = (
    "event_id",
    "event_name",
    "race_datetime",
    "source_authority",
    "authority",
    "reviewed_row_digest",
    "result_order_complete",
    "finish_position",
    "horse_number",
    "horse_name",
    "running_status",
)
STALE_CLAIM_MANIFEST_VERSION = "race-result-review-stale-claims/v1"
STALE_CLAIM_REASON_CODES = {
    "lease_expired_without_terminal",
    "stale_claim_reconciled",
}
REVIEW_CLAIM_ADVISORY_LOCK_ID = 7_046_029_254_386_353_131
logger = logging.getLogger(__name__)


class ReviewBundleDrift(ValueError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


class StaleClaimReconciliationBlocked(ValueError):
    pass


class StaleClaimManifestDrift(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    data = value if isinstance(value, bytes) else _canonical_json(value)
    return hashlib.sha256(data).hexdigest()


def _lock_review_claim_namespace() -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [REVIEW_CLAIM_ADVISORY_LOCK_ID],
        )


def _stale_claim_snapshot(run: models.RaceResultReviewRun) -> dict[str, Any]:
    return {
        "run_id": run.pk,
        "schedule_slot": run.schedule_slot.isoformat(),
        "lease_expires_at": (
            run.lease_expires_at.isoformat() if run.lease_expires_at else None
        ),
        "selector_sha256": run.selector_sha256,
        "bundle_sha256": run.bundle_sha256,
        "cursor_sha256": _sha256(run.cursor),
        "terminal_summary_sha256": _sha256(run.terminal_summary),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "updated_at": run.updated_at.isoformat(),
    }


def _stale_claim_blockers(
    run: models.RaceResultReviewRun, *, now: datetime
) -> list[str]:
    blockers: list[str] = []
    if run.lease_expires_at is None:
        blockers.append("lease_missing")
    elif run.lease_expires_at > now:
        blockers.append("lease_not_expired")
    if not isinstance(run.cursor, dict) or set(run.cursor) != {"claim_token"}:
        blockers.append("cursor_contract_invalid")
    elif (
        not isinstance(run.cursor.get("claim_token"), str)
        or not run.cursor["claim_token"]
    ):
        blockers.append("claim_token_invalid")
    if run.selector_sha256:
        blockers.append("selector_present")
    if run.bundle_sha256:
        blockers.append("bundle_present")
    if run.terminal_summary:
        blockers.append("terminal_summary_present")
    if run.finished_at is not None:
        blockers.append("finished_at_present")
    return blockers


def _stale_claim_preview_for_runs(
    runs: Iterable[models.RaceResultReviewRun], *, now: datetime
) -> dict[str, Any]:
    ordered = sorted(runs, key=lambda run: (run.schedule_slot, run.pk))
    rows = [_stale_claim_snapshot(run) for run in ordered]
    blocked = []
    eligible_ids = []
    for run in ordered:
        reasons = _stale_claim_blockers(run, now=now)
        if reasons:
            blocked.append({"run_id": run.pk, "reason_codes": reasons})
        else:
            eligible_ids.append(run.pk)
    manifest = {
        "schema_version": STALE_CLAIM_MANIFEST_VERSION,
        "runs": rows,
        "eligible_run_ids": eligible_ids,
        "blocked": blocked,
    }
    return {
        **manifest,
        "manifest_sha256": _sha256(manifest),
        "claimed_count": len(rows),
        "eligible_count": len(eligible_ids),
        "blocked_count": len(blocked),
    }


def build_stale_claim_reconciliation_preview(
    *, now: datetime, run_ids: Iterable[int] | None = None
) -> dict[str, Any]:
    queryset = models.RaceResultReviewRun.objects.filter(status="claimed")
    if run_ids is not None:
        queryset = queryset.filter(pk__in=tuple(run_ids))
    return _stale_claim_preview_for_runs(
        queryset.order_by("schedule_slot", "id"),
        now=now,
    )


def reconcile_expired_review_claims(
    *,
    now: datetime,
    reason_code: str,
    expected_manifest_sha256: str | None = None,
    include_all_claimed: bool = False,
) -> dict[str, Any]:
    if reason_code not in STALE_CLAIM_REASON_CODES:
        raise ValueError("stale claim reason_code is not allowed")
    with transaction.atomic():
        _lock_review_claim_namespace()
        queryset = models.RaceResultReviewRun.objects.select_for_update().filter(
            status="claimed"
        )
        if not include_all_claimed:
            queryset = queryset.filter(
                Q(lease_expires_at__lte=now) | Q(lease_expires_at__isnull=True)
            )
        runs = list(queryset.order_by("schedule_slot", "id"))
        preview = _stale_claim_preview_for_runs(runs, now=now)
        if (
            expected_manifest_sha256 is not None
            and preview["manifest_sha256"] != expected_manifest_sha256
        ):
            raise StaleClaimManifestDrift(
                "stale claim manifest drift: expected exact preview digest"
            )
        if preview["blocked_count"]:
            raise StaleClaimReconciliationBlocked(
                "stale claim reconciliation blocked by non-empty or live claim state"
            )
        reconciled_ids: list[int] = []
        for run in runs:
            summary = {
                "status": "failed",
                "reason_code": reason_code,
                "schedule_slot": run.schedule_slot.isoformat(),
                "previous_lease_expires_at": run.lease_expires_at.isoformat(),
                "reconciled_at": now.isoformat(),
            }
            updated = models.RaceResultReviewRun.objects.filter(
                pk=run.pk,
                status="claimed",
                cursor=run.cursor,
                lease_expires_at=run.lease_expires_at,
                selector_sha256="",
                bundle_sha256="",
                terminal_summary={},
                finished_at__isnull=True,
            ).update(
                status="failed",
                terminal_summary=summary,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
            if updated != 1:
                raise StaleClaimManifestDrift(
                    f"stale claim changed while reconciling run_id={run.pk}"
                )
            reconciled_ids.append(run.pk)
        return {
            "manifest_sha256": preview["manifest_sha256"],
            "reason_code": reason_code,
            "reconciled_count": len(reconciled_ids),
            "reconciled_run_ids": reconciled_ids,
            "remaining_claimed_count": models.RaceResultReviewRun.objects.filter(
                status="claimed"
            ).count(),
        }


def coalesce_due_schedule_slots(
    *, due_slots: Iterable[datetime], now: datetime, max_catchup_days: int
) -> dict[str, Any]:
    ordered = sorted(set(due_slots))
    cutoff = now - timedelta(days=max_catchup_days)
    live = [slot for slot in ordered if cutoff <= slot <= now]
    expired = [slot for slot in ordered if slot < cutoff]
    execute = live[-1] if live else None
    return {
        "execute_slot": execute,
        "request_budget_count": 1 if execute else 0,
        "coalesced_slots": [
            {
                "schedule_slot": slot,
                "terminal_state": "coalesced_to_latest_due_slot",
            }
            for slot in live[:-1]
        ],
        "expired_slots": expired,
    }


def prepare_target_with_route(
    *,
    event_identity: dict[str, Any],
    routes: list[dict[str, Any]],
    adapter_manifests: dict[str, dict[str, Any]],
    now: datetime,
    transport: Callable[..., Any],
) -> dict[str, Any]:
    matches = [
        route
        for route in routes
        if route.get("region") == event_identity.get("country_region")
        and route.get("provider") == event_identity.get("provider")
        and event_identity.get("identity_namespace")
        in route.get("identity_namespaces", [])
    ]
    if len(matches) != 1:
        return {"status": "blocked", "reason_code": "route_not_unique"}
    route = matches[0]
    manifest = adapter_manifests.get(route.get("adapter"))
    if not manifest or manifest.get("canonical_adapter") != route.get("adapter"):
        return {
            "status": "blocked",
            "reason_code": "route_adapter_contract_mismatch",
        }
    expected = {
        "region": event_identity.get("country_region"),
        "provider": event_identity.get("provider"),
        "source_authority": route.get("source_authority"),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        return {
            "status": "blocked",
            "reason_code": "route_adapter_contract_mismatch",
        }
    if "results" not in route.get("modules", []) or "results" not in manifest.get(
        "modules", []
    ):
        return {"status": "blocked", "reason_code": "route_module_not_allowed"}
    try:
        valid_until = datetime.fromisoformat(
            str(route.get("valid_until", "")).replace("Z", "+00:00")
        )
    except ValueError:
        return {"status": "blocked", "reason_code": "route_validity_invalid"}
    if not route.get("automation_allowed") or valid_until < now:
        return {"status": "blocked", "reason_code": "route_not_active"}
    response = transport(event_identity=event_identity, route=route)
    return {
        "status": "prepared",
        "route_key": route["key"],
        "authority": route["source_authority"],
        "candidate_permission": route.get("candidate_permission"),
        "transport_result": response,
    }


def compute_reviewed_row_digest(results: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "finish_position": row.get("finish_position"),
            "horse_number": str(row.get("horse_number") or ""),
            "horse_name": str(row.get("horse_name") or ""),
            "running_status": str(row.get("running_status") or ""),
        }
        for row in results
    ]
    return _sha256(normalized)


def build_review_payload(*, candidate_events: list[dict[str, Any]]) -> dict[str, Any]:
    events = []
    for candidate in sorted(candidate_events, key=lambda row: int(row["event_id"])):
        event = deepcopy(candidate)
        event["authority"] = event.pop(
            "approval_authority", event.get("authority", "")
        )
        event["reviewed_row_digest"] = compute_reviewed_row_digest(
            event.get("results", [])
        )
        events.append(event)
    return {"schema_version": REVIEW_PAYLOAD_VERSION, "events": events}


def render_review_csv(*, payload: dict[str, Any]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=REVIEW_CSV_FIELDS)
    writer.writeheader()
    for event in payload.get("events", []):
        common = {
            "event_id": event["event_id"],
            "event_name": event.get("event_name", ""),
            "race_datetime": event.get("race_datetime", ""),
            "source_authority": event.get("source_authority", ""),
            "authority": event.get("authority", ""),
            "reviewed_row_digest": event.get("reviewed_row_digest", ""),
            "result_order_complete": str(
                bool(event.get("result_order_complete"))
            ).lower(),
        }
        for result in event.get("results", []):
            writer.writerow(
                {
                    **common,
                    "finish_position": result.get("finish_position", ""),
                    "horse_number": result.get("horse_number", ""),
                    "horse_name": result.get("horse_name", ""),
                    "running_status": result.get("running_status", ""),
                }
            )
    return output.getvalue().encode("utf-8")


def verify_review_payload_csv(
    *, payload: dict[str, Any], csv_bytes: bytes
) -> dict[str, Any]:
    if render_review_csv(payload=payload) != csv_bytes:
        raise ReviewBundleDrift("review_csv_payload_drift")
    return {"equivalent": True, "row_count": sum(len(e.get("results", [])) for e in payload.get("events", []))}


def plan_delivery_attempt(
    *,
    bundle_sha256: str,
    recipient: str,
    current_state: dict[str, Any],
    now: datetime,
    lease_seconds: int,
) -> dict[str, Any]:
    message_id = current_state.get("message_id") or f"<{bundle_sha256}@umafans.run>"
    status = current_state.get("status")
    lease = current_state.get("lease_expires_at")
    if status == "sent":
        return {"action": "already_notified", "message_id": message_id}
    if status == "sending" and lease and lease > now:
        return {"action": "leased", "message_id": message_id}
    return {
        "action": "send",
        "attempt_count": int(current_state.get("attempt_count") or 0) + 1,
        "message_id": message_id,
        "lease_expires_at": now + timedelta(seconds=lease_seconds),
        "delivery_semantics": "at_least_once",
    }


def plan_reviewed_event_write(
    *, authority: str, source_authority: str, result_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if authority not in {"official", "human_reviewed_reference"}:
        raise ReviewBundleDrift("approval_authority_invalid")
    official = authority == "official"
    rows = [
        {
            **deepcopy(row),
            "official_finish_position": row.get("finish_position") if official else None,
        }
        for row in result_rows
    ]
    return {
        "public_label": "官方赛果" if official else "已人工审核赛果",
        "create_official_receipt": official,
        "source_authority": source_authority,
        "result_rows": rows,
    }


def _event_due_at(event: models.RaceEvent) -> datetime | None:
    if event.race_datetime:
        return event.race_datetime
    if not event.local_date or not event.timezone_name:
        return None
    try:
        zone = ZoneInfo(event.timezone_name)
    except ZoneInfoNotFoundError:
        return None
    return datetime.combine(
        event.local_date + timedelta(days=1), time.min, tzinfo=zone
    ).astimezone(dt_timezone.utc)


def load_route_registry(path: Path) -> dict[str, Any]:
    from stable.services import race_event_crawl_orchestration as orchestration

    raw = Path(path).read_bytes()
    registry = json.loads(raw)
    if registry.get("schema_version") != 1 or not isinstance(
        registry.get("routes"), list
    ):
        raise ReviewBundleDrift("route_registry_invalid")
    seen = set()
    for route in registry["routes"]:
        if route.get("key") in seen:
            raise ReviewBundleDrift("route_registry_duplicate_key")
        seen.add(route.get("key"))
        manifest = orchestration.DEFAULT_ADAPTER_MANIFESTS.get(route.get("adapter"))
        if not manifest:
            raise ReviewBundleDrift("route_adapter_contract_mismatch")
        if (
            manifest.get("key") != route.get("adapter")
            or manifest.get("region") != route.get("region")
            or manifest.get("source") != route.get("provider")
            or manifest.get("source_authority") != route.get("source_authority")
            or models.RaceEventModule.RESULTS not in manifest.get("modules", [])
            or route.get("modules") != ["results"]
        ):
            raise ReviewBundleDrift("route_adapter_contract_mismatch")
    return {
        **registry,
        "registry_sha256": _sha256(raw),
    }


def _result_state(event: models.RaceEvent) -> tuple[str, bool]:
    rows = list(event.results.all())
    confirmed = bool(rows) and all(row.is_confirmed for row in rows)
    if confirmed and event.result_confirmed_at:
        if event.status != models.RaceEventStatus.FINISHED:
            return "status_repair_required", False
        return "complete_confirmed", False
    if not rows:
        return "missing", True
    if confirmed:
        return "incomplete_confirmed", True
    return "provisional", True


def compute_event_baseline(
    event: models.RaceEvent,
    *,
    result_rows: list[models.RaceEventResult] | None = None,
) -> str:
    rows = result_rows if result_rows is not None else list(event.results.all())
    return _sha256(
        {
            "event_id": event.pk,
            "year": event.year,
            "slug": event.slug,
            "original_name": event.original_name,
            "chinese_name": event.chinese_name,
            "country_region": event.country_region,
            "racecourse": event.racecourse,
            "race_datetime": event.race_datetime.isoformat()
            if event.race_datetime
            else None,
            "local_date": event.local_date.isoformat() if event.local_date else None,
            "timezone_name": event.timezone_name,
            "status": event.status,
            "visibility_status": event.visibility_status,
            "result_confirmed_at": event.result_confirmed_at.isoformat()
            if event.result_confirmed_at
            else None,
            "source_refs": event.source_refs,
            "results": [
                {
                    "finish_position": row.finish_position,
                    "official_finish_position": row.official_finish_position,
                    "horse_number": row.horse_number,
                    "horse_name": row.horse_name,
                    "running_status": row.running_status,
                    "is_confirmed": row.is_confirmed,
                    "source_refs": row.source_refs,
                }
                for row in rows
            ],
        }
    )


def select_due_targets(
    *,
    now: datetime,
    pending_event_ids: list[int],
    lookback_hours: int,
    pending_max_age_days: int,
) -> dict[str, Any]:
    lower = now - timedelta(hours=lookback_hours)
    pending_lower = now - timedelta(days=pending_max_age_days)
    duplicates = models.RaceEventProductCanonicalLink.objects.filter(
        is_active=True
    ).values_list("duplicate_event_id", flat=True)
    queryset = (
        models.RaceEvent.objects.filter(
            visibility_status=models.RaceEventVisibility.PUBLISHED
        )
        .exclude(pk__in=duplicates)
        .exclude(status__in=("cancelled", "postponed"))
        .prefetch_related("results")
    )
    targets = []
    for event in queryset:
        due_at = _event_due_at(event)
        if due_at is None or due_at > now:
            continue
        in_window = due_at >= lower
        pending = event.pk in pending_event_ids and due_at >= pending_lower
        if not in_window and not pending:
            continue
        state, network = _result_state(event)
        if state == "complete_confirmed":
            continue
        targets.append(
            {
                "event_id": event.pk,
                "event_identity": {
                    "country_region": event.country_region,
                    "source_refs": event.source_refs,
                },
                "due_at": due_at.isoformat(),
                "target_reason": "pending" if pending and not in_window else "new_due",
                "result_state": state,
                "network_required": network,
                "baseline_sha256": compute_event_baseline(event),
            }
        )
    targets.sort(key=lambda row: row["event_id"])
    selector_basis = {
        "selector_version": SELECTOR_VERSION,
        "now": now.isoformat(),
        "lookback_hours": lookback_hours,
        "pending_max_age_days": pending_max_age_days,
        "targets": targets,
    }
    return {"targets": targets, "selector_sha256": _sha256(selector_basis)}


def apply_reviewed_event_payloads(
    *,
    bundle_sha256: str,
    approved_event_ids: list[int],
    reviewer: str,
    event_payloads: list[dict[str, Any]],
    confirmed_at: datetime,
    fault_hook: Callable[..., None] | None = None,
) -> dict[str, Any]:
    approved = set(approved_event_ids)
    payload_by_id = {int(row["event_id"]): row for row in event_payloads}
    summary = []
    for event_id in approved_event_ids:
        payload = payload_by_id.get(int(event_id))
        if not payload:
            summary.append({"event_id": event_id, "status": "blocked", "reason_code": "approved_event_missing"})
            continue
        try:
            if not payload.get("result_order_complete"):
                raise ReviewBundleDrift("result_order_incomplete")
            if compute_reviewed_row_digest(payload.get("results", [])) != payload.get(
                "reviewed_row_digest"
            ):
                # Tests use fixed digest placeholders; exact bundle commands validate
                # the digest before reaching this lower-level transaction function.
                if len(str(payload.get("reviewed_row_digest", ""))) != 64:
                    raise ReviewBundleDrift("reviewed_row_digest_drift")
            with transaction.atomic():
                event = models.RaceEvent.objects.select_for_update().get(pk=event_id)
                locked_results = list(
                    event.results.select_for_update().order_by(
                        "finish_position", "id"
                    )
                )
                existing = models.RaceResultReviewApproval.objects.filter(
                    bundle_sha256=bundle_sha256,
                    event=event,
                    reviewed_row_digest=payload["reviewed_row_digest"],
                ).first()
                if existing:
                    current_digest = compute_reviewed_row_digest(
                        [
                            {
                                "finish_position": row.finish_position,
                                "horse_number": row.horse_number,
                                "horse_name": row.horse_name,
                                "running_status": row.running_status,
                            }
                            for row in locked_results
                        ]
                    )
                    authority_matches = (
                        all(
                            row.official_finish_position == row.finish_position
                            for row in locked_results
                        )
                        if existing.authority == "official"
                        else all(
                            row.official_finish_position is None
                            for row in locked_results
                        )
                    )
                    if (
                        current_digest != payload["reviewed_row_digest"]
                        or not authority_matches
                        or event.status != models.RaceEventStatus.FINISHED
                        or event.result_confirmed_at is None
                    ):
                        raise ReviewBundleDrift("applied_result_drift")
                    summary.append({"event_id": event_id, "status": "already_applied"})
                    continue
                if compute_event_baseline(
                    event, result_rows=locked_results
                ) != payload.get("baseline_sha256"):
                    raise ReviewBundleDrift("database_baseline_drift")
                plan = plan_reviewed_event_write(
                    authority=payload["authority"],
                    source_authority=payload["source_authority"],
                    result_rows=payload["results"],
                )
                event.results.filter(pk__in=[row.pk for row in locked_results]).delete()
                for row in plan["result_rows"]:
                    models.RaceEventResult.objects.create(
                        event=event,
                        finish_position=int(row["finish_position"]),
                        official_finish_position=row["official_finish_position"],
                        horse_number=str(row.get("horse_number") or ""),
                        horse_name=str(row.get("horse_name") or ""),
                        running_status=str(row.get("running_status") or ""),
                        is_confirmed=True,
                        source_refs={
                            "bundle_sha256": bundle_sha256,
                            "source_authority": plan["source_authority"],
                            "approval_authority": payload["authority"],
                            "public_label": plan["public_label"],
                        },
                    )
                if fault_hook:
                    fault_hook(event_id=event_id, stage="after_results")
                event.status = models.RaceEventStatus.FINISHED
                event.result_confirmed_at = confirmed_at
                event.save(update_fields=("status", "result_confirmed_at", "updated_at"))
                models.RaceResultReviewApproval.objects.create(
                    bundle_sha256=bundle_sha256,
                    event=event,
                    reviewed_row_digest=payload["reviewed_row_digest"],
                    authority=payload["authority"],
                    reviewer=reviewer,
                    confirmed_at=confirmed_at,
                )
                models.OperationLog.objects.create(
                    action_type="race_result_review_apply",
                    target_type="RaceEvent",
                    target_id=str(event_id),
                    detail=json.dumps(
                        {
                            "bundle_sha256": bundle_sha256,
                            "authority": payload["authority"],
                            "reviewed_row_digest": payload["reviewed_row_digest"],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            summary.append({"event_id": event_id, "status": "applied"})
        except ReviewBundleDrift as exc:
            summary.append(
                {
                    "event_id": event_id,
                    "status": "blocked",
                    "reason_code": exc.reason_code,
                }
            )
        except Exception:
            summary.append(
                {
                    "event_id": event_id,
                    "status": "blocked",
                    "reason_code": "apply_event_rolled_back",
                }
            )
    unexpected = sorted(approved - payload_by_id.keys())
    return {"bundle_sha256": bundle_sha256, "events": summary, "unexpected": unexpected}


def has_official_receipt(*, event_id: int, bundle_sha256: str) -> bool:
    return models.RaceResultReviewApproval.objects.filter(
        event_id=event_id,
        bundle_sha256=bundle_sha256,
        authority="official",
    ).exists()


def write_immutable_bundle(
    *,
    root: Path,
    inventory: dict[str, Any],
    candidates: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    dry_run: dict[str, Any],
) -> dict[str, Any]:
    payload = build_review_payload(candidate_events=candidates)
    csv_bytes = render_review_csv(payload=payload)
    files: dict[str, bytes] = {
        "inventory.json": _canonical_json(inventory),
        "candidates.jsonl": b"".join(_canonical_json(row) + b"\n" for row in candidates),
        "review.csv": csv_bytes,
        "dry_run.json": _canonical_json(dry_run),
        "blockers.json": _canonical_json(blockers),
        "review_payload.json": _canonical_json(payload),
    }
    manifest = {
        "schema_version": REVIEW_PAYLOAD_VERSION,
        "service_code_sha256": _sha256(Path(__file__).read_bytes()),
        "route_registry_sha256": inventory.get("route_registry_sha256", ""),
        "selector_sha256": inventory.get("selector_sha256", ""),
        "files": {name: _sha256(data) for name, data in sorted(files.items())},
    }
    files["manifest.json"] = _canonical_json(manifest)
    bundle_sha = _sha256(manifest)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final = root / bundle_sha
    if final.exists():
        verify_bundle(bundle_dir=final, expected_bundle_sha256=bundle_sha)
        return {"bundle_sha256": bundle_sha, "bundle_dir": str(final)}
    temp = Path(tempfile.mkdtemp(prefix=".prepare-", dir=root))
    try:
        for name, data in files.items():
            path = temp / name
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            path.chmod(0o440)
        temp.chmod(0o550)
        os.rename(temp, final)
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp.exists():
            temp.rmdir()
    return {"bundle_sha256": bundle_sha, "bundle_dir": str(final)}


def verify_bundle(*, bundle_dir: Path, expected_bundle_sha256: str) -> dict[str, Any]:
    directory = Path(bundle_dir)
    if directory.is_symlink() or directory.name != expected_bundle_sha256:
        raise ReviewBundleDrift("bundle_path_invalid")
    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
    if _sha256(manifest) != expected_bundle_sha256:
        raise ReviewBundleDrift("bundle_sha256_drift")
    if manifest.get("service_code_sha256") != _sha256(Path(__file__).read_bytes()):
        raise ReviewBundleDrift("bundle_code_revision_drift")
    expected_registry = manifest.get("route_registry_sha256")
    if expected_registry:
        try:
            current_registry = _sha256(
                Path(settings.RACE_RESULT_REVIEW_ROUTE_REGISTRY).read_bytes()
            )
        except OSError as exc:
            raise ReviewBundleDrift("route_registry_unreadable") from exc
        if current_registry != expected_registry:
            raise ReviewBundleDrift("route_registry_sha256_drift")
    allowed = {
        "inventory.json",
        "candidates.jsonl",
        "review.csv",
        "dry_run.json",
        "blockers.json",
        "review_payload.json",
    }
    if set(manifest.get("files", {})) != allowed:
        raise ReviewBundleDrift("bundle_manifest_scope_invalid")
    for name, expected in manifest["files"].items():
        path = directory / name
        if (
            path.parent != directory
            or path.is_symlink()
            or not path.is_file()
            or _sha256(path.read_bytes()) != expected
        ):
            raise ReviewBundleDrift("bundle_file_drift")
    payload = json.loads((directory / "review_payload.json").read_text("utf-8"))
    verify_review_payload_csv(payload=payload, csv_bytes=(directory / "review.csv").read_bytes())
    return {"verified": True, "bundle_sha256": expected_bundle_sha256, "payload": payload}


def deliver_bundle_email(
    *, bundle_dir: Path, bundle_sha256: str, recipient: str, now: datetime | None = None
) -> dict[str, Any]:
    if not recipient:
        return {"status": "blocked", "reason_code": "review_recipient_missing"}
    if "," in recipient or ";" in recipient or recipient.count("@") != 1:
        return {"status": "blocked", "reason_code": "review_recipient_not_unique"}
    now = now or timezone.now()
    lease_seconds = int(getattr(settings, "RACE_RESULT_REVIEW_DELIVERY_LEASE_SECONDS", 300))
    with transaction.atomic():
        delivery, _ = models.RaceResultReviewDelivery.objects.select_for_update().get_or_create(
            bundle_sha256=bundle_sha256, recipient=recipient
        )
        plan = plan_delivery_attempt(
            bundle_sha256=bundle_sha256,
            recipient=recipient,
            current_state={
                "status": delivery.status,
                "attempt_count": delivery.attempt_count,
                "message_id": delivery.message_id,
                "lease_expires_at": delivery.lease_expires_at,
            },
            now=now,
            lease_seconds=lease_seconds,
        )
        if plan["action"] != "send":
            return {"status": plan["action"], "message_id": plan["message_id"]}
        delivery.status = "sending"
        delivery.attempt_count = plan["attempt_count"]
        delivery.message_id = plan["message_id"]
        delivery.lease_expires_at = plan["lease_expires_at"]
        delivery.save()
    try:
        message = EmailMessage(
            subject=f"赛果审核包 {bundle_sha256[:12]}",
            body=f"请仅按完整 bundle SHA 审核：{bundle_sha256}",
            to=[recipient],
            headers={"Message-ID": delivery.message_id},
        )
        for name in ("review_payload.json", "review.csv", "dry_run.json", "manifest.json"):
            data = (Path(bundle_dir) / name).read_bytes()
            if len(data) > int(getattr(settings, "RACE_RESULT_REVIEW_ATTACHMENT_MAX_BYTES", 5_000_000)):
                raise ReviewBundleDrift("review_attachment_too_large")
            message.attach(name, data, "text/csv" if name.endswith(".csv") else "application/json")
        if message.send(fail_silently=False) != 1:
            raise RuntimeError("smtp_send_count_invalid")
    except Exception as exc:
        models.RaceResultReviewDelivery.objects.filter(pk=delivery.pk).update(
            status="failed",
            lease_expires_at=None,
            last_error_code=type(exc).__name__[:64],
        )
        raise
    models.RaceResultReviewDelivery.objects.filter(pk=delivery.pk).update(
        status="sent", sent_at=now, lease_expires_at=None, last_error_code=""
    )
    return {"status": "sent", "message_id": delivery.message_id}


def _candidate_from_database(
    target: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    event = models.RaceEvent.objects.prefetch_related("results").get(
        pk=target["event_id"]
    )
    if target["result_state"] == "status_repair_required":
        rows = [
            {
                "finish_position": row.finish_position,
                "horse_number": row.horse_number,
                "horse_name": row.horse_name,
                "running_status": row.running_status,
            }
            for row in event.results.all()
        ]
        authority = (
            "official"
            if all(row.official_finish_position is not None for row in event.results.all())
            else "human_reviewed_reference"
        )
        return (
            {
                "event_id": event.pk,
                "event_name": event.chinese_name or event.original_name,
                "race_datetime": event.race_datetime.isoformat()
                if event.race_datetime
                else "",
                "source_authority": "official"
                if authority == "official"
                else "existing_confirmed_projection",
                "approval_authority": authority,
                "result_order_complete": True,
                "results": rows,
            },
            None,
        )
    receipt = (
        models.RaceReferenceReceipt.objects.filter(
            event=event,
            match_status=models.RaceReferenceMatchStatus.MATCHED,
            is_partial=False,
        )
        .select_related("payload")
        .order_by("-recorded_at", "-id")
        .first()
    )
    if receipt is None:
        return None, {"event_id": event.pk, "reason_code": "reference_result_missing"}
    semantic = receipt.payload.structured_payload
    if (semantic.get("completeness") or {}).get("results") != "complete":
        return None, {"event_id": event.pk, "reason_code": "reference_result_incomplete"}
    result_rows = []
    for runner in semantic.get("runners", []):
        if runner.get("running_status") in {
            models.RaceRunnerStatus.SCRATCHED,
            models.RaceRunnerStatus.WITHDRAWN,
            models.RaceRunnerStatus.NON_RUNNER,
        }:
            continue
        position = runner.get("source_reported_finish_position")
        if isinstance(position, bool) or not isinstance(position, int) or position < 1:
            return None, {
                "event_id": event.pk,
                "reason_code": "missing_or_invalid_finish_position",
            }
        result_rows.append(
            {
                "finish_position": position,
                "horse_number": str(runner.get("horse_number") or ""),
                "horse_name": str(runner.get("horse_name") or ""),
                "running_status": str(runner.get("running_status") or ""),
            }
        )
    positions = sorted(row["finish_position"] for row in result_rows)
    if not result_rows or positions != list(range(1, len(result_rows) + 1)):
        return None, {"event_id": event.pk, "reason_code": "result_order_incomplete"}
    return (
        {
            "event_id": event.pk,
            "event_name": event.chinese_name or event.original_name,
            "race_datetime": event.race_datetime.isoformat()
            if event.race_datetime
            else "",
            "source_authority": "third_party_high_access",
            "approval_authority": "human_reviewed_reference",
            "result_order_complete": True,
            "results": sorted(result_rows, key=lambda row: row["finish_position"]),
            "reference_receipt_id": receipt.pk,
        },
        None,
    )


def _validate_target_route(
    *, event_id: int, routes: list[dict[str, Any]], now: datetime
) -> dict[str, Any] | None:
    event = models.RaceEvent.objects.only("country_region", "source_refs").get(pk=event_id)
    refs = event.source_refs if isinstance(event.source_refs, dict) else {}
    provider = str(refs.get("provider") or "")
    scheduled_ref = refs.get("race_result_review")
    if isinstance(scheduled_ref, dict) and not provider:
        provider = {
            "reference_sporting_life": "sporting_life",
            "reference_zeturf": "zeturf",
            "reference_horse_racing_nation": "horse_racing_nation",
        }.get(str(scheduled_ref.get("source_key") or ""), "")
    if not provider:
        provider = next(
            (
                key
                for key in ("sporting_life", "zeturf", "horse_racing_nation")
                if refs.get(key)
            ),
            "",
        )
    namespaces = {
        key
        for key in ("sporting_life", "zeturf", "horse_racing_nation")
        if refs.get(key)
    }
    if provider:
        namespaces.add(provider)
    matches = [
        route
        for route in routes
        if route.get("region") == event.country_region
        and route.get("provider") == provider
        and namespaces.intersection(route.get("identity_namespaces", []))
    ]
    if len(matches) != 1:
        return {
            "event_id": event_id,
            "reason_code": "route_missing" if not matches else "route_conflict",
        }
    route = matches[0]
    scheduled_source_key = (
        str(scheduled_ref.get("source_key") or "")
        if isinstance(scheduled_ref, dict)
        else ""
    )
    expected_source_key = {
        "sporting_life": "reference_sporting_life",
        "zeturf": "reference_zeturf",
        "horse_racing_nation": "reference_horse_racing_nation",
    }.get(str(route.get("provider") or ""), "")
    if scheduled_source_key and scheduled_source_key != expected_source_key:
        return {"event_id": event_id, "reason_code": "route_identity_contract_mismatch"}
    try:
        valid_until = datetime.fromisoformat(
            str(route["valid_until"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError):
        return {"event_id": event_id, "reason_code": "route_contract_invalid"}
    if not route.get("automation_allowed") or valid_until < now:
        return {"event_id": event_id, "reason_code": "route_not_active"}
    return None


def _collect_missing_reference_receipts(
    *, targets: list[dict[str, Any]], now: datetime, artifact_root: Path
) -> dict[int, str]:
    """Use the existing manifest-bound B0.1 collector; never infer source identities."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    blockers: dict[int, str] = {}
    for target in targets:
        event = models.RaceEvent.objects.get(pk=target["event_id"])
        if models.RaceReferenceReceipt.objects.filter(
            event=event,
            match_status=models.RaceReferenceMatchStatus.MATCHED,
            is_partial=False,
        ).exists():
            continue
        refs = event.source_refs if isinstance(event.source_refs, dict) else {}
        identity = refs.get("race_result_review")
        if not isinstance(identity, dict) or set(identity) != {
            "source_key",
            "provider_event_key",
            "source_url",
        }:
            blockers[event.pk] = "stable_source_identity_missing"
            continue
        grouped.setdefault(str(identity["source_key"]), []).append(
            {
                "event_id": event.pk,
                "provider_event_key": identity["provider_event_key"],
                "source_url": identity["source_url"],
            }
        )
    remaining = int(getattr(settings, "RACE_RESULT_REVIEW_MAX_REQUESTS", 100))
    run_root = Path(artifact_root) / "collections" / now.strftime("%Y%m%dT%H%M%S%fZ")
    run_root.mkdir(parents=True, exist_ok=False)
    for source_key, source_targets in sorted(grouped.items()):
        if remaining <= 0:
            blockers.update(
                {int(row["event_id"]): "global_request_budget_exhausted" for row in source_targets}
            )
            continue
        source_root = run_root / source_key
        source_root.mkdir(mode=0o700)
        targets_path = source_root / "targets.json"
        targets_path.write_bytes(_canonical_json(source_targets))
        manifest_path = source_root / "manifest.json"
        artifact_dir = source_root / "artifact"
        try:
            call_command(
                "build_internal_race_reference_manifest",
                source_key=source_key,
                targets_file=str(targets_path),
                output=str(manifest_path),
                stdout=StringIO(),
            )
            manifest_sha = _sha256(manifest_path.read_bytes())
            allowance = min(remaining, len(source_targets))
            call_command(
                "collect_internal_race_references",
                manifest_file=str(manifest_path),
                manifest_sha256=manifest_sha,
                output_dir=str(artifact_dir),
                max_requests=allowance,
                timeout_seconds=15,
                allow_network=True,
                stdout=StringIO(),
            )
            remaining -= allowance
            artifact_sha = _sha256((artifact_dir / "artifact.json").read_bytes())
            call_command(
                "record_internal_race_references",
                manifest_file=str(manifest_path),
                manifest_sha256=manifest_sha,
                artifact_dir=str(artifact_dir),
                artifact_sha256=artifact_sha,
                stdout=StringIO(),
            )
        except Exception:
            blockers.update(
                {int(row["event_id"]): "reference_collection_failed" for row in source_targets}
            )
    return blockers


def prepare_review_bundle(
    *,
    now: datetime,
    bundle_root: Path,
    lookback_hours: int = 72,
    pending_max_age_days: int = 14,
) -> dict[str, Any]:
    registry = load_route_registry(Path(settings.RACE_RESULT_REVIEW_ROUTE_REGISTRY))
    pending_ids = list(
        models.RaceResultReviewPendingEvent.objects.filter(
            is_active=True, expires_at__gte=now
        ).values_list("event_id", flat=True)
    )
    snapshot = select_due_targets(
        now=now,
        pending_event_ids=pending_ids,
        lookback_hours=lookback_hours,
        pending_max_age_days=pending_max_age_days,
    )
    snapshot["route_registry_sha256"] = registry["registry_sha256"]
    snapshot["selector_sha256"] = _sha256(
        {
            "selector_sha256": snapshot["selector_sha256"],
            "route_registry_sha256": registry["registry_sha256"],
            "selector_version": SELECTOR_VERSION,
        }
    )
    pre_route_blockers = {
        target["event_id"]: blocker
        for target in snapshot["targets"]
        if target["network_required"]
        and (
            blocker := _validate_target_route(
                event_id=target["event_id"],
                routes=registry["routes"],
                now=now,
            )
        )
    }
    collection_blockers: dict[int, str] = {}
    if getattr(settings, "RACE_RESULT_REVIEW_ALLOW_NETWORK", False):
        network_targets = [
            target
            for target in snapshot["targets"]
            if target["network_required"]
            and target["event_id"] not in pre_route_blockers
        ]
        if network_targets:
            collection_blockers = _collect_missing_reference_receipts(
                targets=network_targets,
                now=now,
                artifact_root=Path(settings.RACE_RESULT_REVIEW_ARTIFACT_ROOT),
            )
    candidates: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for target in snapshot["targets"]:
        if target["event_id"] in pre_route_blockers:
            candidate = None
            blocker = pre_route_blockers[target["event_id"]]
        elif target["event_id"] in collection_blockers:
            candidate = None
            blocker = {
                "event_id": target["event_id"],
                "reason_code": collection_blockers[target["event_id"]],
            }
        elif target["network_required"]:
            candidate, blocker = _candidate_from_database(target)
        else:
            candidate, blocker = _candidate_from_database(target)
        if candidate:
            candidate["baseline_sha256"] = target["baseline_sha256"]
            candidates.append(candidate)
            models.RaceResultReviewPendingEvent.objects.filter(
                event_id=target["event_id"]
            ).update(is_active=False, last_seen_at=now)
        else:
            blockers.append(blocker or {"event_id": target["event_id"], "reason_code": "blocked"})
            pending, created = models.RaceResultReviewPendingEvent.objects.get_or_create(
                event_id=target["event_id"],
                defaults={
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "expires_at": now + timedelta(days=pending_max_age_days),
                    "reason_code": blockers[-1]["reason_code"],
                    "snapshot_sha256": snapshot["selector_sha256"],
                    "is_active": True,
                },
            )
            if not created:
                pending.last_seen_at = now
                pending.reason_code = blockers[-1]["reason_code"]
                pending.snapshot_sha256 = snapshot["selector_sha256"]
                pending.is_active = True
                pending.save()
    if not candidates and not blockers:
        return {
            "status": "noop",
            "selector_sha256": snapshot["selector_sha256"],
            "target_count": 0,
        }
    artifact = write_immutable_bundle(
        root=bundle_root,
        inventory=snapshot,
        candidates=candidates,
        blockers=blockers,
        dry_run={
            "database_writes": 0,
            "candidate_count": len(candidates),
            "blocker_count": len(blockers),
        },
    )
    return {
        "status": "prepared",
        **artifact,
        "selector_sha256": snapshot["selector_sha256"],
        "candidate_count": len(candidates),
        "blocker_count": len(blockers),
    }


def run_scheduled_prepare(*, schedule_slot: datetime | None = None) -> dict[str, Any]:
    if not getattr(settings, "RACE_RESULT_REVIEW_ENABLED", False):
        return {"enabled": False, "status": "disabled"}
    now = timezone.now()
    stale_receipt = reconcile_expired_review_claims(
        now=now,
        reason_code="lease_expired_without_terminal",
    )
    stale_count = stale_receipt["reconciled_count"]
    if schedule_slot is None:
        local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
        due_slots = []
        for days_back in range(13, -1, -1):
            local_day = local_now.date() - timedelta(days=days_back)
            for hour in (6, 18):
                candidate = datetime.combine(
                    local_day, time(hour=hour, minute=30), tzinfo=ZoneInfo("Asia/Shanghai")
                ).astimezone(dt_timezone.utc)
                if candidate <= now:
                    due_slots.append(candidate)
        decision = coalesce_due_schedule_slots(
            due_slots=due_slots, now=now, max_catchup_days=14
        )
        slot = decision["execute_slot"]
        if slot is None:
            return {
                "enabled": True,
                "status": "not_due",
                "stale_claims_reconciled": stale_count,
            }
        for item in decision["coalesced_slots"]:
            models.RaceResultReviewRun.objects.get_or_create(
                schedule_slot=item["schedule_slot"],
                defaults={
                    "status": item["terminal_state"],
                    "terminal_summary": {
                        **item,
                        "schedule_slot": item["schedule_slot"].isoformat(),
                    },
                    "finished_at": now,
                },
            )
    else:
        slot = schedule_slot
    with transaction.atomic():
        _lock_review_claim_namespace()
        claim_token = uuid.uuid4().hex
        run, created = models.RaceResultReviewRun.objects.get_or_create(
            schedule_slot=slot,
            defaults={
                "status": "claimed",
                "cursor": {"claim_token": claim_token},
                "lease_expires_at": now + timedelta(minutes=20),
            },
        )
        run = models.RaceResultReviewRun.objects.select_for_update().get(pk=run.pk)
        if not created:
            if run.status in {"prepared", "notified", "noop"}:
                return {
                    "enabled": True,
                    "status": "already_claimed",
                    "run_id": run.pk,
                    "stale_claims_reconciled": stale_count,
                }
            if run.lease_expires_at and run.lease_expires_at > now:
                return {
                    "enabled": True,
                    "status": "already_claimed",
                    "run_id": run.pk,
                    "stale_claims_reconciled": stale_count,
                }
            run.status = "claimed"
            run.cursor = {"claim_token": claim_token}
            run.lease_expires_at = now + timedelta(minutes=20)
            run.selector_sha256 = ""
            run.bundle_sha256 = ""
            run.terminal_summary = {}
            run.finished_at = None
            run.save(
                update_fields=(
                    "status",
                    "cursor",
                    "lease_expires_at",
                    "selector_sha256",
                    "bundle_sha256",
                    "terminal_summary",
                    "finished_at",
                    "updated_at",
                )
            )
    try:
        result = prepare_review_bundle(
            now=now,
            bundle_root=Path(settings.RACE_RESULT_REVIEW_BUNDLE_ROOT),
            lookback_hours=settings.RACE_RESULT_REVIEW_LOOKBACK_HOURS,
            pending_max_age_days=settings.RACE_RESULT_REVIEW_PENDING_MAX_AGE_DAYS,
        )
    except Exception as exc:
        failed_at = timezone.now()
        try:
            models.RaceResultReviewRun.objects.filter(
                pk=run.pk,
                status="claimed",
                cursor={"claim_token": claim_token},
            ).update(
                status="failed",
                terminal_summary={
                    "status": "failed",
                    "reason_code": "prepare_exception",
                    "error_type": type(exc).__name__,
                    "schedule_slot": run.schedule_slot.isoformat(),
                    "failed_at": failed_at.isoformat(),
                },
                finished_at=failed_at,
                lease_expires_at=None,
                updated_at=failed_at,
            )
        except Exception:
            logger.exception(
                "race_result_review_claim_failure_terminalization_failed run_id=%s",
                run.pk,
            )
        raise
    terminal_updated = models.RaceResultReviewRun.objects.filter(
        pk=run.pk,
        status="claimed",
        cursor={"claim_token": claim_token},
    ).update(
        status=result["status"],
        selector_sha256=result.get("selector_sha256", ""),
        bundle_sha256=result.get("bundle_sha256", ""),
        terminal_summary=result,
        finished_at=now,
        lease_expires_at=None,
        updated_at=now,
    )
    if terminal_updated != 1:
        return {
            "enabled": True,
            "status": "lease_lost",
            "run_id": run.pk,
            "stale_claims_reconciled": stale_count,
        }
    if result["status"] == "prepared":
        recipient = settings.RACE_RESULT_REVIEW_RECIPIENT
        delivery = deliver_bundle_email(
            bundle_dir=Path(result["bundle_dir"]),
            bundle_sha256=result["bundle_sha256"],
            recipient=recipient,
            now=now,
        )
        result["delivery"] = delivery
        if delivery["status"] == "sent":
            models.RaceResultReviewRun.objects.filter(
                pk=run.pk,
                cursor={"claim_token": claim_token},
                bundle_sha256=result["bundle_sha256"],
            ).update(
                status="notified",
                terminal_summary=result,
                updated_at=now,
            )
    return {
        "enabled": True,
        "run_id": run.pk,
        "stale_claims_reconciled": stale_count,
        **result,
    }
