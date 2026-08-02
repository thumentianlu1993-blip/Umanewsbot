from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.management.commands.build_internal_race_reference_manifest import (
    _atomic_write,
    _reject_public_output,
)
from stable.models import RaceReferenceCollectionRun, RaceReferenceReceipt
from stable.services.race_reference_sources import (
    SOURCE_REGISTRY,
)


def _canonical_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _error_detail_date(
    run,
    *,
    detail: dict,
    detail_event_id: int,
    frozen_dates_by_run_event: dict[int, dict[int, date | None]],
) -> date | None:
    supplied_date = _canonical_date(detail.get("local_date"))
    run_event_dates = frozen_dates_by_run_event.get(run.pk, {})
    frozen_date = run_event_dates.get(detail_event_id)
    if (
        frozen_date is not None
        and supplied_date is not None
        and frozen_date != supplied_date
    ):
        return None
    error_date = frozen_date or supplied_date
    if (
        error_date is None
        and not run_event_dates
        and run.local_date_from is not None
        and run.local_date_from == run.local_date_to
    ):
        return run.local_date_from
    return error_date


def _run_has_filtered_event_error(
    run,
    *,
    event_id: int,
    frozen_dates_by_run_event: dict[int, dict[int, date | None]],
    date_from: date,
    date_to: date,
) -> bool:
    summary = run.error_summary if isinstance(run.error_summary, dict) else {}
    details = summary.get("details")
    if not isinstance(details, list):
        return False
    for detail in details:
        if not isinstance(detail, dict):
            continue
        detail_event_id = detail.get("event_id")
        if (
            isinstance(detail_event_id, bool)
            or not isinstance(detail_event_id, int)
            or detail_event_id != event_id
        ):
            continue
        error_date = _error_detail_date(
            run,
            detail=detail,
            detail_event_id=detail_event_id,
            frozen_dates_by_run_event=frozen_dates_by_run_event,
        )
        if error_date is not None and date_from <= error_date <= date_to:
            return True
    return False


def _new_region_date_group(
    country_region: str,
    local_date: str,
) -> dict:
    return {
        "country_region": country_region,
        "local_date": local_date,
        "coverage": {
            "receipts": 0,
            "matched": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "source_only": 0,
            "duplicate_runs": 0,
            "duplicate_observations": 0,
        },
        "completeness": {
            "complete": 0,
            "partial": 0,
        },
        "_latencies": [],
        "_latency_unknown": 0,
        "_event_runs": {},
        "_event_observations": {},
    }


def _count_filtered_errors(
    runs,
    *,
    frozen_dates_by_run_event: dict[int, dict[int, date | None]],
    date_from: date,
    date_to: date,
    event_id: int | None,
) -> tuple[int, int]:
    attributed = 0
    unattributed = 0
    for run in runs:
        summary = run.error_summary if isinstance(run.error_summary, dict) else {}
        details = summary.get("details")
        details = details if isinstance(details, list) else []
        seen_event_ids: set[int] = set()
        accounted = 0
        for detail in details:
            if not isinstance(detail, dict):
                continue
            detail_event_id = detail.get("event_id")
            if (
                isinstance(detail_event_id, bool)
                or not isinstance(detail_event_id, int)
                or detail_event_id <= 0
                or detail_event_id in seen_event_ids
            ):
                continue
            seen_event_ids.add(detail_event_id)
            accounted += 1
            if event_id is not None and detail_event_id != event_id:
                continue

            error_date = _error_detail_date(
                run,
                detail=detail,
                detail_event_id=detail_event_id,
                frozen_dates_by_run_event=frozen_dates_by_run_event,
            )
            if error_date is None:
                unattributed += 1
            elif date_from <= error_date <= date_to:
                attributed += 1

        remaining = max(0, run.error_count - accounted)
        if remaining == 0 or event_id is not None:
            continue
        if (
            not details
            and run.local_date_from is not None
            and run.local_date_from == run.local_date_to
        ):
            if date_from <= run.local_date_from <= date_to:
                attributed += remaining
        else:
            unattributed += remaining
    return attributed, unattributed


class Command(BaseCommand):
    help = "导出仅供内部查看的赛后参考观察汇总 JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-key",
            required=True,
            choices=tuple(SOURCE_REGISTRY),
        )
        parser.add_argument("--date-from", required=True)
        parser.add_argument("--date-to", required=True)
        parser.add_argument("--event-id", type=int)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        try:
            date_from = date.fromisoformat(options["date_from"])
            date_to = date.fromisoformat(options["date_to"])
        except ValueError as exc:
            raise CommandError("date-from/date-to 必须为 YYYY-MM-DD") from exc
        if date_from > date_to:
            raise CommandError("date-from 不能晚于 date-to")
        event_id = options["event_id"]
        if event_id is not None and event_id <= 0:
            raise CommandError("event-id 必须为正整数")

        runs = list(
            RaceReferenceCollectionRun.objects.filter(
                source_key=options["source_key"],
                local_date_to__gte=date_from,
                local_date_from__lte=date_to,
            ).order_by("created_at", "pk")
        )
        receipts = RaceReferenceReceipt.objects.filter(run__in=runs)

        status_counts = {
            "matched": 0,
            "unmatched": 0,
            "ambiguous": 0,
            "source_only": 0,
        }
        partial_count = 0
        excluded_invalid_snapshot_count = 0
        receipt_rows = []
        included_run_ids: set[int] = set()
        frozen_dates_by_run_event: dict[int, dict[int, date | None]] = {}
        grouped: dict[tuple[str, str], dict] = {}
        for receipt in receipts.select_related("run", "payload").order_by(
            "recorded_at", "pk"
        ):
            snapshot = receipt.event_snapshot
            if not isinstance(snapshot, dict):
                excluded_invalid_snapshot_count += 1
                continue
            snapshot_date_value = snapshot.get("local_date")
            if not isinstance(snapshot_date_value, str):
                excluded_invalid_snapshot_count += 1
                continue
            try:
                snapshot_local_date = date.fromisoformat(snapshot_date_value)
            except ValueError:
                excluded_invalid_snapshot_count += 1
                continue
            if snapshot_local_date.isoformat() != snapshot_date_value:
                excluded_invalid_snapshot_count += 1
                continue
            snapshot_event_id = snapshot.get("event_id")
            if (
                isinstance(snapshot_event_id, bool)
                or not isinstance(snapshot_event_id, int)
                or snapshot_event_id <= 0
            ):
                excluded_invalid_snapshot_count += 1
                continue
            run_event_dates = frozen_dates_by_run_event.setdefault(
                receipt.run_id,
                {},
            )
            previous_date = run_event_dates.get(snapshot_event_id)
            if previous_date is None and snapshot_event_id not in run_event_dates:
                run_event_dates[snapshot_event_id] = snapshot_local_date
            elif previous_date != snapshot_local_date:
                run_event_dates[snapshot_event_id] = None
            if not date_from <= snapshot_local_date <= date_to:
                continue
            if event_id is not None:
                if snapshot_event_id != event_id:
                    continue

            status_counts[receipt.match_status] += 1
            partial_count += int(receipt.is_partial)
            included_run_ids.add(receipt.run_id)
            key = (
                receipt.run.country_region,
                snapshot_local_date.isoformat(),
            )
            group = grouped.setdefault(
                key,
                _new_region_date_group(key[0], key[1]),
            )
            group["coverage"]["receipts"] += 1
            group["coverage"][receipt.match_status] += 1
            group["completeness"][
                "partial" if receipt.is_partial else "complete"
            ] += 1
            group["_event_runs"].setdefault(
                snapshot_event_id,
                set(),
            ).add(receipt.run_id)
            group["_event_observations"][snapshot_event_id] = (
                group["_event_observations"].get(snapshot_event_id, 0) + 1
            )
            if receipt.source_observed_at is None:
                group["_latency_unknown"] += 1
            else:
                latency = (
                    receipt.fetched_at - receipt.source_observed_at
                ).total_seconds()
                if latency < 0:
                    group["_latency_unknown"] += 1
                else:
                    group["_latencies"].append(latency)
            receipt_rows.append(
                {
                    "run_id": receipt.run_id,
                    "receipt_id": receipt.pk,
                    "event_id": receipt.event_id,
                    "snapshot_event_id": snapshot_event_id,
                    "provider_event_key": receipt.payload.provider_event_key,
                    "payload_sha256": receipt.payload.payload_sha256,
                    "match_status": receipt.match_status,
                    "match_confidence": receipt.match_confidence,
                    "is_partial": receipt.is_partial,
                    "gap_codes": receipt.gap_codes,
                    "recorded_at": receipt.recorded_at.isoformat(),
                }
            )
        if event_id is None:
            selected_runs = runs
        else:
            selected_runs = [
                run
                for run in runs
                if run.pk in included_run_ids
                or _run_has_filtered_event_error(
                    run,
                    event_id=event_id,
                    frozen_dates_by_run_event=frozen_dates_by_run_event,
                    date_from=date_from,
                    date_to=date_to,
                )
            ]
        for run in selected_runs:
            summary = (
                run.error_summary
                if isinstance(run.error_summary, dict)
                else {}
            )
            details = summary.get("details")
            if not isinstance(details, list):
                continue
            seen_event_ids: set[int] = set()
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                detail_event_id = detail.get("event_id")
                if (
                    isinstance(detail_event_id, bool)
                    or not isinstance(detail_event_id, int)
                    or detail_event_id <= 0
                    or detail_event_id in seen_event_ids
                    or (
                        event_id is not None
                        and detail_event_id != event_id
                    )
                ):
                    continue
                seen_event_ids.add(detail_event_id)
                error_date = _error_detail_date(
                    run,
                    detail=detail,
                    detail_event_id=detail_event_id,
                    frozen_dates_by_run_event=frozen_dates_by_run_event,
                )
                if (
                    error_date is None
                    or not date_from <= error_date <= date_to
                ):
                    continue
                key = (run.country_region, error_date.isoformat())
                group = grouped.setdefault(
                    key,
                    _new_region_date_group(key[0], key[1]),
                )
                group["_event_runs"].setdefault(
                    detail_event_id,
                    set(),
                ).add(run.pk)
        by_region_date = []
        for key in sorted(grouped):
            group = grouped[key]
            latencies = group.pop("_latencies")
            unknown_count = group.pop("_latency_unknown")
            event_runs = group.pop("_event_runs")
            event_observations = group.pop("_event_observations")
            group["coverage"]["duplicate_runs"] = sum(
                max(0, len(run_ids) - 1)
                for run_ids in event_runs.values()
            )
            group["coverage"]["duplicate_observations"] = sum(
                max(0, count - 1)
                for count in event_observations.values()
            )
            group["collection_latency_seconds"] = {
                "known_count": len(latencies),
                "unknown_count": unknown_count,
                "average": (
                    sum(latencies) / len(latencies) if latencies else None
                ),
            }
            by_region_date.append(group)
        attributed_errors, unattributed_errors = _count_filtered_errors(
            selected_runs,
            frozen_dates_by_run_event=frozen_dates_by_run_event,
            date_from=date_from,
            date_to=date_to,
            event_id=event_id,
        )
        report = {
            "schema_version": 1,
            "visibility": "internal_only",
            "source_key": options["source_key"],
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "event_id": event_id,
            "coverage": {
                "runs": len(selected_runs),
                "failed_runs": sum(
                    run.status == "failed" for run in selected_runs
                ),
                "errors": attributed_errors,
                "unattributed_errors": unattributed_errors,
                "receipts": len(receipt_rows),
                "excluded_invalid_snapshot": excluded_invalid_snapshot_count,
                **status_counts,
            },
            "partial": {"count": partial_count},
            "mismatch": {
                "unmatched": status_counts["unmatched"],
                "ambiguous": status_counts["ambiguous"],
                "source_only": status_counts["source_only"],
            },
            "by_region_date": by_region_date,
            "receipts": receipt_rows,
        }
        output = Path(options["output"])
        _reject_public_output(output)
        if output.exists() or output.is_symlink():
            raise CommandError("output 必须是不存在的新文件")
        report_bytes = json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        _atomic_write(output, report_bytes)
        self.stdout.write(
            self.style.SUCCESS(
                f"内部报告已生成：runs={report['coverage']['runs']} "
                f"receipts={len(receipt_rows)}"
            )
        )
