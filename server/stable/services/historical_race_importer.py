from __future__ import annotations

from typing import Any
import unicodedata

from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEventHistoryWinner,
    RaceEventModule,
    TermAlias,
    TermEntry,
    TermType,
)
from stable.services.historical_race_batches import target_identity
from stable.services.historical_race_inventory import (
    InventoryValidationError,
    canonical_json,
    merge_authoritative_fields,
)
from stable.services.race_events import apply_data_candidate, save_data_candidate


RUNNER_DERIVED_FIELDS = (
    "horse_number",
    "barrier",
    "horse_name",
    "jockey_name",
    "trainer_name",
    "carried_weight",
    "odds_value",
    "popularity",
    "running_status",
)
CHAMPION_SUPPLEMENT_AUTHORITIES = {"official", "official_current", "official_archive", "high_trust_database"}
UPDATABLE_BASIC_FIELDS = (
    "original_name",
    "chinese_name",
    "racecourse",
    "grade_text",
    "normalized_grade",
    "surface",
    "distance_text",
    "local_date",
)


def derive_runners_from_complete_results(result_payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not result_payload.get("is_complete"):
        raise InventoryValidationError("partial results cannot be used to derive runners")
    items = result_payload.get("items")
    if not isinstance(items, list) or not items:
        raise InventoryValidationError("complete result payload has no rows")
    runners = []
    for index, result in enumerate(items, start=1):
        if not isinstance(result, dict) or not str(result.get("horse_name") or "").strip():
            raise InventoryValidationError("complete result payload contains an invalid horse row")
        source_refs = dict(result.get("source_refs") or {})
        source_refs["derived_from_results"] = True
        runners.append(
            {
                **{field: result.get(field, "") for field in RUNNER_DERIVED_FIELDS},
                "sort_order": index,
                "source_refs": source_refs,
            }
        )
    return runners


def _nonempty_field_counts(items: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, int]:
    return {
        field: sum(item.get(field) not in (None, "", [], {}) for item in items)
        for field in fields
    }


def _term_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def historical_race_term_gaps(target: HistoricalRaceEventTarget) -> list[dict[str, str]]:
    values_by_type = {
        TermType.HORSE: {
            str(value).strip()
            for value in target.event.runners.values_list("horse_name", flat=True)
            if str(value).strip()
        }
        | {
            str(value).strip()
            for value in target.event.results.values_list("horse_name", flat=True)
            if str(value).strip()
        },
        TermType.JOCKEY: {
            str(value).strip()
            for value in target.event.runners.values_list("jockey_name", flat=True)
            if str(value).strip()
        }
        | {
            str(value).strip()
            for value in target.event.results.values_list("jockey_name", flat=True)
            if str(value).strip()
        },
    }
    query_values = {_term_identity(value) for values in values_by_type.values() for value in values}
    matched: set[tuple[str, str]] = set()
    if query_values:
        for term in (
            TermEntry.objects.filter(is_active=True, term_type__in=values_by_type)
            .annotate(identity=Lower("source_ja"))
            .filter(identity__in=query_values)
        ):
            matched.add((term.term_type, _term_identity(term.source_ja)))
        for alias in (
            TermAlias.objects.select_related("term")
            .filter(is_active=True, term__is_active=True, term__term_type__in=values_by_type)
            .annotate(identity=Lower("text"))
            .filter(identity__in=query_values)
        ):
            matched.add((alias.term.term_type, _term_identity(alias.text)))
    return [
        {
            "term_type": term_type,
            "source_text": value,
            "country_region": target.country_region,
        }
        for term_type, values in values_by_type.items()
        for value in sorted(values)
        if (term_type, _term_identity(value)) not in matched
    ]


def _prevent_detail_regression(target: HistoricalRaceEventTarget, modules: dict[str, dict[str, Any]]) -> None:
    event = target.event
    comparisons = {
        RaceEventModule.RUNNERS: (
            list(event.runners.values()),
            ("horse_name", "jockey_name", "trainer_name", "horse_number", "barrier"),
        ),
        RaceEventModule.RESULTS: (
            list(event.results.values()),
            ("horse_name", "jockey_name", "trainer_name", "finish_time", "margin"),
        ),
    }
    for module, (existing, fields) in comparisons.items():
        candidate = list((modules.get(module) or {}).get("items") or [])
        if not existing:
            continue
        if len(candidate) < len(existing):
            raise InventoryValidationError(f"candidate_less_complete: {module} row count")
        existing_counts = _nonempty_field_counts(existing, fields)
        candidate_counts = _nonempty_field_counts(candidate, fields)
        regressions = [field for field in fields if candidate_counts[field] < existing_counts[field]]
        if regressions:
            raise InventoryValidationError(
                f"candidate_less_complete: {module} fields={','.join(regressions)}"
            )


def validate_historical_target_candidate(
    *,
    target_id: int,
    expected_target_sha256: str,
    inventory_artifact_sha256: str,
    modules: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    target = HistoricalRaceEventTarget.objects.select_related("race_series", "event").get(pk=target_id)
    if target_identity(target)["target_sha256"] != expected_target_sha256:
        raise InventoryValidationError("historical target changed after candidate approval")
    if target.artifact_sha256 != inventory_artifact_sha256:
        raise InventoryValidationError("historical target inventory artifact mismatch")
    if target.resolution_status != HistoricalRaceResolutionStatus.READY or target.event is None:
        raise InventoryValidationError("historical target is not ready for import")
    if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
        if modules:
            raise InventoryValidationError("cancelled target must not import fabricated runners or results")
        return {}
    results_payload = modules.get(RaceEventModule.RESULTS) or {}
    result_items = results_payload.get("items")
    if not results_payload.get("is_complete") or not isinstance(result_items, list) or not result_items:
        raise InventoryValidationError("held historical target requires complete results")
    runners_payload = modules.get(RaceEventModule.RUNNERS) or {}
    runner_items = runners_payload.get("items") if isinstance(runners_payload.get("items"), list) else []
    if not runner_items:
        runner_items = derive_runners_from_complete_results(results_payload)
        runners_payload = {
            "items": runner_items,
            "is_complete": True,
            "derived_from_results": True,
            "source_cache_identity": results_payload.get("source_cache_identity") or {},
        }
    elif not runners_payload.get("is_complete"):
        raise InventoryValidationError("held historical target requires complete runners")
    normalized = {
        RaceEventModule.RUNNERS: runners_payload,
        RaceEventModule.RESULTS: results_payload,
    }
    _prevent_detail_regression(target, normalized)
    return normalized


def apply_historical_target_candidate(
    *,
    target_id: int,
    expected_target_sha256: str,
    inventory_artifact_sha256: str,
    source_name: str,
    source_url: str,
    modules: dict[str, dict[str, Any]],
    actor=None,
) -> dict[str, int]:
    with transaction.atomic():
        target = (
            HistoricalRaceEventTarget.objects.select_for_update()
            .select_related("race_series", "event")
            .get(pk=target_id)
        )
        normalized_modules = validate_historical_target_candidate(
            target_id=target.pk,
            expected_target_sha256=expected_target_sha256,
            inventory_artifact_sha256=inventory_artifact_sha256,
            modules=modules,
        )

        if target.expectation_status == HistoricalRaceExpectationStatus.CANCELLED:
            if modules:
                raise InventoryValidationError("cancelled target must not import fabricated runners or results")
            target.resolution_status = HistoricalRaceResolutionStatus.IMPORTED
            target.module_statuses = {"basic": "complete", "runners": "not_applicable", "results": "not_applicable"}
            target.last_checked_at = timezone.now()
            target.save(update_fields={"resolution_status", "module_statuses", "last_checked_at"})
            return {"runners": 0, "results": 0, "history_winners": 0}

        applied_counts: dict[str, int] = {}
        for module, payload in normalized_modules.items():
            candidate = save_data_candidate(
                event=target.event,
                module=module,
                source_name=source_name,
                source_url=source_url,
                candidate_payload=payload,
                raw_payload={
                    "historical_target_id": target.pk,
                    "target_sha256": expected_target_sha256,
                    "inventory_artifact_sha256": inventory_artifact_sha256,
                    "source_cache_identity": payload.get("source_cache_identity") or {},
                    "item_count": len(payload["items"]),
                },
                confidence=100,
            )
            apply_data_candidate(candidate, user=actor)
            applied_counts[module] = len(payload["items"])

        actual_counts = {
            RaceEventModule.RUNNERS: target.event.runners.count(),
            RaceEventModule.RESULTS: target.event.results.count(),
        }
        if actual_counts != applied_counts:
            raise InventoryValidationError(
                f"historical write-after count mismatch: expected={applied_counts} actual={actual_counts}"
            )
        target.resolution_status = HistoricalRaceResolutionStatus.IMPORTED
        target.module_statuses = {
            "basic": "complete",
            "runners": "complete",
            "results": "complete",
            "history_winners": "covered_by_results",
            "term_gaps": historical_race_term_gaps(target),
        }
        target.last_checked_at = timezone.now()
        target.save(update_fields={"resolution_status", "module_statuses", "last_checked_at"})
        OperationLog.objects.create(
            admin=actor,
            action_type="historical_target_imported",
            target_type="historical_race_event_target",
            target_id=str(target.pk),
            detail=canonical_json(
                {
                    "target_sha256": expected_target_sha256,
                    "inventory_artifact_sha256": inventory_artifact_sha256,
                    "counts": applied_counts,
                }
            ),
        )
        return {
            "runners": applied_counts[RaceEventModule.RUNNERS],
            "results": applied_counts[RaceEventModule.RESULTS],
            "history_winners": 0,
        }


def apply_historical_champion_supplement(
    *,
    target_id: int,
    expected_target_sha256: str,
    source_authority: str,
    source_refs: dict[str, Any],
    winners: list[dict[str, Any]],
    actor=None,
) -> int:
    if source_authority not in CHAMPION_SUPPLEMENT_AUTHORITIES:
        raise InventoryValidationError("champion supplement source authority is insufficient")
    if not source_refs or not winners:
        raise InventoryValidationError("champion supplement requires source evidence and winner rows")
    with transaction.atomic():
        target = (
            HistoricalRaceEventTarget.objects.select_for_update()
            .select_related("race_series", "event")
            .get(pk=target_id)
        )
        if target_identity(target)["target_sha256"] != expected_target_sha256:
            raise InventoryValidationError("historical target changed after champion approval")
        if target.event is None:
            raise InventoryValidationError("champion supplement requires a real annual RaceEvent")
        if target.event.results.filter(official_finish_position=1).exists() or target.event.results.filter(
            official_finish_position__isnull=True,
            finish_position=1,
        ).exists():
            raise InventoryValidationError("official annual result already supplies the champion")
        created_or_updated = 0
        for winner in winners:
            if int(winner.get("winner_year") or 0) != target.year or not str(winner.get("horse_name") or "").strip():
                raise InventoryValidationError("champion supplement may only contain this target year")
            RaceEventHistoryWinner.objects.update_or_create(
                event=target.event,
                winner_year=target.year,
                horse_name=str(winner["horse_name"]).strip(),
                defaults={
                    "jockey_name": str(winner.get("jockey_name") or ""),
                    "trainer_name": str(winner.get("trainer_name") or ""),
                    "finish_time": str(winner.get("finish_time") or ""),
                    "margin": str(winner.get("margin") or ""),
                    "source_refs": {**source_refs, "source_authority": source_authority},
                },
            )
            created_or_updated += 1
        module_statuses = dict(target.module_statuses or {})
        module_statuses["history_winners"] = "supplemented"
        target.module_statuses = module_statuses
        target.last_checked_at = timezone.now()
        target.save(update_fields={"module_statuses", "last_checked_at"})
        OperationLog.objects.create(
            admin=actor,
            action_type="historical_champion_supplemented",
            target_type="historical_race_event_target",
            target_id=str(target.pk),
            detail=canonical_json(
                {"winner_count": created_or_updated, "source_authority": source_authority}
            ),
        )
    return created_or_updated


def audit_historical_candidate_coverage(
    *,
    expected_targets: list[dict[str, Any]],
    candidate_records: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_by_id = {int(row["target_id"]): row for row in expected_targets}
    records_by_id: dict[int, list[dict[str, Any]]] = {}
    unexpected = []
    for record in candidate_records:
        target_id = int(record.get("target_id") or 0)
        if target_id not in expected_by_id:
            unexpected.append(target_id)
            continue
        records_by_id.setdefault(target_id, []).append(record)
    if unexpected:
        raise InventoryValidationError(f"unexpected historical candidates: {sorted(set(unexpected))}")

    complete_scopes = []
    gaps = []
    for target_id, expected in sorted(expected_by_id.items()):
        records = records_by_id.get(target_id) or []
        if not records:
            gaps.append({"target_id": target_id, "reason": "missing_candidate"})
            continue
        if len(records) > 1:
            gaps.append({"target_id": target_id, "reason": "duplicate_candidate"})
            continue
        record = records[0]
        if not str(record.get("source_url") or "").strip() or not str(record.get("source_name") or "").strip():
            gaps.append({"target_id": target_id, "reason": "source_provenance_missing"})
            continue
        try:
            validate_historical_target_candidate(
                target_id=target_id,
                expected_target_sha256=str(expected["target_sha256"]),
                inventory_artifact_sha256=str(expected["artifact_sha256"]),
                modules=record.get("modules") if isinstance(record.get("modules"), dict) else {},
            )
        except (HistoricalRaceEventTarget.DoesNotExist, InventoryValidationError) as exc:
            gaps.append({"target_id": target_id, "reason": str(exc)})
            continue
        complete_scopes.append(record)
    return {
        "expected_count": len(expected_by_id),
        "complete_count": len(complete_scopes),
        "gap_count": len(gaps),
        "complete_scopes": complete_scopes,
        "gaps": gaps,
    }


def apply_authoritative_event_fields(
    *,
    target_id: int,
    artifact_sha256: str,
    candidates: list[dict[str, Any]],
    actor=None,
) -> dict[str, Any]:
    if not artifact_sha256:
        raise InventoryValidationError("event field update requires a new artifact identity")
    with transaction.atomic():
        target = (
            HistoricalRaceEventTarget.objects.select_for_update()
            .select_related("event", "race_series")
            .get(pk=target_id)
        )
        if target.event is None:
            raise InventoryValidationError("event field update requires a RaceEvent")
        event = target.event
        existing = {field: getattr(event, field) for field in UPDATABLE_BASIC_FIELDS}
        merged = merge_authoritative_fields(
            candidates,
            existing_fields=existing,
            existing_provenance=target.field_provenance,
            manual_locks=event.manual_lock_flags,
        )
        if merged["blocked"]:
            raise InventoryValidationError(
                f"authoritative event field conflict: {[item['field'] for item in merged['conflicts']]}"
            )
        before = {}
        after = {}
        update_fields = []
        for field in UPDATABLE_BASIC_FIELDS:
            value = merged["fields"].get(field, existing[field])
            if value != existing[field]:
                before[field] = existing[field]
                after[field] = value
                setattr(event, field, value)
                update_fields.append(field)
        if update_fields:
            event.save(update_fields=set(update_fields))
        target.field_provenance = merged["field_provenance"]
        target.last_checked_at = timezone.now()
        target.save(update_fields={"field_provenance", "last_checked_at"})
        OperationLog.objects.create(
            admin=actor,
            action_type="historical_event_fields_updated",
            target_type="race_event",
            target_id=str(event.pk),
            detail=canonical_json(
                {
                    "artifact_sha256": artifact_sha256,
                    "before": {
                        key: value.isoformat() if hasattr(value, "isoformat") else value
                        for key, value in before.items()
                    },
                    "after": {
                        key: value.isoformat() if hasattr(value, "isoformat") else value
                        for key, value in after.items()
                    },
                    "skipped_manual": [item["field"] for item in merged["skipped_manual"]],
                    "lower_authority_disagreements": len(merged["lower_authority_disagreements"]),
                }
            ),
        )
    return {
        "updated_fields": update_fields,
        "before": before,
        "after": after,
        "skipped_manual": [item["field"] for item in merged["skipped_manual"]],
    }
