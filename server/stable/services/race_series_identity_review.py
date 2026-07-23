from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    OperationLog,
    RaceEvent,
    RaceSeries,
    RaceSeriesName,
    RaceSeriesRelation,
    RaceSeriesRelationType,
    RaceSeriesReviewStatus,
)
from stable.services.race_event_reconciliation import (
    RaceEventReconciliationError,
    _canonical_bytes,
    _cleanup_prepared_ledger,
    _parse_json_object_bytes,
    _prepare_rollback_ledger,
    _publish_prepared_ledger,
    _read_regular_file_bytes,
    _set_repeatable_read_snapshot,
    _sha256_bytes,
    event_identity as reconciliation_event_identity,
    target_identity as reconciliation_target_identity,
)


SCHEMA_VERSION = "1.0"
DECISION_MERGE_AND_LINK = "merge_and_link"
DECISION_KEEP_INDEPENDENT = "keep_independent"
DECISION_IGNORE_FALSE_MATCH = "ignore_false_match"
NEGATIVE_DECISIONS = {
    DECISION_KEEP_INDEPENDENT,
    DECISION_IGNORE_FALSE_MATCH,
}
SUPPORTED_DECISIONS = {DECISION_MERGE_AND_LINK, *NEGATIVE_DECISIONS}
MANIFEST_ARTIFACTS = {
    "actions.json",
    "decisions.normalized.jsonl",
    "input.decisions.json",
    "input.field_repairs.json",
    "review.json",
    "summary.json",
}
DETAIL_RELATIONS = (
    "aliases",
    "runners",
    "results",
    "history_winners",
    "data_candidates",
    "article_links",
)


class RaceSeriesIdentityReviewError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedIdentityReviewArtifacts:
    root: Path
    manifest: dict[str, Any]
    artifact_bytes: dict[str, bytes]
    actions: dict[str, Any]


def _safe_read(path: Path, *, label: str) -> bytes:
    try:
        return _read_regular_file_bytes(path, label=label)
    except RaceEventReconciliationError as exc:
        raise RaceSeriesIdentityReviewError(str(exc)) from exc


def _parse_object(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        return _parse_json_object_bytes(payload, label=label)
    except RaceEventReconciliationError as exc:
        raise RaceSeriesIdentityReviewError(str(exc)) from exc


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    return {"payload": payload, "sha256": _sha256_bytes(_canonical_bytes(payload))}


def _model_payload(instance) -> dict[str, Any]:
    return {
        field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields
    }


def _model_identity(instance) -> dict[str, Any]:
    return _identity(_model_payload(instance))


def race_series_identity(series: RaceSeries) -> dict[str, Any]:
    """Return the full concrete-field identity used by identity-review CAS."""
    return _model_identity(series)


def _event_detail_identity(event: RaceEvent) -> dict[str, Any]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for relation_name in DETAIL_RELATIONS:
        manager = getattr(event, relation_name)
        rows[relation_name] = [
            _model_payload(row) for row in manager.all().order_by("pk")
        ]
    return _identity(rows)


def _artifact_identity(name: str, payload: bytes) -> dict[str, Any]:
    return {"path": name, "size": len(payload), "sha256": _sha256_bytes(payload)}


def _required_text(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise RaceSeriesIdentityReviewError(f"{label} missing {key}")
    return value


def _required_positive_int(payload: dict[str, Any], key: str, *, label: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise RaceSeriesIdentityReviewError(f"{label} has invalid {key}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RaceSeriesIdentityReviewError(f"{label} has invalid {key}") from exc
    if parsed <= 0:
        raise RaceSeriesIdentityReviewError(f"{label} has invalid {key}")
    return parsed


def _optional_identity_sha256(
    payload: dict[str, Any], key: str, *, label: str
) -> str | None:
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise RaceSeriesIdentityReviewError(f"{label} has invalid {key}")
    return value


def _normalize_evidence(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RaceSeriesIdentityReviewError(f"{label} evidence must be an object")
    summary = str(value.get("summary") or "").strip()
    source_urls = value.get("source_urls")
    if (
        not summary
        or not isinstance(source_urls, list)
        or not source_urls
        or not all(isinstance(url, str) and url.strip() for url in source_urls)
    ):
        raise RaceSeriesIdentityReviewError(
            f"{label} evidence requires summary and source_urls"
        )
    return {
        "summary": summary,
        "source_urls": [url.strip() for url in source_urls],
    }


def _normalize_decisions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RaceSeriesIdentityReviewError("unsupported decision schema")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise RaceSeriesIdentityReviewError("decisions must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    decision_ids: set[str] = set()
    sheet_sequences: set[tuple[str, int]] = set()
    for index, row in enumerate(decisions, start=1):
        label = f"decision row {index}"
        if not isinstance(row, dict):
            raise RaceSeriesIdentityReviewError(f"{label} must be an object")
        decision_id = _required_text(row, "decision_id", label=label)
        sheet = _required_text(row, "sheet", label=label)
        sequence = _required_positive_int(row, "sequence", label=label)
        decision = _required_text(row, "decision", label=label)
        if decision not in SUPPORTED_DECISIONS:
            raise RaceSeriesIdentityReviewError(f"{label} has unsupported decision")
        sheet_sequence = (sheet, sequence)
        if decision_id in decision_ids or sheet_sequence in sheet_sequences:
            raise RaceSeriesIdentityReviewError(
                "decision IDs and sheet/sequence pairs must be unique"
            )
        decision_ids.add(decision_id)
        sheet_sequences.add(sheet_sequence)
        target_identity_sha256 = _optional_identity_sha256(
            row, "target_identity_sha256", label=label
        )
        event_identity_sha256 = _optional_identity_sha256(
            row, "event_identity_sha256", label=label
        )
        source_series_identity_sha256 = _optional_identity_sha256(
            row, "source_series_identity_sha256", label=label
        )
        destination_series_identity_sha256 = _optional_identity_sha256(
            row, "destination_series_identity_sha256", label=label
        )
        normalized.append(
            {
                "decision_id": decision_id,
                "sheet": sheet,
                "sequence": sequence,
                "decision": decision,
                "target_id": _required_positive_int(row, "target_id", label=label),
                "target_series_id": _required_positive_int(
                    row, "target_series_id", label=label
                ),
                "event_id": _required_positive_int(row, "event_id", label=label),
                "event_series_id": _required_positive_int(
                    row, "event_series_id", label=label
                ),
                "year": _required_positive_int(row, "year", label=label),
                "country_region": _required_text(row, "country_region", label=label),
                "confidence": _required_text(row, "confidence", label=label),
                "evidence": _normalize_evidence(row.get("evidence"), label=label),
                **(
                    {"target_identity_sha256": target_identity_sha256}
                    if target_identity_sha256 is not None
                    else {}
                ),
                **(
                    {"event_identity_sha256": event_identity_sha256}
                    if event_identity_sha256 is not None
                    else {}
                ),
                **(
                    {
                        "source_series_identity_sha256": source_series_identity_sha256
                    }
                    if source_series_identity_sha256 is not None
                    else {}
                ),
                **(
                    {
                        "destination_series_identity_sha256": (
                            destination_series_identity_sha256
                        )
                    }
                    if destination_series_identity_sha256 is not None
                    else {}
                ),
            }
        )
    return sorted(
        normalized,
        key=lambda row: (row["sheet"], row["sequence"], row["decision_id"]),
    )


def _normalize_repairs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RaceSeriesIdentityReviewError("unsupported field repair schema")
    repairs = payload.get("repairs")
    if not isinstance(repairs, list):
        raise RaceSeriesIdentityReviewError("repairs must be a list")
    normalized: list[dict[str, Any]] = []
    repair_ids: set[str] = set()
    event_fields: set[tuple[int, str]] = set()
    surface_values = {
        value for value, _label in RaceEvent._meta.get_field("surface").choices
    }
    for index, row in enumerate(repairs, start=1):
        label = f"field repair row {index}"
        if not isinstance(row, dict):
            raise RaceSeriesIdentityReviewError(f"{label} must be an object")
        repair_id = _required_text(row, "repair_id", label=label)
        event_id = _required_positive_int(row, "event_id", label=label)
        field = _required_text(row, "field", label=label)
        if field != "surface":
            raise RaceSeriesIdentityReviewError(
                f"{label} only supports an explicit surface repair"
            )
        expected_before = str(row.get("expected_before") or "").strip()
        value = str(row.get("value") or "").strip()
        if expected_before not in surface_values or value not in surface_values:
            raise RaceSeriesIdentityReviewError(f"{label} has invalid surface values")
        if expected_before == value:
            raise RaceSeriesIdentityReviewError(f"{label} does not change surface")
        if repair_id in repair_ids or (event_id, field) in event_fields:
            raise RaceSeriesIdentityReviewError("field repairs must be unique")
        repair_ids.add(repair_id)
        event_fields.add((event_id, field))
        normalized.append(
            {
                "repair_id": repair_id,
                "event_id": event_id,
                "field": field,
                "expected_before": expected_before,
                "value": value,
                "evidence": _normalize_evidence(row.get("evidence"), label=label),
            }
        )
    return sorted(normalized, key=lambda row: (row["event_id"], row["repair_id"]))


def _series_dependency_snapshot(series_id: int) -> dict[str, list[int]]:
    relation_ids = set(
        RaceSeriesRelation.objects.filter(from_series_id=series_id).values_list(
            "id", flat=True
        )
    )
    relation_ids.update(
        RaceSeriesRelation.objects.filter(to_series_id=series_id).values_list(
            "id", flat=True
        )
    )
    return {
        "annual_event_ids": list(
            RaceEvent.objects.filter(race_series_id=series_id)
            .order_by("pk")
            .values_list("id", flat=True)
        ),
        "historical_target_ids": list(
            HistoricalRaceEventTarget.objects.filter(race_series_id=series_id)
            .order_by("pk")
            .values_list("id", flat=True)
        ),
        "name_ids": list(
            RaceSeriesName.objects.filter(series_id=series_id)
            .order_by("pk")
            .values_list("id", flat=True)
        ),
        "relation_ids": sorted(relation_ids),
    }


def _destination_year_event_ids(series_id: int, year: int) -> list[int]:
    return list(
        RaceEvent.objects.filter(race_series_id=series_id, year=year)
        .order_by("pk")
        .values_list("id", flat=True)
    )


def _repair_provenance(repair: dict[str, Any]) -> dict[str, Any]:
    return {
        "repair_id": repair["repair_id"],
        "field": repair["field"],
        "expected_before": repair["expected_before"],
        "value": repair["value"],
        "evidence": repair["evidence"],
    }


def _event_payload_after_repairs(
    before_payload: dict[str, Any],
    repairs: list[dict[str, Any]],
    *,
    destination_series_id: int,
    destination_series_key: str,
) -> dict[str, Any]:
    payload = deepcopy(before_payload)
    payload["race_series_id"] = destination_series_id
    payload["series_key"] = destination_series_key
    for repair in repairs:
        if payload.get(repair["field"]) != repair["expected_before"]:
            raise RaceSeriesIdentityReviewError(
                f"field repair expected-before drift: {repair['repair_id']}"
            )
        payload[repair["field"]] = repair["value"]
        source_refs = deepcopy(payload.get("source_refs") or {})
        existing_repairs = source_refs.get("identity_review_field_repairs", [])
        if not isinstance(existing_repairs, list):
            raise RaceSeriesIdentityReviewError(
                "event source_refs identity_review_field_repairs must be a list"
            )
        provenance = _repair_provenance(repair)
        if provenance not in existing_repairs:
            existing_repairs.append(provenance)
        source_refs["identity_review_field_repairs"] = existing_repairs
        payload["source_refs"] = source_refs
        manual_locks = deepcopy(payload.get("manual_lock_flags") or {})
        manual_locks[repair["field"]] = True
        payload["manual_lock_flags"] = manual_locks
    return payload


def _negative_evidence(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": decision["decision_id"],
        "sheet": decision["sheet"],
        "sequence": decision["sequence"],
        "decision": decision["decision"],
        "target_id": decision["target_id"],
        "event_id": decision["event_id"],
        "year": decision["year"],
        "evidence": decision["evidence"],
    }


def _flags_with_do_not_merge(
    before_flags: dict[str, Any],
    *,
    other_series_id: int,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    decision_values = {decision["decision"] for decision in decisions}
    if len(decision_values) != 1 or not decision_values <= NEGATIVE_DECISIONS:
        raise RaceSeriesIdentityReviewError(
            "exact pair has conflicting negative decisions"
        )
    pair_decision = next(iter(decision_values))
    flags = deepcopy(before_flags or {})
    pair_map = flags.get("identity_do_not_merge", {})
    if not isinstance(pair_map, dict):
        raise RaceSeriesIdentityReviewError(
            "identity_do_not_merge manual lock must be an object"
        )
    pair_map = deepcopy(pair_map)
    key = str(other_series_id)
    entry = pair_map.get(key, {})
    if not isinstance(entry, dict):
        raise RaceSeriesIdentityReviewError("identity pair manual lock must be an object")
    existing_decision = entry.get("decision")
    if existing_decision not in (None, pair_decision):
        raise RaceSeriesIdentityReviewError("identity pair has a conflicting manual lock")
    evidence = entry.get("evidence", [])
    if not isinstance(evidence, list):
        raise RaceSeriesIdentityReviewError("identity pair evidence must be a list")
    evidence_by_id = {
        item.get("decision_id"): item
        for item in evidence
        if isinstance(item, dict) and item.get("decision_id")
    }
    for decision in decisions:
        item = _negative_evidence(decision)
        evidence_by_id[item["decision_id"]] = item
    pair_map[key] = {
        **{
            field: value
            for field, value in entry.items()
            if field not in {"decision", "other_series_id", "evidence"}
        },
        "decision": pair_decision,
        "other_series_id": other_series_id,
        "evidence": [
            evidence_by_id[decision_id] for decision_id in sorted(evidence_by_id)
        ],
    }
    flags["identity_do_not_merge"] = pair_map
    return flags


def is_identity_pair_do_not_merge(left: RaceSeries, right: RaceSeries) -> bool:
    if not left.pk or not right.pk or left.pk == right.pk:
        return False

    def has_lock(series: RaceSeries, other_id: int) -> bool:
        pair_map = (series.manual_lock_flags or {}).get("identity_do_not_merge", {})
        if not isinstance(pair_map, dict):
            return False
        entry = pair_map.get(str(other_id), {})
        return (
            isinstance(entry, dict)
            and entry.get("decision") in NEGATIVE_DECISIONS
        )

    return has_lock(left, right.pk) or has_lock(right, left.pk)


def _validate_decision_identity(
    decision: dict[str, Any],
    *,
    target: HistoricalRaceEventTarget,
    event: RaceEvent,
) -> None:
    target_region = decision["country_region"]
    if (
        target.pk != decision["target_id"]
        or target.race_series_id != decision["target_series_id"]
        or target.year != decision["year"]
        or target.country_region != target_region
        or target.race_series.country_region != target_region
        or event.pk != decision["event_id"]
        or event.race_series_id != decision["event_series_id"]
        or event.year != decision["year"]
        or event.country_region != event.race_series.country_region
        or (
            decision["decision"] != DECISION_IGNORE_FALSE_MATCH
            and (
                event.country_region != target_region
                or event.race_series.country_region != target_region
            )
        )
    ):
        raise RaceSeriesIdentityReviewError(
            f"decision identity drift: {decision['decision_id']}"
        )
    if target.race_series_id == event.race_series_id:
        raise RaceSeriesIdentityReviewError(
            f"decision series pair is not distinct: {decision['decision_id']}"
        )


def _build_actions(
    decisions: list[dict[str, Any]], repairs: list[dict[str, Any]]
) -> dict[str, Any]:
    target_ids = sorted({decision["target_id"] for decision in decisions})
    event_ids = sorted({decision["event_id"] for decision in decisions})
    targets = {
        target.pk: target
        for target in HistoricalRaceEventTarget.objects.select_related("race_series")
        .filter(pk__in=target_ids)
        .order_by("pk")
    }
    events = {
        event.pk: event
        for event in RaceEvent.objects.select_related("race_series")
        .filter(pk__in=event_ids)
        .order_by("pk")
    }
    if len(targets) != len(target_ids) or len(events) != len(event_ids):
        raise RaceSeriesIdentityReviewError("decision target or event does not exist")
    for decision in decisions:
        target = targets[decision["target_id"]]
        event = events[decision["event_id"]]
        expected_target_sha256 = decision.get("target_identity_sha256")
        expected_event_sha256 = decision.get("event_identity_sha256")
        expected_source_series_sha256 = decision.get(
            "source_series_identity_sha256"
        )
        expected_destination_series_sha256 = decision.get(
            "destination_series_identity_sha256"
        )
        if (
            expected_target_sha256 is not None
            and reconciliation_target_identity(target)["sha256"]
            != expected_target_sha256
        ):
            raise RaceSeriesIdentityReviewError(
                f"review target identity drift: {decision['decision_id']}"
            )
        if (
            expected_event_sha256 is not None
            and reconciliation_event_identity(event)["sha256"]
            != expected_event_sha256
        ):
            raise RaceSeriesIdentityReviewError(
                f"review event identity drift: {decision['decision_id']}"
            )
        if (
            expected_source_series_sha256 is not None
            and race_series_identity(event.race_series)["sha256"]
            != expected_source_series_sha256
        ):
            raise RaceSeriesIdentityReviewError(
                f"review source series identity drift: {decision['decision_id']}"
            )
        if (
            expected_destination_series_sha256 is not None
            and race_series_identity(target.race_series)["sha256"]
            != expected_destination_series_sha256
        ):
            raise RaceSeriesIdentityReviewError(
                f"review destination series identity drift: {decision['decision_id']}"
            )
        _validate_decision_identity(
            decision,
            target=target,
            event=event,
        )
        if (
            decision["decision"] == DECISION_MERGE_AND_LINK
            and is_identity_pair_do_not_merge(
                target.race_series, event.race_series
            )
        ):
            raise RaceSeriesIdentityReviewError(
                f"identity pair has do_not_merge veto: {decision['decision_id']}"
            )

    repairs_by_event: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for repair in repairs:
        repairs_by_event[repair["event_id"]].append(repair)
    positive_event_ids = {
        decision["event_id"]
        for decision in decisions
        if decision["decision"] == DECISION_MERGE_AND_LINK
    }
    if set(repairs_by_event) - positive_event_ids:
        raise RaceSeriesIdentityReviewError(
            "field repairs must bind a merge_and_link event"
        )

    positives: list[dict[str, Any]] = []
    positive_series_ids: set[int] = set()
    positive_pairs: set[tuple[int, int]] = set()
    used_positive_targets: set[int] = set()
    used_positive_events: set[int] = set()
    negative_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for decision in decisions:
        target = targets[decision["target_id"]]
        event = events[decision["event_id"]]
        if decision["decision"] in NEGATIVE_DECISIONS:
            pair = tuple(sorted((target.race_series_id, event.race_series_id)))
            negative_groups[pair].append(decision)
            continue
        if (
            target.pk in used_positive_targets
            or event.pk in used_positive_events
            or target.race_series_id in positive_series_ids
            or event.race_series_id in positive_series_ids
        ):
            raise RaceSeriesIdentityReviewError(
                "positive identity actions must use distinct targets, events, and series"
            )
        used_positive_targets.add(target.pk)
        used_positive_events.add(event.pk)
        positive_series_ids.update(
            {target.race_series_id, event.race_series_id}
        )
        positive_pairs.add(
            tuple(sorted((target.race_series_id, event.race_series_id)))
        )
        source_dependencies = _series_dependency_snapshot(event.race_series_id)
        expected_source_dependencies = {
            "annual_event_ids": [event.pk],
            "historical_target_ids": [],
            "name_ids": [],
            "relation_ids": [],
        }
        if source_dependencies != expected_source_dependencies:
            raise RaceSeriesIdentityReviewError(
                f"source series dependency conflict: {event.race_series_id}"
            )
        destination_year_events = _destination_year_event_ids(
            target.race_series_id, target.year
        )
        if destination_year_events:
            raise RaceSeriesIdentityReviewError(
                f"destination series/year conflict: {target.race_series_id}/{target.year}"
            )
        if target.event_id is not None:
            raise RaceSeriesIdentityReviewError(
                f"target already has an event: {target.pk}"
            )
        event_repairs = repairs_by_event.get(event.pk, [])
        for repair in event_repairs:
            if getattr(event, repair["field"]) != repair["expected_before"]:
                raise RaceSeriesIdentityReviewError(
                    f"field repair expected-before drift: {repair['repair_id']}"
                )
        target_before = _model_identity(target)
        event_before = _model_identity(event)
        target_after_payload = deepcopy(target_before["payload"])
        target_after_payload["event_id"] = event.pk
        event_after_payload = _event_payload_after_repairs(
            event_before["payload"],
            event_repairs,
            destination_series_id=target.race_series_id,
            destination_series_key=target.race_series.key,
        )
        positives.append(
            {
                "decision": decision,
                "target_id": target.pk,
                "event_id": event.pk,
                "source_series_id": event.race_series_id,
                "destination_series_id": target.race_series_id,
                "year": target.year,
                "target_before": target_before,
                "target_after": _identity(target_after_payload),
                "event_before": event_before,
                "event_after": _identity(event_after_payload),
                "event_detail": _event_detail_identity(event),
                "source_series": _model_identity(event.race_series),
                "destination_series": _model_identity(target.race_series),
                "source_dependencies": source_dependencies,
                "destination_year_event_ids": destination_year_events,
                "repairs": event_repairs,
                "relation_source_refs": {
                    "identity_review_decision_ids": [decision["decision_id"]],
                    "evidence": [decision["evidence"]],
                },
            }
        )

    for pair, pair_decisions in negative_groups.items():
        if pair in positive_pairs or len(
            {decision["decision"] for decision in pair_decisions}
        ) != 1:
            raise RaceSeriesIdentityReviewError(
                f"exact pair decisions conflict: {pair[0]}/{pair[1]}"
            )
        if any(
            decision["target_id"] in used_positive_targets
            for decision in pair_decisions
        ):
            raise RaceSeriesIdentityReviewError(
                f"positive/negative target evidence row conflict: {pair[0]}/{pair[1]}"
            )

    positive_event_after_identities = {
        int(action["event_id"]): action["event_after"] for action in positives
    }
    negative_series_ids = sorted(
        {series_id for pair in negative_groups for series_id in pair}
    )
    negative_series = {
        series.pk: series
        for series in RaceSeries.objects.filter(pk__in=negative_series_ids).order_by(
            "pk"
        )
    }
    if len(negative_series) != len(negative_series_ids):
        raise RaceSeriesIdentityReviewError("negative decision series does not exist")
    series_before = {
        series_id: _model_identity(series)
        for series_id, series in negative_series.items()
    }
    cumulative_flags = {
        series_id: deepcopy(series.manual_lock_flags)
        for series_id, series in negative_series.items()
    }
    negatives: list[dict[str, Any]] = []
    for pair, pair_decisions in sorted(negative_groups.items()):
        left_id, right_id = pair
        decision_rows: list[dict[str, Any]] = []
        for decision in pair_decisions:
            event = events[decision["event_id"]]
            event_identity = _model_identity(event)
            decision_rows.append(
                {
                    "decision": decision,
                    "target_id": decision["target_id"],
                    "event_id": decision["event_id"],
                    "target_identity": _model_identity(
                        targets[decision["target_id"]]
                    ),
                    "event_identity": event_identity,
                    "event_after_identity": positive_event_after_identities.get(
                        decision["event_id"], event_identity
                    ),
                    "event_detail": _event_detail_identity(event),
                }
            )
        cumulative_flags[left_id] = _flags_with_do_not_merge(
            cumulative_flags[left_id],
            other_series_id=right_id,
            decisions=pair_decisions,
        )
        cumulative_flags[right_id] = _flags_with_do_not_merge(
            cumulative_flags[right_id],
            other_series_id=left_id,
            decisions=pair_decisions,
        )
        negatives.append(
            {
                "left_series_id": left_id,
                "right_series_id": right_id,
                "decisions": pair_decisions,
                "decision_rows": decision_rows,
            }
        )

    series_after: dict[int, dict[str, Any]] = {}
    for series_id, before in series_before.items():
        after_payload = deepcopy(before["payload"])
        after_payload["manual_lock_flags"] = cumulative_flags[series_id]
        series_after[series_id] = _identity(after_payload)
    for action in negatives:
        left_id = action["left_series_id"]
        right_id = action["right_series_id"]
        action.update(
            {
                "left_before": series_before[left_id],
                "left_after": series_after[left_id],
                "right_before": series_before[right_id],
                "right_after": series_after[right_id],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "scope_baseline": {
            "series_ids": sorted(
                {
                    decision["target_series_id"]
                    for decision in decisions
                }
                | {
                    decision["event_series_id"]
                    for decision in decisions
                }
            ),
            "target_ids": target_ids,
            "event_ids": event_ids,
        },
        "positive_actions": positives,
        "negative_actions": negatives,
    }


def _publish_directory_no_replace(temporary: Path, destination: Path) -> None:
    try:
        os.mkdir(destination)
    except FileExistsError as exc:
        raise RaceSeriesIdentityReviewError(
            f"artifact output already exists: {destination}"
        ) from exc
    except OSError as exc:
        raise RaceSeriesIdentityReviewError(
            f"artifact output cannot be reserved: {destination}"
        ) from exc
    try:
        for source in sorted(temporary.iterdir(), key=lambda path: path.name):
            os.link(source, destination / source.name, follow_symlinks=False)
        for source in list(temporary.iterdir()):
            source.unlink()
        temporary.rmdir()
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def prepare_race_series_identity_review(
    *,
    decisions_path: str | Path,
    field_repairs_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    destination = Path(output_dir)
    decisions_bytes = _safe_read(Path(decisions_path), label="decisions input")
    repairs_bytes = _safe_read(Path(field_repairs_path), label="field repairs input")
    decisions_payload = _parse_object(decisions_bytes, label="decisions input")
    repairs_payload = _parse_object(repairs_bytes, label="field repairs input")
    decisions = _normalize_decisions(decisions_payload)
    repairs = _normalize_repairs(repairs_payload)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    try:
        with transaction.atomic():
            _set_repeatable_read_snapshot()
            actions = _build_actions(decisions, repairs)
        decision_counts = dict(
            sorted(Counter(row["decision"] for row in decisions).items())
        )
        summary = {
            "schema_version": SCHEMA_VERSION,
            "decision_count": len(decisions),
            "decision_counts": decision_counts,
            "positive_action_count": len(actions["positive_actions"]),
            "negative_pair_count": len(actions["negative_actions"]),
            "field_repair_count": len(repairs),
        }
        review = {
            "schema_version": SCHEMA_VERSION,
            "status": "prepared",
            "decisions": decisions,
            "field_repairs": repairs,
        }
        payloads = {
            "actions.json": _canonical_bytes(actions),
            "decisions.normalized.jsonl": b"".join(
                _canonical_bytes(row) for row in decisions
            ),
            "input.decisions.json": decisions_bytes,
            "input.field_repairs.json": repairs_bytes,
            "review.json": _canonical_bytes(review),
            "summary.json": _canonical_bytes(summary),
        }
        for name, payload in payloads.items():
            (temporary / name).write_bytes(payload)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": timezone.now().isoformat(),
            "artifacts": {
                name: _artifact_identity(name, payload)
                for name, payload in sorted(payloads.items())
            },
            "summary": summary,
        }
        manifest_bytes = _canonical_bytes(manifest)
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        approval = {
            "schema_version": SCHEMA_VERSION,
            "status": "pending",
            "approved_by": "",
            "approved_at": "",
            "manifest_sha256": manifest_sha256,
        }
        approval_bytes = _canonical_bytes(approval)
        (temporary / "approval.json").write_bytes(approval_bytes)
        _publish_directory_no_replace(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "output_dir": str(destination),
        "manifest_sha256": manifest_sha256,
        "approval_sha256": _sha256_bytes(approval_bytes),
        **summary,
    }


def _load_artifacts(
    artifact_dir: str | Path, expected_manifest_sha256: str
) -> VerifiedIdentityReviewArtifacts:
    root = Path(artifact_dir)
    try:
        if root.is_symlink() or not root.is_dir():
            raise RaceSeriesIdentityReviewError(
                "artifact directory must be a real directory"
            )
    except OSError as exc:
        raise RaceSeriesIdentityReviewError(
            "artifact directory cannot be safely inspected"
        ) from exc
    manifest_bytes = _safe_read(root / "manifest.json", label="manifest")
    if _sha256_bytes(manifest_bytes) != expected_manifest_sha256:
        raise RaceSeriesIdentityReviewError("manifest SHA-256 mismatch")
    manifest = _parse_object(manifest_bytes, label="manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RaceSeriesIdentityReviewError("unsupported identity review manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != MANIFEST_ARTIFACTS:
        raise RaceSeriesIdentityReviewError(
            "manifest artifact set is incomplete or unexpected"
        )
    artifact_bytes: dict[str, bytes] = {}
    for name in sorted(MANIFEST_ARTIFACTS):
        descriptor = artifacts.get(name)
        if (
            not isinstance(descriptor, dict)
            or descriptor.get("path") != name
            or Path(name).name != name
        ):
            raise RaceSeriesIdentityReviewError(
                "manifest artifact key/path binding mismatch"
            )
        payload = _safe_read(root / name, label=f"artifact {name}")
        if (
            len(payload) != descriptor.get("size")
            or _sha256_bytes(payload) != descriptor.get("sha256")
        ):
            raise RaceSeriesIdentityReviewError(
                f"manifest artifact identity mismatch: {name}"
            )
        artifact_bytes[name] = payload
    actions = _parse_object(artifact_bytes["actions.json"], label="actions")
    if actions.get("schema_version") != SCHEMA_VERSION:
        raise RaceSeriesIdentityReviewError("unsupported identity review actions")
    if not isinstance(actions.get("positive_actions"), list) or not isinstance(
        actions.get("negative_actions"), list
    ):
        raise RaceSeriesIdentityReviewError("identity review actions are malformed")
    return VerifiedIdentityReviewArtifacts(root, manifest, artifact_bytes, actions)


def _load_approval(
    *,
    approval_path: str | Path,
    expected_approval_sha256: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    approval_bytes = _safe_read(Path(approval_path), label="approval")
    if _sha256_bytes(approval_bytes) != expected_approval_sha256:
        raise RaceSeriesIdentityReviewError("approval SHA-256 mismatch")
    approval = _parse_object(approval_bytes, label="approval")
    if (
        approval.get("schema_version") != SCHEMA_VERSION
        or approval.get("status") != "approved"
        or not str(approval.get("approved_by") or "").strip()
        or not str(approval.get("approved_at") or "").strip()
        or approval.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise RaceSeriesIdentityReviewError(
            "approval is incomplete or binds a different manifest"
        )
    try:
        approved_at = datetime.fromisoformat(
            str(approval["approved_at"]).replace("Z", "+00:00")
        )
        if approved_at.tzinfo is None or approved_at.utcoffset() is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise RaceSeriesIdentityReviewError("approval timestamp is invalid") from exc
    approval["approved_at_parsed"] = approved_at
    return approval


def _actor_username(actor) -> str:
    if actor is None or not getattr(actor, "pk", None):
        raise RaceSeriesIdentityReviewError("actor is required")
    username = str(actor.get_username() or "").strip()
    if not username:
        raise RaceSeriesIdentityReviewError("actor username is required")
    return username


def _require_actor_matches_approval(actor, approval: dict[str, Any]) -> str:
    username = _actor_username(actor)
    if username != str(approval["approved_by"]).strip():
        raise RaceSeriesIdentityReviewError(
            "actor username does not match approval"
        )
    return username


def _identity_rows_for_update(model, ids: set[int]):
    return (
        model.objects.select_for_update(of=("self",))
        .select_related("race_series")
        .filter(pk__in=ids)
        .order_by("pk")
    )


def _lock_action_rows(actions: dict[str, Any]) -> tuple[
    dict[int, RaceSeries],
    dict[int, HistoricalRaceEventTarget],
    dict[int, RaceEvent],
]:
    series_ids: set[int] = set()
    target_ids: set[int] = set()
    event_ids: set[int] = set()
    for action in actions["positive_actions"]:
        series_ids.update(
            {
                int(action["source_series_id"]),
                int(action["destination_series_id"]),
            }
        )
        target_ids.add(int(action["target_id"]))
        event_ids.add(int(action["event_id"]))
    for action in actions["negative_actions"]:
        series_ids.update(
            {int(action["left_series_id"]), int(action["right_series_id"])}
        )
        for row in action["decision_rows"]:
            target_ids.add(int(row["target_id"]))
            event_ids.add(int(row["event_id"]))
    series = {
        row.pk: row
        for row in RaceSeries.objects.select_for_update()
        .filter(pk__in=series_ids)
        .order_by("pk")
    }
    targets = {
        row.pk: row
        for row in _identity_rows_for_update(
            HistoricalRaceEventTarget,
            target_ids,
        )
    }
    events = {
        row.pk: row
        for row in _identity_rows_for_update(
            RaceEvent,
            event_ids,
        )
    }
    if (
        len(series) != len(series_ids)
        or len(targets) != len(target_ids)
        or len(events) != len(event_ids)
    ):
        raise RaceSeriesIdentityReviewError("identity review row drift or deletion")
    return series, targets, events


def _same_identity(current, expected: dict[str, Any]) -> bool:
    return _model_identity(current)["sha256"] == expected.get("sha256")


def _preflight_actions(
    actions: dict[str, Any],
    *,
    series: dict[int, RaceSeries],
    targets: dict[int, HistoricalRaceEventTarget],
    events: dict[int, RaceEvent],
) -> None:
    if actions.get("scope_baseline") != {
        "series_ids": sorted(series),
        "target_ids": sorted(targets),
        "event_ids": sorted(events),
    }:
        raise RaceSeriesIdentityReviewError("scoped baseline drift before apply")
    for action in actions["positive_actions"]:
        target = targets[int(action["target_id"])]
        event = events[int(action["event_id"])]
        source = series[int(action["source_series_id"])]
        destination = series[int(action["destination_series_id"])]
        if not _same_identity(target, action["target_before"]):
            raise RaceSeriesIdentityReviewError(
                f"target identity drift: {target.pk}"
            )
        if not _same_identity(event, action["event_before"]):
            raise RaceSeriesIdentityReviewError(
                f"event identity drift: {event.pk}"
            )
        if not _same_identity(source, action["source_series"]):
            raise RaceSeriesIdentityReviewError(
                f"source series identity drift: {source.pk}"
            )
        if not _same_identity(destination, action["destination_series"]):
            raise RaceSeriesIdentityReviewError(
                f"destination series identity drift: {destination.pk}"
            )
        if (
            _series_dependency_snapshot(source.pk)
            != action["source_dependencies"]
        ):
            raise RaceSeriesIdentityReviewError(
                f"source series dependency drift: {source.pk}"
            )
        if (
            _destination_year_event_ids(destination.pk, int(action["year"]))
            != action["destination_year_event_ids"]
        ):
            raise RaceSeriesIdentityReviewError(
                f"destination series/year conflict: {destination.pk}/{action['year']}"
            )
        if (
            target.event_id is not None
            or event.race_series_id != source.pk
            or target.race_series_id != destination.pk
            or target.year != event.year
        ):
            raise RaceSeriesIdentityReviewError(
                f"positive identity conflict: {action['decision']['decision_id']}"
            )
        if _event_detail_identity(event)["sha256"] != action["event_detail"]["sha256"]:
            raise RaceSeriesIdentityReviewError(
                f"event detail drift: {event.pk}"
            )
    for action in actions["negative_actions"]:
        left = series[int(action["left_series_id"])]
        right = series[int(action["right_series_id"])]
        left_sha = _model_identity(left)["sha256"]
        right_sha = _model_identity(right)["sha256"]
        if left_sha not in {
            action["left_before"]["sha256"],
            action["left_after"]["sha256"],
        }:
            raise RaceSeriesIdentityReviewError(
                f"negative series identity drift: {left.pk}"
            )
        if right_sha not in {
            action["right_before"]["sha256"],
            action["right_after"]["sha256"],
        }:
            raise RaceSeriesIdentityReviewError(
                f"negative series identity drift: {right.pk}"
            )
        for row in action["decision_rows"]:
            target = targets[int(row["target_id"])]
            event = events[int(row["event_id"])]
            if not _same_identity(target, row["target_identity"]):
                raise RaceSeriesIdentityReviewError(
                    f"negative target identity drift: {target.pk}"
                )
            if not _same_identity(event, row["event_identity"]):
                raise RaceSeriesIdentityReviewError(
                    f"negative event identity drift: {event.pk}"
                )
            if (
                _event_detail_identity(event)["sha256"]
                != row["event_detail"]["sha256"]
            ):
                raise RaceSeriesIdentityReviewError(
                    f"negative event detail drift: {event.pk}"
                )
            _validate_decision_identity(
                row["decision"], target=target, event=event
            )


def _apply_positive_action(
    action: dict[str, Any],
    *,
    actor,
    approved_at: datetime,
    source: RaceSeries,
    destination: RaceSeries,
    target: HistoricalRaceEventTarget,
    event: RaceEvent,
) -> tuple[RaceSeriesRelation, dict[str, Any]]:
    relation = RaceSeriesRelation.objects.create(
        from_series=source,
        to_series=destination,
        relation_type=RaceSeriesRelationType.MERGED_INTO,
        source_refs=action["relation_source_refs"],
        review_status=RaceSeriesReviewStatus.APPROVED,
        approved_by=actor,
        approved_at=approved_at,
    )
    target.event_id = event.pk
    target.save(update_fields={"event"})
    after_payload = action["event_after"]["payload"]
    event.race_series_id = destination.pk
    event.series_key = destination.key
    update_fields = {"race_series", "series_key"}
    for repair in action["repairs"]:
        setattr(event, repair["field"], after_payload[repair["field"]])
        update_fields.add(repair["field"])
    if action["repairs"]:
        event.source_refs = deepcopy(after_payload["source_refs"])
        event.manual_lock_flags = deepcopy(after_payload["manual_lock_flags"])
        update_fields.update({"source_refs", "manual_lock_flags"})
    event.save(update_fields=update_fields)
    if not _same_identity(target, action["target_after"]):
        raise RaceSeriesIdentityReviewError(
            f"post-apply target identity mismatch: {target.pk}"
        )
    if not _same_identity(event, action["event_after"]):
        raise RaceSeriesIdentityReviewError(
            f"post-apply event identity mismatch: {event.pk}"
        )
    if _event_detail_identity(event)["sha256"] != action["event_detail"]["sha256"]:
        raise RaceSeriesIdentityReviewError(
            f"post-apply event detail mismatch: {event.pk}"
        )
    return relation, {
        "target_before": action["target_before"],
        "target_after": _model_identity(target),
        "event_before": action["event_before"],
        "event_after": _model_identity(event),
        "event_detail_before": action["event_detail"],
        "event_detail_after": _event_detail_identity(event),
        "relation_identity": _model_identity(relation),
    }


def _apply_negative_action(
    action: dict[str, Any],
    *,
    left: RaceSeries,
    right: RaceSeries,
) -> dict[str, Any]:
    left_before_apply = _model_identity(left)
    right_before_apply = _model_identity(right)
    if left_before_apply["sha256"] != action["left_after"]["sha256"]:
        left.manual_lock_flags = deepcopy(
            action["left_after"]["payload"]["manual_lock_flags"]
        )
        left.save(update_fields={"manual_lock_flags"})
    if right_before_apply["sha256"] != action["right_after"]["sha256"]:
        right.manual_lock_flags = deepcopy(
            action["right_after"]["payload"]["manual_lock_flags"]
        )
        right.save(update_fields={"manual_lock_flags"})
    if not _same_identity(left, action["left_after"]) or not _same_identity(
        right, action["right_after"]
    ):
        raise RaceSeriesIdentityReviewError("post-apply negative lock mismatch")
    return {
        "left_series_id": left.pk,
        "right_series_id": right.pk,
        "left_before_artifact": action["left_before"],
        "right_before_artifact": action["right_before"],
        "left_before_apply": left_before_apply,
        "right_before_apply": right_before_apply,
        "left_after": _model_identity(left),
        "right_after": _model_identity(right),
        "decision_rows": [
            {
                "target_id": row["target_id"],
                "event_id": row["event_id"],
                "target_identity": row["target_identity"],
                "event_identity": row["event_identity"],
                "event_after_identity": row["event_after_identity"],
                "event_detail": row["event_detail"],
            }
            for row in action["decision_rows"]
        ],
    }


def _verify_actions(
    actions: dict[str, Any], *, expected_state: str
) -> dict[str, Any]:
    if expected_state not in {"prepared", "applied", "rolled_back"}:
        raise RaceSeriesIdentityReviewError("unsupported verifier state")
    errors: list[str] = []
    for action in actions["positive_actions"]:
        target = HistoricalRaceEventTarget.objects.filter(
            pk=action["target_id"]
        ).first()
        event = RaceEvent.objects.filter(pk=action["event_id"]).first()
        if target is None or event is None:
            errors.append(f"positive row missing: {action['target_id']}/{action['event_id']}")
            continue
        expected_target = (
            action["target_after"]
            if expected_state == "applied"
            else action["target_before"]
        )
        expected_event = (
            action["event_after"]
            if expected_state == "applied"
            else action["event_before"]
        )
        if not _same_identity(target, expected_target):
            errors.append(f"target identity mismatch: {target.pk}")
        if not _same_identity(event, expected_event):
            errors.append(f"event identity mismatch: {event.pk}")
        if _event_detail_identity(event)["sha256"] != action["event_detail"]["sha256"]:
            errors.append(f"event detail mismatch: {event.pk}")
        relation_query = RaceSeriesRelation.objects.filter(
            from_series_id=action["source_series_id"],
            to_series_id=action["destination_series_id"],
            relation_type=RaceSeriesRelationType.MERGED_INTO,
        )
        if expected_state == "applied":
            relation = relation_query.first()
            if (
                relation is None
                or relation.review_status != RaceSeriesReviewStatus.APPROVED
                or relation.approved_by_id is None
                or relation.approved_at is None
                or relation.source_refs != action["relation_source_refs"]
            ):
                errors.append(
                    f"approved merge relation mismatch: {action['source_series_id']}"
                )
            source_dependencies = _series_dependency_snapshot(
                int(action["source_series_id"])
            )
            expected_relation_ids = [relation.pk] if relation is not None else []
            if source_dependencies != {
                "annual_event_ids": [],
                "historical_target_ids": [],
                "name_ids": [],
                "relation_ids": expected_relation_ids,
            }:
                errors.append(
                    f"source dependency mismatch: {action['source_series_id']}"
                )
            if _destination_year_event_ids(
                int(action["destination_series_id"]), int(action["year"])
            ) != [int(action["event_id"])]:
                errors.append(
                    f"destination year mismatch: {action['destination_series_id']}"
                )
        else:
            if relation_query.exists():
                errors.append(
                    f"merge relation unexpectedly exists: {action['source_series_id']}"
                )
            if (
                _series_dependency_snapshot(int(action["source_series_id"]))
                != action["source_dependencies"]
            ):
                errors.append(
                    f"source dependency mismatch: {action['source_series_id']}"
                )
            if (
                _destination_year_event_ids(
                    int(action["destination_series_id"]), int(action["year"])
                )
                != action["destination_year_event_ids"]
            ):
                errors.append(
                    f"destination year mismatch: {action['destination_series_id']}"
                )
    for action in actions["negative_actions"]:
        left = RaceSeries.objects.filter(pk=action["left_series_id"]).first()
        right = RaceSeries.objects.filter(pk=action["right_series_id"]).first()
        if left is None or right is None:
            errors.append(
                f"negative series missing: {action['left_series_id']}/{action['right_series_id']}"
            )
            continue
        expected_left = (
            action["left_after"]
            if expected_state == "applied"
            else action["left_before"]
        )
        expected_right = (
            action["right_after"]
            if expected_state == "applied"
            else action["right_before"]
        )
        if not _same_identity(left, expected_left):
            errors.append(f"negative left identity mismatch: {left.pk}")
        if not _same_identity(right, expected_right):
            errors.append(f"negative right identity mismatch: {right.pk}")
        if expected_state == "applied" and not is_identity_pair_do_not_merge(
            left, right
        ):
            errors.append(f"negative pair helper mismatch: {left.pk}/{right.pk}")
        for row in action["decision_rows"]:
            target = HistoricalRaceEventTarget.objects.filter(
                pk=row["target_id"]
            ).first()
            event = RaceEvent.objects.filter(pk=row["event_id"]).first()
            if target is None or event is None:
                errors.append(
                    f"negative evidence row missing: {row['target_id']}/{row['event_id']}"
                )
                continue
            if not _same_identity(target, row["target_identity"]):
                errors.append(
                    f"negative target identity mismatch: {target.pk}"
                )
            expected_event = (
                row["event_after_identity"]
                if expected_state == "applied"
                else row["event_identity"]
            )
            if not _same_identity(event, expected_event):
                errors.append(
                    f"negative event identity mismatch: {event.pk}"
                )
            if (
                _event_detail_identity(event)["sha256"]
                != row["event_detail"]["sha256"]
            ):
                errors.append(f"negative event detail mismatch: {event.pk}")
    return {"ok": not errors, "error_count": len(errors), "errors": errors}


def verify_race_series_identity_review(
    *,
    artifact_dir: str | Path,
    expected_manifest_sha256: str,
    expected_state: str = "applied",
) -> dict[str, Any]:
    loaded = _load_artifacts(artifact_dir, expected_manifest_sha256)
    return _verify_actions(loaded.actions, expected_state=expected_state)


def apply_race_series_identity_review(
    *,
    artifact_dir: str | Path,
    expected_manifest_sha256: str,
    approval_path: str | Path,
    expected_approval_sha256: str,
    actor,
    rollback_path: str | Path | None = None,
) -> dict[str, Any]:
    loaded = _load_artifacts(artifact_dir, expected_manifest_sha256)
    approval = _load_approval(
        approval_path=approval_path,
        expected_approval_sha256=expected_approval_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    actor_username = _require_actor_matches_approval(actor, approval)
    ledger_path = (
        Path(rollback_path)
        if rollback_path is not None
        else loaded.root / "rollback.jsonl"
    )
    try:
        prepared = _prepare_rollback_ledger(ledger_path)
    except RaceEventReconciliationError as exc:
        raise RaceSeriesIdentityReviewError(str(exc)) from exc
    positive_ledger: list[dict[str, Any]] = []
    negative_ledger: list[dict[str, Any]] = []
    try:
        with transaction.atomic():
            _set_repeatable_read_snapshot()
            series, targets, events = _lock_action_rows(loaded.actions)
            _preflight_actions(
                loaded.actions,
                series=series,
                targets=targets,
                events=events,
            )
            for action in loaded.actions["positive_actions"]:
                relation, snapshots = _apply_positive_action(
                    action,
                    actor=actor,
                    approved_at=approval["approved_at_parsed"],
                    source=series[int(action["source_series_id"])],
                    destination=series[int(action["destination_series_id"])],
                    target=targets[int(action["target_id"])],
                    event=events[int(action["event_id"])],
                )
                positive_ledger.append(
                    {
                        "target_id": int(action["target_id"]),
                        "event_id": int(action["event_id"]),
                        "source_series_id": int(action["source_series_id"]),
                        "destination_series_id": int(
                            action["destination_series_id"]
                        ),
                        "relation_id": relation.pk,
                        **snapshots,
                    }
                )
            for action in loaded.actions["negative_actions"]:
                negative_ledger.append(
                    _apply_negative_action(
                        action,
                        left=series[int(action["left_series_id"])],
                        right=series[int(action["right_series_id"])],
                    )
                )
            verification = _verify_actions(
                loaded.actions, expected_state="applied"
            )
            if not verification["ok"]:
                raise RaceSeriesIdentityReviewError(
                    "post-apply verifier failed: "
                    + "; ".join(verification["errors"])
                )
            OperationLog.objects.create(
                admin=actor,
                action_type="race_series_identity_review_applied",
                target_type="race_series_identity_review",
                target_id=expected_manifest_sha256[:16],
                detail=json.dumps(
                    {
                        "manifest_sha256": expected_manifest_sha256,
                        "actor_username": actor_username,
                        "positive_count": len(positive_ledger),
                        "negative_pair_count": len(negative_ledger),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            ledger = {
                "schema_version": SCHEMA_VERSION,
                "manifest_sha256": expected_manifest_sha256,
                "actor_username": actor_username,
                "positive_actions": positive_ledger,
                "negative_actions": negative_ledger,
            }
            try:
                rollback_sha256 = _publish_prepared_ledger(prepared, [ledger])
            except RaceEventReconciliationError as exc:
                raise RaceSeriesIdentityReviewError(str(exc)) from exc
    except Exception:
        _cleanup_prepared_ledger(prepared, remove_published=True)
        raise
    else:
        _cleanup_prepared_ledger(prepared)
    return {
        "positive_count": len(positive_ledger),
        "negative_pair_count": len(negative_ledger),
        "rollback_path": str(ledger_path),
        "rollback_sha256": rollback_sha256,
        "verification": verification,
    }


def _read_single_rollback_row(payload: bytes) -> dict[str, Any]:
    rows = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RaceSeriesIdentityReviewError(
                f"invalid rollback row: {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise RaceSeriesIdentityReviewError(
                f"invalid rollback row: {line_number}"
            )
        rows.append(row)
    if len(rows) != 1:
        raise RaceSeriesIdentityReviewError(
            "rollback ledger must contain exactly one batch row"
        )
    return rows[0]


def _validate_rollback_ledger_identity(
    ledger: dict[str, Any], actions: dict[str, Any]
) -> None:
    positive_rows = ledger.get("positive_actions")
    negative_rows = ledger.get("negative_actions")
    if (
        not isinstance(positive_rows, list)
        or not isinstance(negative_rows, list)
        or len(positive_rows) != len(actions["positive_actions"])
        or len(negative_rows) != len(actions["negative_actions"])
    ):
        raise RaceSeriesIdentityReviewError(
            "rollback ledger action scope does not match manifest"
        )
    for row, action in zip(positive_rows, actions["positive_actions"], strict=True):
        if (
            int(row.get("target_id", 0)) != int(action["target_id"])
            or int(row.get("event_id", 0)) != int(action["event_id"])
            or int(row.get("source_series_id", 0))
            != int(action["source_series_id"])
            or int(row.get("destination_series_id", 0))
            != int(action["destination_series_id"])
            or row.get("target_before") != action["target_before"]
            or row.get("event_before") != action["event_before"]
            or row.get("event_detail_before") != action["event_detail"]
        ):
            raise RaceSeriesIdentityReviewError(
                "rollback ledger positive identity does not match manifest"
            )
    for row, action in zip(negative_rows, actions["negative_actions"], strict=True):
        expected_decision_rows = [
            {
                "target_id": decision_row["target_id"],
                "event_id": decision_row["event_id"],
                "target_identity": decision_row["target_identity"],
                "event_identity": decision_row["event_identity"],
                "event_after_identity": decision_row["event_after_identity"],
                "event_detail": decision_row["event_detail"],
            }
            for decision_row in action["decision_rows"]
        ]
        if (
            int(row.get("left_series_id", 0))
            != int(action["left_series_id"])
            or int(row.get("right_series_id", 0))
            != int(action["right_series_id"])
            or row.get("left_before_artifact") != action["left_before"]
            or row.get("right_before_artifact") != action["right_before"]
            or row.get("left_after") != action["left_after"]
            or row.get("right_after") != action["right_after"]
            or row.get("decision_rows") != expected_decision_rows
        ):
            raise RaceSeriesIdentityReviewError(
                "rollback ledger negative identity does not match manifest"
            )


def _require_sha(instance, expected: dict[str, Any], *, label: str) -> None:
    if _model_identity(instance)["sha256"] != expected.get("sha256"):
        raise RaceSeriesIdentityReviewError(label)


def rollback_race_series_identity_review(
    *,
    artifact_dir: str | Path,
    expected_manifest_sha256: str,
    approval_path: str | Path,
    expected_approval_sha256: str,
    rollback_path: str | Path,
    expected_rollback_sha256: str,
    actor,
) -> dict[str, Any]:
    loaded = _load_artifacts(artifact_dir, expected_manifest_sha256)
    approval = _load_approval(
        approval_path=approval_path,
        expected_approval_sha256=expected_approval_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    actor_username = _require_actor_matches_approval(actor, approval)
    rollback_bytes = _safe_read(Path(rollback_path), label="rollback ledger")
    if _sha256_bytes(rollback_bytes) != expected_rollback_sha256:
        raise RaceSeriesIdentityReviewError("rollback ledger SHA-256 mismatch")
    ledger = _read_single_rollback_row(rollback_bytes)
    if (
        ledger.get("schema_version") != SCHEMA_VERSION
        or ledger.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise RaceSeriesIdentityReviewError(
            "rollback ledger binds a different manifest"
        )
    if ledger.get("actor_username") != str(approval["approved_by"]).strip():
        raise RaceSeriesIdentityReviewError(
            "rollback ledger actor does not match approval"
        )

    positive_rows = ledger.get("positive_actions")
    negative_rows = ledger.get("negative_actions")
    if not isinstance(positive_rows, list) or not isinstance(negative_rows, list):
        raise RaceSeriesIdentityReviewError("rollback ledger is malformed")
    _validate_rollback_ledger_identity(ledger, loaded.actions)
    positive_target_ids = [int(row["target_id"]) for row in positive_rows]
    positive_event_ids = [int(row["event_id"]) for row in positive_rows]
    negative_decision_rows = [
        decision_row
        for row in negative_rows
        for decision_row in row["decision_rows"]
    ]
    target_ids = sorted(
        set(positive_target_ids)
        | {int(row["target_id"]) for row in negative_decision_rows}
    )
    event_ids = sorted(
        set(positive_event_ids)
        | {int(row["event_id"]) for row in negative_decision_rows}
    )
    relation_ids = [int(row["relation_id"]) for row in positive_rows]
    series_ids = {
        int(row["source_series_id"]) for row in positive_rows
    } | {
        int(row["destination_series_id"]) for row in positive_rows
    }
    for row in negative_rows:
        series_ids.update(
            {int(row["left_series_id"]), int(row["right_series_id"])}
        )
    if (
        len(positive_target_ids) != len(set(positive_target_ids))
        or len(positive_event_ids) != len(set(positive_event_ids))
        or len(relation_ids) != len(set(relation_ids))
    ):
        raise RaceSeriesIdentityReviewError("rollback ledger contains duplicates")

    with transaction.atomic():
        _set_repeatable_read_snapshot()
        series = {
            row.pk: row
            for row in RaceSeries.objects.select_for_update()
            .filter(pk__in=series_ids)
            .order_by("pk")
        }
        targets = {
            row.pk: row
            for row in HistoricalRaceEventTarget.objects.select_for_update()
            .filter(pk__in=target_ids)
            .order_by("pk")
        }
        events = {
            row.pk: row
            for row in RaceEvent.objects.select_for_update()
            .filter(pk__in=event_ids)
            .order_by("pk")
        }
        relations = {
            row.pk: row
            for row in RaceSeriesRelation.objects.select_for_update()
            .filter(pk__in=relation_ids)
            .order_by("pk")
        }
        if (
            len(series) != len(series_ids)
            or len(targets) != len(target_ids)
            or len(events) != len(event_ids)
            or len(relations) != len(relation_ids)
        ):
            raise RaceSeriesIdentityReviewError(
                "rollback identity row drift or deletion"
            )
        for row in positive_rows:
            target = targets[int(row["target_id"])]
            event = events[int(row["event_id"])]
            relation = relations[int(row["relation_id"])]
            _require_sha(
                target,
                row["target_after"],
                label=f"target drift before rollback: {target.pk}",
            )
            _require_sha(
                event,
                row["event_after"],
                label=f"event drift before rollback: {event.pk}",
            )
            if (
                _event_detail_identity(event)["sha256"]
                != row["event_detail_after"]["sha256"]
            ):
                raise RaceSeriesIdentityReviewError(
                    f"event detail drift before rollback: {event.pk}"
                )
            _require_sha(
                relation,
                row["relation_identity"],
                label=f"relation drift before rollback: {relation.pk}",
            )
        for row in negative_rows:
            left = series[int(row["left_series_id"])]
            right = series[int(row["right_series_id"])]
            _require_sha(
                left,
                row["left_after"],
                label=f"negative left drift before rollback: {left.pk}",
            )
            _require_sha(
                right,
                row["right_after"],
                label=f"negative right drift before rollback: {right.pk}",
            )
            for decision_row in row["decision_rows"]:
                target = targets[int(decision_row["target_id"])]
                event = events[int(decision_row["event_id"])]
                _require_sha(
                    target,
                    decision_row["target_identity"],
                    label=f"negative target drift before rollback: {target.pk}",
                )
                _require_sha(
                    event,
                    decision_row["event_after_identity"],
                    label=f"negative event drift before rollback: {event.pk}",
                )
                if (
                    _event_detail_identity(event)["sha256"]
                    != decision_row["event_detail"]["sha256"]
                ):
                    raise RaceSeriesIdentityReviewError(
                        f"negative event detail drift before rollback: {event.pk}"
                    )

        for row in reversed(positive_rows):
            relation = relations[int(row["relation_id"])]
            relation.delete()
            target = targets[int(row["target_id"])]
            event = events[int(row["event_id"])]
            target.event_id = row["target_before"]["payload"]["event_id"]
            target.save(update_fields={"event"})
            before_event = row["event_before"]["payload"]
            event.race_series_id = before_event["race_series_id"]
            event.series_key = before_event["series_key"]
            update_fields = {"race_series", "series_key"}
            if event.surface != before_event["surface"]:
                event.surface = before_event["surface"]
                update_fields.add("surface")
            if event.source_refs != before_event["source_refs"]:
                event.source_refs = deepcopy(before_event["source_refs"])
                update_fields.add("source_refs")
            if event.manual_lock_flags != before_event["manual_lock_flags"]:
                event.manual_lock_flags = deepcopy(before_event["manual_lock_flags"])
                update_fields.add("manual_lock_flags")
            event.save(update_fields=update_fields)
        for row in reversed(negative_rows):
            left = series[int(row["left_series_id"])]
            right = series[int(row["right_series_id"])]
            left.manual_lock_flags = deepcopy(
                row["left_before_apply"]["payload"]["manual_lock_flags"]
            )
            right.manual_lock_flags = deepcopy(
                row["right_before_apply"]["payload"]["manual_lock_flags"]
            )
            left.save(update_fields={"manual_lock_flags"})
            right.save(update_fields={"manual_lock_flags"})

        verification = _verify_actions(
            loaded.actions, expected_state="rolled_back"
        )
        if not verification["ok"]:
            raise RaceSeriesIdentityReviewError(
                "post-rollback verifier failed: "
                + "; ".join(verification["errors"])
            )
        OperationLog.objects.create(
            admin=actor,
            action_type="race_series_identity_review_rolled_back",
            target_type="race_series_identity_review",
            target_id=expected_manifest_sha256[:16],
            detail=json.dumps(
                {
                    "manifest_sha256": expected_manifest_sha256,
                    "actor_username": actor_username,
                    "positive_count": len(positive_rows),
                    "negative_pair_count": len(negative_rows),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    return {
        "positive_count": len(positive_rows),
        "negative_pair_count": len(negative_rows),
        "verification": verification,
    }
