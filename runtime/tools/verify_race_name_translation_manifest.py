#!/usr/bin/env python3
"""Independent read-only verifier for a race-name translation bundle."""

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
FORBIDDEN_HANDICAP_MARKERS = ("让赛", "讓賽", "让步赛", "讓步賽")


class VerificationError(RuntimeError):
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


def verify_bundle(bundle_dir: Path, expected_index_sha256: str) -> dict[str, Any]:
    index_path = bundle_dir / "bundle-index.json"
    if not index_path.is_file() or index_path.is_symlink():
        raise VerificationError("bundle-index.json must be a regular file")
    if sha256_file(index_path) != expected_index_sha256:
        raise VerificationError("bundle index sha mismatch")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    content = dict(index)
    expected_content_sha256 = content.pop("contentSha256", None)
    if expected_content_sha256 != sha256_json(content):
        raise VerificationError("bundle index content sha mismatch")
    rows = index.get("files")
    if not isinstance(rows, list):
        raise VerificationError("bundle index files must be a list")
    by_name = {row.get("file"): row for row in rows if isinstance(row, dict)}
    if set(by_name) != set(BUNDLE_MEMBERS) or len(rows) != len(BUNDLE_MEMBERS):
        raise VerificationError("bundle member set mismatch")
    for name in BUNDLE_MEMBERS:
        member = bundle_dir / name
        row = by_name[name]
        if (
            not member.is_file()
            or member.is_symlink()
            or member.stat().st_size != row.get("sizeBytes")
            or sha256_file(member) != row.get("sha256")
        ):
            raise VerificationError(f"bundle member mismatch: {name}")
    return index


def _setup_django() -> None:
    server_root = Path("/app/server")
    if server_root.exists():
        sys.path.insert(0, str(server_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    import django

    django.setup()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


MUTABLE_FIELDS_BY_KIND = {
    "series": {"chinese_name", "updated_at"},
    "event": {"chinese_name", "race_series_id", "series_key", "updated_at"},
    "historical_target": {"race_series_id", "updated_at"},
}


def _expected_mutable_fields(
    plan_row: dict[str, Any],
    *,
    mode: str,
    operation_time: str,
    target_kind: str,
) -> dict[str, Any]:
    restore = plan_row.get("restore")
    if isinstance(restore, dict):
        fields = dict(restore)
    else:
        fields = {
            key: value
            for key, value in plan_row["before"]["fields"].items()
            if key in MUTABLE_FIELDS_BY_KIND[target_kind]
        }
    if mode == "applied":
        after = plan_row["after"]
        if target_kind in {"series", "event"}:
            fields["chinese_name"] = after["chineseName"]
        if target_kind in {"event", "historical_target"} and "raceSeriesId" in after:
            fields["race_series_id"] = int(after["raceSeriesId"])
        if target_kind == "event" and "seriesKey" in after:
            fields["series_key"] = after["seriesKey"]
    fields["updated_at"] = operation_time
    return fields


def _assert_expected_instance(
    instance: Any,
    plan_row: dict[str, Any],
    *,
    mode: str,
    operation_time: str,
    target_kind: str,
    label: str,
) -> None:
    actual = canonical_model_row(instance)["fields"]
    stable_sha = plan_row.get("stableFieldsSha256")
    if stable_sha:
        mutable_fields = MUTABLE_FIELDS_BY_KIND[target_kind]
        stable_fields = {
            key: value for key, value in actual.items() if key not in mutable_fields
        }
        if sha256_json(stable_fields) != stable_sha:
            raise VerificationError(f"{label} stable-field mismatch: id={instance.id}")
        expected_mutable = _expected_mutable_fields(
            plan_row,
            mode=mode,
            operation_time=operation_time,
            target_kind=target_kind,
        )
        if any(actual.get(key) != value for key, value in expected_mutable.items()):
            raise VerificationError(f"{label} mutable-field mismatch: id={instance.id}")
        return

    expected = dict(plan_row["before"]["fields"])
    expected.update(
        _expected_mutable_fields(
            plan_row,
            mode=mode,
            operation_time=operation_time,
            target_kind=target_kind,
        )
    )
    if actual != expected:
        raise VerificationError(f"{label} after-state mismatch: id={instance.id}")


def verify_database(
    plan: dict[str, Any],
    *,
    batch_id: str,
    mode: str,
    expected_rollback_artifact_sha256: str | None = None,
    expected_audit_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    from django.db import connection, transaction

    from stable.models import (
        HistoricalRaceEventTarget,
        OperationLog,
        RaceEvent,
        RaceSeries,
    )

    action_type = (
        "race_name_translations_applied"
        if mode == "applied"
        else "race_name_translations_rolled_back"
    )
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                cursor.execute("SET LOCAL statement_timeout = '120s'")
        logs = list(
            OperationLog.objects.filter(
                action_type=action_type,
                target_type="race_name_translation_batch",
                target_id=batch_id,
            )
        )
        if len(logs) != 1:
            raise VerificationError(
                f"expected exactly one {action_type} OperationLog, found {len(logs)}"
            )
        detail = json.loads(logs[0].detail)
        if expected_audit_identity is not None:
            for field, expected_value in expected_audit_identity.items():
                if (
                    not isinstance(expected_value, str)
                    or len(expected_value) != 64
                    or detail.get(field) != expected_value
                ):
                    raise VerificationError(
                        f"OperationLog bundle identity mismatch: {field}"
                    )
        time_key = "appliedAt" if mode == "applied" else "rolledBackAt"
        operation_time = detail.get(time_key)
        if not operation_time:
            raise VerificationError(f"OperationLog is missing {time_key}")
        if (
            mode == "rolled-back"
            and expected_rollback_artifact_sha256 is not None
            and detail.get("rollbackSha256")
            != expected_rollback_artifact_sha256
        ):
            raise VerificationError("OperationLog rollback artifact SHA mismatch")
        series_plan = plan.get("series") or []
        event_plan = plan.get("events") or []
        historical_target_plan = plan.get("historicalTargets") or []
        series_ids = sorted(int(row["seriesId"]) for row in series_plan)
        event_ids = sorted(int(row["eventId"]) for row in event_plan)
        historical_target_ids = sorted(
            int(row["historicalTargetId"]) for row in historical_target_plan
        )
        event_scope = plan.get("eventScope")
        if not isinstance(event_scope, dict):
            raise VerificationError("execution plan eventScope is required")
        scope_series_plan = event_scope.get("series") or []
        scope_series_ids = sorted(
            int(row["seriesId"]) for row in scope_series_plan
        )
        scope_event_plan = event_scope.get("events") or []
        scope_event_ids = sorted(int(row["eventId"]) for row in scope_event_plan)
        if (
            not scope_series_ids
            or len(scope_series_ids) != len(set(scope_series_ids))
            or len(scope_event_ids) != len(set(scope_event_ids))
        ):
            raise VerificationError("invalid execution plan eventScope")
        series_rows = list(
            RaceSeries.objects.filter(id__in=series_ids).order_by("id")
        )
        scope_series_rows = list(
            RaceSeries.objects.filter(id__in=scope_series_ids).order_by("id")
        )
        event_rows = list(RaceEvent.objects.filter(id__in=event_ids).order_by("id"))
        scope_event_rows = list(
            RaceEvent.objects.filter(race_series_id__in=scope_series_ids).order_by("id")
        )
        historical_target_rows = list(
            HistoricalRaceEventTarget.objects.filter(
                id__in=historical_target_ids
            ).order_by("id")
        )
        if [row.id for row in series_rows] != series_ids:
            raise VerificationError("RaceSeries target set mismatch")
        if [row.id for row in scope_series_rows] != scope_series_ids:
            raise VerificationError("RaceSeries complete event-scope mismatch")
        if [row.id for row in event_rows] != event_ids:
            raise VerificationError("RaceEvent target set mismatch")
        if [row.id for row in scope_event_rows] != scope_event_ids:
            raise VerificationError("RaceEvent complete series scope mismatch")
        if [row.id for row in historical_target_rows] != historical_target_ids:
            raise VerificationError("HistoricalRaceEventTarget target set mismatch")
        series_by_id = {int(row["seriesId"]): row for row in series_plan}
        scope_series_by_id = {
            int(row["seriesId"]): row for row in scope_series_plan
        }
        if not set(series_by_id).issubset(set(scope_series_by_id)):
            raise VerificationError("RaceSeries action set is outside event scope")
        event_by_id = {int(row["eventId"]): row for row in event_plan}
        scope_event_by_id = {
            int(row["eventId"]): row for row in scope_event_plan
        }
        historical_target_by_id = {
            int(row["historicalTargetId"]): row
            for row in historical_target_plan
        }
        for instance in series_rows:
            _assert_expected_instance(
                instance,
                series_by_id[instance.id],
                mode=mode,
                operation_time=operation_time,
                target_kind="series",
                label="RaceSeries",
            )
        action_series_ids = set(series_by_id)
        for instance in scope_series_rows:
            if instance.id not in action_series_ids:
                if canonical_model_row(instance)["rowSha256"] != scope_series_by_id[
                    instance.id
                ].get("beforeRowSha256"):
                    raise VerificationError(
                        f"RaceSeries event-scope full-row CAS mismatch: id={instance.id}"
                    )
        correction_count = 0
        for instance in event_rows:
            plan_row = event_by_id[instance.id]
            _assert_expected_instance(
                instance,
                plan_row,
                mode=mode,
                operation_time=operation_time,
                target_kind="event",
                label="RaceEvent",
            )
            if mode == "applied" and any(
                marker in instance.chinese_name
                for marker in FORBIDDEN_HANDICAP_MARKERS
            ):
                raise VerificationError(
                    f"forbidden handicap marker remains: id={instance.id}"
                )
            correction_count += (
                plan_row.get("actionType") == "reassign_series_and_translate"
            )
        action_ids = set(event_by_id)
        for instance in scope_event_rows:
            scope_row = scope_event_by_id[instance.id]
            expected_series_id = int(scope_row["raceSeriesId"])
            if mode == "applied" and instance.id in action_ids:
                expected_series_id = int(
                    (event_by_id[instance.id].get("after") or {}).get(
                        "raceSeriesId", expected_series_id
                    )
                )
            if instance.race_series_id != expected_series_id:
                raise VerificationError(
                    f"RaceEvent event-scope series mismatch: id={instance.id}"
                )
            if instance.id not in action_ids:
                if canonical_model_row(instance)["rowSha256"] != scope_row.get(
                    "beforeRowSha256"
                ):
                    raise VerificationError(
                        f"RaceEvent event-scope full-row CAS mismatch: id={instance.id}"
                    )
        for instance in historical_target_rows:
            plan_row = historical_target_by_id[instance.id]
            _assert_expected_instance(
                instance,
                plan_row,
                mode=mode,
                operation_time=operation_time,
                target_kind="historical_target",
                label="HistoricalRaceEventTarget",
            )
            event = next(
                (
                    row
                    for row in event_rows
                    if row.id == int(plan_row["eventId"])
                ),
                None,
            )
            if (
                event is None
                or instance.event_id != event.id
                or instance.year != event.year
                or instance.race_series_id != event.race_series_id
            ):
                raise VerificationError(
                    f"HistoricalRaceEventTarget/event identity mismatch: id={instance.id}"
                )
        content = {
            "series": [canonical_model_row(row) for row in series_rows],
            "events": [canonical_model_row(row) for row in event_rows],
            "historicalTargets": [
                canonical_model_row(row) for row in historical_target_rows
            ],
        }
        actual_sha256 = sha256_json(content)
        expected_sha_key = (
            "afterSha256"
            if mode == "applied"
            else "rollbackAfterAggregateSha256"
        )
        if actual_sha256 != detail.get(expected_sha_key):
            raise VerificationError(f"aggregate {expected_sha_key} mismatch")
        if detail.get("seriesCount") != len(series_ids) or detail.get(
            "eventCount"
        ) != len(event_ids):
            raise VerificationError("OperationLog target counts mismatch")
        if detail.get("historicalTargetCount") != len(historical_target_ids):
            raise VerificationError("OperationLog historical target count mismatch")
        if mode == "applied":
            if detail.get("identityCorrectionCount") != correction_count:
                raise VerificationError("OperationLog identity correction count mismatch")
        return {
            "ok": True,
            "mode": mode,
            "batchId": batch_id,
            "seriesCount": len(series_ids),
            "eventCount": len(event_ids),
            "historicalTargetCount": len(historical_target_ids),
            "identityCorrectionCount": correction_count,
            "snapshotSha256": actual_sha256,
            "operationLogId": logs[0].id,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--expected-bundle-index-sha256", required=True)
    parser.add_argument("--mode", choices=("applied", "rolled-back"), default="applied")
    args = parser.parse_args()
    bundle_dir = Path(args.bundle_dir).resolve()
    index = verify_bundle(bundle_dir, args.expected_bundle_index_sha256)
    metadata = _read_json(bundle_dir / "execution-metadata.json")
    plan = _read_json(bundle_dir / "execution-plan.json")
    if metadata.get("schemaVersion") != "race-name-translation-execution-metadata.v1":
        raise VerificationError("unsupported execution metadata schema")
    if plan.get("schemaVersion") != "race-name-translation-execution-plan.v1":
        raise VerificationError("unsupported execution plan schema")
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
        raise VerificationError("execution metadata/file identity mismatch")
    plan_content = dict(plan)
    plan_content_sha256 = plan_content.pop("contentSha256", None)
    if (
        plan_content_sha256 != metadata.get("executionPlanContentSha256")
        or plan_content_sha256 != sha256_json(plan_content)
    ):
        raise VerificationError("execution plan content identity mismatch")
    rollback_artifact_sha256 = metadata.get("rollbackContentSha256")
    if plan.get("sourceRollbackContentSha256") != rollback_artifact_sha256:
        raise VerificationError("execution plan/rollback identity mismatch")
    manifest_sha256 = metadata.get("manifestContentSha256")
    if not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64:
        raise VerificationError("manifest content SHA is missing")
    expected_audit_identity = {
        "bundleIndexSha256": args.expected_bundle_index_sha256,
        "bundleContentSha256": index["contentSha256"],
        "toolSha256": file_hashes["apply_race_name_translation_manifest.py"],
        "verifierSha256": file_hashes["verify_race_name_translation_manifest.py"],
        "manifestSha256": metadata["manifestContentSha256"],
        "productionBeforeSha256": metadata["productionBeforeSecondSha256"],
        "dryRunSha256": metadata["dryRunContentSha256"],
        "rollbackSha256": metadata["rollbackContentSha256"],
    }
    _setup_django()
    result = verify_database(
        plan,
        batch_id=manifest_sha256[:32],
        mode=args.mode,
        expected_rollback_artifact_sha256=rollback_artifact_sha256,
        expected_audit_identity=expected_audit_identity,
    )
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (VerificationError, OSError, json.JSONDecodeError) as exc:
        print(canonical_json({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
