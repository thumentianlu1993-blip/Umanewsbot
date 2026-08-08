from __future__ import annotations

import os
import shutil
import tempfile
from collections import defaultdict
from datetime import timezone as dt_timezone
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from stable.models import (
    HistoricalRaceCalendarRepairReceipt,
    HistoricalRaceCalendarRepairReceiptStatus,
    HistoricalRaceEventTarget,
    RaceEvent,
    RaceEventPublicPath,
    RaceEventProductCanonicalLink,
    RaceSeries,
)
from stable.services.historical_race_calendar_admission import (
    _verified_repair_writer,
    require_exact_active_gate,
)
from stable.services.historical_race_calendar_integrity import (
    MAINTENANCE_SCHEMA,
    REQUIRED_MAINTENANCE_CHECKS,
    _advisory_lock,
    _canonical_bytes,
    _code_identity,
    _controlled_path,
    _controlled_root,
    _database_snapshot_id,
    _digest,
    _load_json,
    _model_payload,
    _read_only_snapshot,
    _read_regular_file,
    _row_identity,
    _rows_identity,
    _sha256_bytes,
    _write_new_file,
    _aware_timestamp,
)
from stable.services.race_event_public_cache import invalidate_public_race_cache
from stable.services.race_event_years import validate_authority_url
from stable.services.race_series_identity_review import _publish_directory_no_replace


MANIFEST_SCHEMA_V2 = "historical-race-calendar-integrity-manifest.v2"
REVIEW_SCHEMA_V2 = "historical-race-calendar-integrity-review.v2"
APPROVAL_SCHEMA_V2 = "historical-race-calendar-integrity-approval.v2"
LEDGER_KEYS = {
    "managed_targets_and_paths",
    "managed_canonical_links",
    "immutable_reverse_dependencies",
}
ALLOWED_OPERATIONS_V2 = {
    "collapse_exact_duplicate_boundary",
    "rotate_ordinary_season_chain",
    "preserve_cross_year_edition",
    "reassign_targets_paths",
}
ROLLBACK_SCHEMA_V2 = "historical-race-calendar-integrity-rollback.v2"
MANIFEST_SHA256_SENTINEL = "__RELEASE_B_MANIFEST_SHA256__"


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _stable_timestamp(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    return (
        _aware_timestamp(value, label=label)
        .astimezone(dt_timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _serialized_payload(instance: Any) -> dict[str, Any]:
    return {
        field.attname: _json_value(getattr(instance, field.attname))
        for field in instance._meta.concrete_fields
    }


def _scope_ids(actions: list[dict[str, Any]]) -> dict[str, list[int]]:
    return {
        "series_ids": sorted({int(action["series_id"]) for action in actions}),
        "event_ids": sorted(
            {
                int(row["id"])
                for action in actions
                for row in action["events"]
            }
        ),
        "target_ids": sorted(
            {
                int(row["payload"]["id"])
                for action in actions
                for row in action["ledgers"]["managed_targets_and_paths"]["targets"]
            }
        ),
        "path_ids": sorted(
            {
                int(row["payload"]["id"])
                for action in actions
                for row in action["ledgers"]["managed_targets_and_paths"]["paths"]
            }
        ),
    }


def _scope_snapshot(actions: list[dict[str, Any]]) -> dict[str, Any]:
    ids = _scope_ids(actions)
    event_ids = ids["event_ids"]
    events = list(RaceEvent._base_manager.filter(pk__in=event_ids).order_by("pk"))
    targets = list(
        HistoricalRaceEventTarget._base_manager.filter(
            pk__in=ids["target_ids"]
        ).order_by("pk")
    )
    paths = list(
        RaceEventPublicPath._base_manager.filter(pk__in=ids["path_ids"]).order_by("pk")
    )
    links = list(
        RaceEventProductCanonicalLink._base_manager.filter(
            Q(duplicate_event_id__in=event_ids) | Q(canonical_event_id__in=event_ids)
        )
        .distinct()
        .order_by("pk")
    )
    payload = {
        "scope": ids,
        "events": [_serialized_payload(row) for row in events],
        "targets": [_serialized_payload(row) for row in targets],
        "paths": [_serialized_payload(row) for row in paths],
        "canonical_links": [_serialized_payload(row) for row in links],
        "immutable_reverse_dependencies": _immutable_dependencies_for_events(events),
    }
    return {"payload": payload, "sha256": _digest(payload)}


def _restore_values(model, payload: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in model._meta.concrete_fields:
        if field.primary_key:
            continue
        value = payload[field.attname]
        values[field.attname] = None if value is None else field.to_python(value)
    return values


def _code_identity_v2() -> dict[str, str]:
    identity = dict(_code_identity())
    identity["v2_tool_source_sha256"] = _sha256_bytes(
        _read_regular_file(Path(__file__), label="release b repair service source")
    )
    return identity


def _relation_key(relation) -> str:
    return ":".join(
        (
            relation.related_model._meta.label_lower,
            relation.get_accessor_name(),
            relation.field.name,
        )
    )


def _immutable_dependencies_for_events(events: list[RaceEvent]) -> dict[str, Any]:
    excluded_models = {
        HistoricalRaceEventTarget,
        RaceEventPublicPath,
        RaceEventProductCanonicalLink,
    }
    relation_rows: dict[str, dict[int, Any]] = defaultdict(dict)
    event_ids = [event.pk for event in events]
    for relation in sorted(
        events[0]._meta.related_objects if events else [],
        key=lambda item: (
            item.related_model._meta.label_lower,
            item.get_accessor_name(),
            item.field.name,
        ),
    ):
        if relation.many_to_many or relation.related_model in excluded_models:
            continue
        queryset = relation.related_model._base_manager.filter(
            **{f"{relation.field.name}__in": event_ids}
        ).order_by("pk")
        for row in queryset:
            relation_rows[_relation_key(relation)][row.pk] = row
    result = {}
    for key, rows in sorted(relation_rows.items()):
        ordered = [rows[pk] for pk in sorted(rows)]
        result[key] = {
            **_rows_identity(ordered),
            "rows": [
                {
                    "payload": _serialized_payload(row),
                    "sha256": _digest(_serialized_payload(row)),
                }
                for row in ordered
            ],
        }
    return result


def _lock_immutable_dependencies(events: list[RaceEvent]) -> None:
    excluded_models = {
        HistoricalRaceEventTarget,
        RaceEventPublicPath,
        RaceEventProductCanonicalLink,
    }
    event_ids = [event.pk for event in events]
    for relation in sorted(
        events[0]._meta.related_objects if events else [],
        key=lambda item: (
            item.related_model._meta.label_lower,
            item.get_accessor_name(),
            item.field.name,
        ),
    ):
        if relation.many_to_many or relation.related_model in excluded_models:
            continue
        list(
            relation.related_model._base_manager.select_for_update()
            .filter(**{f"{relation.field.name}__in": event_ids})
            .order_by("pk")
        )


def _series_contexts(
    series_ids: list[int],
) -> tuple[dict[int, dict[str, Any]], dict[int, list[RaceEvent]]]:
    events = list(
        RaceEvent._base_manager.filter(race_series_id__in=series_ids).order_by("pk")
    )
    events_by_series: dict[int, list[RaceEvent]] = defaultdict(list)
    event_to_series: dict[int, int] = {}
    for event in events:
        events_by_series[event.race_series_id].append(event)
        event_to_series[event.pk] = event.race_series_id
    event_ids = [event.pk for event in events]
    targets = list(
        HistoricalRaceEventTarget._base_manager.filter(
            race_series_id__in=series_ids
        ).order_by("pk")
    )
    paths = list(
        RaceEventPublicPath._base_manager.filter(event_id__in=event_ids).order_by("pk")
    )
    links = list(
        RaceEventProductCanonicalLink._base_manager.filter(
            Q(duplicate_event_id__in=event_ids) | Q(canonical_event_id__in=event_ids)
        )
        .distinct()
        .order_by("pk")
    )
    targets_by_series: dict[int, list[Any]] = defaultdict(list)
    paths_by_series: dict[int, list[Any]] = defaultdict(list)
    links_by_series: dict[int, dict[int, Any]] = defaultdict(dict)
    for row in targets:
        targets_by_series[row.race_series_id].append(row)
    for row in paths:
        paths_by_series[event_to_series[row.event_id]].append(row)
    for row in links:
        endpoint_series = {
            event_to_series[event_id]
            for event_id in (row.duplicate_event_id, row.canonical_event_id)
            if event_id in event_to_series
        }
        for series_id in endpoint_series:
            links_by_series[series_id][row.pk] = row

    excluded_models = {
        HistoricalRaceEventTarget,
        RaceEventPublicPath,
        RaceEventProductCanonicalLink,
    }
    dependency_rows: dict[int, dict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for relation in sorted(
        events[0]._meta.related_objects if events else [],
        key=lambda item: (
            item.related_model._meta.label_lower,
            item.get_accessor_name(),
            item.field.name,
        ),
    ):
        if relation.many_to_many or relation.related_model in excluded_models:
            continue
        for row in relation.related_model._base_manager.filter(
            **{f"{relation.field.name}__in": event_ids}
        ).order_by("pk"):
            event_id = getattr(row, relation.field.attname)
            dependency_rows[event_to_series[event_id]][_relation_key(relation)].append(row)

    ledgers: dict[int, dict[str, Any]] = {}
    for series_id in series_ids:
        immutable = {}
        for key, rows in sorted(dependency_rows[series_id].items()):
            immutable[key] = {
                **_rows_identity(rows),
                "rows": [
                    {
                        "payload": _serialized_payload(row),
                        "sha256": _digest(_serialized_payload(row)),
                    }
                    for row in rows
                ],
            }
        ledger = {
            "managed_targets_and_paths": {
                "targets": [_row_identity(row) for row in targets_by_series[series_id]],
                "paths": [_row_identity(row) for row in paths_by_series[series_id]],
            },
            "managed_canonical_links": [
                _row_identity(links_by_series[series_id][pk])
                for pk in sorted(links_by_series[series_id])
            ],
            "immutable_reverse_dependencies": immutable,
        }
        if set(ledger) != LEDGER_KEYS:
            raise RuntimeError("release_b_ledger_partition_incomplete")
        ledgers[series_id] = ledger
    return ledgers, events_by_series


def enumerate_series_ledgers(series_id: int) -> dict[str, Any]:
    ledgers, _ = _series_contexts([series_id])
    return ledgers[series_id]


def _event_snapshot(event: RaceEvent) -> dict[str, Any]:
    return {
        "id": event.pk,
        "year": event.year,
        "edition_year": event.edition_year,
        "slug": event.slug,
        "local_date": event.local_date.isoformat() if event.local_date else None,
        "visibility_status": event.visibility_status,
        "race_series_id": event.race_series_id,
        "country_region": event.country_region,
        "source_refs_sha256": _digest(event.source_refs),
    }


def _official_result_identity(source_refs: Any) -> dict[str, str] | None:
    if not isinstance(source_refs, dict):
        return None
    discovery = source_refs.get("detail_discovery")
    if not isinstance(discovery, dict):
        return None
    urls = discovery.get("urls")
    if not isinstance(urls, dict):
        return None
    result = urls.get("result_url")
    if not isinstance(result, dict):
        return None
    if str(result.get("source_authority") or "").strip().casefold() != "official":
        return None
    source_provider = str(result.get("source_provider") or "").strip().casefold()
    if not source_provider:
        return None
    try:
        parsed = validate_authority_url(result.get("url"))
    except ValidationError:
        return None
    official_url = parsed.geturl()
    approved_sources = discovery.get("approved_detail_sources")
    if not isinstance(approved_sources, list):
        return None
    approved_matches = [
        source
        for source in approved_sources
        if isinstance(source, dict)
        and str(source.get("source_authority") or "").strip().casefold()
        == "official"
        and str(source.get("source_provider") or "").strip().casefold()
        == source_provider
        and str(source.get("url") or "").strip() == official_url
    ]
    if len(approved_matches) != 1:
        return None
    cache_identity = approved_matches[0].get("source_cache_identity")
    content_sha256 = (
        str(cache_identity.get("sha256") or "").strip().casefold()
        if isinstance(cache_identity, dict)
        else ""
    )
    if len(content_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in content_sha256
    ):
        return None
    return {
        "source_provider": source_provider,
        "url": official_url,
        "content_sha256": content_sha256,
    }


def _duplicate_identity_sha256(event: RaceEvent) -> str:
    runner_fields = (
        "sort_order",
        "horse_number",
        "horse_name",
        "jockey_name",
        "trainer_name",
        "barrier",
        "carried_weight",
        "running_status",
    )
    result_fields = (
        "finish_position",
        "official_finish_position",
        "horse_number",
        "horse_name",
        "jockey_name",
        "trainer_name",
        "barrier",
        "carried_weight",
        "running_status",
    )
    official_result_identity = _official_result_identity(event.source_refs)
    core = {
        "country_region": event.country_region,
        "racecourse": " ".join(event.racecourse.casefold().split()),
        "grade_text": " ".join(event.grade_text.casefold().split()),
        "normalized_grade": event.normalized_grade,
        "surface": event.surface,
        "distance_text": " ".join(event.distance_text.casefold().split()),
        "local_date": event.local_date.isoformat() if event.local_date else None,
    }
    if official_result_identity is None:
        core.update(
            {
                "original_name": " ".join(event.original_name.casefold().split()),
                "source_refs_sha256": _digest(event.source_refs),
            }
        )
    else:
        core["official_result_identity"] = official_result_identity
    payload = {
        "identity_contract": "official-result-or-strict-source-refs.v1",
        "core": core,
        "runners": list(event.runners.order_by(*runner_fields).values(*runner_fields)),
        "results": list(event.results.order_by(*result_fields).values(*result_fields)),
    }
    return _digest(payload)


def _series_action(
    series_id: int,
    *,
    events: list[RaceEvent] | None = None,
    ledgers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = events or list(
        RaceEvent._base_manager.filter(race_series_id=series_id).order_by("pk")
    )
    events = sorted(
        events,
        key=lambda row: (
            row.local_date is None,
            row.local_date,
            row.edition_year is None,
            row.edition_year,
            row.year,
            row.pk,
        ),
    )
    event_snapshots = [_event_snapshot(event) for event in events]
    mismatch_event_ids = sorted(
        event.pk
        for event in events
        if event.local_date is not None and event.year != event.local_date.year
    )
    by_local_date: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if event.local_date is not None:
            by_local_date[event.local_date.isoformat()].append(event.pk)
    events_by_id = {event.pk: event for event in events}
    duplicate_groups = [
        {
            "local_date": local_date,
            "event_ids": sorted(ids),
            "identity_sha256_by_event": {
                str(event_id): _duplicate_identity_sha256(events_by_id[event_id])
                for event_id in sorted(ids)
            },
        }
        for local_date, ids in sorted(by_local_date.items())
        if len(ids) > 1
    ]
    ledgers = ledgers or enumerate_series_ledgers(series_id)
    precondition_payload = {
        "events": event_snapshots,
        "ledgers": ledgers,
    }
    block_reasons = ["reviewed_overlay_required"]
    if duplicate_groups:
        block_reasons.append("duplicate_equivalence_review_required")
    return {
        "action_id": f"series-{series_id}",
        "series_id": series_id,
        "events": event_snapshots,
        "mismatch_event_ids": mismatch_event_ids,
        "duplicate_groups": duplicate_groups,
        "ledgers": ledgers,
        "series_precondition_sha256": _digest(precondition_payload),
        "disposition": "block",
        "operations": [],
        "block_reasons": block_reasons,
    }


def build_release_b_series_actions() -> list[dict[str, Any]]:
    mismatch_rows = list(
        RaceEvent._base_manager.filter(local_date__isnull=False)
        .order_by("race_series_id", "pk")
        .only("pk", "year", "local_date", "race_series_id")
    )
    series_ids = sorted(
        {
            row.race_series_id
            for row in mismatch_rows
            if row.race_series_id is not None and row.year != row.local_date.year
        }
    )
    ledgers, events_by_series = _series_contexts(series_ids)
    actions = [
        _series_action(
            series_id,
            events=events_by_series[series_id],
            ledgers=ledgers[series_id],
        )
        for series_id in series_ids
    ]
    for row in mismatch_rows:
        if row.year == row.local_date.year or row.race_series_id is not None:
            continue
        actions.append(
            {
                "action_id": f"event-{row.pk}",
                "series_id": None,
                "events": [_event_snapshot(RaceEvent._base_manager.get(pk=row.pk))],
                "mismatch_event_ids": [row.pk],
                "duplicate_groups": [],
                "ledgers": None,
                "series_precondition_sha256": "",
                "disposition": "block",
                "operations": [],
                "block_reasons": ["race_series_required"],
            }
        )
    return sorted(actions, key=lambda row: row["action_id"])


def prepare_release_b_series_census(
    *,
    output_dir: str | Path,
    artifact_root: str | Path | None,
    all_regions: bool,
) -> dict[str, Any]:
    if not all_regions:
        raise ValueError("release_b_prepare_requires_all_regions")
    root = _controlled_root(artifact_root, create=True)
    destination = _controlled_path(
        output_dir,
        root=root,
        must_exist=False,
        direct_child=True,
    )
    if os.path.lexists(destination):
        raise ValueError("release_b_prepare_output_exists")
    temporary = Path(tempfile.mkdtemp(prefix=".prepare-b-", dir=root))
    try:
        with _read_only_snapshot():
            actions = build_release_b_series_actions()
            generated_at = timezone.now().astimezone(dt_timezone.utc).isoformat()
            action_scope_sha256 = release_b_action_scope_sha256(actions)
            census = {
                "schema_version": MANIFEST_SCHEMA_V2,
                "generated_at": generated_at,
                "database_snapshot": _database_snapshot_id(),
                "code_identity": _code_identity_v2(),
                "scope": "all_regions_all_years_by_series",
                "actions": actions,
            }
            review = {
                "schema_version": REVIEW_SCHEMA_V2,
                "status": "pending",
                # The census manifest digest cannot be known until every
                # artifact (including this template) has been written.  Leave
                # the one parser-supported binding field for the reviewer to
                # fill together with status/operations/reviewed.
                "census_manifest_sha256": "",
                "actions": [
                    {
                        "action_id": action["action_id"],
                        "operations": [],
                        "reviewed": None,
                    }
                    for action in actions
                ],
            }
            summary = {
                "schema_version": MANIFEST_SCHEMA_V2,
                "series_action_count": sum(
                    action["series_id"] is not None for action in actions
                ),
                "unscoped_event_action_count": sum(
                    action["series_id"] is None for action in actions
                ),
                "mismatch_count": sum(
                    len(action["mismatch_event_ids"]) for action in actions
                ),
                "duplicate_boundary_count": sum(
                    len(action["duplicate_groups"]) for action in actions
                ),
                "executable_action_count": 0,
                "action_scope_sha256": action_scope_sha256,
            }
            artifacts = {
                "census.json": _canonical_bytes(census),
                "review.template.json": _canonical_bytes(review),
                "summary.json": _canonical_bytes(summary),
            }
            for name, payload in artifacts.items():
                _write_new_file(temporary / name, payload)
            manifest = {
                **census,
                "action_scope_sha256": action_scope_sha256,
                "artifacts": {
                    name: {
                        "path": name,
                        "size": len(payload),
                        "sha256": _sha256_bytes(payload),
                    }
                    for name, payload in sorted(artifacts.items())
                },
            }
            manifest_bytes = _canonical_bytes(manifest)
            _write_new_file(temporary / "manifest.json", manifest_bytes)
            manifest_sha256 = _sha256_bytes(manifest_bytes)
        _publish_directory_no_replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "status": "prepared_v2",
        "output_dir": str(destination),
        "manifest_path": str(destination / "manifest.json"),
        "manifest_sha256": manifest_sha256,
        "action_scope_sha256": action_scope_sha256,
        **summary,
    }


def prepare_reviewed_release_b_manifest(
    *,
    census_manifest_path: str | Path,
    expected_census_manifest_sha256: str,
    review_overlay_path: str | Path,
    expected_review_overlay_sha256: str,
    output_dir: str | Path,
    artifact_root: str | Path | None,
) -> dict[str, Any]:
    root = _controlled_root(artifact_root)
    census = _load_json(
        census_manifest_path,
        root=root,
        label="release b census manifest",
        expected_sha256=expected_census_manifest_sha256,
    )
    manifest = census.payload
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_V2
        or manifest.get("code_identity") != _code_identity_v2()
        or manifest.get("scope") != "all_regions_all_years_by_series"
        or not isinstance(manifest.get("actions"), list)
    ):
        raise ValueError("release_b_census_manifest_invalid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "census.json",
        "review.template.json",
        "summary.json",
    }:
        raise ValueError("release_b_census_artifacts_invalid")
    census_dir = census.path.parent
    for name, identity in artifacts.items():
        payload = _read_regular_file(
            census_dir / name,
            label=f"release b census artifact {name}",
            root=root,
        )
        if (
            not isinstance(identity, dict)
            or identity.get("path") != name
            or identity.get("size") != len(payload)
            or identity.get("sha256") != _sha256_bytes(payload)
        ):
            raise ValueError("release_b_census_artifact_drift")
    if manifest.get("action_scope_sha256") != release_b_action_scope_sha256(
        manifest["actions"]
    ):
        raise ValueError("release_b_census_scope_invalid")

    overlay = _load_json(
        review_overlay_path,
        root=root,
        label="release b review overlay",
        expected_sha256=expected_review_overlay_sha256,
    )
    review = overlay.payload
    if (
        review.get("schema_version") != REVIEW_SCHEMA_V2
        or review.get("status") != "reviewed"
        or review.get("census_manifest_sha256") != census.sha256
        or not isinstance(review.get("actions"), list)
    ):
        raise ValueError("release_b_review_overlay_invalid")
    census_by_id = {row["action_id"]: row for row in manifest["actions"]}
    overlay_ids = [row.get("action_id") for row in review["actions"]]
    if overlay_ids != sorted(census_by_id) or len(overlay_ids) != len(set(overlay_ids)):
        raise ValueError("release_b_review_action_scope_mismatch")
    reviewed_actions = []
    for overlay_row in review["actions"]:
        if set(overlay_row) != {"action_id", "operations", "reviewed"}:
            raise ValueError("release_b_review_action_fields_invalid")
        original = census_by_id[overlay_row["action_id"]]
        if original.get("series_id") is None:
            raise ValueError("release_b_unscoped_event_cannot_be_approved")
        merged = {
            **original,
            "disposition": "action",
            "operations": overlay_row["operations"],
            "reviewed": overlay_row["reviewed"],
            "block_reasons": [],
        }
        _validate_reviewed_action(merged)
        reviewed_actions.append(merged)
    reviewed_scope = release_b_action_scope_sha256(reviewed_actions)
    destination = _controlled_path(
        output_dir,
        root=root,
        must_exist=False,
        direct_child=True,
    )
    if os.path.lexists(destination):
        raise ValueError("release_b_reviewed_output_exists")
    temporary = Path(tempfile.mkdtemp(prefix=".reviewed-b-", dir=root))
    try:
        census_bytes = _read_regular_file(
            census.path,
            label="release b census manifest",
            root=root,
        )
        review_bytes = _read_regular_file(
            overlay.path,
            label="release b review overlay",
            root=root,
        )
        summary = {
            "schema_version": MANIFEST_SCHEMA_V2,
            "executable_action_count": len(reviewed_actions),
            "series_ids": [row["series_id"] for row in reviewed_actions],
            "action_scope_sha256": reviewed_scope,
        }
        bound_artifacts = {
            "census.manifest.json": census_bytes,
            "review.json": review_bytes,
            "summary.json": _canonical_bytes(summary),
        }
        for name, payload in bound_artifacts.items():
            _write_new_file(temporary / name, payload)
        reviewed_manifest = {
            "schema_version": MANIFEST_SCHEMA_V2,
            "generated_at": timezone.now().astimezone(dt_timezone.utc).isoformat(),
            "code_identity": _code_identity_v2(),
            "scope": "reviewed_series_actions",
            "census_manifest_sha256": census.sha256,
            "review_overlay_sha256": overlay.sha256,
            "action_scope_sha256": reviewed_scope,
            "actions": reviewed_actions,
            "artifacts": {
                name: {
                    "path": name,
                    "size": len(payload),
                    "sha256": _sha256_bytes(payload),
                }
                for name, payload in sorted(bound_artifacts.items())
            },
        }
        manifest_bytes = _canonical_bytes(reviewed_manifest)
        _write_new_file(temporary / "manifest.json", manifest_bytes)
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        approval_template = {
            "schema_version": "historical-race-calendar-integrity-approval.v2",
            "status": "pending",
            "manifest_sha256": manifest_sha256,
            "action_scope_sha256": reviewed_scope,
            "approved_action_ids": [row["action_id"] for row in reviewed_actions],
            "approved_by": "",
            "approved_at": "",
            "actor": "",
        }
        _write_new_file(
            temporary / "approval.template.json",
            _canonical_bytes(approval_template),
        )
        _publish_directory_no_replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "status": "reviewed_v2",
        "output_dir": str(destination),
        "manifest_path": str(destination / "manifest.json"),
        "manifest_sha256": manifest_sha256,
        "action_scope_sha256": reviewed_scope,
        "executable_action_count": len(reviewed_actions),
    }


def validate_target_supersession_overlay(rows: Iterable[dict[str, Any]]) -> None:
    targets = {int(row["id"]): row for row in rows}
    for target_id, row in targets.items():
        status = row.get("resolution_status")
        survivor_id = row.get("superseded_by_id")
        if status != "superseded":
            if survivor_id is not None:
                raise ValueError("active_target_cannot_have_superseded_by")
            continue
        if not isinstance(survivor_id, int) or survivor_id == target_id:
            raise ValueError("target_supersession_survivor_required")
        survivor = targets.get(survivor_id)
        if survivor is None:
            raise ValueError("target_supersession_survivor_out_of_scope")
        if survivor.get("race_series_id") != row.get("race_series_id"):
            raise ValueError("target_supersession_series_mismatch")
        if survivor.get("year") != row.get("year"):
            raise ValueError("target_supersession_edition_mismatch")
        if survivor.get("resolution_status") == "superseded" or survivor.get(
            "superseded_by_id"
        ) is not None:
            raise ValueError("target_supersession_chain_forbidden")


def release_b_action_scope_sha256(actions: list[dict[str, Any]]) -> str:
    return _digest(
        [
            {
                "action_id": action.get("action_id"),
                "series_id": action.get("series_id"),
                "series_precondition_sha256": action.get(
                    "series_precondition_sha256"
                ),
                "operations": action.get("operations"),
                "reviewed": action.get("reviewed"),
            }
            for action in actions
        ]
    )


def _validate_reviewed_action(action: dict[str, Any]) -> dict[str, Any]:
    if action.get("disposition") != "action" or action.get("block_reasons"):
        raise ValueError("reviewed_action_not_executable")
    series_id = action.get("series_id")
    if not isinstance(series_id, int):
        raise ValueError("reviewed_action_series_required")
    operations = action.get("operations")
    if (
        not isinstance(operations, list)
        or not operations
        or len(operations) != len(set(operations))
        or not set(operations).issubset(ALLOWED_OPERATIONS_V2)
    ):
        raise ValueError("reviewed_action_operations_invalid")
    current = _series_action(series_id)
    if current["series_precondition_sha256"] != action.get(
        "series_precondition_sha256"
    ):
        raise ValueError("reviewed_action_precondition_drift")
    reviewed = action.get("reviewed")
    if not isinstance(reviewed, dict):
        raise ValueError("reviewed_overlay_required")
    if set(reviewed) != {
        "events",
        "targets",
        "paths",
        "canonical_links",
        "duplicate_boundaries",
        "dependency_policies",
    }:
        raise ValueError("reviewed_overlay_fields_incomplete")

    current_event_ids = {row["id"] for row in current["events"]}
    final_events = reviewed["events"]
    if not isinstance(final_events, list) or {
        row.get("id") for row in final_events if isinstance(row, dict)
    } != current_event_ids:
        raise ValueError("reviewed_event_scope_mismatch")
    required_event_fields = {
        "id",
        "year",
        "edition_year",
        "slug",
        "race_series_id",
        "visibility_status",
    }
    if any(not isinstance(row, dict) or set(row) != required_event_fields for row in final_events):
        raise ValueError("reviewed_event_fields_invalid")
    if any(
        not isinstance(row["year"], int)
        or not 1 <= row["year"] <= 32767
        or (
            row["edition_year"] is not None
            and (
                not isinstance(row["edition_year"], int)
                or not 1 <= row["edition_year"] <= 32767
            )
        )
        or not isinstance(row["slug"], str)
        or not row["slug"]
        or row["visibility_status"] not in {"draft", "published", "hidden"}
        or row["race_series_id"] not in {series_id, None}
        for row in final_events
    ):
        raise ValueError("reviewed_event_values_invalid")
    path_keys = [(row["year"], row["slug"]) for row in final_events]
    if len(path_keys) != len(set(path_keys)):
        raise ValueError("reviewed_event_path_collision")
    edition_keys = [
        (row["race_series_id"], row["edition_year"])
        for row in final_events
        if row["race_series_id"] is not None and row["edition_year"] is not None
    ]
    if len(edition_keys) != len(set(edition_keys)):
        raise ValueError("reviewed_series_edition_collision")

    targets = reviewed["targets"]
    current_target_ids = {
        row["payload"]["id"]
        for row in current["ledgers"]["managed_targets_and_paths"]["targets"]
    }
    if not isinstance(targets, list) or {
        row.get("id") for row in targets if isinstance(row, dict)
    } != current_target_ids:
        raise ValueError("reviewed_target_scope_mismatch")
    required_target_fields = {
        "id",
        "race_series_id",
        "year",
        "event_id",
        "resolution_status",
        "superseded_by_id",
        "superseded_at",
        "supersession_manifest_sha256",
    }
    if any(
        not isinstance(row, dict)
        or set(row) != required_target_fields
        for row in targets
    ):
        raise ValueError("reviewed_target_fields_invalid")
    validate_target_supersession_overlay(targets)
    final_events_by_id = {row["id"]: row for row in final_events}
    valid_target_statuses = {
        value
        for value, _label in HistoricalRaceEventTarget._meta.get_field(
            "resolution_status"
        ).flatchoices
    }
    assigned_event_ids: list[int] = []
    active_target_keys: list[tuple[int, int]] = []
    for row in targets:
        event_id = row["event_id"]
        if row["resolution_status"] not in valid_target_statuses:
            raise ValueError("reviewed_target_resolution_status_invalid")
        if row["race_series_id"] != series_id:
            raise ValueError("reviewed_target_series_mismatch")
        if row["resolution_status"] == "superseded":
            if event_id is not None:
                raise ValueError("reviewed_superseded_target_has_event")
            if (
                not row["superseded_at"]
                or row["supersession_manifest_sha256"]
                != MANIFEST_SHA256_SENTINEL
            ):
                raise ValueError("reviewed_superseded_target_audit_invalid")
            _aware_timestamp(
                row["superseded_at"], label="release b target superseded_at"
            )
        elif (
            row["superseded_by_id"] is not None
            or row["superseded_at"] is not None
            or row["supersession_manifest_sha256"]
        ):
            raise ValueError("reviewed_active_target_supersession_audit_invalid")
        if row["resolution_status"] == "imported" and event_id is None:
            raise ValueError("reviewed_imported_target_event_required")
        if event_id is not None:
            event = final_events_by_id.get(event_id)
            if event is None:
                raise ValueError("reviewed_target_event_out_of_scope")
            edition_year = event["edition_year"] or event["year"]
            if event["race_series_id"] != series_id or edition_year != row["year"]:
                raise ValueError("reviewed_target_event_identity_mismatch")
            assigned_event_ids.append(event_id)
        if row["resolution_status"] != "superseded":
            active_target_keys.append((row["race_series_id"], row["year"]))
    if len(assigned_event_ids) != len(set(assigned_event_ids)):
        raise ValueError("reviewed_target_event_not_one_to_one")
    if len(active_target_keys) != len(set(active_target_keys)):
        raise ValueError("reviewed_active_target_collision")

    paths = reviewed["paths"]
    current_path_ids = {
        row["payload"]["id"]
        for row in current["ledgers"]["managed_targets_and_paths"]["paths"]
    }
    required_path_fields = {"id", "event_id", "year", "slug", "path_kind"}
    if (
        not isinstance(paths, list)
        or {row.get("id") for row in paths if isinstance(row, dict)} != current_path_ids
        or any(not isinstance(row, dict) or set(row) != required_path_fields for row in paths)
    ):
        raise ValueError("reviewed_path_scope_mismatch")
    final_path_keys = [(row["year"], row["slug"]) for row in paths]
    if len(final_path_keys) != len(set(final_path_keys)):
        raise ValueError("reviewed_registry_path_collision")
    if any(row["event_id"] not in current_event_ids for row in paths):
        raise ValueError("reviewed_path_owner_out_of_scope")
    for row in paths:
        if row["path_kind"] == "canonical":
            event = final_events_by_id[row["event_id"]]
            if (row["year"], row["slug"]) != (event["year"], event["slug"]):
                raise ValueError("reviewed_canonical_path_owner_mismatch")
        elif row["path_kind"] != "legacy":
            raise ValueError("reviewed_path_kind_invalid")
    event_ids = sorted(current_event_ids)
    path_ids = sorted(current_path_ids)
    for year, slug in path_keys:
        if RaceEvent._base_manager.filter(year=year, slug=slug).exclude(
            pk__in=event_ids
        ).exists():
            raise ValueError("reviewed_event_global_path_collision")
    for year, slug in final_path_keys:
        if RaceEventPublicPath._base_manager.filter(year=year, slug=slug).exclude(
            pk__in=path_ids
        ).exists():
            raise ValueError("reviewed_registry_global_path_collision")

    policies = reviewed["dependency_policies"]
    immutable = current["ledgers"]["immutable_reverse_dependencies"]
    if not isinstance(policies, dict) or set(policies) != set(immutable):
        raise ValueError("reviewed_dependency_policy_scope_mismatch")
    if any(value != "retain_on_tombstone" for value in policies.values()):
        raise ValueError("reviewed_dependency_policy_unsupported")

    links = reviewed["canonical_links"]
    required_link_fields = {
        "duplicate_event_id",
        "canonical_event_id",
        "identity_sha256",
        "is_active",
    }
    if not isinstance(links, list) or any(
        not isinstance(row, dict) or set(row) != required_link_fields for row in links
    ):
        raise ValueError("reviewed_canonical_link_fields_invalid")
    if any(row["is_active"] is not True for row in links):
        raise ValueError("reviewed_canonical_link_must_be_active")
    boundaries = reviewed["duplicate_boundaries"]
    required_boundary_fields = {
        "local_date",
        "event_ids",
        "identity_sha256_by_event",
        "survivor_event_id",
        "duplicate_event_ids",
        "decision",
        "rationale",
    }
    if not isinstance(boundaries, list) or any(
        not isinstance(row, dict) or set(row) != required_boundary_fields
        for row in boundaries
    ):
        raise ValueError("reviewed_duplicate_boundary_fields_invalid")
    expected_groups = {
        (row["local_date"], tuple(row["event_ids"])): row
        for row in current["duplicate_groups"]
    }
    reviewed_groups = {
        (row["local_date"], tuple(row["event_ids"])): row for row in boundaries
    }
    if set(reviewed_groups) != set(expected_groups):
        raise ValueError("reviewed_duplicate_boundary_scope_mismatch")
    links_by_pair = {
        (row["duplicate_event_id"], row["canonical_event_id"]): row for row in links
    }
    if len(links_by_pair) != len(links):
        raise ValueError("reviewed_canonical_link_duplicate_pair")
    expected_links_by_pair: dict[tuple[int, int], str] = {}
    for key, row in reviewed_groups.items():
        original = expected_groups[key]
        if row["identity_sha256_by_event"] != original["identity_sha256_by_event"]:
            raise ValueError("reviewed_duplicate_identity_drift")
        survivor_id = row["survivor_event_id"]
        duplicate_ids = row["duplicate_event_ids"]
        if (
            row["decision"] not in {"equivalent", "distinct"}
            or not isinstance(row["rationale"], str)
            or not row["rationale"].strip()
            or survivor_id not in row["event_ids"]
            or sorted(duplicate_ids)
            != sorted(set(row["event_ids"]) - {survivor_id})
        ):
            raise ValueError("reviewed_duplicate_boundary_decision_invalid")
        identity_values = set(row["identity_sha256_by_event"].values())
        if row["decision"] == "equivalent" and len(identity_values) != 1:
            raise ValueError("reviewed_duplicate_boundary_not_equivalent")
        if row["decision"] == "equivalent":
            for duplicate_id in duplicate_ids:
                duplicate = final_events_by_id[duplicate_id]
                if (
                    duplicate["visibility_status"] != "draft"
                    or duplicate["race_series_id"] is not None
                    or duplicate["slug"] != f"release-b-tombstone-{duplicate_id}"
                ):
                    raise ValueError("reviewed_equivalent_duplicate_tombstone_invalid")
                expected_links_by_pair[(duplicate_id, survivor_id)] = row[
                    "identity_sha256_by_event"
                ][str(duplicate_id)]
    if "collapse_exact_duplicate_boundary" in operations and any(
        row["decision"] != "equivalent" for row in boundaries
    ):
        raise ValueError("reviewed_collapse_requires_equivalent_boundaries")
    if set(links_by_pair) != set(expected_links_by_pair):
        raise ValueError("reviewed_canonical_link_boundary_mismatch")
    if any(
        links_by_pair[pair]["identity_sha256"] != identity_sha256
        for pair, identity_sha256 in expected_links_by_pair.items()
    ):
        raise ValueError("reviewed_canonical_link_identity_mismatch")
    duplicate_ids: set[int] = set()
    canonical_ids: set[int] = set()
    for row in links:
        duplicate_id = row["duplicate_event_id"]
        canonical_id = row["canonical_event_id"]
        if (
            duplicate_id == canonical_id
            or duplicate_id not in current_event_ids
            or canonical_id not in current_event_ids
        ):
            raise ValueError("reviewed_canonical_link_endpoint_invalid")
        if duplicate_id in duplicate_ids:
            raise ValueError("reviewed_canonical_link_chain_or_cycle")
        duplicate_ids.add(duplicate_id)
        canonical_ids.add(canonical_id)
    if duplicate_ids & canonical_ids:
        raise ValueError("reviewed_canonical_link_chain_or_cycle")
    return current


def apply_release_b_series_actions(
    *,
    actions: list[dict[str, Any]],
    manifest_sha256: str,
    action_scope_sha256: str,
    actor: Any,
    confirm_reviewed_artifact: bool,
    rollback_output_path: Path | None = None,
) -> dict[str, Any]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise ValueError("historical race backfill is disabled")
    if not confirm_reviewed_artifact:
        raise ValueError("apply requires reviewed artifact confirmation")
    if action_scope_sha256 != release_b_action_scope_sha256(actions):
        raise ValueError("release_b_action_scope_mismatch")
    require_exact_active_gate(
        manifest_sha256=manifest_sha256,
        action_scope_sha256=action_scope_sha256,
        actor=actor,
    )
    if not actions or [row.get("series_id") for row in actions] != sorted(
        {row.get("series_id") for row in actions}
    ):
        raise ValueError("release_b_series_scope_must_be_sorted_unique")

    with transaction.atomic():
        _advisory_lock(manifest_sha256)
        require_exact_active_gate(
            manifest_sha256=manifest_sha256,
            action_scope_sha256=action_scope_sha256,
            actor=actor,
        )
        series_ids = [row["series_id"] for row in actions]
        list(
            RaceSeries.objects.select_for_update()
            .filter(pk__in=series_ids)
            .order_by("pk")
        )
        validated = [_validate_reviewed_action(action) for action in actions]
        event_ids = sorted(
            {row["id"] for current in validated for row in current["events"]}
        )
        target_ids = sorted(
            {
                row["payload"]["id"]
                for current in validated
                for row in current["ledgers"]["managed_targets_and_paths"]["targets"]
            }
        )
        path_ids = sorted(
            {
                row["payload"]["id"]
                for current in validated
                for row in current["ledgers"]["managed_targets_and_paths"]["paths"]
            }
        )
        list(
            HistoricalRaceEventTarget.objects.select_for_update()
            .filter(pk__in=target_ids)
            .order_by("pk")
        )
        list(
            RaceEvent.objects.select_for_update().filter(pk__in=event_ids).order_by("pk")
        )
        list(
            RaceEventPublicPath.objects.select_for_update()
            .filter(pk__in=path_ids)
            .order_by("pk")
        )
        list(
            RaceEventProductCanonicalLink.objects.select_for_update()
            .filter(Q(duplicate_event_id__in=event_ids) | Q(canonical_event_id__in=event_ids))
            .order_by("pk")
        )
        _lock_immutable_dependencies(
            list(RaceEvent._base_manager.filter(pk__in=event_ids).order_by("pk"))
        )
        # Recheck after every row lock is held.
        validated = [_validate_reviewed_action(action) for action in actions]
        before_snapshot = _scope_snapshot(actions)
        before_ledgers = {
            current["series_id"]: current["ledgers"] for current in validated
        }
        with _verified_repair_writer(
            manifest_sha256=manifest_sha256,
            action_scope_sha256=action_scope_sha256,
        ):
            temporary_identity = manifest_sha256
            for event_id in event_ids:
                RaceEvent._base_manager.filter(pk=event_id).update(
                    year=32767,
                    slug=(
                        f"release-b-temp-event-{temporary_identity}-{event_id}"
                    ),
                    edition_year=None,
                    race_series_id=None,
                    updated_at=timezone.now(),
                )
            for path_id in path_ids:
                RaceEventPublicPath._base_manager.filter(pk=path_id).update(
                    year=32767,
                    slug=f"release-b-temp-path-{temporary_identity}-{path_id}",
                    path_kind="legacy",
                    updated_at=timezone.now(),
                )
            desired_links = {
                row["duplicate_event_id"]: row
                for action in actions
                for row in action["reviewed"]["canonical_links"]
            }
            retained_duplicate_ids: set[int] = set()
            for existing_link in RaceEventProductCanonicalLink._base_manager.filter(
                Q(duplicate_event_id__in=event_ids)
                | Q(canonical_event_id__in=event_ids),
                is_active=True,
            ).order_by("pk"):
                desired = desired_links.get(existing_link.duplicate_event_id)
                if (
                    desired is not None
                    and existing_link.canonical_event_id
                    == desired["canonical_event_id"]
                    and existing_link.identity_sha256 == desired["identity_sha256"]
                ):
                    RaceEventProductCanonicalLink._base_manager.filter(
                        pk=existing_link.pk
                    ).update(
                        manifest_sha256=manifest_sha256,
                        approved_by=actor,
                        approved_at=timezone.now(),
                    )
                    retained_duplicate_ids.add(existing_link.duplicate_event_id)
                else:
                    RaceEventProductCanonicalLink._base_manager.filter(
                        pk=existing_link.pk
                    ).update(
                        is_active=False,
                        deactivated_by=actor,
                        deactivated_at=timezone.now(),
                    )
            for action in actions:
                reviewed = action["reviewed"]
                for row in reviewed["events"]:
                    RaceEvent._base_manager.filter(pk=row["id"]).update(
                        year=row["year"],
                        edition_year=row["edition_year"],
                        slug=row["slug"],
                        race_series_id=row["race_series_id"],
                        visibility_status=row["visibility_status"],
                        updated_at=timezone.now(),
                    )
                for row in reviewed["targets"]:
                    target_values = {
                        key: value for key, value in row.items() if key != "id"
                    }
                    if target_values["resolution_status"] == "superseded":
                        target_values["supersession_manifest_sha256"] = manifest_sha256
                    HistoricalRaceEventTarget._base_manager.filter(pk=row["id"]).update(
                        **target_values,
                        updated_at=timezone.now(),
                    )
                for row in reviewed["paths"]:
                    RaceEventPublicPath._base_manager.filter(pk=row["id"]).update(
                        event_id=row["event_id"],
                        year=row["year"],
                        slug=row["slug"],
                        path_kind=row["path_kind"],
                        reason="historical_calendar_release_b",
                        manifest_sha256=manifest_sha256,
                        updated_at=timezone.now(),
                    )
                for row in reviewed["canonical_links"]:
                    if row["duplicate_event_id"] in retained_duplicate_ids:
                        continue
                    RaceEventProductCanonicalLink.objects.create(
                        duplicate_event_id=row["duplicate_event_id"],
                        canonical_event_id=row["canonical_event_id"],
                        identity_sha256=row["identity_sha256"],
                        manifest_sha256=manifest_sha256,
                        approved_by=actor,
                        approved_at=timezone.now(),
                        is_active=row["is_active"],
                    )
        for action, current in zip(actions, validated, strict=True):
            original_event_ids = [row["id"] for row in current["events"]]
            after_immutable = _immutable_dependencies_for_events(
                list(
                    RaceEvent._base_manager.filter(pk__in=original_event_ids).order_by("pk")
                )
            )
            before_immutable = before_ledgers[action["series_id"]][
                "immutable_reverse_dependencies"
            ]
            if after_immutable != before_immutable:
                raise ValueError("release_b_immutable_dependency_drift")
        verification = verify_release_b_series_actions(
            actions=actions, manifest_sha256=manifest_sha256
        )
        if not verification["ok"]:
            raise ValueError("release_b_post_apply_verification_failed")
        after_snapshot = _scope_snapshot(actions)
        rollback_payload = {
            "schema_version": ROLLBACK_SCHEMA_V2,
            "manifest_sha256": manifest_sha256,
            "action_scope_sha256": action_scope_sha256,
            "actions": actions,
            "before": before_snapshot,
            "after": after_snapshot,
        }
        rollback_payload["payload_sha256"] = _digest(rollback_payload)
        rollback_sha256 = ""
        if rollback_output_path is not None:
            rollback_bytes = _canonical_bytes(rollback_payload)
            _write_new_file(rollback_output_path, rollback_bytes)
            rollback_sha256 = _sha256_bytes(rollback_bytes)
        transaction.on_commit(invalidate_public_race_cache)
        return {
            "status": "applied",
            "manifest_sha256": manifest_sha256,
            "action_scope_sha256": action_scope_sha256,
            "applied_series_ids": series_ids,
            "rollback_payload": rollback_payload,
            "rollback_sha256": rollback_sha256,
        }


def verify_release_b_series_actions(
    *, actions: list[dict[str, Any]], manifest_sha256: str = ""
) -> dict[str, Any]:
    errors: list[str] = []
    for action in actions:
        reviewed = action.get("reviewed") or {}
        events = {
            row.pk: row
            for row in RaceEvent._base_manager.filter(
                pk__in=[item["id"] for item in action.get("events", [])]
            )
        }
        for expected in reviewed.get("events", []):
            event = events.get(expected["id"])
            if event is None or any(
                getattr(event, key if key != "race_series_id" else "race_series_id")
                != value
                for key, value in expected.items()
                if key != "id"
            ):
                errors.append(f"event_final_state:{expected['id']}")
                continue
            if event.local_date is not None and event.year != event.local_date.year:
                errors.append(f"event_natural_year:{event.pk}")

        target_rows = {
            row.pk: row
            for row in HistoricalRaceEventTarget._base_manager.filter(
                pk__in=[item["id"] for item in reviewed.get("targets", [])]
            )
        }
        for expected in reviewed.get("targets", []):
            target = target_rows.get(expected["id"])
            expected_target = dict(expected)
            if expected_target["resolution_status"] == "superseded":
                if not manifest_sha256:
                    errors.append(f"target_manifest_identity_missing:{expected['id']}")
                    continue
                expected_target["supersession_manifest_sha256"] = manifest_sha256
            target_matches = target is not None
            if target_matches:
                for key, value in expected_target.items():
                    if key == "id":
                        continue
                    actual = getattr(target, key)
                    if key == "superseded_at":
                        actual = _stable_timestamp(
                            actual,
                            label="release b actual target superseded_at",
                        )
                        value = _stable_timestamp(
                            value,
                            label="release b expected target superseded_at",
                        )
                    if actual != value:
                        target_matches = False
                        break
            if not target_matches:
                errors.append(f"target_final_state:{expected['id']}")
                continue
            if target.event_id:
                edition = target.event.edition_year or target.event.year
                if target.event.race_series_id != target.race_series_id or edition != target.year:
                    errors.append(f"target_event_identity:{target.pk}")

        actual_paths = {
            row.pk: row
            for row in RaceEventPublicPath._base_manager.filter(
                pk__in=[item["id"] for item in reviewed.get("paths", [])]
            )
        }
        for expected in reviewed.get("paths", []):
            path = actual_paths.get(expected["id"])
            if path is None or any(
                getattr(path, key) != value for key, value in expected.items() if key != "id"
            ):
                errors.append(f"path_final_state:{expected['id']}")

        event_ids = sorted(events)
        actual_links = list(
            RaceEventProductCanonicalLink._base_manager.filter(
                Q(duplicate_event_id__in=event_ids)
                | Q(canonical_event_id__in=event_ids),
                is_active=True,
            )
            .order_by("duplicate_event_id", "canonical_event_id", "pk")
            .values(
                "duplicate_event_id",
                "canonical_event_id",
                "identity_sha256",
                "is_active",
            )
        )
        expected_links = sorted(
            reviewed.get("canonical_links", []),
            key=lambda row: (row["duplicate_event_id"], row["canonical_event_id"]),
        )
        if actual_links != expected_links:
            errors.append(f"canonical_link_topology:{action.get('action_id')}")

        immutable = _immutable_dependencies_for_events(
            list(RaceEvent._base_manager.filter(pk__in=event_ids).order_by("pk"))
        )
        if immutable != action["ledgers"]["immutable_reverse_dependencies"]:
            errors.append(f"immutable_dependency_drift:{action.get('action_id')}")

    ids = _scope_ids(actions)
    if RaceEvent._base_manager.filter(
        pk__in=ids["event_ids"], slug__startswith="release-b-temp-event-"
    ).exists() or RaceEventPublicPath._base_manager.filter(
        pk__in=ids["path_ids"], slug__startswith="release-b-temp-path-"
    ).exists():
        errors.append("temporary_key_residue")
    for event in RaceEvent._base_manager.filter(local_date__isnull=False).only(
        "pk", "year", "local_date"
    ):
        if event.year != event.local_date.year:
            errors.append(f"global_natural_year:{event.pk}")
    if (
        RaceEvent._base_manager.filter(
            race_series__isnull=False,
            edition_year__isnull=False,
        )
        .values("race_series_id", "edition_year")
        .annotate(row_count=Count("pk"))
        .filter(row_count__gt=1)
        .exists()
    ):
        errors.append("global_series_edition_duplicate")
    if (
        HistoricalRaceEventTarget._base_manager.exclude(resolution_status="superseded")
        .values("race_series_id", "year")
        .annotate(row_count=Count("pk"))
        .filter(row_count__gt=1)
        .exists()
    ):
        errors.append("global_active_target_duplicate")
    for target in HistoricalRaceEventTarget._base_manager.select_related(
        "event", "superseded_by"
    ).order_by("pk"):
        if target.resolution_status == "superseded":
            survivor = target.superseded_by
            if (
                target.event_id is not None
                or survivor is None
                or survivor.race_series_id != target.race_series_id
                or survivor.year != target.year
                or survivor.resolution_status == "superseded"
                or survivor.superseded_by_id is not None
                or target.superseded_at is None
                or len(target.supersession_manifest_sha256) != 64
            ):
                errors.append(f"global_target_supersession:{target.pk}")
        elif target.superseded_by_id is not None:
            errors.append(f"global_active_target_superseded_by:{target.pk}")
        if target.resolution_status == "imported" and target.event_id is None:
            errors.append(f"global_imported_target_event_required:{target.pk}")
        if target.event_id is not None:
            edition = target.event.edition_year or target.event.year
            if target.event.race_series_id != target.race_series_id or edition != target.year:
                errors.append(f"global_target_event_identity:{target.pk}")
    for path in RaceEventPublicPath._base_manager.filter(path_kind="canonical").select_related(
        "event"
    ):
        if path.year != path.event.year or path.slug != path.event.slug:
            errors.append(f"global_canonical_path_owner:{path.pk}")
    published_without_one_canonical = (
        RaceEvent._base_manager.filter(visibility_status="published")
        .annotate(
            canonical_path_count=Count(
                "public_paths",
                filter=Q(public_paths__path_kind="canonical"),
            )
        )
        .exclude(canonical_path_count=1)
        .values_list("pk", flat=True)
    )
    errors.extend(
        f"global_published_canonical_path_count:{event_id}"
        for event_id in published_without_one_canonical
    )
    return {"ok": not errors, "errors": errors}


def rollback_release_b_series_actions(
    *,
    rollback_payload: dict[str, Any],
    manifest_sha256: str,
    action_scope_sha256: str,
    actor: Any,
    confirm_reviewed_artifact: bool,
) -> dict[str, Any]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise ValueError("historical race backfill is disabled")
    if not confirm_reviewed_artifact:
        raise ValueError("rollback requires reviewed artifact confirmation")
    if rollback_payload.get("schema_version") != ROLLBACK_SCHEMA_V2:
        raise ValueError("release_b_rollback_schema_invalid")
    expected_payload_sha = rollback_payload.get("payload_sha256")
    unsigned_payload = {
        key: value for key, value in rollback_payload.items() if key != "payload_sha256"
    }
    if expected_payload_sha != _digest(unsigned_payload):
        raise ValueError("release_b_rollback_payload_drift")
    if (
        rollback_payload.get("manifest_sha256") != manifest_sha256
        or rollback_payload.get("action_scope_sha256") != action_scope_sha256
    ):
        raise ValueError("release_b_rollback_identity_mismatch")
    actions = rollback_payload.get("actions")
    if not isinstance(actions, list) or release_b_action_scope_sha256(actions) != action_scope_sha256:
        raise ValueError("release_b_rollback_action_scope_mismatch")
    require_exact_active_gate(
        manifest_sha256=manifest_sha256,
        action_scope_sha256=action_scope_sha256,
        actor=actor,
    )
    ids = _scope_ids(actions)
    with transaction.atomic():
        _advisory_lock(manifest_sha256)
        require_exact_active_gate(
            manifest_sha256=manifest_sha256,
            action_scope_sha256=action_scope_sha256,
            actor=actor,
        )
        list(RaceSeries.objects.select_for_update().filter(pk__in=ids["series_ids"]).order_by("pk"))
        list(RaceEvent.objects.select_for_update().filter(pk__in=ids["event_ids"]).order_by("pk"))
        list(HistoricalRaceEventTarget.objects.select_for_update().filter(pk__in=ids["target_ids"]).order_by("pk"))
        list(RaceEventPublicPath.objects.select_for_update().filter(pk__in=ids["path_ids"]).order_by("pk"))
        list(
            RaceEventProductCanonicalLink.objects.select_for_update()
            .filter(
                Q(duplicate_event_id__in=ids["event_ids"])
                | Q(canonical_event_id__in=ids["event_ids"])
            )
            .order_by("pk")
        )
        if _scope_snapshot(actions) != rollback_payload.get("after"):
            raise ValueError("release_b_rollback_post_state_drift")
        before = rollback_payload["before"]["payload"]
        with _verified_repair_writer(
            manifest_sha256=manifest_sha256,
            action_scope_sha256=action_scope_sha256,
        ):
            RaceEventProductCanonicalLink._base_manager.filter(
                Q(duplicate_event_id__in=ids["event_ids"])
                | Q(canonical_event_id__in=ids["event_ids"])
            ).delete()
            HistoricalRaceEventTarget._base_manager.filter(pk__in=ids["target_ids"]).update(
                resolution_status="superseded"
            )
            for event_id in ids["event_ids"]:
                RaceEvent._base_manager.filter(pk=event_id).update(
                    year=30000 + (event_id % 2000),
                    slug=f"release-b-temp-event-{event_id}",
                    edition_year=None,
                    race_series_id=None,
                )
            for path_id in ids["path_ids"]:
                RaceEventPublicPath._base_manager.filter(pk=path_id).update(
                    year=30000 + (path_id % 2000),
                    slug=f"release-b-temp-path-{path_id}",
                    path_kind="legacy",
                )
            for payload in before["events"]:
                RaceEvent._base_manager.filter(pk=payload["id"]).update(
                    **_restore_values(RaceEvent, payload)
                )
            for payload in before["targets"]:
                HistoricalRaceEventTarget._base_manager.filter(pk=payload["id"]).update(
                    **_restore_values(HistoricalRaceEventTarget, payload)
                )
            for payload in before["paths"]:
                RaceEventPublicPath._base_manager.filter(pk=payload["id"]).update(
                    **_restore_values(RaceEventPublicPath, payload)
                )
            for payload in before["canonical_links"]:
                RaceEventProductCanonicalLink._base_manager.create(
                    id=payload["id"],
                    **_restore_values(RaceEventProductCanonicalLink, payload),
                )
                RaceEventProductCanonicalLink._base_manager.filter(
                    pk=payload["id"]
                ).update(
                    created_at=RaceEventProductCanonicalLink._meta.get_field(
                        "created_at"
                    ).to_python(payload["created_at"]),
                    updated_at=RaceEventProductCanonicalLink._meta.get_field(
                        "updated_at"
                    ).to_python(payload["updated_at"]),
                )
        if _scope_snapshot(actions) != rollback_payload.get("before"):
            raise ValueError("release_b_rollback_restore_verification_failed")
        transaction.on_commit(invalidate_public_race_cache)
    return {
        "status": "rolled_back",
        "manifest_sha256": manifest_sha256,
        "action_scope_sha256": action_scope_sha256,
        "rolled_back_series_ids": ids["series_ids"],
    }


def _load_release_b_manifest(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    artifact_root: str | Path | None,
) -> tuple[Path, dict[str, Any], str]:
    root = _controlled_root(artifact_root)
    frozen = _load_json(
        manifest_path,
        root=root,
        label="release b reviewed manifest",
        expected_sha256=expected_manifest_sha256,
    )
    manifest = frozen.payload
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_V2
        or manifest.get("scope") != "reviewed_series_actions"
        or manifest.get("code_identity") != _code_identity_v2()
        or not isinstance(manifest.get("actions"), list)
        or manifest.get("action_scope_sha256")
        != release_b_action_scope_sha256(manifest.get("actions", []))
    ):
        raise ValueError("release_b_reviewed_manifest_invalid")
    artifacts = manifest.get("artifacts")
    expected_names = {"census.manifest.json", "review.json", "summary.json"}
    if not isinstance(artifacts, dict) or set(artifacts) != expected_names:
        raise ValueError("release_b_reviewed_artifacts_invalid")
    for name, identity in artifacts.items():
        payload = _read_regular_file(
            frozen.path.parent / name,
            label=f"release b reviewed artifact {name}",
            root=root,
        )
        if (
            not isinstance(identity, dict)
            or identity.get("path") != name
            or identity.get("size") != len(payload)
            or identity.get("sha256") != _sha256_bytes(payload)
        ):
            raise ValueError("release_b_reviewed_artifact_drift")
    return root, manifest, frozen.sha256


def _validate_release_b_approval(
    *,
    path: str | Path,
    expected_sha256: str,
    root: Path,
    manifest: dict[str, Any],
    manifest_sha256: str,
    actor: Any,
) -> str:
    approval = _load_json(
        path,
        root=root,
        label="release b approval",
        expected_sha256=expected_sha256,
    )
    payload = approval.payload
    expected_ids = [row["action_id"] for row in manifest["actions"]]
    reviewer = str(payload.get("approved_by") or "").strip()
    actor_name = actor.get_username()
    if (
        payload.get("schema_version") != APPROVAL_SCHEMA_V2
        or payload.get("status") != "approved"
        or payload.get("manifest_sha256") != manifest_sha256
        or payload.get("action_scope_sha256") != manifest["action_scope_sha256"]
        or payload.get("approved_action_ids") != expected_ids
        or not reviewer
        or reviewer == actor_name
        or payload.get("actor") != actor_name
    ):
        raise ValueError("release_b_approval_invalid")
    _aware_timestamp(payload.get("approved_at"), label="release b approval")
    user_model = get_user_model()
    if not user_model._default_manager.filter(
        **{user_model.USERNAME_FIELD: reviewer}
    ).exists():
        raise ValueError("release_b_approval_reviewer_missing")
    return approval.sha256


def _validate_release_b_maintenance(
    *,
    path: str | Path,
    expected_sha256: str,
    root: Path,
    manifest: dict[str, Any],
    manifest_sha256: str,
) -> None:
    frozen = _load_json(
        path,
        root=root,
        label="release b maintenance evidence",
        expected_sha256=expected_sha256,
    )
    payload = frozen.payload
    checks = payload.get("checks")
    if (
        payload.get("schema_version") != MAINTENANCE_SCHEMA
        or payload.get("status") != "frozen"
        or payload.get("manifest_sha256") != manifest_sha256
        or payload.get("action_scope_sha256") != manifest["action_scope_sha256"]
        or not isinstance(checks, dict)
        or set(checks) != REQUIRED_MAINTENANCE_CHECKS
        or any(value != "stopped" for value in checks.values())
    ):
        raise ValueError("release_b_maintenance_evidence_invalid")
    _aware_timestamp(payload.get("observed_at"), label="release b maintenance evidence")


def apply_release_b_reviewed_manifest(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    approval_path: str | Path,
    expected_approval_sha256: str,
    maintenance_evidence_path: str | Path,
    expected_maintenance_evidence_sha256: str,
    actor: Any,
    artifact_root: str | Path | None,
    confirm_reviewed_artifact: bool,
) -> dict[str, Any]:
    root, manifest, manifest_sha256 = _load_release_b_manifest(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        artifact_root=artifact_root,
    )
    approval_sha256 = _validate_release_b_approval(
        path=approval_path,
        expected_sha256=expected_approval_sha256,
        root=root,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        actor=actor,
    )
    existing = HistoricalRaceCalendarRepairReceipt.objects.filter(
        manifest_sha256=manifest_sha256
    ).first()
    if existing is not None:
        if (
            existing.approval_sha256 != approval_sha256
            or existing.action_scope_sha256 != manifest["action_scope_sha256"]
            or existing.actor_id != actor.pk
        ):
            raise ValueError("release_b_existing_receipt_identity_conflict")
        verifier = verify_release_b_reviewed_manifest(
            manifest_path=manifest_path,
            expected_manifest_sha256=manifest_sha256,
            artifact_root=root,
            update_receipt=True,
        )
        if not verifier["ok"]:
            raise ValueError("release_b_existing_receipt_verification_failed")
        return {
            "status": "already_applied",
            "receipt_id": existing.pk,
            "verifier": verifier,
        }
    _validate_release_b_maintenance(
        path=maintenance_evidence_path,
        expected_sha256=expected_maintenance_evidence_sha256,
        root=root,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    reviewed_manifest_path = _controlled_path(
        manifest_path,
        root=root,
        must_exist=True,
    )
    rollback_path = reviewed_manifest_path.parent / f"rollback-{manifest_sha256}.json"
    if os.path.lexists(rollback_path):
        raise ValueError("release_b_rollback_artifact_already_exists")
    rollback_created = False
    try:
        with transaction.atomic():
            result = apply_release_b_series_actions(
                actions=manifest["actions"],
                manifest_sha256=manifest_sha256,
                action_scope_sha256=manifest["action_scope_sha256"],
                actor=actor,
                confirm_reviewed_artifact=confirm_reviewed_artifact,
                rollback_output_path=rollback_path,
            )
            rollback_created = True
            receipt = HistoricalRaceCalendarRepairReceipt.objects.create(
                manifest_sha256=manifest_sha256,
                approval_sha256=approval_sha256,
                action_scope_sha256=manifest["action_scope_sha256"],
                actor=actor,
                status=HistoricalRaceCalendarRepairReceiptStatus.APPLIED,
                rollback_sha256=result["rollback_sha256"],
                applied_at=timezone.now(),
            )
    except Exception:
        if rollback_created:
            rollback_path.unlink(missing_ok=True)
        raise
    verifier = verify_release_b_reviewed_manifest(
        manifest_path=manifest_path,
        expected_manifest_sha256=manifest_sha256,
        artifact_root=root,
        update_receipt=True,
    )
    if not verifier["ok"]:
        raise ValueError("release_b_post_commit_verification_failed")
    return {
        "status": verifier["receipt_status"],
        "receipt_id": receipt.pk,
        "rollback_path": str(rollback_path),
        "rollback_sha256": result["rollback_sha256"],
        "verifier": verifier,
    }


def verify_release_b_reviewed_manifest(
    *,
    manifest_path: str | Path,
    expected_manifest_sha256: str,
    artifact_root: str | Path | None,
    update_receipt: bool,
) -> dict[str, Any]:
    _, manifest, manifest_sha256 = _load_release_b_manifest(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        artifact_root=artifact_root,
    )
    with _read_only_snapshot():
        result = verify_release_b_series_actions(
            actions=manifest["actions"], manifest_sha256=manifest_sha256
        )
        result["verifier_result_sha256"] = _digest(result)
    receipt_status = ""
    if update_receipt:
        with transaction.atomic():
            try:
                receipt = HistoricalRaceCalendarRepairReceipt.objects.select_for_update().get(
                    manifest_sha256=manifest_sha256
                )
            except HistoricalRaceCalendarRepairReceipt.DoesNotExist as exc:
                raise ValueError("release_b_verifier_receipt_missing") from exc
            if receipt.status == HistoricalRaceCalendarRepairReceiptStatus.ROLLED_BACK:
                raise ValueError("release_b_verifier_receipt_rolled_back")
            receipt.status = (
                HistoricalRaceCalendarRepairReceiptStatus.VERIFIED
                if result["ok"]
                else HistoricalRaceCalendarRepairReceiptStatus.VERIFICATION_FAILED
            )
            receipt.verified_at = timezone.now()
            receipt.verifier_result_sha256 = result["verifier_result_sha256"]
            receipt.save(
                update_fields={"status", "verified_at", "verifier_result_sha256", "updated_at"}
            )
            receipt_status = receipt.status
    result["receipt_status"] = receipt_status
    return result


def rollback_release_b_reviewed_manifest(
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
    artifact_root: str | Path | None,
    confirm_reviewed_artifact: bool,
) -> dict[str, Any]:
    root, manifest, manifest_sha256 = _load_release_b_manifest(
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        artifact_root=artifact_root,
    )
    approval_sha256 = _validate_release_b_approval(
        path=approval_path,
        expected_sha256=expected_approval_sha256,
        root=root,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        actor=actor,
    )
    _validate_release_b_maintenance(
        path=maintenance_evidence_path,
        expected_sha256=expected_maintenance_evidence_sha256,
        root=root,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
    )
    rollback = _load_json(
        rollback_path,
        root=root,
        label="release b rollback artifact",
        expected_sha256=expected_rollback_sha256,
    )
    try:
        receipt = HistoricalRaceCalendarRepairReceipt.objects.get(
            manifest_sha256=manifest_sha256
        )
    except HistoricalRaceCalendarRepairReceipt.DoesNotExist as exc:
        raise ValueError("release_b_rollback_receipt_missing") from exc
    if receipt.status == HistoricalRaceCalendarRepairReceiptStatus.ROLLED_BACK:
        return {"status": "already_rolled_back", "receipt_id": receipt.pk}
    if (
        receipt.approval_sha256 != approval_sha256
        or receipt.rollback_sha256 != rollback.sha256
        or receipt.actor_id != actor.pk
    ):
        raise ValueError("release_b_rollback_receipt_identity_mismatch")
    with transaction.atomic():
        result = rollback_release_b_series_actions(
            rollback_payload=rollback.payload,
            manifest_sha256=manifest_sha256,
            action_scope_sha256=manifest["action_scope_sha256"],
            actor=actor,
            confirm_reviewed_artifact=confirm_reviewed_artifact,
        )
        receipt = HistoricalRaceCalendarRepairReceipt.objects.select_for_update().get(pk=receipt.pk)
        receipt.status = HistoricalRaceCalendarRepairReceiptStatus.ROLLED_BACK
        receipt.rolled_back_at = timezone.now()
        receipt.save(update_fields={"status", "rolled_back_at", "updated_at"})
    return {**result, "receipt_id": receipt.pk, "rollback_sha256": rollback.sha256}
