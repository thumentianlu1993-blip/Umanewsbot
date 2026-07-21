#!/usr/bin/env python3
"""Fail-closed one-shot apply/rollback tool for the reviewed race-name bundle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any


BUNDLE_MEMBERS = (
    "apply_race_name_translation_manifest.py",
    "verify_race_name_translation_manifest.py",
    "input-lock.json",
    "normalized-input.json",
    "manifest.json",
    "production-before.json",
    "dry-run.json",
    "rollback-before.json",
    "execution-metadata.json",
    "execution-plan.json",
    "artifact-index.json",
)
BATCH_SIZE = 500
EXPECTED_PRODUCTION_SERIES_COUNT = 1300
EXPECTED_PRODUCTION_EVENT_COUNT = 8883


class ApplyError(RuntimeError):
    pass


def normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return {"__bytes_base64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(
        normalize_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_model_row(instance: Any) -> dict[str, Any]:
    fields = {
        field.attname: normalize_value(getattr(instance, field.attname))
        for field in sorted(instance._meta.concrete_fields, key=lambda item: item.attname)
    }
    return {"fields": fields, "rowSha256": sha256_json(fields)}


def verify_bundle(bundle_dir: str | Path, expected_index_sha256: str) -> dict[str, Any]:
    directory = Path(bundle_dir).resolve()
    index_path = directory / "bundle-index.json"
    if not index_path.is_file() or index_path.is_symlink():
        raise ApplyError("bundle-index.json must be a regular file")
    actual_index_sha256 = sha256_file(index_path)
    if actual_index_sha256 != expected_index_sha256:
        raise ApplyError(
            f"bundle index sha mismatch: {actual_index_sha256} != {expected_index_sha256}"
        )
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplyError(f"invalid bundle index: {exc}") from exc
    expected_content_sha256 = index.get("contentSha256")
    content = dict(index)
    content.pop("contentSha256", None)
    if expected_content_sha256 != sha256_json(content):
        raise ApplyError("bundle index content sha mismatch")
    if index.get("schemaVersion") != "race-name-translation-bundle-index.v1":
        raise ApplyError("unsupported bundle index schema")
    rows = index.get("files")
    if not isinstance(rows, list):
        raise ApplyError("bundle index files must be a list")
    by_name = {row.get("file"): row for row in rows if isinstance(row, dict)}
    if set(by_name) != set(BUNDLE_MEMBERS) or len(rows) != len(BUNDLE_MEMBERS):
        raise ApplyError("bundle member set mismatch")
    for name in BUNDLE_MEMBERS:
        member = directory / name
        if not member.is_file() or member.is_symlink():
            raise ApplyError(f"bundle member is not a regular file: {name}")
        stat = member.stat()
        row = by_name[name]
        if stat.st_size != row.get("sizeBytes") or sha256_file(member) != row.get("sha256"):
            raise ApplyError(f"bundle member sha/size mismatch: {name}")
    return index


def _configure_transaction_timeouts() -> None:
    from django.db import connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '120s'")


def _expected_ids(rows: list[dict[str, Any]], key: str) -> list[int]:
    values = [int(row[key]) for row in rows]
    if len(values) != len(set(values)):
        raise ApplyError(f"duplicate {key} in rollback plan")
    return sorted(values)


def _lock_exact(model: Any, ids: list[int], label: str) -> list[Any]:
    locked = list(model.objects.select_for_update().filter(id__in=ids).order_by("id"))
    actual = [row.id for row in locked]
    if actual != ids:
        raise ApplyError(f"{label} primary-key set mismatch: expected={ids}, actual={actual}")
    return locked


def _lock_event_scope(
    plan: dict[str, Any],
    *,
    RaceSeries: Any,
    RaceEvent: Any,
    require_before_hashes: bool,
) -> tuple[list[Any], list[Any]]:
    scope = plan.get("eventScope")
    if not isinstance(scope, dict):
        if plan.get("schemaVersion") == "race-name-translation-execution-plan.v1":
            raise ApplyError("execution plan eventScope is required")
        return [], []
    scope_series_plan = scope.get("series") or []
    scope_series_ids = _expected_ids(scope_series_plan, "seriesId")
    scope_event_plan = scope.get("events") or []
    scope_event_ids = _expected_ids(scope_event_plan, "eventId")
    if not scope_series_ids:
        raise ApplyError("eventScope seriesIds must not be empty")
    locked_scope_series = _lock_exact(
        RaceSeries, scope_series_ids, "RaceSeries event scope"
    )
    scope_series_by_id = {
        int(row["seriesId"]): row for row in scope_series_plan
    }
    action_series_ids = {
        int(row["seriesId"]) for row in (plan.get("series") or [])
    }
    if not action_series_ids.issubset(set(scope_series_ids)):
        raise ApplyError("RaceSeries action set is outside event scope")
    for instance in locked_scope_series:
        if (
            require_before_hashes or instance.id not in action_series_ids
        ) and canonical_model_row(instance)["rowSha256"] != scope_series_by_id[
            instance.id
        ].get("beforeRowSha256"):
            raise ApplyError(
                f"RaceSeries event-scope full-row CAS mismatch: id={instance.id}"
            )
    locked_scope_events = list(
        RaceEvent.objects.select_for_update()
        .filter(race_series_id__in=scope_series_ids)
        .order_by("id")
    )
    actual_ids = [row.id for row in locked_scope_events]
    if actual_ids != scope_event_ids:
        raise ApplyError(
            "RaceEvent complete series scope mismatch: "
            f"expected={scope_event_ids}, actual={actual_ids}"
        )
    expected_by_id = {int(row["eventId"]): row for row in scope_event_plan}
    action_ids = {
        int(row["eventId"]) for row in (plan.get("events") or [])
    }
    action_by_id = {
        int(row["eventId"]): row for row in (plan.get("events") or [])
    }
    for instance in locked_scope_events:
        expected = expected_by_id[instance.id]
        expected_series_id = int(expected["raceSeriesId"])
        if not require_before_hashes and instance.id in action_ids:
            expected_series_id = int(
                (action_by_id[instance.id].get("after") or {}).get(
                    "raceSeriesId", expected_series_id
                )
            )
        if instance.race_series_id != expected_series_id:
            raise ApplyError(f"RaceEvent event-scope series mismatch: id={instance.id}")
        if (
            require_before_hashes or instance.id not in action_ids
        ) and canonical_model_row(instance)["rowSha256"] != expected.get(
            "beforeRowSha256"
        ):
            raise ApplyError(f"RaceEvent event-scope full-row CAS mismatch: id={instance.id}")
    return locked_scope_series, locked_scope_events


def _assert_before_cas(
    locked: list[Any], plan_rows: list[dict[str, Any]], id_key: str, label: str
) -> None:
    expected = {
        int(row[id_key]): row.get("beforeRowSha256")
        or (row.get("before") or {}).get("rowSha256")
        for row in plan_rows
    }
    for instance in locked:
        actual = canonical_model_row(instance)
        if actual.get("rowSha256") != expected[instance.id]:
            raise ApplyError(f"{label} full-row CAS mismatch: id={instance.id}")


def _restore_fields(plan_row: dict[str, Any]) -> dict[str, Any]:
    restore = plan_row.get("restore")
    if isinstance(restore, dict):
        return restore
    return (plan_row.get("before") or {}).get("fields") or {}


def _assert_manual_locks(
    series_rows: list[Any],
    event_rows: list[Any],
    event_plan: dict[int, dict[str, Any]],
) -> None:
    for row in series_rows:
        if bool((row.manual_lock_flags or {}).get("chinese_name")):
            raise ApplyError(f"RaceSeries manual lock: id={row.id}")
    for row in event_rows:
        flags = row.manual_lock_flags or {}
        if bool(flags.get("chinese_name")):
            raise ApplyError(f"RaceEvent chinese_name manual lock: id={row.id}")
        if event_plan[row.id].get("actionType") == "reassign_series_and_translate":
            if any(bool(flags.get(key)) for key in ("race_series", "series_key", "identity")):
                raise ApplyError(f"RaceEvent identity manual lock: id={row.id}")


def _aggregate_rows(
    series_rows: list[Any],
    event_rows: list[Any],
    historical_target_rows: list[Any],
) -> dict[str, Any]:
    content = {
        "series": [canonical_model_row(row) for row in series_rows],
        "events": [canonical_model_row(row) for row in event_rows],
        "historicalTargets": [
            canonical_model_row(row) for row in historical_target_rows
        ],
    }
    return {"content": content, "sha256": sha256_json(content)}


def _validate_identity_corrections(
    event_plan: dict[int, dict[str, Any]],
    historical_target_plan: dict[int, dict[str, Any]],
    locked_events: list[Any],
    locked_historical_targets: list[Any],
) -> None:
    corrections = {
        event_id: row
        for event_id, row in event_plan.items()
        if row.get("actionType") == "reassign_series_and_translate"
    }
    target_by_event_id: dict[int, tuple[Any, dict[str, Any]]] = {}
    for target in locked_historical_targets:
        plan_row = historical_target_plan[target.id]
        event_id = int(plan_row.get("eventId") or 0)
        if event_id in target_by_event_id:
            raise ApplyError(f"duplicate historical target for correction event: {event_id}")
        target_by_event_id[event_id] = (target, plan_row)
    if set(target_by_event_id) != set(corrections):
        raise ApplyError(
            "historical target/correction event set mismatch: "
            f"targets={sorted(target_by_event_id)}, corrections={sorted(corrections)}"
        )
    events_by_id = {row.id: row for row in locked_events}
    for event_id, correction in corrections.items():
        event = events_by_id[event_id]
        target, target_plan = target_by_event_id[event_id]
        destination_id = int(correction["after"]["raceSeriesId"])
        if (
            target.event_id != event.id
            or target.year != event.year
            or target.race_series_id != event.race_series_id
            or int(target_plan["after"]["raceSeriesId"]) != destination_id
        ):
            raise ApplyError(
                f"historical target/event identity mismatch: target={target.id}, event={event.id}"
            )
        from stable.models import HistoricalRaceEventTarget

        collision = (
            HistoricalRaceEventTarget.objects.select_for_update()
            .filter(race_series_id=destination_id, year=target.year)
            .exclude(pk=target.pk)
            .exists()
        )
        if collision:
            raise ApplyError(
                "historical target destination series/year conflict: "
                f"target={target.id}, series={destination_id}, year={target.year}"
            )


def execute_plan(
    plan: dict[str, Any],
    *,
    commit: bool,
    audit_context: dict[str, Any],
) -> dict[str, Any]:
    from django.db import transaction
    from django.utils import timezone

    from stable.models import (
        HistoricalRaceEventTarget,
        OperationLog,
        RaceEvent,
        RaceSeries,
    )

    if plan.get("schemaVersion") not in {
        "race-name-translation-rollback-before.v3",
        "race-name-translation-execution-plan.v1",
    }:
        raise ApplyError("unsupported execution plan schema")
    series_plan = plan.get("series") or []
    event_plan_rows = plan.get("events") or []
    historical_target_plan_rows = plan.get("historicalTargets") or []
    series_ids = _expected_ids(series_plan, "seriesId")
    event_ids = _expected_ids(event_plan_rows, "eventId")
    historical_target_ids = _expected_ids(
        historical_target_plan_rows, "historicalTargetId"
    )
    batch_id = str(audit_context.get("batchId") or "")
    if not batch_id or len(batch_id) > 64:
        raise ApplyError("invalid audit batchId")

    with transaction.atomic():
        _configure_transaction_timeouts()
        existing = OperationLog.objects.filter(
            action_type="race_name_translations_applied",
            target_type="race_name_translation_batch",
            target_id=batch_id,
        )
        if existing.exists():
            raise ApplyError(f"batch already applied: {batch_id}")
        locked_scope_series, locked_scope_events = _lock_event_scope(
            plan,
            RaceSeries=RaceSeries,
            RaceEvent=RaceEvent,
            require_before_hashes=True,
        )
        if locked_scope_series:
            locked_series_by_id = {row.id: row for row in locked_scope_series}
            locked_series = [locked_series_by_id[row_id] for row_id in series_ids]
            locked_events_by_id = {row.id: row for row in locked_scope_events}
            locked_events = [locked_events_by_id[row_id] for row_id in event_ids]
        else:
            locked_series = _lock_exact(RaceSeries, series_ids, "RaceSeries")
            locked_events = _lock_exact(RaceEvent, event_ids, "RaceEvent")
        locked_historical_targets = _lock_exact(
            HistoricalRaceEventTarget,
            historical_target_ids,
            "HistoricalRaceEventTarget",
        )
        _assert_before_cas(locked_series, series_plan, "seriesId", "RaceSeries")
        _assert_before_cas(locked_events, event_plan_rows, "eventId", "RaceEvent")
        _assert_before_cas(
            locked_historical_targets,
            historical_target_plan_rows,
            "historicalTargetId",
            "HistoricalRaceEventTarget",
        )
        event_plan = {int(row["eventId"]): row for row in event_plan_rows}
        historical_target_plan = {
            int(row["historicalTargetId"]): row
            for row in historical_target_plan_rows
        }
        series_by_id = {int(row["seriesId"]): row for row in series_plan}
        _assert_manual_locks(locked_series, locked_events, event_plan)
        _validate_identity_corrections(
            event_plan,
            historical_target_plan,
            locked_events,
            locked_historical_targets,
        )

        correction_count = 0
        if commit:
            applied_at = timezone.now()
            for row in locked_series:
                row.chinese_name = series_by_id[row.id]["after"]["chineseName"]
                row.updated_at = applied_at
            for row in locked_events:
                after = event_plan[row.id]["after"]
                row.chinese_name = after["chineseName"]
                if "raceSeriesId" in after:
                    correction_count += 1
                    row.race_series_id = int(after["raceSeriesId"])
                    row.series_key = after["seriesKey"]
                row.updated_at = applied_at
            for row in locked_historical_targets:
                row.race_series_id = int(
                    historical_target_plan[row.id]["after"]["raceSeriesId"]
                )
                row.updated_at = applied_at
            RaceSeries.objects.bulk_update(
                locked_series, ["chinese_name", "updated_at"], batch_size=BATCH_SIZE
            )
            event_fields = ["chinese_name", "race_series_id", "series_key", "updated_at"]
            RaceEvent.objects.bulk_update(
                locked_events, event_fields, batch_size=BATCH_SIZE
            )
            HistoricalRaceEventTarget.objects.bulk_update(
                locked_historical_targets,
                ["race_series_id", "updated_at"],
                batch_size=BATCH_SIZE,
            )
            after_series = list(
                RaceSeries.objects.filter(id__in=series_ids).order_by("id")
            )
            after_events = list(RaceEvent.objects.filter(id__in=event_ids).order_by("id"))
            after_historical_targets = list(
                HistoricalRaceEventTarget.objects.filter(
                    id__in=historical_target_ids
                ).order_by("id")
            )
            after_snapshot = _aggregate_rows(
                after_series, after_events, after_historical_targets
            )
            detail = {
                "schemaVersion": "race-name-translation-operation-log.v1",
                **normalize_value(audit_context),
                "batchId": batch_id,
                "operator": audit_context.get("operator", "mentianlu_via_codex"),
                "seriesCount": len(series_ids),
                "eventCount": len(event_ids),
                "historicalTargetCount": len(historical_target_ids),
                "identityCorrectionCount": correction_count,
                "appliedAt": normalize_value(applied_at),
                "afterSha256": after_snapshot["sha256"],
            }
            OperationLog.objects.create(
                admin=None,
                action_type="race_name_translations_applied",
                target_type="race_name_translation_batch",
                target_id=batch_id,
                detail=canonical_json(detail),
            )
        return {
            "mode": "commit" if commit else "verify-only",
            "batchId": batch_id,
            "seriesCount": len(series_ids),
            "eventCount": len(event_ids),
            "historicalTargetCount": len(historical_target_ids),
            "identityCorrectionCount": (
                correction_count
                if commit
                else sum(
                    row.get("actionType") == "reassign_series_and_translate"
                    for row in event_plan_rows
                )
            ),
        }


def execute_rollback(
    plan: dict[str, Any],
    *,
    audit_context: dict[str, Any],
) -> dict[str, Any]:
    from django.db import transaction
    from django.utils import timezone

    from stable.models import (
        HistoricalRaceEventTarget,
        OperationLog,
        RaceEvent,
        RaceSeries,
    )

    if plan.get("schemaVersion") not in {
        "race-name-translation-rollback-before.v3",
        "race-name-translation-execution-plan.v1",
    }:
        raise ApplyError("unsupported execution plan schema")
    batch_id = str(audit_context.get("batchId") or "")
    series_plan = plan.get("series") or []
    event_plan_rows = plan.get("events") or []
    historical_target_plan_rows = plan.get("historicalTargets") or []
    series_ids = _expected_ids(series_plan, "seriesId")
    event_ids = _expected_ids(event_plan_rows, "eventId")
    historical_target_ids = _expected_ids(
        historical_target_plan_rows, "historicalTargetId"
    )
    with transaction.atomic():
        _configure_transaction_timeouts()
        logs = list(
            OperationLog.objects.select_for_update().filter(
                action_type="race_name_translations_applied",
                target_type="race_name_translation_batch",
                target_id=batch_id,
            )
        )
        if len(logs) != 1:
            raise ApplyError(f"expected exactly one apply log for rollback: {batch_id}")
        if OperationLog.objects.filter(
            action_type="race_name_translations_rolled_back",
            target_type="race_name_translation_batch",
            target_id=batch_id,
        ).exists():
            raise ApplyError(f"batch already rolled back: {batch_id}")
        apply_detail = json.loads(logs[0].detail)
        for identity_field in (
            "bundleIndexSha256",
            "rollbackSha256",
            "productionBeforeSha256",
        ):
            expected_identity = audit_context.get(identity_field)
            if (
                not isinstance(expected_identity, str)
                or len(expected_identity) != 64
                or apply_detail.get(identity_field) != expected_identity
            ):
                raise ApplyError(
                    f"rollback bundle identity mismatch: {identity_field}"
                )
        locked_scope_series, locked_scope_events = _lock_event_scope(
            plan,
            RaceSeries=RaceSeries,
            RaceEvent=RaceEvent,
            require_before_hashes=False,
        )
        if locked_scope_series:
            locked_series_by_id = {row.id: row for row in locked_scope_series}
            locked_series = [locked_series_by_id[row_id] for row_id in series_ids]
            locked_events_by_id = {row.id: row for row in locked_scope_events}
            locked_events = [locked_events_by_id[row_id] for row_id in event_ids]
        else:
            locked_series = _lock_exact(RaceSeries, series_ids, "RaceSeries")
            locked_events = _lock_exact(RaceEvent, event_ids, "RaceEvent")
        locked_historical_targets = _lock_exact(
            HistoricalRaceEventTarget,
            historical_target_ids,
            "HistoricalRaceEventTarget",
        )
        current = _aggregate_rows(
            locked_series, locked_events, locked_historical_targets
        )
        if current["sha256"] != apply_detail.get("afterSha256"):
            raise ApplyError("rollback after-state full-row CAS mismatch")
        rolled_back_at = timezone.now()
        series_by_id = {int(row["seriesId"]): row for row in series_plan}
        event_by_id = {int(row["eventId"]): row for row in event_plan_rows}
        historical_target_by_id = {
            int(row["historicalTargetId"]): row
            for row in historical_target_plan_rows
        }
        for row in locked_series:
            row.chinese_name = _restore_fields(series_by_id[row.id])["chinese_name"]
            row.updated_at = rolled_back_at
        for row in locked_events:
            before = _restore_fields(event_by_id[row.id])
            row.chinese_name = before["chinese_name"]
            row.race_series_id = before["race_series_id"]
            row.series_key = before["series_key"]
            row.updated_at = rolled_back_at
        for row in locked_historical_targets:
            before = _restore_fields(historical_target_by_id[row.id])
            row.race_series_id = before["race_series_id"]
            row.updated_at = rolled_back_at
        RaceSeries.objects.bulk_update(
            locked_series, ["chinese_name", "updated_at"], batch_size=BATCH_SIZE
        )
        RaceEvent.objects.bulk_update(
            locked_events,
            ["chinese_name", "race_series_id", "series_key", "updated_at"],
            batch_size=BATCH_SIZE,
        )
        HistoricalRaceEventTarget.objects.bulk_update(
            locked_historical_targets,
            ["race_series_id", "updated_at"],
            batch_size=BATCH_SIZE,
        )
        rollback_rows = _aggregate_rows(
            list(RaceSeries.objects.filter(id__in=series_ids).order_by("id")),
            list(RaceEvent.objects.filter(id__in=event_ids).order_by("id")),
            list(
                HistoricalRaceEventTarget.objects.filter(
                    id__in=historical_target_ids
                ).order_by("id")
            ),
        )
        detail = {
            "schemaVersion": "race-name-translation-operation-log.v1",
            **normalize_value(audit_context),
            "batchId": batch_id,
            "operator": audit_context.get("operator", "mentianlu_via_codex"),
            "applyLogId": logs[0].id,
            "seriesCount": len(series_ids),
            "eventCount": len(event_ids),
            "historicalTargetCount": len(historical_target_ids),
            "rolledBackAt": normalize_value(rolled_back_at),
            "rollbackAfterAggregateSha256": rollback_rows["sha256"],
        }
        OperationLog.objects.create(
            admin=None,
            action_type="race_name_translations_rolled_back",
            target_type="race_name_translation_batch",
            target_id=batch_id,
            detail=canonical_json(detail),
        )
        return {
            "mode": "rollback-commit",
            "batchId": batch_id,
            "seriesCount": len(series_ids),
            "eventCount": len(event_ids),
            "historicalTargetCount": len(historical_target_ids),
        }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplyError(f"invalid JSON {path.name}: {exc}") from exc


def _bundle_audit_context(
    index: dict[str, Any],
    args: argparse.Namespace,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    file_hashes = {row["file"]: row["sha256"] for row in index["files"]}
    return {
        "batchId": str(metadata["manifestContentSha256"])[:32],
        "operator": args.operator,
        "authorizationRef": args.authorization_ref,
        "authorizationTime": args.authorization_time,
        "commitOid": args.commit_oid,
        "bundleIndexSha256": args.expected_bundle_index_sha256,
        "bundleContentSha256": index["contentSha256"],
        "toolSha256": file_hashes["apply_race_name_translation_manifest.py"],
        "verifierSha256": file_hashes["verify_race_name_translation_manifest.py"],
        "manifestSha256": metadata["manifestContentSha256"],
        "productionBeforeSha256": metadata["productionBeforeSecondSha256"],
        "dryRunSha256": metadata["dryRunContentSha256"],
        "rollbackSha256": metadata["rollbackContentSha256"],
        "backupSha256": args.backup_sha256,
        "backupSizeBytes": args.backup_size_bytes,
    }


def _load_execution_inputs(
    bundle_dir: Path,
    index: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = _read_json(bundle_dir / "execution-metadata.json")
    if metadata.get("schemaVersion") != "race-name-translation-execution-metadata.v1":
        raise ApplyError("unsupported execution metadata schema")
    required_sha_fields = (
        "manifestContentSha256",
        "productionBeforeSecondSha256",
        "dryRunContentSha256",
        "rollbackContentSha256",
        "executionPlanContentSha256",
        "manifestFileSha256",
        "productionBeforeFileSha256",
        "dryRunFileSha256",
        "rollbackFileSha256",
    )
    if any(
        not isinstance(metadata.get(field), str) or len(metadata[field]) != 64
        for field in required_sha_fields
    ):
        raise ApplyError("invalid execution metadata SHA")
    if (
        metadata.get("dryRunApplyReady") is not True
        or metadata.get("dryRunBlockerCount") != 0
    ):
        raise ApplyError("dry-run is not apply-ready")
    if index is not None:
        file_hashes = {row["file"]: row["sha256"] for row in index["files"]}
        metadata_file_fields = {
            "manifest.json": "manifestFileSha256",
            "production-before.json": "productionBeforeFileSha256",
            "dry-run.json": "dryRunFileSha256",
            "rollback-before.json": "rollbackFileSha256",
        }
        if any(
            file_hashes.get(filename) != metadata.get(field)
            for filename, field in metadata_file_fields.items()
        ):
            raise ApplyError("execution metadata/file identity mismatch")

    execution_plan = _read_json(bundle_dir / "execution-plan.json")
    if (
        execution_plan.get("schemaVersion")
        != "race-name-translation-execution-plan.v1"
    ):
        raise ApplyError("unsupported execution plan schema")
    if (
        execution_plan.get("sourceRollbackContentSha256")
        != metadata["rollbackContentSha256"]
    ):
        raise ApplyError("execution plan/rollback identity mismatch")
    content = dict(execution_plan)
    actual_content_sha256 = content.pop("contentSha256", None)
    if (
        actual_content_sha256 != metadata["executionPlanContentSha256"]
        or actual_content_sha256 != sha256_json(content)
    ):
        raise ApplyError("execution plan content identity mismatch")
    return metadata, execution_plan


def _setup_django() -> None:
    server_root = Path("/app/server")
    if server_root.exists():
        sys.path.insert(0, str(server_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    import django

    django.setup()


def _assert_production_target_counts(rollback: dict[str, Any]) -> None:
    series_count = len(rollback.get("series") or [])
    event_count = len(rollback.get("events") or [])
    if (
        series_count != EXPECTED_PRODUCTION_SERIES_COUNT
        or event_count != EXPECTED_PRODUCTION_EVENT_COUNT
    ):
        raise ApplyError(
            "production target counts must be "
            f"{EXPECTED_PRODUCTION_SERIES_COUNT}/{EXPECTED_PRODUCTION_EVENT_COUNT}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--expected-bundle-index-sha256", required=True)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--rollback-commit", action="store_true")
    parser.add_argument("--operator", default="mentianlu_via_codex")
    parser.add_argument("--authorization-ref", default="")
    parser.add_argument("--authorization-time", default="")
    parser.add_argument("--commit-oid", default="")
    parser.add_argument("--backup-sha256", default="")
    parser.add_argument("--backup-size-bytes", type=int, default=0)
    args = parser.parse_args()
    if args.commit and args.rollback_commit:
        raise ApplyError("--commit and --rollback-commit are mutually exclusive")
    bundle_dir = Path(args.bundle_dir).resolve()
    index = verify_bundle(bundle_dir, args.expected_bundle_index_sha256)
    metadata, rollback = _load_execution_inputs(bundle_dir, index)
    if args.commit:
        _assert_production_target_counts(rollback)
    if (args.commit or args.rollback_commit) and (
        not args.authorization_ref
        or not args.authorization_time
        or not args.commit_oid
        or len(args.backup_sha256) != 64
        or args.backup_size_bytes <= 0
    ):
        raise ApplyError("commit/rollback requires authorization, commit, and backup identity")
    audit_context = _bundle_audit_context(
        index,
        args,
        metadata,
    )
    _setup_django()
    result = (
        execute_rollback(rollback, audit_context=audit_context)
        if args.rollback_commit
        else execute_plan(rollback, commit=args.commit, audit_context=audit_context)
    )
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApplyError as exc:
        print(canonical_json({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
