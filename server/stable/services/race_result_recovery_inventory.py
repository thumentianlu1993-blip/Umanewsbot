from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from django.db.models import Prefetch
from django.utils import timezone

from stable import models
from stable.services.race_event_lifecycle import decide_race_lifecycle


_TERMINAL_STATES = {
    "confirmed_result",
    "cancelled",
    "postponed",
    "blocked_with_evidence",
}
RECOVERY_FROZEN_DUPLICATE_PAIRS = (
    (79, 15441),
    (405, 15640),
    (408, 15587),
    (409, 15487),
    (410, 15484),
    (729, 16193),
    (730, 16176),
    (731, 16199),
    (732, 16198),
)


class RecoveryInventoryError(ValueError):
    pass


class RecoveryInventoryDrift(RecoveryInventoryError):
    def __init__(self, reason_codes: list[str]):
        self.reason_codes = sorted(set(reason_codes))
        super().__init__(", ".join(self.reason_codes))


class RecoveryAccountingError(RecoveryInventoryError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _event_identity(event: models.RaceEvent) -> dict[str, Any]:
    return {
        "event_id": event.pk,
        "year": event.year,
        "slug": event.slug,
        "series_id": event.race_series_id,
        "series_key": event.series_key,
        "original_name": event.original_name,
        "chinese_name": event.chinese_name,
        "region": event.country_region,
        "racecourse": event.racecourse,
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "race_datetime": (
            event.race_datetime.isoformat() if event.race_datetime else None
        ),
        "timezone_name": event.timezone_name,
        "status": event.status,
        "visibility_status": event.visibility_status,
        "data_quality_status": event.data_quality_status,
        "priority": event.priority,
        "is_featured": event.is_featured,
        "source_refs": event.source_refs or {},
        "manual_lock_flags": event.manual_lock_flags or {},
        "result_confirmed_at": (
            event.result_confirmed_at.isoformat()
            if event.result_confirmed_at
            else None
        ),
    }


def _result_identity(results: list[models.RaceEventResult]) -> list[dict[str, Any]]:
    return [
        {
            "id": result.pk,
            "finish_position": result.finish_position,
            "official_finish_position": result.official_finish_position,
            "horse_number": result.horse_number,
            "horse_name": result.horse_name,
            "jockey_name": result.jockey_name,
            "running_status": result.running_status,
            "is_confirmed": result.is_confirmed,
        }
        for result in sorted(results, key=lambda item: (item.finish_position, item.pk))
    ]


def _group_key(event: models.RaceEvent) -> tuple[str, str, str]:
    return (
        event.country_region,
        event.local_date.isoformat() if event.local_date else "",
        " ".join((event.original_name or "").casefold().split()),
    )


def _inventory_group_key(
    event: models.RaceEvent,
    *,
    frozen_pair_by_event: Mapping[int, tuple[int, int]],
) -> tuple[str, str, str]:
    pair = frozen_pair_by_event.get(event.pk)
    if pair is None:
        return _group_key(event)
    return (
        event.country_region,
        event.local_date.isoformat() if event.local_date else "",
        f"frozen-pair:{pair[0]}:{pair[1]}",
    )


def _lifecycle(event: models.RaceEvent, *, as_of: datetime) -> tuple[Any, bool]:
    decision = decide_race_lifecycle(
        race_datetime=event.race_datetime,
        timezone_name=event.timezone_name,
        status=event.status,
        now=as_of,
        local_date=event.local_date,
        region=event.country_region,
    )
    due = (
        event.status == models.RaceEventStatus.FINISHED
        or (
            decision.action == "transition"
            and decision.to_status == models.RaceEventStatus.FINISHED
        )
    )
    if event.status in {
        models.RaceEventStatus.CANCELLED,
        models.RaceEventStatus.POSTPONED,
    }:
        due = False
    return decision, due


def build_recovery_inventory(
    *,
    start_date: date,
    end_date: date,
    as_of: datetime,
    expected_event_ids: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise RecoveryInventoryError("start_date and end_date must be dates")
    if start_date > end_date:
        raise RecoveryInventoryError("start_date must not be after end_date")
    if not isinstance(as_of, datetime) or timezone.is_naive(as_of):
        raise RecoveryInventoryError("as_of must be an aware datetime")

    expected_ids = [int(value) for value in (expected_event_ids or [])]
    if len(expected_ids) != len(set(expected_ids)):
        raise RecoveryInventoryError("expected_event_ids contains duplicates")

    queryset = (
        models.RaceEvent.objects.filter(
            local_date__gte=start_date,
            local_date__lte=end_date,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )
        .select_related("race_series")
        .prefetch_related(
            Prefetch(
                "results",
                queryset=models.RaceEventResult.objects.only(
                    "id",
                    "event_id",
                    "finish_position",
                    "official_finish_position",
                    "horse_number",
                    "horse_name",
                    "jockey_name",
                    "running_status",
                    "is_confirmed",
                ),
                to_attr="_recovery_results",
            )
        )
        .order_by("id")
    )
    if expected_ids:
        queryset = queryset.filter(pk__in=expected_ids)
    events = list(queryset)
    observed_ids = [event.pk for event in events]
    if expected_ids and set(observed_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(observed_ids))
        unexpected = sorted(set(observed_ids) - set(expected_ids))
        raise RecoveryInventoryError(
            f"frozen event scope drift: missing={missing} unexpected={unexpected}"
        )

    observed_set = set(observed_ids)
    frozen_pair_by_event = {
        event_id: pair
        for pair in RECOVERY_FROZEN_DUPLICATE_PAIRS
        if set(pair) <= observed_set
        for event_id in pair
    }
    grouped: dict[tuple[str, str, str], list[models.RaceEvent]] = {}
    for event in events:
        grouped.setdefault(
            _inventory_group_key(
                event, frozen_pair_by_event=frozen_pair_by_event
            ),
            [],
        ).append(event)

    duplicate_event_ids: set[int] = set()
    identity_reviews: list[dict[str, Any]] = []
    for group_events in grouped.values():
        zero = [
            event for event in group_events if not event._recovery_results
        ]
        confirmed = [
            event
            for event in group_events
            if event._recovery_results
            and all(result.is_confirmed for result in event._recovery_results)
        ]
        if len(group_events) == 2 and len(zero) == 1 and len(confirmed) == 1:
            duplicate_event_ids.update(event.pk for event in group_events)
            identity_reviews.append(
                {
                    "event_ids": sorted(event.pk for event in group_events),
                    "status": "pending",
                    "canonical_event_id": None,
                    "cross_series": (
                        group_events[0].race_series_id
                        != group_events[1].race_series_id
                    ),
                    "identity_sha256": _sha256(
                        {
                            "event_ids": sorted(
                                event.pk for event in group_events
                            ),
                            "group_key": _inventory_group_key(
                                group_events[0],
                                frozen_pair_by_event=frozen_pair_by_event,
                            ),
                        }
                    ),
                }
            )

    event_rows: list[dict[str, Any]] = []
    classifications: Counter[str] = Counter()
    provisional_ids: list[int] = []
    for event in events:
        results = list(event._recovery_results)
        event_identity = _event_identity(event)
        result_identity = _result_identity(results)
        if event.pk in duplicate_event_ids:
            classification = (
                "duplicate_zero" if not results else "duplicate_confirmed"
            )
        elif not results:
            classification = "missing_result"
        elif any(not result.is_confirmed for result in results):
            classification = "provisional"
            provisional_ids.append(event.pk)
        else:
            classification = "confirmed_result"
        classifications[classification] += 1
        lifecycle, result_due = _lifecycle(event, as_of=as_of)
        event_rows.append(
            {
                **event_identity,
                "result_count": len(results),
                "confirmed_result_count": sum(
                    1 for result in results if result.is_confirmed
                ),
                "classification": classification,
                "lifecycle_action": lifecycle.action,
                "lifecycle_to_status": lifecycle.to_status,
                "lifecycle_reason_code": lifecycle.reason_code,
                "lifecycle_error": lifecycle.error_message,
                "result_due": result_due,
                "event_identity_sha256": _sha256(event_identity),
                "result_identity_sha256": _sha256(result_identity),
                "result_identity": result_identity,
            }
        )

    race_groups = [
        {
            "group_id": _sha256(
                {
                    "key": key,
                    "event_ids": sorted(event.pk for event in group_events),
                }
            ),
            "region": key[0],
            "local_date": key[1] or None,
            "normalized_original_name": key[2],
            "event_ids": sorted(event.pk for event in group_events),
            "identity_status": (
                "pending"
                if any(event.pk in duplicate_event_ids for event in group_events)
                else "single_event"
            ),
        }
        for key, group_events in sorted(grouped.items())
    ]
    baseline = {
        "event_rows": [
            {
                "event_id": row["event_id"],
                "event_identity_sha256": row["event_identity_sha256"],
                "result_identity_sha256": row["result_identity_sha256"],
            }
            for row in event_rows
        ]
    }
    baseline_sha = _sha256(baseline)
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "race_result_recovery_inventory",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "as_of": as_of.isoformat(),
        "expected_event_ids": sorted(observed_ids),
        "event_rows": event_rows,
        "race_groups": race_groups,
        "identity_reviews": sorted(
            identity_reviews, key=lambda item: item["event_ids"]
        ),
        "provisional_event_ids": sorted(provisional_ids),
        "classification_counts": dict(sorted(classifications.items())),
        "baseline_sha256": baseline_sha,
    }
    artifact["manifest_sha256"] = _sha256(artifact)
    return artifact


def verify_recovery_inventory(artifact: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(artifact, Mapping):
        raise RecoveryInventoryDrift(["manifest_invalid"])
    supplied = dict(artifact)
    manifest_sha = str(supplied.pop("manifest_sha256", ""))
    if manifest_sha != _sha256(supplied):
        raise RecoveryInventoryDrift(["manifest_sha256_mismatch"])
    try:
        rebuilt = build_recovery_inventory(
            start_date=date.fromisoformat(str(artifact["start_date"])),
            end_date=date.fromisoformat(str(artifact["end_date"])),
            as_of=datetime.fromisoformat(str(artifact["as_of"])),
            expected_event_ids=list(artifact["expected_event_ids"]),
        )
    except (KeyError, TypeError, ValueError, RecoveryInventoryError) as exc:
        raise RecoveryInventoryDrift(["manifest_invalid"]) from exc

    before = {
        int(row["event_id"]): row for row in artifact.get("event_rows", [])
    }
    after = {
        int(row["event_id"]): row for row in rebuilt.get("event_rows", [])
    }
    reasons: list[str] = []
    if set(before) != set(after):
        reasons.append("event_scope_drift")
    for event_id in sorted(set(before) & set(after)):
        if (
            before[event_id].get("event_identity_sha256")
            != after[event_id].get("event_identity_sha256")
        ):
            reasons.append("event_identity_drift")
        if (
            before[event_id].get("result_identity_sha256")
            != after[event_id].get("result_identity_sha256")
        ):
            reasons.append("result_identity_drift")
    if reasons:
        raise RecoveryInventoryDrift(reasons)
    return {
        "status": "verified",
        "manifest_sha256": artifact["manifest_sha256"],
        "event_row_count": len(after),
        "race_group_count": len(rebuilt["race_groups"]),
    }


def write_immutable_inventory(
    artifact: Mapping[str, Any], output_path: str | Path
) -> dict[str, Any]:
    verify_manifest = dict(artifact)
    supplied_sha = str(verify_manifest.pop("manifest_sha256", ""))
    if supplied_sha != _sha256(verify_manifest):
        raise RecoveryInventoryError("manifest_sha256 mismatch")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RecoveryInventoryError("inventory artifact already exists")
    body = json.dumps(
        artifact, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o444)
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return {
        "path": str(path.resolve()),
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "manifest_sha256": supplied_sha,
    }


def summarize_recovery_accounting(
    *,
    target_ids: list[int] | tuple[int, ...],
    terminal_states: Mapping[int, str],
) -> dict[str, Any]:
    ids = [int(value) for value in target_ids]
    if len(ids) != len(set(ids)):
        raise RecoveryAccountingError("target_ids contains duplicates")
    normalized_states = {int(key): value for key, value in terminal_states.items()}
    if set(ids) != set(normalized_states):
        raise RecoveryAccountingError("terminal states do not conserve target scope")
    unknown = sorted(set(normalized_states.values()) - _TERMINAL_STATES)
    if unknown:
        raise RecoveryAccountingError(
            f"unknown terminal states: {', '.join(unknown)}"
        )
    counts = Counter(normalized_states.values())
    blocker_count = counts["blocked_with_evidence"]
    is_accounted = len(normalized_states) == len(ids)
    is_completed = is_accounted and blocker_count == 0
    return {
        "target_total": len(ids),
        "accounted_total": len(normalized_states),
        "terminal_counts": {
            state: counts[state] for state in sorted(_TERMINAL_STATES)
        },
        "blocker_count": blocker_count,
        "is_accounted": is_accounted,
        "is_completed": is_completed,
        "run_status": "completed" if is_completed else "partial",
    }
