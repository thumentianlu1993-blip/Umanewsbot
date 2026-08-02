from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from stable.models import (
    HistoricalRaceCalendarRepairReceipt,
    HistoricalRaceCalendarRepairReceiptStatus,
    HistoricalRaceEventTarget,
    RaceEvent,
    RaceEventPublicPath,
    RaceEventPublicPathKind,
    RaceSeries,
)
from stable.services.historical_race_calendar_admission import (
    _verified_repair_writer,
    require_exact_active_gate,
)
from stable.services.race_event_public_cache import invalidate_public_race_cache
from stable.services.race_event_years import validate_authority_url


MANIFEST_SCHEMA = "historical-race-calendar-integrity-manifest.v1"
APPROVAL_SCHEMA = "historical-race-calendar-integrity-approval.v1"
MAINTENANCE_SCHEMA = "historical-race-calendar-maintenance-evidence.v1"
ROLLBACK_SCHEMA = "historical-race-calendar-integrity-rollback.v1"
VERIFIER_SCHEMA = "historical-race-calendar-integrity-verifier.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
INVALID_CROSS_YEAR_REASON = "hong_kong_racing_season_spans_calendar_years"
TEMPORARY_YEAR_MINIMUM = 65000
REQUIRED_MAINTENANCE_CHECKS = {
    "historical_import",
    "reconciliation",
    "race_live_projection",
    "p0_participant",
}
BOUND_ARTIFACT_NAMES = {
    "census.json",
    "review.csv",
    "summary.json",
    "report.md",
}


class HistoricalRaceCalendarIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class FrozenJson:
    path: Path
    sha256: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class VerifiedManifest:
    root: Path
    manifest: dict[str, Any]
    manifest_sha256: str


def _fail(message: str) -> None:
    raise HistoricalRaceCalendarIntegrityError(message)


def _require_historical_backfill_enabled() -> None:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        _fail("historical race backfill is disabled")


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def default_artifact_root() -> Path:
    configured = os.environ.get("HISTORICAL_RACE_CALENDAR_REPAIR_ROOT", "").strip()
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR).parent / "runtime" / "historical_race_calendar_repair"


def _validate_sha256(value: str, *, label: str) -> str:
    normalized = str(value or "")
    if SHA256_RE.fullmatch(normalized) is None:
        _fail(f"{label} must be a lowercase SHA-256")
    return normalized


def _reject_symlink_components(path: Path, *, stop: Path | None = None) -> None:
    current = path
    stop_value = stop
    while True:
        if os.path.lexists(current):
            try:
                metadata = current.lstat()
            except OSError:
                _fail("artifact path metadata is unreadable")
            if stat.S_ISLNK(metadata.st_mode):
                _fail("artifact path must not contain symlinks")
        if current.parent == current or (stop_value is not None and current == stop_value):
            return
        current = current.parent


def _controlled_root(root: str | Path | None, *, create: bool = False) -> Path:
    candidate = Path(root) if root is not None else default_artifact_root()
    if not candidate.is_absolute():
        _fail("artifact root must be absolute")
    if os.path.lexists(candidate) and candidate.is_symlink():
        _fail("artifact root must not be a symlink")
    candidate = candidate.resolve(strict=False)
    _reject_symlink_components(candidate)
    if create:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            _fail("artifact root cannot be created")
    try:
        metadata = candidate.lstat()
    except OSError:
        _fail("artifact root does not exist")
    if not stat.S_ISDIR(metadata.st_mode):
        _fail("artifact root must be a directory")
    return candidate.resolve()


def _controlled_path(
    path: str | Path,
    *,
    root: Path,
    must_exist: bool,
    direct_child: bool = False,
) -> Path:
    raw_candidate = Path(path)
    if not raw_candidate.is_absolute():
        _fail("artifact path must be absolute")
    # Inspect the caller-provided spelling before resolve; resolving first can
    # erase an in-root symlink alias and make it indistinguishable from the
    # legitimate target. The resolved path is checked again below.
    _reject_symlink_components(raw_candidate, stop=root)
    candidate = raw_candidate.resolve(strict=False)
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        _fail("artifact path escapes the controlled root")
    if not relative.parts:
        _fail("artifact path cannot equal the controlled root")
    if direct_child and len(relative.parts) != 1:
        _fail("output directory must be a direct child of the controlled root")
    _reject_symlink_components(candidate, stop=root)
    current = root
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            _fail("artifact path must not contain symlinks")
    if must_exist and not os.path.lexists(candidate):
        _fail("required artifact does not exist")
    return candidate


def _read_regular_file(
    path: Path, *, label: str, root: Path | None = None
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_descriptors: list[int] = []
    try:
        if root is None:
            descriptor = os.open(path, flags)
        else:
            try:
                relative = path.relative_to(root)
            except ValueError:
                _fail(f"{label} path is outside the controlled root")
            if not relative.parts:
                _fail(f"{label} path is invalid")
            directory_flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_DIRECTORY", 0)
            )
            current_fd = os.open(root, directory_flags)
            directory_descriptors.append(current_fd)
            for component in relative.parts[:-1]:
                current_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=current_fd,
                )
                directory_descriptors.append(current_fd)
            descriptor = os.open(relative.parts[-1], flags, dir_fd=current_fd)
    except OSError:
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
        _fail(f"{label} cannot be opened safely")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _fail(f"{label} must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)


def _load_json(
    path: str | Path,
    *,
    root: Path,
    label: str,
    expected_sha256: str | None = None,
) -> FrozenJson:
    controlled = _controlled_path(path, root=root, must_exist=True)
    payload_bytes = _read_regular_file(controlled, label=label, root=root)
    return _load_json_bytes(
        path=controlled,
        payload_bytes=payload_bytes,
        label=label,
        expected_sha256=expected_sha256,
    )


def _load_json_bytes(
    *,
    path: Path,
    payload_bytes: bytes,
    label: str,
    expected_sha256: str | None = None,
) -> FrozenJson:
    """Decode and hash the exact bytes returned by one safe descriptor read."""

    actual_sha256 = _sha256_bytes(payload_bytes)
    if expected_sha256 is not None:
        if actual_sha256 != _validate_sha256(expected_sha256, label=f"{label} SHA-256"):
            _fail(f"{label} SHA-256 mismatch")
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeError, json.JSONDecodeError):
        _fail(f"{label} is not valid JSON")
    if not isinstance(payload, dict):
        _fail(f"{label} must be a JSON object")
    return FrozenJson(path, actual_sha256, payload)


def _model_payload(instance: Any) -> dict[str, Any]:
    return {
        field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields
    }


def _row_identity(instance: Any) -> dict[str, Any]:
    payload = _model_payload(instance)
    return {"payload": payload, "sha256": _digest(payload)}


def _code_identity() -> dict[str, str]:
    source = _read_regular_file(Path(__file__), label="repair service source")
    models = (RaceEvent, HistoricalRaceEventTarget, RaceEventPublicPath)
    model_contract = {
        model._meta.label_lower: [
            {
                "name": field.name,
                "type": field.get_internal_type(),
                "null": field.null,
            }
            for field in model._meta.concrete_fields
        ]
        for model in models
    }
    return {
        "tool_source_sha256": _sha256_bytes(source),
        "model_contract_sha256": _digest(model_contract),
        "release_commit": os.environ.get("UMANEWS_RELEASE_COMMIT", "").strip(),
    }


def _rows_identity(rows: Iterable[Any]) -> dict[str, Any]:
    payload = [_model_payload(row) for row in rows]
    return {"count": len(payload), "sha256": _digest(payload)}


def _event_dependencies(event: RaceEvent) -> dict[str, dict[str, Any]]:
    """Hash all reverse FK/O2O dependencies not intentionally changed by this tool."""
    dependencies: dict[str, dict[str, Any]] = {}
    excluded_models = {HistoricalRaceEventTarget, RaceEventPublicPath}
    for relation in sorted(
        event._meta.related_objects,
        key=lambda item: (
            item.related_model._meta.label_lower,
            item.get_accessor_name(),
            item.field.name,
        ),
    ):
        model = relation.related_model
        if model in excluded_models or relation.many_to_many:
            continue
        field = relation.field
        try:
            queryset = model._default_manager.filter(
                **{field.attname: event.pk}
            ).order_by("pk")
            rows = list(queryset)
        except (AttributeError, TypeError):
            _fail("an event dependency cannot be enumerated safely")
        relation_key = ":".join(
            (
                model._meta.label_lower,
                relation.get_accessor_name(),
                field.name,
            )
        )
        dependencies[relation_key] = _rows_identity(rows)
    return dependencies


def _series_graph(series_id: int | None) -> dict[str, Any]:
    if series_id is None:
        return {"series_id": None, "events": [], "targets": []}
    events = list(
        RaceEvent.objects.filter(race_series_id=series_id)
        .order_by("edition_year", "year", "pk")
        .values("id", "year", "edition_year", "slug", "visibility_status")
    )
    targets = list(
        HistoricalRaceEventTarget.objects.filter(race_series_id=series_id)
        .order_by("year", "pk")
        .values(
            "id",
            "year",
            "event_id",
            "resolution_status",
            "superseded_by_id",
        )
    )
    return {"series_id": series_id, "events": events, "targets": targets}


def _target_snapshot(event: RaceEvent) -> list[dict[str, Any]]:
    return [
        _model_payload(target)
        for target in HistoricalRaceEventTarget.objects.filter(event_id=event.pk)
        .order_by("pk")
    ]


def _path_snapshot(event: RaceEvent) -> list[dict[str, Any]]:
    return [
        _model_payload(path)
        for path in RaceEventPublicPath.objects.filter(event_id=event.pk).order_by("pk")
    ]


def _precondition(event: RaceEvent) -> dict[str, Any]:
    payload = {
        "event": _model_payload(event),
        "targets": _target_snapshot(event),
        "paths": _path_snapshot(event),
        "dependencies": _event_dependencies(event),
        "series_graph": _series_graph(event.race_series_id),
    }
    return {"sha256": _digest(payload), "payload": payload}


def _approved_cross_year_evidence(event: RaceEvent) -> dict[str, Any] | None:
    refs = event.source_refs if isinstance(event.source_refs, dict) else {}
    evidence = refs.get("cross_year_evidence")
    if not isinstance(evidence, dict):
        return None
    reason = str(evidence.get("reason") or "").strip()
    classification = str(evidence.get("classification") or "").strip()
    try:
        parsed = validate_authority_url(evidence.get("authority_url"))
    except ValidationError:
        return None
    if not (
        evidence.get("actual_year") == event.local_date.year
        and reason
        and reason != INVALID_CROSS_YEAR_REASON
        and classification
        in {"ordinary_season_year_shift", "legitimate_cross_year_edition"}
        and evidence.get("approved") is True
    ):
        return None
    return {
        "actual_year": event.local_date.year,
        "reason": reason,
        "classification": classification,
        "authority_host": parsed.hostname.casefold(),
        "evidence_sha256": _digest(evidence),
    }


def _repaired_slug(event: RaceEvent) -> str:
    old_suffix = f"-{event.year}"
    new_suffix = f"-{event.local_date.year}"
    if event.slug.endswith(old_suffix):
        base = event.slug[: -len(old_suffix)]
    else:
        base = event.slug
    maximum_base = 160 - len(new_suffix)
    return f"{base[:maximum_base].rstrip('-')}{new_suffix}"


def _classify_event(event: RaceEvent) -> dict[str, Any]:
    if event.local_date is None or event.year == event.local_date.year:
        _fail("census classifier received a non-mismatch event")
    natural_year = event.local_date.year
    edition_year = event.edition_year or event.year
    desired_slug = _repaired_slug(event)
    precondition = _precondition(event)
    action_id = f"event-{event.pk}"
    block_reasons: list[str] = []
    same_series_natural = []
    if event.race_series_id:
        same_series_natural = list(
            RaceEvent.objects.filter(
                race_series_id=event.race_series_id,
                year=natural_year,
            )
            .exclude(pk=event.pk)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
    path_conflict = (
        RaceEventPublicPath.objects.filter(year=natural_year, slug=desired_slug)
        .exclude(event_id=event.pk)
        .exists()
        or RaceEvent.objects.filter(year=natural_year, slug=desired_slug)
        .exclude(pk=event.pk)
        .exists()
    )
    targets = precondition["payload"]["targets"]
    paths = precondition["payload"]["paths"]
    target_years = sorted(
        {row["year"] for row in targets if isinstance(row.get("year"), int)}
    )
    canonical_paths = [
        row
        for row in paths
        if row.get("path_kind") == RaceEventPublicPathKind.CANONICAL
    ]
    evidence = _approved_cross_year_evidence(event)
    target_natural_conflict = False
    if event.race_series_id:
        attached_target_ids = [row["id"] for row in targets]
        target_natural_conflict = (
            HistoricalRaceEventTarget.objects.filter(
                race_series_id=event.race_series_id,
                year=natural_year,
            )
            .exclude(pk__in=attached_target_ids)
            .exists()
        )

    if len(canonical_paths) != 1:
        classification = "conflict"
        disposition = "block"
        operation = "none"
        block_reasons.append("canonical_registry_missing_or_ambiguous")
    elif any(year != edition_year for year in target_years):
        classification = "conflict"
        disposition = "block"
        operation = "none"
        block_reasons.append("target_edition_year_mismatch")
    elif same_series_natural or target_natural_conflict:
        classification = "canonicalize_duplicate"
        disposition = "block"
        operation = "canonicalize_duplicate"
        block_reasons.append("release_b_required")
        block_reasons.append("duplicate_requires_reviewed_survivor_and_fk_ledger")
    elif path_conflict:
        classification = "conflict"
        disposition = "block"
        operation = "none"
        block_reasons.append("public_path_conflict")
    elif (
        evidence is not None
        and evidence["classification"] == "legitimate_cross_year_edition"
        and edition_year != natural_year
    ):
        classification = "legitimate_cross_year_edition"
        disposition = "action"
        operation = "repair_public_year_keep_edition"
    elif (
        event.country_region == "hong_kong"
        and evidence is not None
        and evidence["classification"] == "ordinary_season_year_shift"
    ):
        classification = "ordinary_season_year_shift"
        disposition = "action"
        operation = (
            "repair_public_year_keep_edition"
            if edition_year == natural_year
            else "rotate_year"
        )
    elif event.country_region == "hong_kong":
        classification = "needs_manual_review"
        disposition = "manual"
        operation = "none"
        block_reasons.append("hkjc_authoritative_classification_missing")
    else:
        classification = "needs_manual_review"
        disposition = "manual"
        operation = "none"
        block_reasons.append("authoritative_cross_year_classification_missing")

    return {
        "action_id": action_id,
        "event_id": event.pk,
        "series_id": event.race_series_id,
        "country_region": event.country_region,
        "classification": classification,
        "disposition": disposition,
        "operation": operation,
        "block_reasons": block_reasons,
        "before": {
            "public_year": event.year,
            "edition_year": edition_year,
            "local_date": event.local_date.isoformat(),
            "slug": event.slug,
            "target_years": target_years,
        },
        "expected_after": {
            "public_year": natural_year,
            "edition_year": (
                natural_year
                if classification == "ordinary_season_year_shift"
                else edition_year
            ),
            "slug": desired_slug,
        },
        "evidence": evidence or {"evidence_sha256": _digest(event.source_refs or {})},
        "duplicate_candidate_event_ids": same_series_natural,
        "precondition_sha256": precondition["sha256"],
        "dependency_snapshot": precondition["payload"]["dependencies"],
        "series_graph": precondition["payload"]["series_graph"],
    }


class _ReadOnlySql:
    ALLOWED = {"SELECT", "SET", "SHOW", "PRAGMA", "EXPLAIN"}

    def __call__(self, execute, sql, params, many, context):
        first = str(sql or "").lstrip().split(None, 1)
        if not first or first[0].upper() not in self.ALLOWED:
            _fail("prepare attempted a database write")
        return execute(sql, params, many, context)


@contextmanager
def _read_only_snapshot():
    with transaction.atomic(), connection.execute_wrapper(_ReadOnlySql()):
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
        yield


def _database_snapshot_id() -> str:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT txid_current_snapshot()")
            return f"postgresql:{cursor.fetchone()[0]}"
    return f"{connection.vendor}:transactional-test-snapshot"


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        _fail("artifact output already exists or cannot be created safely")
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _review_csv(actions: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "action_id",
            "event_id",
            "series_id",
            "country_region",
            "classification",
            "disposition",
            "operation",
            "public_year_before",
            "edition_year",
            "natural_year_after",
            "block_reasons",
            "precondition_sha256",
        ]
    )
    for row in actions:
        writer.writerow(
            [
                row["action_id"],
                row["event_id"],
                row["series_id"] or "",
                row["country_region"],
                row["classification"],
                row["disposition"],
                row["operation"],
                row["before"]["public_year"],
                row["before"]["edition_year"],
                row["expected_after"]["public_year"],
                "|".join(row["block_reasons"]),
                row["precondition_sha256"],
            ]
        )
    return stream.getvalue().encode("utf-8")


def prepare_historical_race_calendar_integrity(
    *,
    output_dir: str | Path,
    artifact_root: str | Path | None = None,
    all_regions: bool,
) -> dict[str, Any]:
    if not all_regions:
        _fail("prepare requires an explicit all-regions census")
    root = _controlled_root(artifact_root, create=True)
    destination = _controlled_path(
        output_dir,
        root=root,
        must_exist=False,
        direct_child=True,
    )
    if os.path.lexists(destination):
        _fail("prepare output directory already exists")
    temporary = Path(tempfile.mkdtemp(prefix=".prepare-", dir=root))
    try:
        with _read_only_snapshot():
            snapshot_id = _database_snapshot_id()
            actions = sorted(
                [
                    _classify_event(event)
                    for event in RaceEvent.objects.filter(
                        local_date__isnull=False
                    )
                    .exclude(year=models_year_expression())
                    .select_related("race_series")
                    .order_by(
                        "country_region",
                        "race_series_id",
                        "local_date",
                        "pk",
                    )
                    .iterator(chunk_size=500)
                ],
                key=lambda row: row["event_id"],
            )
            classification_counts = dict(
                sorted(Counter(row["classification"] for row in actions).items())
            )
            disposition_counts = dict(
                sorted(Counter(row["disposition"] for row in actions).items())
            )
            action_scope_sha256 = _digest(
                [
                    {
                        "action_id": row["action_id"],
                        "precondition_sha256": row["precondition_sha256"],
                        "operation": row["operation"],
                    }
                    for row in actions
                ]
            )
            generated_at = timezone.now().astimezone(dt_timezone.utc).isoformat()
            code_identity = _code_identity()
            census = {
                "schema_version": MANIFEST_SCHEMA,
                "generated_at": generated_at,
                "database_snapshot": snapshot_id,
                "code_identity": code_identity,
                "scope": "all_regions_all_years",
                "actions": actions,
            }
            summary = {
                "schema_version": MANIFEST_SCHEMA,
                "mismatch_count": len(actions),
                "classification_counts": classification_counts,
                "disposition_counts": disposition_counts,
                "executable_action_count": sum(
                    row["disposition"] == "action" for row in actions
                ),
                "blocked_or_manual_count": sum(
                    row["disposition"] != "action" for row in actions
                ),
                "action_scope_sha256": action_scope_sha256,
            }
            report_lines = [
                "# 历史赛事赛历完整性全库 census",
                "",
                f"- snapshot: `{snapshot_id}`",
                f"- mismatch: `{len(actions)}`",
                f"- 可执行 action: `{summary['executable_action_count']}`",
                f"- block/manual: `{summary['blocked_or_manual_count']}`",
                "",
                "任何 block/manual 未清零前，不得整批 apply；Release A 下 duplicate 固定阻断。",
                "",
            ]
            artifact_payloads = {
                "census.json": _canonical_bytes(census),
                "review.csv": _review_csv(actions),
                "summary.json": _canonical_bytes(summary),
                "report.md": "\n".join(report_lines).encode("utf-8"),
            }
            for name, payload in artifact_payloads.items():
                _write_new_file(temporary / name, payload)
            manifest = {
                "schema_version": MANIFEST_SCHEMA,
                "generated_at": generated_at,
                "database_snapshot": snapshot_id,
                "code_identity": code_identity,
                "scope": "all_regions_all_years",
                "action_scope_sha256": action_scope_sha256,
                "actions": actions,
                "classification_counts": classification_counts,
                "disposition_counts": disposition_counts,
                "artifacts": {
                    name: {
                        "path": name,
                        "size": len(payload),
                        "sha256": _sha256_bytes(payload),
                    }
                    for name, payload in sorted(artifact_payloads.items())
                },
            }
            manifest_bytes = _canonical_bytes(manifest)
            _write_new_file(temporary / "manifest.json", manifest_bytes)
            manifest_sha256 = _sha256_bytes(manifest_bytes)
            approval_template = {
                "schema_version": APPROVAL_SCHEMA,
                "status": "pending",
                "manifest_sha256": manifest_sha256,
                "action_scope_sha256": action_scope_sha256,
                "approved_action_ids": [
                    row["action_id"]
                    for row in actions
                    if row["disposition"] == "action"
                ],
                "approved_by": "",
                "approved_at": "",
                "actor": "",
            }
            _write_new_file(
                temporary / "approval.template.json",
                _canonical_bytes(approval_template),
            )
        os.rename(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "status": "prepared",
        "output_dir": str(destination),
        "manifest_path": str(destination / "manifest.json"),
        "manifest_sha256": manifest_sha256,
        "action_scope_sha256": action_scope_sha256,
        "mismatch_count": len(actions),
        "classification_counts": classification_counts,
        "disposition_counts": disposition_counts,
    }


def models_year_expression():
    from django.db.models.functions import ExtractYear

    return ExtractYear("local_date")


def _load_manifest(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    artifact_root: str | Path | None,
) -> VerifiedManifest:
    root = _controlled_root(artifact_root)
    frozen = _load_json(
        manifest_path,
        root=root,
        label="manifest",
        expected_sha256=expected_manifest_sha256,
    )
    manifest = frozen.payload
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        _fail("unsupported manifest schema")
    if manifest.get("code_identity") != _code_identity():
        _fail("manifest code or model contract drift")
    actions = manifest.get("actions")
    if not isinstance(actions, list):
        _fail("manifest actions must be a list")
    ids = [row.get("action_id") for row in actions if isinstance(row, dict)]
    event_ids = [row.get("event_id") for row in actions if isinstance(row, dict)]
    if (
        len(ids) != len(actions)
        or not all(isinstance(value, str) and value for value in ids)
        or len(set(ids)) != len(ids)
        or not all(isinstance(value, int) and value > 0 for value in event_ids)
        or event_ids != sorted(set(event_ids))
    ):
        _fail("manifest action and event IDs must be sorted and unique")
    expected_scope = _digest(
        [
            {
                "action_id": row.get("action_id"),
                "precondition_sha256": row.get("precondition_sha256"),
                "operation": row.get("operation"),
            }
            for row in actions
        ]
    )
    if manifest.get("action_scope_sha256") != expected_scope:
        _fail("manifest action scope SHA-256 mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != BOUND_ARTIFACT_NAMES:
        _fail("manifest artifact set is incomplete or unexpected")
    artifact_dir = frozen.path.parent
    if artifact_dir == root:
        _fail("manifest must be inside a dedicated artifact directory")
    for name, identity in artifacts.items():
        if (
            not isinstance(identity, dict)
            or identity.get("path") != name
            or not isinstance(identity.get("size"), int)
        ):
            _fail("manifest artifact identity is invalid")
        payload = _read_regular_file(artifact_dir / name, label=f"artifact {name}")
        if (
            len(payload) != identity["size"]
            or _sha256_bytes(payload) != identity.get("sha256")
        ):
            _fail(f"manifest artifact identity mismatch: {name}")
    return VerifiedManifest(root, manifest, frozen.sha256)


def _aware_timestamp(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        _fail(f"{label} timestamp is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{label} timestamp must include a timezone")
    return parsed


def _validate_approval(
    *,
    approval_path: str | Path,
    expected_approval_sha256: str,
    loaded: VerifiedManifest,
    actor: Any,
) -> FrozenJson:
    approval = _load_json(
        approval_path,
        root=loaded.root,
        label="approval",
        expected_sha256=expected_approval_sha256,
    )
    payload = approval.payload
    expected_ids = [
        row["action_id"]
        for row in loaded.manifest["actions"]
        if row["disposition"] == "action"
    ]
    approved_ids = payload.get("approved_action_ids")
    if (
        payload.get("schema_version") != APPROVAL_SCHEMA
        or payload.get("status") != "approved"
        or payload.get("manifest_sha256") != loaded.manifest_sha256
        or payload.get("action_scope_sha256")
        != loaded.manifest["action_scope_sha256"]
    ):
        _fail("approval is incomplete or binds a different manifest")
    if approved_ids != expected_ids:
        _fail("approval action IDs do not exactly match the executable manifest scope")
    approved_by = str(payload.get("approved_by") or "").strip()
    actor_name = actor.get_username()
    if (
        not approved_by
        or approved_by == actor_name
        or payload.get("actor") != actor_name
    ):
        _fail("approval must bind a distinct independent reviewer and the exact actor")
    _aware_timestamp(payload.get("approved_at"), label="approval")
    user_model = get_user_model()
    lookup = {user_model.USERNAME_FIELD: approved_by}
    if not user_model._default_manager.filter(**lookup).exists():
        _fail("approval reviewer does not exist")
    return approval


def _validate_maintenance(
    *,
    path: str | Path,
    expected_sha256: str,
    loaded: VerifiedManifest,
) -> FrozenJson:
    evidence = _load_json(
        path,
        root=loaded.root,
        label="maintenance evidence",
        expected_sha256=expected_sha256,
    )
    payload = evidence.payload
    checks = payload.get("checks")
    if (
        payload.get("schema_version") != MAINTENANCE_SCHEMA
        or payload.get("status") != "frozen"
        or payload.get("manifest_sha256") != loaded.manifest_sha256
        or payload.get("action_scope_sha256")
        != loaded.manifest["action_scope_sha256"]
        or not isinstance(checks, dict)
        or set(checks) != REQUIRED_MAINTENANCE_CHECKS
        or any(value != "stopped" for value in checks.values())
    ):
        _fail("maintenance evidence does not prove the exact frozen write scope")
    _aware_timestamp(payload.get("observed_at"), label="maintenance evidence")
    return evidence


def _advisory_lock(manifest_sha256: str) -> None:
    if connection.vendor != "postgresql":
        return
    signed = int.from_bytes(
        hashlib.sha256(f"historical-calendar:{manifest_sha256}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [signed])


def _lock_scope(actions: list[dict[str, Any]]) -> None:
    series_ids = sorted(
        {row["series_id"] for row in actions if row.get("series_id") is not None}
    )
    event_ids = sorted(row["event_id"] for row in actions)
    target_ids = sorted(
        HistoricalRaceEventTarget.objects.filter(event_id__in=event_ids).values_list(
            "pk", flat=True
        )
    )
    path_ids = sorted(
        RaceEventPublicPath.objects.filter(event_id__in=event_ids).values_list(
            "pk", flat=True
        )
    )
    list(RaceSeries.objects.select_for_update().filter(pk__in=series_ids).order_by("pk"))
    list(
        HistoricalRaceEventTarget.objects.select_for_update()
        .filter(pk__in=target_ids)
        .order_by("pk")
    )
    list(RaceEvent.objects.select_for_update().filter(pk__in=event_ids).order_by("pk"))
    list(
        RaceEventPublicPath.objects.select_for_update()
        .filter(pk__in=path_ids)
        .order_by("pk")
    )


def _current_action_precondition(action: dict[str, Any]) -> str:
    try:
        event = RaceEvent.objects.select_related("race_series").get(pk=action["event_id"])
    except RaceEvent.DoesNotExist:
        _fail(f"precondition drift for {action['action_id']}")
    return _precondition(event)["sha256"]


def _apply_action(
    action: dict[str, Any],
    *,
    manifest_sha256: str,
) -> dict[str, Any]:
    event = RaceEvent.objects.select_related("race_series").get(pk=action["event_id"])
    before_event = _model_payload(event)
    targets = list(
        HistoricalRaceEventTarget.objects.filter(event_id=event.pk).order_by("pk")
    )
    targets_before = [_model_payload(target) for target in targets]
    canonical_paths = list(
        RaceEventPublicPath.objects.filter(
            event=event,
            path_kind=RaceEventPublicPathKind.CANONICAL,
        ).order_by("pk")
    )
    if len(canonical_paths) != 1:
        _fail(f"canonical registry precondition failed for {action['action_id']}")
    canonical = canonical_paths[0]
    before_path = _model_payload(canonical)
    before = action["before"]
    after = action["expected_after"]
    if (
        event.year != before["public_year"]
        or (event.edition_year or event.year) != before["edition_year"]
        or event.slug != before["slug"]
        or canonical.year != event.year
        or canonical.slug != event.slug
    ):
        _fail(f"field precondition drift for {action['action_id']}")
    if RaceEvent.objects.filter(
        year=after["public_year"], slug=after["slug"]
    ).exclude(pk=event.pk).exists():
        _fail(f"event path conflict for {action['action_id']}")
    if RaceEventPublicPath.objects.filter(
        year=after["public_year"], slug=after["slug"]
    ).exclude(pk=canonical.pk).exists():
        _fail(f"registry path conflict for {action['action_id']}")
    legacy_year = canonical.year
    legacy_slug = canonical.slug
    canonical.year = after["public_year"]
    canonical.slug = after["slug"]
    canonical.reason = "historical_calendar_canonical_repair"
    canonical.manifest_sha256 = manifest_sha256
    canonical.save(
        update_fields={"year", "slug", "reason", "manifest_sha256", "updated_at"}
    )
    legacy = RaceEventPublicPath.objects.create(
        year=legacy_year,
        slug=legacy_slug,
        event=event,
        path_kind=RaceEventPublicPathKind.LEGACY,
        reason="historical_calendar_public_year_repair",
        manifest_sha256=manifest_sha256,
        created_by=None,
    )
    source_refs = dict(event.source_refs or {})
    source_refs["historical_calendar_integrity_repair"] = {
        "manifest_sha256": manifest_sha256,
        "action_id": action["action_id"],
        "operation": action["operation"],
        "before_public_year": before["public_year"],
        "after_public_year": after["public_year"],
    }
    if action["operation"] == "rotate_year":
        target_ids = [target.pk for target in targets]
        if (
            event.race_series_id
            and HistoricalRaceEventTarget.objects.filter(
                race_series_id=event.race_series_id,
                year=after["edition_year"],
            )
            .exclude(pk__in=target_ids)
            .exists()
        ):
            _fail(f"target year conflict for {action['action_id']}")
        HistoricalRaceEventTarget.objects.filter(pk__in=target_ids).update(
            year=after["edition_year"],
            updated_at=timezone.now(),
        )
    event.year = after["public_year"]
    event.slug = after["slug"]
    event.edition_year = after["edition_year"]
    event.source_refs = source_refs
    # This private manifest-bound path already validates the exact pre-state,
    # target year, canonical/legacy path conflicts and the resulting core
    # invariants.  Avoid ``RaceEvent.save()`` here because its global signal
    # invalidates the public cache before this transaction is committed.
    RaceEvent._base_manager.filter(pk=event.pk).update(
        year=event.year,
        slug=event.slug,
        edition_year=event.edition_year,
        source_refs=event.source_refs,
        updated_at=timezone.now(),
    )
    event.refresh_from_db()
    canonical.refresh_from_db()
    targets_after = [
        _model_payload(target)
        for target in HistoricalRaceEventTarget.objects.filter(
            event_id=event.pk
        ).order_by("pk")
    ]
    return {
        "action_id": action["action_id"],
        "operation": action["operation"],
        "event_id": event.pk,
        "event_before": before_event,
        "event_after": _model_payload(event),
        "targets_before": targets_before,
        "targets_after": targets_after,
        "canonical_path_id": canonical.pk,
        "canonical_path_before": before_path,
        "canonical_path_after": _model_payload(canonical),
        "legacy_path_id": legacy.pk,
        "legacy_path": _model_payload(legacy),
        "dependencies_sha256": _digest(_event_dependencies(event)),
    }


def _new_rollback_path(root: Path, manifest_sha256: str) -> Path:
    rollback_root = root / "rollback"
    _reject_symlink_components(rollback_root, stop=root)
    try:
        rollback_root.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        _fail("rollback artifact directory cannot be created")
    return rollback_root / f"{manifest_sha256}.json"


def _write_rollback_ledger(
    *,
    path: Path,
    manifest_sha256: str,
    action_scope_sha256: str,
    rows: list[dict[str, Any]],
) -> str:
    payload = {
        "schema_version": ROLLBACK_SCHEMA,
        "manifest_sha256": manifest_sha256,
        "action_scope_sha256": action_scope_sha256,
        "rows": rows,
    }
    encoded = _canonical_bytes(payload)
    _write_new_file(path, encoded)
    return _sha256_bytes(encoded)


def _orphan_ledger_matches_manifest(
    *, rows: list[dict[str, Any]], actions: list[dict[str, Any]]
) -> bool:
    required_keys = {
        "action_id",
        "operation",
        "event_id",
        "event_before",
        "event_after",
        "targets_before",
        "targets_after",
        "canonical_path_id",
        "canonical_path_before",
        "canonical_path_after",
        "legacy_path_id",
        "legacy_path",
        "dependencies_sha256",
    }
    if len(rows) != len(actions):
        return False
    for row, action in zip(rows, actions, strict=True):
        if not isinstance(row, dict) or set(row) != required_keys:
            return False
        before = row.get("event_before")
        after = row.get("event_after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            return False
        expected_before = action["before"]
        expected_after = action["expected_after"]
        if (
            row["action_id"] != action["action_id"]
            or row["operation"] != action["operation"]
            or row["event_id"] != action["event_id"]
            or before.get("id") != action["event_id"]
            or before.get("year") != expected_before["public_year"]
            or (before.get("edition_year") or before.get("year"))
            != expected_before["edition_year"]
            or before.get("slug") != expected_before["slug"]
            or after.get("id") != action["event_id"]
            or after.get("year") != expected_after["public_year"]
            or (after.get("edition_year") or after.get("year"))
            != expected_after["edition_year"]
            or after.get("slug") != expected_after["slug"]
            or row["dependencies_sha256"]
            != _digest(action["dependency_snapshot"])
        ):
            return False
    return True


def _existing_receipt_result(
    receipt: HistoricalRaceCalendarRepairReceipt,
    *,
    loaded: VerifiedManifest,
    approval_sha256: str,
    actor: Any,
) -> dict[str, Any]:
    if (
        receipt.approval_sha256 != approval_sha256
        or receipt.action_scope_sha256 != loaded.manifest["action_scope_sha256"]
        or receipt.actor_id != actor.pk
    ):
        _fail("existing receipt identity conflicts with this apply request")
    verification = verify_historical_race_calendar_integrity(
        manifest_path=loaded.root / Path("unused"),
        expected_manifest_sha256=loaded.manifest_sha256,
        artifact_root=loaded.root,
        update_receipt=True,
        _loaded=loaded,
    )
    return {
        "status": "already_applied",
        "receipt_id": receipt.pk,
        "receipt_status": verification["receipt_status"],
        "verifier": verification,
    }


def apply_historical_race_calendar_integrity(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    approval_path: str | Path,
    expected_approval_sha256: str,
    maintenance_evidence_path: str | Path,
    expected_maintenance_evidence_sha256: str,
    actor: Any,
    artifact_root: str | Path | None = None,
    confirm_reviewed_artifact: bool,
) -> dict[str, Any]:
    _require_historical_backfill_enabled()
    if not confirm_reviewed_artifact:
        _fail("apply requires --confirm-reviewed-artifact")
    loaded = _load_manifest(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        artifact_root=artifact_root,
    )
    actions = loaded.manifest["actions"]
    if any(row.get("disposition") != "action" for row in actions):
        _fail("manifest contains block/manual rows and cannot be applied")
    if any(
        row.get("operation")
        not in {"repair_public_year_keep_edition", "rotate_year"}
        for row in actions
    ):
        _fail("manifest contains an operation unavailable in Release A")
    approval = _validate_approval(
        approval_path=approval_path,
        expected_approval_sha256=expected_approval_sha256,
        loaded=loaded,
        actor=actor,
    )
    require_exact_active_gate(
        manifest_sha256=loaded.manifest_sha256,
        action_scope_sha256=loaded.manifest["action_scope_sha256"],
        actor=actor,
    )
    existing = HistoricalRaceCalendarRepairReceipt.objects.filter(
        manifest_sha256=loaded.manifest_sha256
    ).first()
    if existing is not None:
        return _existing_receipt_result(
            existing,
            loaded=loaded,
            approval_sha256=approval.sha256,
            actor=actor,
        )
    _validate_maintenance(
        path=maintenance_evidence_path,
        expected_sha256=expected_maintenance_evidence_sha256,
        loaded=loaded,
    )
    rollback_path = _new_rollback_path(loaded.root, loaded.manifest_sha256)
    if os.path.lexists(rollback_path):
        _reject_symlink_components(rollback_path, stop=loaded.root)
        controlled_rollback_path = _controlled_path(
            rollback_path,
            root=loaded.root,
            must_exist=True,
        )
        orphan_bytes = _read_regular_file(
            controlled_rollback_path,
            label="orphan rollback artifact",
            root=loaded.root,
        )
        orphan = _validate_rollback_frozen(
            frozen=_load_json_bytes(
                path=rollback_path,
                payload_bytes=orphan_bytes,
                label="orphan rollback artifact",
                expected_sha256=_sha256_bytes(orphan_bytes),
            ),
            loaded=loaded,
        )
        if not _orphan_ledger_matches_manifest(
            rows=orphan.payload["rows"], actions=actions
        ) or any(
            _current_action_precondition(action) != action["precondition_sha256"]
            for action in actions
        ):
            _fail(
                "orphan rollback artifact does not match exact scope and current pre-state"
            )
        rollback_path.unlink()
    rollback_created = False
    try:
        with transaction.atomic():
            _advisory_lock(loaded.manifest_sha256)
            require_exact_active_gate(
                manifest_sha256=loaded.manifest_sha256,
                action_scope_sha256=loaded.manifest["action_scope_sha256"],
                actor=actor,
            )
            _lock_scope(actions)
            for action in actions:
                if _current_action_precondition(action) != action["precondition_sha256"]:
                    _fail(f"precondition drift for {action['action_id']}")
            with _verified_repair_writer(
                manifest_sha256=loaded.manifest_sha256,
                action_scope_sha256=loaded.manifest["action_scope_sha256"],
            ):
                ledger_rows = [
                    _apply_action(
                        action,
                        manifest_sha256=loaded.manifest_sha256,
                    )
                    for action in actions
                ]
            rollback_sha256 = _write_rollback_ledger(
                path=rollback_path,
                manifest_sha256=loaded.manifest_sha256,
                action_scope_sha256=loaded.manifest["action_scope_sha256"],
                rows=ledger_rows,
            )
            rollback_created = True
            receipt = HistoricalRaceCalendarRepairReceipt.objects.create(
                manifest_sha256=loaded.manifest_sha256,
                approval_sha256=approval.sha256,
                action_scope_sha256=loaded.manifest["action_scope_sha256"],
                actor=actor,
                status=HistoricalRaceCalendarRepairReceiptStatus.APPLIED,
                rollback_sha256=rollback_sha256,
                applied_at=timezone.now(),
            )
            core = _verify_loaded_manifest(loaded)
            if not core["ok"]:
                _fail("core invariants failed inside the apply transaction")
            transaction.on_commit(invalidate_public_race_cache)
    except Exception:
        if rollback_created:
            rollback_path.unlink(missing_ok=True)
        raise
    verifier = verify_historical_race_calendar_integrity(
        manifest_path=manifest_path,
        expected_manifest_sha256=loaded.manifest_sha256,
        artifact_root=loaded.root,
        update_receipt=True,
        _loaded=loaded,
    )
    receipt.refresh_from_db()
    return {
        "status": receipt.status,
        "receipt_id": receipt.pk,
        "rollback_path": str(rollback_path),
        "rollback_sha256": receipt.rollback_sha256,
        "verifier": verifier,
    }


def _verify_loaded_manifest(loaded: VerifiedManifest) -> dict[str, Any]:
    errors: list[str] = []
    actions = loaded.manifest["actions"]
    for action in actions:
        action_id = action["action_id"]
        try:
            event = RaceEvent.objects.get(pk=action["event_id"])
        except RaceEvent.DoesNotExist:
            errors.append(f"{action_id}:event_missing")
            continue
        expected = action["expected_after"]
        if (
            event.year != expected["public_year"]
            or (event.edition_year or event.year) != expected["edition_year"]
            or event.slug != expected["slug"]
        ):
            errors.append(f"{action_id}:event_state_mismatch")
        targets = list(
            HistoricalRaceEventTarget.objects.filter(event_id=event.pk).order_by("pk")
        )
        if any(target.year != (event.edition_year or event.year) for target in targets):
            errors.append(f"{action_id}:target_edition_mismatch")
        canonical = list(
            RaceEventPublicPath.objects.filter(
                event_id=event.pk,
                path_kind=RaceEventPublicPathKind.CANONICAL,
            )
        )
        if (
            len(canonical) != 1
            or canonical[0].year != event.year
            or canonical[0].slug != event.slug
        ):
            errors.append(f"{action_id}:canonical_registry_mismatch")
        old = action["before"]
        legacy_count = RaceEventPublicPath.objects.filter(
            event_id=event.pk,
            path_kind=RaceEventPublicPathKind.LEGACY,
            year=old["public_year"],
            slug=old["slug"],
            manifest_sha256=loaded.manifest_sha256,
        ).count()
        if legacy_count != 1:
            errors.append(f"{action_id}:legacy_registry_mismatch")
        if _digest(_event_dependencies(event)) != _digest(
            action["dependency_snapshot"]
        ):
            errors.append(f"{action_id}:dependency_conservation_mismatch")

    mismatch_count = (
        RaceEvent.objects.filter(local_date__isnull=False)
        .exclude(year=models_year_expression())
        .count()
    )
    if mismatch_count:
        errors.append("global:natural_year_mismatch")
    linked_targets = HistoricalRaceEventTarget.objects.filter(event__isnull=False).select_related(
        "event"
    )
    if any(
        target.year != (target.event.edition_year or target.event.year)
        for target in linked_targets.iterator(chunk_size=500)
    ):
        errors.append("global:target_edition_mismatch")
    seen_series_editions: set[tuple[int, int]] = set()
    for event in RaceEvent.objects.filter(race_series__isnull=False).only(
        "id", "race_series_id", "year", "edition_year"
    ).iterator(chunk_size=500):
        identity = (event.race_series_id, event.edition_year or event.year)
        if identity in seen_series_editions:
            errors.append("global:duplicate_series_edition")
            break
        seen_series_editions.add(identity)
    if RaceEvent.objects.filter(year__gte=TEMPORARY_YEAR_MINIMUM).exists():
        errors.append("global:temporary_year_residue")
    result = {
        "schema_version": VERIFIER_SCHEMA,
        "manifest_sha256": loaded.manifest_sha256,
        "ok": not errors,
        "errors": sorted(set(errors)),
        "natural_year_mismatch_count": mismatch_count,
        "checked_action_count": len(actions),
    }
    result["verifier_result_sha256"] = _digest(result)
    return result


def verify_historical_race_calendar_integrity(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    artifact_root: str | Path | None = None,
    update_receipt: bool = False,
    _loaded: VerifiedManifest | None = None,
) -> dict[str, Any]:
    loaded = _loaded or _load_manifest(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        artifact_root=artifact_root,
    )
    with _read_only_snapshot():
        result = _verify_loaded_manifest(loaded)
    receipt_status = ""
    if update_receipt:
        with transaction.atomic():
            try:
                receipt = HistoricalRaceCalendarRepairReceipt.objects.select_for_update().get(
                    manifest_sha256=loaded.manifest_sha256
                )
            except HistoricalRaceCalendarRepairReceipt.DoesNotExist:
                _fail("verifier cannot update a missing receipt")
            if receipt.status == HistoricalRaceCalendarRepairReceiptStatus.ROLLED_BACK:
                _fail("verifier cannot rewrite a rolled-back receipt")
            receipt.status = (
                HistoricalRaceCalendarRepairReceiptStatus.VERIFIED
                if result["ok"]
                else HistoricalRaceCalendarRepairReceiptStatus.VERIFICATION_FAILED
            )
            receipt.verified_at = timezone.now()
            receipt.verifier_result_sha256 = result["verifier_result_sha256"]
            receipt.save(
                update_fields={
                    "status",
                    "verified_at",
                    "verifier_result_sha256",
                    "updated_at",
                }
            )
            receipt_status = receipt.status
    result["receipt_status"] = receipt_status
    return result


def _load_rollback(
    *,
    rollback_path: str | Path,
    expected_rollback_sha256: str,
    loaded: VerifiedManifest,
) -> FrozenJson:
    frozen = _load_json(
        rollback_path,
        root=loaded.root,
        label="rollback artifact",
        expected_sha256=expected_rollback_sha256,
    )
    return _validate_rollback_frozen(frozen=frozen, loaded=loaded)


def _validate_rollback_frozen(
    *, frozen: FrozenJson, loaded: VerifiedManifest
) -> FrozenJson:
    payload = frozen.payload
    if (
        payload.get("schema_version") != ROLLBACK_SCHEMA
        or payload.get("manifest_sha256") != loaded.manifest_sha256
        or payload.get("action_scope_sha256")
        != loaded.manifest["action_scope_sha256"]
        or not isinstance(payload.get("rows"), list)
    ):
        _fail("rollback artifact does not bind the exact apply scope")
    return frozen


def rollback_historical_race_calendar_integrity(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    approval_path: str | Path,
    expected_approval_sha256: str,
    maintenance_evidence_path: str | Path,
    expected_maintenance_evidence_sha256: str,
    rollback_path: str | Path,
    expected_rollback_sha256: str,
    actor: Any,
    artifact_root: str | Path | None = None,
    confirm_reviewed_artifact: bool,
) -> dict[str, Any]:
    _require_historical_backfill_enabled()
    if not confirm_reviewed_artifact:
        _fail("rollback requires --confirm-reviewed-artifact")
    loaded = _load_manifest(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        artifact_root=artifact_root,
    )
    approval = _validate_approval(
        approval_path=approval_path,
        expected_approval_sha256=expected_approval_sha256,
        loaded=loaded,
        actor=actor,
    )
    require_exact_active_gate(
        manifest_sha256=loaded.manifest_sha256,
        action_scope_sha256=loaded.manifest["action_scope_sha256"],
        actor=actor,
    )
    _validate_maintenance(
        path=maintenance_evidence_path,
        expected_sha256=expected_maintenance_evidence_sha256,
        loaded=loaded,
    )
    rollback = _load_rollback(
        rollback_path=rollback_path,
        expected_rollback_sha256=expected_rollback_sha256,
        loaded=loaded,
    )
    try:
        receipt = HistoricalRaceCalendarRepairReceipt.objects.get(
            manifest_sha256=loaded.manifest_sha256
        )
    except HistoricalRaceCalendarRepairReceipt.DoesNotExist:
        _fail("rollback receipt is missing")
    if receipt.status == HistoricalRaceCalendarRepairReceiptStatus.ROLLED_BACK:
        return {"status": "already_rolled_back", "receipt_id": receipt.pk}
    if (
        receipt.approval_sha256 != approval.sha256
        or receipt.rollback_sha256 != rollback.sha256
        or receipt.actor_id != actor.pk
    ):
        _fail("rollback identity does not match the apply receipt")
    rows = rollback.payload["rows"]
    with transaction.atomic():
        _advisory_lock(loaded.manifest_sha256)
        require_exact_active_gate(
            manifest_sha256=loaded.manifest_sha256,
            action_scope_sha256=loaded.manifest["action_scope_sha256"],
            actor=actor,
        )
        _lock_scope(loaded.manifest["actions"])
        receipt = HistoricalRaceCalendarRepairReceipt.objects.select_for_update().get(
            pk=receipt.pk
        )
        for row in rows:
            action_id = row.get("action_id", "unknown")
            try:
                event = RaceEvent.objects.get(pk=row["event_id"])
                canonical = RaceEventPublicPath.objects.get(
                    pk=row["canonical_path_id"]
                )
                legacy = RaceEventPublicPath.objects.get(pk=row["legacy_path_id"])
            except (
                KeyError,
                RaceEvent.DoesNotExist,
                RaceEventPublicPath.DoesNotExist,
            ):
                _fail(f"rollback current state drift for {action_id}")
            if (
                _digest(_model_payload(event)) != _digest(row["event_after"])
                or _digest(_model_payload(canonical))
                != _digest(row["canonical_path_after"])
                or _digest(_model_payload(legacy)) != _digest(row["legacy_path"])
                or _digest(
                    [
                        _model_payload(target)
                        for target in HistoricalRaceEventTarget.objects.filter(
                            event_id=event.pk
                        ).order_by("pk")
                    ]
                )
                != _digest(row["targets_after"])
                or _digest(_event_dependencies(event))
                != row["dependencies_sha256"]
            ):
                _fail(f"rollback current state drift for {action_id}")
        with _verified_repair_writer(
            manifest_sha256=loaded.manifest_sha256,
            action_scope_sha256=loaded.manifest["action_scope_sha256"],
        ):
            for row in reversed(rows):
                RaceEventPublicPath.objects.filter(pk=row["legacy_path_id"]).delete()
                for target_before in row["targets_before"]:
                    HistoricalRaceEventTarget.objects.filter(
                        pk=target_before["id"]
                    ).update(
                        **{
                            key: value
                            for key, value in target_before.items()
                            if key not in {"id", "created_at", "updated_at"}
                        },
                        updated_at=timezone.now(),
                    )
                canonical_before = row["canonical_path_before"]
                RaceEventPublicPath.objects.filter(pk=row["canonical_path_id"]).update(
                    **{
                        key: value
                        for key, value in canonical_before.items()
                        if key not in {"id", "created_at", "updated_at"}
                    },
                    updated_at=timezone.now(),
                )
                event_before = row["event_before"]
                # Exact rollback payload was hash-checked above. Use the base
                # manager here because the pre-Release-A state can intentionally
                # violate the new identity contract and is the only state this
                # private, manifest-bound repair path may restore.
                RaceEvent._base_manager.filter(pk=row["event_id"]).update(
                    **{
                        key: value
                        for key, value in event_before.items()
                        if key not in {"id", "created_at", "updated_at"}
                    },
                    updated_at=timezone.now(),
                )
        receipt.status = HistoricalRaceCalendarRepairReceiptStatus.ROLLED_BACK
        receipt.rolled_back_at = timezone.now()
        receipt.save(update_fields={"status", "rolled_back_at", "updated_at"})
        transaction.on_commit(invalidate_public_race_cache)
    return {
        "status": "rolled_back",
        "receipt_id": receipt.pk,
        "rollback_sha256": rollback.sha256,
    }
