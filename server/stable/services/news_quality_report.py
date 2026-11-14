"""P01 只读观测：独立事件分母、源时刻、席位和响应日志分开核算。"""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from stable.models import (NewsProcessingRun, NewsPublicationReceipt, NewsDiscoveryObservation,
    NewsFeedSnapshot, NewsPublicEntry, NewsModelBudget, NewsStageAttempt, NewsSource)
from stable.services.news_pipeline import REGIONS, digest, policy_sha

MAX_ROWS = 100000


def _time(value):
    try:
        result = value if isinstance(value, datetime) else parse_datetime(value or "")
        return result if result and result.tzinfo else None
    except (ValueError, TypeError):
        return None


def timeliness(*, source_time, time_verified, priority, published_at, now):
    source_time, published_at = _time(source_time), _time(published_at)
    if time_verified is not True or not source_time or source_time > now or (published_at and published_at < source_time):
        return {"status": "unknown", "delay_seconds": None, "deadline": None}
    if priority == "major":
        deadline = source_time + timedelta(hours=1)
        on_time = published_at and published_at <= deadline
    else:
        deadline = source_time.astimezone(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        on_time = published_at and published_at < deadline
    status = ("on_time" if on_time else "late") if published_at else ("unpublished_overdue" if now >= deadline else "awaiting")
    return {"status": status, "delay_seconds": (published_at-source_time).total_seconds() if published_at else None,
            "deadline": deadline.isoformat()}


def _bounded(query):
    if query.count() > MAX_ROWS:
        raise ValueError("report_scope_exceeds_bound")
    return list(query)


def _covers(start, end, intervals, expected_sha):
    cursor = start
    for row in sorted(intervals, key=lambda item: item.get("start", "")):
        begin, finish = _time(row.get("start")), _time(row.get("end"))
        if not begin or not finish or finish <= begin or row.get("policy_sha") != expected_sha:
            return False
        if finish <= start or begin >= end:
            continue
        if begin > cursor:
            return False
        cursor = max(cursor, finish)
    return cursor >= end


def exposure_report(records, access, *, start, end):
    result = {"status": "unknown", "responses": 0, "opportunities": dict.fromkeys(REGIONS, 0),
              "followed_opportunities": 0, "errors": []}
    if records is None:
        return result
    if len(records) > MAX_ROWS:
        raise ValueError("exposure_scope_exceeds_bound")
    generations = {str(row.generation): row for row in NewsFeedSnapshot.objects.filter(generation__in={r.get("generation") for r in records})}
    entry_ids = {item.get("id") for row in records for item in row.get("entries", [])}
    entry_ids |= {pk for row in records for pk in row.get("followed_entry_ids", [])}
    entries = {row.pk: row for row in NewsPublicEntry.objects.filter(pk__in=entry_ids)}
    seen = set()
    for row in records:
        at = _time(row.get("at"))
        if not at or not start <= at <= end:
            result["errors"].append("record_outside_window")
            continue
        response_id = row.get("response_id")
        snapshot = generations.get(row.get("generation"))
        if not response_id or response_id in seen or row.get("event") != "news_feed_response" or row.get("status") != 200 or not snapshot or not snapshot.cutoff_at <= at < snapshot.expires_at:
            result["errors"].append("response_identity_or_generation_invalid")
            continue
        shown = row.get("entries", [])
        ids = [item.get("id") for item in shown]
        if len(ids) != len(set(ids)) or any(pk not in entries or entries[pk].feed_seq > snapshot.catalog_watermark for pk in ids):
            result["errors"].append("response_entries_invalid")
            continue
        if any(item.get("region") != entries[item["id"]].primary_region for item in shown):
            result["errors"].append("response_region_mismatch")
            continue
        followed = row.get("followed_entry_ids", [])
        if len(followed) != len(set(followed)) or any(pk not in entries for pk in followed):
            result["errors"].append("followed_entries_invalid")
            continue
        seen.add(response_id)
        result["responses"] += 1
        for item in shown:
            region = item["region"]
            result["opportunities"][region] = result["opportunities"].get(region, 0) + 1
        result["followed_opportunities"] += len(followed)
    if result["errors"]:
        result["status"] = "log_gap"
    elif access and access.get("complete") is True:
        ids = access.get("response_ids", [])
        if type(ids) is not list or len(ids) != len(set(ids)) or set(ids) != seen:
            result["status"] = "log_gap"
        elif (_time(access.get("start")) and _time(access.get("end"))
                and _time(access["start"]) <= start and _time(access["end"]) >= end and access.get("provenance")):
            result["status"] = "verified" if seen else "no_visits"
    return result


def build_report(*, start, end, independent_events=(), exposure_records=None, exposure_access=None, evidence=None):
    start, end = _time(start), _time(end)
    now = timezone.now()
    if not start or not end or not start < end <= now or end-start > timedelta(days=31):
        raise ValueError("report_window_invalid")
    if len(independent_events) > 2000:
        raise ValueError("independent_inventory_unbounded")
    evidence = evidence or {}
    policy = getattr(settings, "NEWS_QUALITY_POLICY", {})
    sources = list(NewsSource.objects.filter(pk__in=policy.get("source_ids", [])))
    source_ids = [row.pk for row in sources]
    runs = _bounded(NewsProcessingRun.objects.filter(created_at__gte=start, created_at__lte=end))
    receipts = _bounded(NewsPublicationReceipt.objects.filter(published_at__gte=start, published_at__lte=end).select_related("run", "event"))
    observations = _bounded(NewsDiscoveryObservation.objects.filter(observed_at__gte=start, observed_at__lte=end, source_id__in=source_ids).order_by("observed_at", "pk"))
    latest = {}
    for row in observations:
        if row.kind == "stub":
            latest[(row.source_id, row.item_key)] = row
    discovery = {"candidates": len(latest), "failed": sum(row.outcome == "failed" for row in latest.values()),
        "without_article": sum(row.article_id is None for row in latest.values()),
        "gaps": [{"source_id": row.source_id, "item_key": row.item_key, "stage": row.stage, "reason": row.reason,
                  "outcome": row.outcome, "article_id": row.article_id} for row in latest.values() if row.outcome != "ok"]}
    source_windows = []
    for source in sources:
        rows = [row for row in observations if row.kind == "source_window" and row.source_id == source.pk]
        times = [start, *[row.observed_at for row in rows], end]
        maximum_gap = max((b-a).total_seconds() for a, b in zip(times, times[1:]))
        interval = source.effective_crawl_interval_minutes or source.crawl_interval_minutes
        source_windows.append({"source_id": source.pk, "region": source.racing_region, "windows": len(rows),
            "failed": sum(row.outcome not in {"ok", "empty"} or bool(row.source_snapshot.get("query_failure_count")) for row in rows),
            "configured_interval_minutes": interval, "maximum_gap_seconds": maximum_gap,
            "discovery_target_gap": interval > 5,
            "covered": bool(rows) and maximum_gap <= interval*60+60 and all(row.outcome in {"ok", "empty"} and not row.source_snapshot.get("query_failure_count") for row in rows)})
    region_rows = {}
    for region in REGIONS:
        regional = [run for run in runs if run.primary_region == region]
        chosen = {run.event_id for run in regional if run.event_id and run.priority in {"major", "regional"}}
        qualified = {run.event_id for run in regional if run.event_id and run.quality_snapshot.get("passed") is True}
        published = {row.event_id for row in receipts if row.run.primary_region == region}
        region_rows[region] = {"discovered": sum(row.primary_region == region for row in latest.values()),
            "selected_events": len(chosen), "qualified_events": len(qualified), "published_events": len(published),
            "backlog": dict(Counter(run.state for run in regional)), "supply_gap": not qualified}
    inventory_ids, major_rows = set(), []
    for item in independent_events:
        if (not isinstance(item, dict) or not item.get("id") or item["id"] in inventory_ids
                or item.get("primary_region") not in REGIONS or not item.get("provenance") or not item.get("identity_key")):
            raise ValueError("independent_inventory_invalid")
        inventory_ids.add(item["id"])
        receipt = NewsPublicationReceipt.objects.filter(event__identity_key=item["identity_key"], published_at__lte=end).order_by("published_at").first()
        clock = timeliness(source_time=item.get("source_time"), time_verified=item.get("time_verified"), priority="major",
            published_at=receipt.published_at if receipt else None, now=end)
        major_rows.append({"id": item["id"], "region": item["primary_region"], "receipt_id": str(receipt.pk) if receipt else None,
            "identity_key": item["identity_key"], **clock})
    major_counts = Counter(row["status"] for row in major_rows)
    major = {"denominator": len(major_rows), "unknown": major_counts["unknown"],
        "overdue": major_counts["late"]+major_counts["unpublished_overdue"], "on_time": major_counts["on_time"],
        "known_time_denominator": len(major_rows)-major_counts["unknown"], "events": major_rows}
    major["known_time_target_rate"] = major["on_time"]/major["known_time_denominator"] if major["known_time_denominator"] else None
    ordinary = []
    by_event = {}
    for run in sorted(runs, key=lambda row: (row.created_at, row.pk)):
        if run.event_id and run.priority == "regional":
            by_event.setdefault(run.event_id, run)
    for event_id, run in by_event.items():
        receipt = NewsPublicationReceipt.objects.filter(event_id=event_id, published_at__lte=end).order_by("published_at").first()
        ordinary.append({"event_id": str(event_id), "region": run.primary_region, **timeliness(
            source_time=run.source_snapshot.get("source_time"), time_verified=run.source_snapshot.get("time_verified"),
            priority="regional", published_at=receipt.published_at if receipt else None, now=end)})
    snapshots = _bounded(NewsFeedSnapshot.objects.filter(cutoff_at__gte=start-timedelta(days=1), cutoff_at__lte=end).order_by("cutoff_at", "id"))
    seconds = Counter()
    for index, snap in enumerate(snapshots):
        stop = min(end, snap.expires_at, snapshots[index+1].cutoff_at if index+1<len(snapshots) else end)
        duration = max(0, (stop-max(start, snap.cutoff_at)).total_seconds())
        for region, slots in snap.slots_metadata.get("all_region_slots", {}).items():
            seconds[region] += duration*slots
    exposure = exposure_report(exposure_records, exposure_access, start=start, end=end)
    attempts = _bounded(NewsStageAttempt.objects.select_related("run").filter(reserved_at__gte=start, reserved_at__lte=end).exclude(provider=""))
    cost = {"requests": sum(row.provider != "cache" for row in attempts),
        "cache_hits": sum(row.provider == "cache" for row in attempts),
        "unknown_reserved": str(sum((row.reservation for row in attempts if row.state == "unknown" and not row.settlement_version), Decimal(0))), "actual": str(sum((row.actual_cost for row in attempts), Decimal(0))),
        "unknown_requests": sum(row.state == "unknown" for row in attempts),
        "reserved": str(sum((row.reservation for row in attempts if not row.settlement_version), Decimal(0))),
        "blocked_budgets": list(NewsModelBudget.objects.exclude(state__in=["open", "closed"]).values("id", "period_kind", "period_start", "currency", "state", "spent", "reserved", "overage"))}
    # 单篇以全历史run聚合，报表时间窗不重置文章额度；币种分开显示。
    from django.db.models import Sum, Case, When, F, Value, DecimalField
    article_ids = {row.run.article_id for row in attempts}
    cost["articles"] = list(NewsStageAttempt.objects.filter(run__article_id__in=article_ids,
        month_budget__isnull=False).values("run__article_id", "month_budget__currency").annotate(
            spent=Sum("actual_cost"), reserved=Sum(Case(When(settlement_version=0, then=F("reservation")),
                default=Value(0), output_field=DecimalField())),
            unknown=Sum(Case(When(state="unknown", settlement_version=0, then=F("reservation")),
                default=Value(0), output_field=DecimalField()))).order_by("run__article_id", "month_budget__currency"))
    cost["periods"] = list(NewsModelBudget.objects.filter(period_start__gte=start.date().replace(day=1),
        period_start__lte=end.date()).values("period_kind", "period_start", "currency", "spent", "reserved", "cap", "state"))
    invalid_quality = []
    for receipt in receipts:
        run = receipt.run
        quality = run.quality_snapshot
        strong = list(run.attempts.filter(pk__in=[run.entity_snapshot.get("strong_attempt_id"), quality.get("strong_attempt_id")], state="completed"))
        if (quality.get("passed") is not True or quality.get("target_sha") != receipt.target_revision_sha
                or digest(run.translation_snapshot) != receipt.target_revision_sha
                or any(receipt.content.get(key) != run.translation_snapshot.get(key) for key in ("title", "body", "summary"))
                or len(strong) != 2 or any(row.output_sha != digest(row.result) or row.input_sha != digest(row.usage.get("input")) or row.usage.get("price", {}).get("quality_tier") != "strong" for row in strong)):
            invalid_quality.append(str(receipt.pk))
    inventory = evidence.get("independent_inventory", {})
    probes = evidence.get("public_probe", {})
    hard = {
        "full_168_hours": end-start >= timedelta(hours=168),
        "single_policy": _covers(start, end, evidence.get("policy_timeline", []), policy_sha()) and all(row.policy_sha == policy_sha() for row in runs),
        "source_windows_covered": bool(sources) and all(row["covered"] for row in source_windows),
        "five_regions_qualified": all(row["qualified_events"] for row in region_rows.values()),
        "independent_inventory_complete": inventory.get("complete") is True and bool(inventory.get("provenance")) and inventory.get("sha256") == digest(independent_events),
        "published_quality": not invalid_quality,
        "exposure_reconciled": exposure["status"] == "verified" and all(exposure["opportunities"].get(region, 0) > 0 for region in REGIONS),
        "public_probe": probes.get("complete") is True and probes.get("policy_sha") == policy_sha() and bool(probes.get("artifact_sha256")) and _time(probes.get("start")) == start and _time(probes.get("end")) == end,
        "cost_reconciled": not cost["unknown_requests"] and not cost["blocked_budgets"],
    }
    return {"schema": "p01-observation-v1", "generated_at": now.isoformat(), "policy_sha": policy_sha(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "elapsed_hours": (end-start).total_seconds()/3600, "full_168_hours": hard["full_168_hours"]},
        "status": "observation_checks_passed" if all(hard.values()) else "observation_incomplete",
        "hard_checks": hard, "regions": region_rows, "major": major, "ordinary": ordinary,
        "discovery": discovery, "source_windows": source_windows, "seat_seconds": dict(seconds), "exposure": exposure,
        "cost": cost, "invalid_quality_receipts": invalid_quality,
        "notes": ["时效达成率为产品目标统计，不暗设100%硬门槛。", "合成测试、快照次数与不足168小时窗口均不构成真实周验收。"]}
