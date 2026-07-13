from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from stable.models import MultiregionAttributionRun, MultiregionAttributionRunStatus, NewsArticle


def _article_fingerprint(article: NewsArticle) -> str:
    payload = {
        "id": article.id,
        "title": article.title_ja,
        "source_url": article.source_url,
        "published_at": article.published_at.isoformat() if article.published_at else "",
        "published_at_verified": article.published_at_verified,
        "updated_at": article.updated_at.isoformat() if article.updated_at else "",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _json_datetime(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


@dataclass(frozen=True)
class TimeRepairCommitResult:
    applied_ids: list[int] = field(default_factory=list)
    drifted_ids: list[int] = field(default_factory=list)
    skipped: dict[int, str] = field(default_factory=dict)


def create_time_repair_dry_run(
    articles,
    *,
    evidence_by_article: dict[int, dict],
) -> MultiregionAttributionRun:
    rows = []
    for article in articles:
        evidence = evidence_by_article.get(article.id) or {}
        published_at = evidence.get("published_at")
        rows.append(
            {
                "article_id": article.id,
                "article_fingerprint": _article_fingerprint(article),
                "before_published_at": article.published_at.isoformat() if article.published_at else "",
                "published_at": _json_datetime(published_at),
                "raw": evidence.get("raw", ""),
                "timezone": evidence.get("timezone", "Europe/Paris"),
                "verified": bool(published_at),
                "error": evidence.get("error", "") or ("missing_date" if not published_at else ""),
            }
        )
    manifest_payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_sha256 = hashlib.sha256(manifest_payload.encode()).hexdigest()
    return MultiregionAttributionRun.objects.create(
        mode="dry_run",
        selectors={"kind": "france_galop_published_at_repair"},
        status=MultiregionAttributionRunStatus.COMPLETED,
        candidate_payload=rows,
        outcomes=rows,
        manifest_sha256=manifest_sha256,
        finished_at=timezone.now(),
    )


def commit_time_repair(*, run_id: int, manifest_sha256: str) -> TimeRepairCommitResult:
    run = MultiregionAttributionRun.objects.get(pk=run_id)
    if run.status != MultiregionAttributionRunStatus.COMPLETED or run.manifest_sha256 != manifest_sha256:
        raise ValidationError("dry-run 状态或 manifest 不匹配")
    if (run.selectors or {}).get("kind") != "france_galop_published_at_repair":
        raise ValidationError("run 类型不匹配")
    applied_ids: list[int] = []
    drifted_ids: list[int] = []
    skipped: dict[int, str] = {}
    completed_ids = list(run.completed_article_ids or [])
    for row in run.candidate_payload or []:
        article_id = int(row["article_id"])
        if article_id in completed_ids:
            continue
        if not row.get("verified") or not row.get("published_at"):
            skipped[article_id] = str(row.get("error") or "missing_date")
            completed_ids.append(article_id)
            run.completed_article_ids = completed_ids
            run.cursor = len(completed_ids)
            run.save(update_fields=["completed_article_ids", "cursor", "updated_at"])
            continue
        skip_reason = ""
        with transaction.atomic():
            article = NewsArticle.objects.select_for_update().filter(pk=article_id).first()
            if article is None:
                skip_reason = "article_missing"
            elif _article_fingerprint(article) != row["article_fingerprint"]:
                drifted_ids.append(article.id)
                skip_reason = "article_fingerprint"
            else:
                try:
                    published_at = datetime.fromisoformat(row["published_at"])
                except (TypeError, ValueError):
                    skip_reason = "invalid_published_at"
            if skip_reason:
                skipped[article_id] = skip_reason
                completed_ids.append(article_id)
            else:
                evidence = {
                    "source": "detail",
                    "raw": row.get("raw", ""),
                    "timezone": row.get("timezone", "Europe/Paris"),
                    "verified": True,
                    "previous_published_at": article.published_at.isoformat() if article.published_at else "",
                    "repair_run_id": run.id,
                }
                article.published_at = published_at
                article.published_at_verified = True
                article.published_at_evidence = evidence
                article.save(
                    update_fields=[
                        "published_at",
                        "published_at_verified",
                        "published_at_evidence",
                        "updated_at",
                    ]
                )
                applied_ids.append(article.id)
                completed_ids.append(article.id)
        run.completed_article_ids = completed_ids
        run.cursor = len(completed_ids)
        run.save(update_fields=["completed_article_ids", "cursor", "updated_at"])
    return TimeRepairCommitResult(applied_ids=applied_ids, drifted_ids=drifted_ids, skipped=skipped)
