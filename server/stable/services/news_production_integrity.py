from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

from django.db import connection, transaction
from django.db.models import Count
from django.utils import timezone

from stable.models import (
    CrawlJob,
    NewsSource,
    ProductionWindow,
    ProductionWindowStatus,
    TaskExecutionLog,
    TaskStatus,
)


INDEX_ERROR_PATTERNS = (
    "overlaps with invalid duplicate tuple",
    "cannot find insert offset",
    "contains unexpected zero page",
    "failed to re-find parent key",
)
INDEX_NAME_RE = re.compile(r'index\s+"(?P<name>[^"]+)"', re.IGNORECASE)
SENSITIVE_KEY_RE = re.compile(r"(?:secret|token|password|credential|api[_-]?key)", re.IGNORECASE)
CRAWL_TASK_NAMES = {
    "stable.tasks.crawl_enabled_news_sources_task",
    "stable.tasks.crawl_jra_news",
    "stable.tasks.crawl_netkeiba_access",
    "stable.tasks.crawl_netkeiba_attention",
    "stable.tasks.crawl_netkeiba_latest",
    "stable.tasks.crawl_news_source_task",
    "stable.tasks.crawl_production_sources_window_task",
}


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_sha256(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes({key: value for key, value in manifest.items() if key != "manifest_sha256"})).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED_SECRET]" if SENSITIVE_KEY_RE.search(str(key)) else _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return repr(value)


def _safe_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(task.get("id") or ""),
        "name": str(task.get("name") or ""),
        "args": _json_safe(list(task.get("args") or [])[:4]),
        "kwargs": _json_safe(dict(task.get("kwargs") or {})),
        "hostname": str(task.get("hostname") or ""),
    }


def _flatten_inspection(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for rows in (payload or {}).values():
        for row in rows or []:
            tasks.append(_safe_task(row))
    return tasks


def _fixed_task_source_id(task_name: str) -> int | None:
    mapping = {
        "stable.tasks.crawl_netkeiba_latest": ("netkeiba", "latest"),
        "stable.tasks.crawl_netkeiba_access": ("netkeiba", "access"),
        "stable.tasks.crawl_netkeiba_attention": ("netkeiba", "attention"),
        "stable.tasks.crawl_jra_news": ("jra", "official"),
    }
    key = mapping.get(task_name)
    if key is None:
        return None
    return (
        NewsSource.objects.filter(source_site=key[0], source_mode=key[1], deleted_at__isnull=True)
        .values_list("id", flat=True)
        .first()
    )


def collect_celery_crawl_activity(*, timeout: float = 3.0) -> dict[str, Any]:
    try:
        from app.celery import app

        inspector = app.control.inspect(timeout=timeout)
        active_payload = inspector.active()
        reserved_payload = inspector.reserved()
        if (
            not isinstance(active_payload, dict)
            or not active_payload
            or not isinstance(reserved_payload, dict)
            or not reserved_payload
        ):
            return {
                "available": False,
                "active_source_ids": [],
                "active_tasks": [],
                "reserved_tasks": [],
                "unmapped_crawl_tasks": [],
                "errors": ["celery_inspect_no_reply"],
            }
        if set(active_payload) != set(reserved_payload):
            return {
                "available": False,
                "active_source_ids": [],
                "active_tasks": [],
                "reserved_tasks": [],
                "unmapped_crawl_tasks": [],
                "errors": ["celery_inspect_partial_reply"],
            }
        active = [
            task for task in _flatten_inspection(active_payload) if task["name"] in CRAWL_TASK_NAMES
        ]
        reserved = [
            task for task in _flatten_inspection(reserved_payload) if task["name"] in CRAWL_TASK_NAMES
        ]
    except Exception as exc:
        return {
            "available": False,
            "active_source_ids": [],
            "active_tasks": [],
            "reserved_tasks": [],
            "unmapped_crawl_tasks": [],
            "errors": [f"celery_inspect_failed:{exc.__class__.__name__}"],
        }

    source_ids: set[int] = set()
    unmapped: list[dict[str, Any]] = []
    for task in [*active, *reserved]:
        task_name = task["name"]
        source_id: int | None = None
        if task_name == "stable.tasks.crawl_news_source_task" and task["args"]:
            try:
                source_id = int(task["args"][0])
            except (TypeError, ValueError):
                source_id = None
        else:
            source_id = _fixed_task_source_id(task_name)
        if source_id is None:
            unmapped.append(task)
        else:
            source_ids.add(source_id)
    return {
        "available": True,
        "active_source_ids": sorted(source_ids),
        "active_tasks": active,
        "reserved_tasks": reserved,
        "unmapped_crawl_tasks": unmapped,
        "errors": [],
    }


def _active_window_source_ids(*, now) -> set[int]:
    return set(
        ProductionWindow.objects.filter(
            status=ProductionWindowStatus.RUNNING,
            source_id__isnull=False,
            lease_expires_at__gt=now,
        ).values_list("source_id", flat=True)
    )


def build_stale_crawl_manifest(
    *,
    now=None,
    stale_minutes: int = 60,
    activity_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or timezone.now()
    stale_minutes = max(1, int(stale_minutes))
    evidence = activity_evidence if activity_evidence is not None else collect_celery_crawl_activity()
    active_source_ids = {int(value) for value in evidence.get("active_source_ids", [])}
    active_window_source_ids = _active_window_source_ids(now=now)
    evidence_available = bool(evidence.get("available"))
    has_unmapped = bool(evidence.get("unmapped_crawl_tasks"))
    cutoff = now - timedelta(minutes=stale_minutes)
    jobs = (
        CrawlJob.objects.filter(status=TaskStatus.STARTED, started_at__lte=cutoff)
        .select_related("source")
        .annotate(article_count=Count("articles"))
        .order_by("id")
    )
    rows: list[dict[str, Any]] = []
    for job in jobs:
        source_active = bool(job.source_id and job.source_id in active_source_ids)
        window_active = bool(job.source_id and job.source_id in active_window_source_ids)
        if not evidence_available:
            action = "skip_activity_evidence_unavailable"
        elif source_active or window_active or has_unmapped:
            action = "skip_active_evidence"
        else:
            action = "reconcile_failed"
        rows.append(
            {
                "job_id": job.id,
                "source_id": job.source_id,
                "source_name": job.source.name if job.source else "",
                "status": job.status,
                "started_at": job.started_at.isoformat(),
                "age_minutes": int((now - job.started_at).total_seconds() // 60),
                "article_count": int(job.article_count),
                "success_count": job.success_count,
                "fail_count": job.fail_count,
                "activity": {
                    "celery_source_active": source_active,
                    "production_window_active": window_active,
                    "unmapped_crawl_task_present": has_unmapped,
                },
                "recommended_action": action,
            }
        )
    manifest: dict[str, Any] = {
        "schema": "stale-crawl-job-manifest-v1",
        "generated_at": now.isoformat(),
        "selector": {
            "status": TaskStatus.STARTED,
            "stale_minutes": stale_minutes,
            "started_at_lte": cutoff.isoformat(),
        },
        "activity_evidence": evidence,
        "jobs": rows,
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def apply_stale_crawl_manifest(
    manifest: dict[str, Any],
    *,
    expected_sha256: str,
    activity_evidence: dict[str, Any] | None = None,
    now=None,
    limit: int = 100,
) -> dict[str, Any]:
    actual_sha = manifest_sha256(manifest)
    if manifest.get("manifest_sha256") != actual_sha or expected_sha256 != actual_sha:
        raise ValueError("manifest_sha256_mismatch")
    if manifest.get("schema") != "stale-crawl-job-manifest-v1":
        raise ValueError("unsupported_manifest_schema")
    try:
        cutoff = datetime.fromisoformat(manifest["selector"]["started_at_lte"])
        manifest_rows = list(manifest["jobs"])
        manifest_job_ids = [int(row["job_id"]) for row in manifest_rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid_manifest_shape") from exc
    if not timezone.is_aware(cutoff):
        raise ValueError("invalid_manifest_shape")
    if len(manifest_job_ids) != len(set(manifest_job_ids)):
        raise ValueError("duplicate_manifest_job_id")
    evidence = activity_evidence if activity_evidence is not None else collect_celery_crawl_activity()
    if not evidence.get("available") or evidence.get("unmapped_crawl_tasks"):
        raise ValueError("active_execution_evidence_incomplete")
    now = now or timezone.now()
    active_source_ids = {int(value) for value in evidence.get("active_source_ids", [])}
    active_source_ids.update(_active_window_source_ids(now=now))
    limit = int(limit)
    if limit < 1:
        raise ValueError("invalid_limit")
    limit = min(limit, 500)
    eligible_rows = [row for row in manifest_rows if row.get("recommended_action") == "reconcile_failed"]
    rows = eligible_rows[:limit]
    updated_ids: list[int] = []
    status_drift_ids: list[int] = []
    active_evidence_ids: list[int] = []
    identity_drift_ids: list[int] = []
    missing_ids: list[int] = []
    for row in rows:
        job_id = int(row["job_id"])
        with transaction.atomic():
            job = CrawlJob.objects.select_for_update().filter(pk=job_id).first()
            if job is None:
                missing_ids.append(job_id)
                continue
            if job.status != TaskStatus.STARTED:
                status_drift_ids.append(job_id)
                continue
            if job.started_at.isoformat() != row.get("started_at") or job.source_id != row.get("source_id"):
                identity_drift_ids.append(job_id)
                continue
            if job.started_at > cutoff:
                identity_drift_ids.append(job_id)
                continue
            if job.source_id and job.source_id in active_source_ids:
                active_evidence_ids.append(job_id)
                continue
            job.status = TaskStatus.FAILED
            job.finished_at = now
            suffix = f"stale_reconciled manifest={actual_sha}"
            job.error_message = f"{job.error_message}\n{suffix}".strip()
            job.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
            updated_ids.append(job_id)
    return {
        "manifest_sha256": actual_sha,
        "requested_count": len(eligible_rows),
        "processed_count": len(rows),
        "deferred_ids": [int(row["job_id"]) for row in eligible_rows[limit:]],
        "updated_ids": updated_ids,
        "status_drift_ids": status_drift_ids,
        "active_evidence_ids": active_evidence_ids,
        "identity_drift_ids": identity_drift_ids,
        "missing_ids": missing_ids,
    }


def _index_error_from_records(records: list[tuple[Any, str]]) -> dict[str, Any]:
    matches: list[tuple[Any, str]] = []
    for happened_at, raw_message in records:
        message = (raw_message or "").strip()
        lowered = message.lower()
        if any(pattern in lowered for pattern in INDEX_ERROR_PATTERNS):
            matches.append((happened_at, message))
    if not matches:
        return {"active": False, "count": 0, "index_name": "", "first_at": None, "last_at": None, "first_error": ""}
    matches.sort(key=lambda item: item[0])
    name_match = INDEX_NAME_RE.search(matches[0][1])
    return {
        "active": True,
        "count": len(matches),
        "index_name": name_match.group("name") if name_match else "",
        "first_at": matches[0][0],
        "last_at": matches[-1][0],
        "first_error": matches[0][1][:240],
    }


def _index_error_snapshot(jobs) -> dict[str, Any]:
    return _index_error_from_records([(job.started_at, job.error_message) for job in jobs])


def task_execution_index_error_snapshot(*, now=None, window_hours: int = 2) -> dict[str, Any]:
    now = now or timezone.now()
    window_hours = max(1, int(window_hours))
    logs = TaskExecutionLog.objects.filter(
        status=TaskStatus.FAILED,
        started_at__gte=now - timedelta(hours=window_hours),
    ).only("started_at", "detail")
    return _index_error_from_records([(log.started_at, log.detail) for log in logs])


def source_health_snapshot(
    source: NewsSource,
    *,
    now=None,
    stale_minutes: int = 60,
    short_window_hours: int = 2,
    long_window_hours: int = 24,
) -> dict[str, Any]:
    now = now or timezone.now()
    short_window_hours = max(1, int(short_window_hours))
    long_window_hours = max(short_window_hours, int(long_window_hours))
    jobs_24h = list(
        source.crawl_jobs.filter(started_at__gte=now - timedelta(hours=long_window_hours)).order_by("started_at", "id")
    )
    failures = [job for job in jobs_24h if job.status == TaskStatus.FAILED]
    running = list(source.crawl_jobs.filter(status=TaskStatus.STARTED).order_by("started_at", "id"))
    completed = [job for job in jobs_24h if job.status != TaskStatus.STARTED]
    successes = [job for job in completed if job.status == TaskStatus.SUCCESS]
    latest_completed = completed[-1] if completed else None
    timed_out = [job for job in running if job.started_at <= now - timedelta(minutes=stale_minutes)]
    failures_2h = [job for job in failures if job.started_at >= now - timedelta(hours=short_window_hours)]
    categories: dict[str, int] = {}
    for job in failures:
        message = (job.error_message or "").lower()
        if any(pattern in message for pattern in INDEX_ERROR_PATTERNS):
            category = "index_physical_error"
        elif "timeout" in message:
            category = "timeout"
        elif "429" in message:
            category = "http_429"
        elif "parse" in message or "empty detail" in message:
            category = "parse_error"
        else:
            category = "other"
        categories[category] = categories.get(category, 0) + 1
    return {
        "current_running_count": len(running),
        "timed_out_started_count": len(timed_out),
        "failures_2h": len(failures_2h),
        "failures_24h": len(failures),
        "last_completed_at": latest_completed.finished_at if latest_completed else None,
        "last_completed_status": latest_completed.status if latest_completed else "",
        "last_success_at": successes[-1].finished_at if successes else source.last_crawl_at if source.last_crawl_status == TaskStatus.SUCCESS else None,
        "failure_categories": categories,
        "first_failure_summary": (failures[0].error_message or "")[:240] if failures else "",
        "index_error": _index_error_snapshot(failures_2h),
        "index_error_24h": _index_error_snapshot(failures),
    }


def region_source_health_summary(
    sources,
    *,
    now=None,
    stale_minutes: int = 60,
    short_window_hours: int = 2,
    long_window_hours: int = 24,
) -> dict[str, Any]:
    now = now or timezone.now()
    short_window_hours = max(1, int(short_window_hours))
    long_window_hours = max(short_window_hours, int(long_window_hours))
    source_ids = list(sources.values_list("id", flat=True))
    recent_jobs = list(
        CrawlJob.objects.filter(source_id__in=source_ids, started_at__gte=now - timedelta(hours=long_window_hours))
        .only("id", "source_id", "status", "started_at", "finished_at", "error_message")
        .order_by("started_at", "id")
    )
    failures = [job for job in recent_jobs if job.status == TaskStatus.FAILED]
    running = list(
        CrawlJob.objects.filter(source_id__in=source_ids, status=TaskStatus.STARTED)
        .only("id", "source_id", "started_at")
        .order_by("started_at", "id")
    )
    failures_short = [
        job for job in failures if job.started_at >= now - timedelta(hours=short_window_hours)
    ]
    return {
        "current_running_count": len(running),
        "timed_out_started_count": sum(
            job.started_at <= now - timedelta(minutes=stale_minutes) for job in running
        ),
        "failures_2h": len(failures_short),
        "failures_24h": len(failures),
        "index_error": _index_error_snapshot(failures_short),
        "index_error_24h": _index_error_snapshot(failures),
    }


def production_index_snapshot(index_name: str) -> dict[str, Any]:
    if connection.vendor != "postgresql":
        return {"supported": False, "database_vendor": connection.vendor, "index_name": index_name}
    raw_index_name = str(index_name or "").strip()
    if "." in raw_index_name:
        schema_name, relation_name = raw_index_name.split(".", 1)
    else:
        schema_name, relation_name = "public", raw_index_name
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT n.nspname, c.relname, t.relname, i.indisunique, i.indisprimary,
                   i.indisvalid, i.indisready, i.indislive,
                   pg_get_indexdef(c.oid), pg_relation_size(c.oid), pg_relation_size(t.oid),
                   EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid=c.oid),
                   EXISTS (SELECT 1 FROM pg_extension WHERE extname='amcheck'),
                   EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='amcheck')
            FROM pg_class c
            JOIN pg_index i ON i.indexrelid=c.oid
            JOIN pg_class t ON t.oid=i.indrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s
            """,
            [schema_name, relation_name],
        )
        row = cursor.fetchone()
    if row is None:
        return {"supported": True, "database_vendor": connection.vendor, "index_name": index_name, "found": False}
    return {
        "supported": True,
        "database_vendor": connection.vendor,
        "schema_name": row[0],
        "index_name": row[1],
        "qualified_index_name": f"{row[0]}.{row[1]}",
        "table_name": row[2],
        "found": True,
        "is_unique": row[3],
        "is_primary": row[4],
        "is_valid": row[5],
        "is_ready": row[6],
        "is_live": row[7],
        "index_definition": row[8],
        "index_size_bytes": row[9],
        "table_size_bytes": row[10],
        "backs_constraint": row[11],
        "amcheck_installed": row[12],
        "amcheck_available": row[13],
    }
