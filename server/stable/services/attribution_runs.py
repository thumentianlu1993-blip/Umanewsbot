from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import prefetch_related_objects
from django.utils import timezone

from stable.models import (
    AttributionStatus,
    MultiregionAttributionLock,
    MultiregionAttributionRun,
    MultiregionAttributionRunStatus,
    NewsArticle,
    RacingRegion,
)
from stable.services.news_attribution import (
    ATTRIBUTION_RULE_VERSION,
    AttributionBatchContext,
    infer_article_attribution,
    set_article_regions,
)
from stable.services.validation import apply_validation_outcome, validate_rewrite


@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    expires_at: object | None = None
    owner_token: str = ""


@dataclass(frozen=True)
class AttributionCommitResult:
    status: str
    applied_ids: list[int] = field(default_factory=list)
    already_completed_ids: list[int] = field(default_factory=list)
    drifted: dict[int, str] = field(default_factory=dict)
    restored_ids: list[int] = field(default_factory=list)
    still_blocked_ids: list[int] = field(default_factory=list)


OPERATIONAL_REGIONS = (
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
)


def _fingerprint(article: NewsArticle) -> str:
    payload = {
        "id": article.id,
        "title": article.title_ja,
        "body": article.body_ja_normalized or article.body_ja_raw,
        "region": article.racing_region,
        "locked": article.attribution_locked,
        "updated_at": article.updated_at.isoformat() if article.updated_at else "",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def create_attribution_run(
    *,
    mode: str,
    selectors: dict,
    status: str = MultiregionAttributionRunStatus.PENDING,
    **kwargs,
) -> MultiregionAttributionRun:
    return MultiregionAttributionRun.objects.create(mode=mode, selectors=selectors, status=status, **kwargs)


def _sha256(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def build_attribution_settings_sha256() -> str:
    return _sha256(
        {
            "rule_version": ATTRIBUTION_RULE_VERSION,
            "common_english_terms": list(getattr(settings, "MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS", [])),
            "ignored_source_terms": list(getattr(settings, "MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS", [])),
        }
    )


def build_attribution_term_snapshot_sha256(context: AttributionBatchContext | None = None) -> str:
    context = context or AttributionBatchContext.build()
    rows = []
    for entry in sorted(context.entries, key=lambda item: item.pk):
        rows.append(
            {
                "id": entry.pk,
                "type": entry.term_type,
                "region": entry.racing_region,
                "active": entry.is_active,
                "terms": {
                    language: list((terms_by_entry or {}).get(entry.pk, []))
                    for language, terms_by_entry in sorted(context.terms_by_language.items())
                },
            }
        )
    return _sha256(rows)


def _manifest_sha256(
    *,
    rows: list[dict],
    rule_version: str,
    term_version: str,
    gold_version: str,
    settings_sha256: str,
    term_snapshot_sha256: str,
    gold_snapshot_sha256: str,
    metrics: dict,
) -> str:
    return _sha256(
        {
            "rows": rows,
            "rule_version": rule_version,
            "term_version": term_version,
            "gold_version": gold_version,
            "settings_sha256": settings_sha256,
            "term_snapshot_sha256": term_snapshot_sha256,
            "gold_snapshot_sha256": gold_snapshot_sha256,
            "metrics": metrics,
        }
    )


def verify_attribution_run_manifest(run: MultiregionAttributionRun) -> bool:
    rows = list(run.candidate_payload or [])
    current_manifest = _manifest_sha256(
        rows=rows,
        rule_version=run.rule_version,
        term_version=run.term_version,
        gold_version=run.gold_version,
        settings_sha256=run.settings_sha256,
        term_snapshot_sha256=run.term_snapshot_sha256,
        gold_snapshot_sha256=run.gold_snapshot_sha256,
        metrics=dict(run.metrics or {}),
    )
    return (
        current_manifest == run.manifest_sha256
        and run.candidate_fingerprint == _sha256(rows)
    )


def acquire_attribution_lease(
    run: MultiregionAttributionRun,
    *,
    now=None,
    owner_token: str = "",
) -> LeaseResult:
    now = now or timezone.now()
    requested_token = owner_token or uuid.uuid4().hex
    expires = now + timedelta(minutes=int(getattr(settings, "MULTIREGION_ATTRIBUTION_LEASE_MINUTES", 30)))
    with transaction.atomic():
        lock, _created = MultiregionAttributionLock.objects.select_for_update().get_or_create(key="attribution")
        if lock.lease_expires_at and lock.lease_expires_at > now:
            if owner_token and (lock.locked_by_run_id != run.id or lock.owner_token != requested_token):
                return LeaseResult(False, lock.lease_expires_at, lock.owner_token)
            if not owner_token and lock.locked_by_run_id != run.id:
                return LeaseResult(False, lock.lease_expires_at, lock.owner_token)
            if not owner_token and lock.locked_by_run_id == run.id:
                return LeaseResult(True, lock.lease_expires_at, lock.owner_token)
        lock.locked_by_run = run
        lock.owner_token = requested_token
        lock.lease_expires_at = expires
        lock.heartbeat_at = now
        lock.save()
    return LeaseResult(True, expires, requested_token)


def renew_attribution_lease(run: MultiregionAttributionRun, *, now=None, owner_token: str = "") -> LeaseResult:
    now = now or timezone.now()
    expires = now + timedelta(minutes=int(getattr(settings, "MULTIREGION_ATTRIBUTION_LEASE_MINUTES", 30)))
    filters = {"key": "attribution", "locked_by_run": run}
    if owner_token:
        filters["owner_token"] = owner_token
    updated = MultiregionAttributionLock.objects.filter(**filters).update(
        lease_expires_at=expires,
        heartbeat_at=now,
        updated_at=now,
    )
    return LeaseResult(bool(updated), expires if updated else None, owner_token)


def release_attribution_lease(run: MultiregionAttributionRun, *, owner_token: str) -> bool:
    updated = MultiregionAttributionLock.objects.filter(
        key="attribution",
        locked_by_run=run,
        owner_token=owner_token,
    ).update(
        locked_by_run=None,
        owner_token="",
        lease_expires_at=None,
        heartbeat_at=None,
        updated_at=timezone.now(),
    )
    return bool(updated)


def create_attribution_dry_run(
    articles,
    *,
    rule_version: str,
    gold_version: str,
    term_version: str = "",
    gold_snapshot_sha256: str = "",
    metrics: dict | None = None,
    selectors: dict | None = None,
) -> MultiregionAttributionRun:
    article_rows = list(articles)
    prefetch_related_objects(article_rows, "related_region_links")
    rows = []
    batch_context = AttributionBatchContext.build(article_rows)
    for article in article_rows:
        related_links = article._prefetched_objects_cache.get("related_region_links", [])
        before = {
            "primary": article.racing_region,
            "related": [link.region for link in related_links],
        }
        result = infer_article_attribution(article, batch_context=batch_context)
        proposed = {
            "primary": result.primary_region,
            "related": result.related_regions,
            "status": result.status,
            "confidence": result.confidence,
            "evidence": result.evidence,
            "reason": result.reason,
            "source": result.source,
            "content_category": result.content_category,
            "rule_version": result.rule_version,
        }
        if article.attribution_locked:
            after = {
                **before,
                "status": AttributionStatus.LOCKED_SKIP,
                "confidence": article.attribution_confidence or 0,
                "evidence": {"attribution_locked": True},
                "reason": "attribution_locked",
                "source": article.attribution_source or "existing",
                "content_category": article.content_category,
                "rule_version": article.attribution_rule_version or rule_version,
            }
        else:
            after = proposed
        row = {
            "article_id": article.id,
            "fingerprint": _fingerprint(article),
            "before": before,
            "after": after,
        }
        if article.attribution_locked:
            row["proposed"] = proposed
        rows.append(row)
    settings_sha256 = build_attribution_settings_sha256()
    term_snapshot_sha256 = build_attribution_term_snapshot_sha256(batch_context)
    resolved_gold_snapshot_sha256 = gold_snapshot_sha256 or _sha256({"gold_version": gold_version})
    resolved_metrics = dict(metrics or {})
    if selectors is not None:
        scope = str(selectors.get("scope") or "gate_candidates")
        resolved_metrics["_run_contract"] = {
            "scope": scope,
            "scope_complete": bool(selectors.get("scope_complete", True)),
            "commit_policy": "attribution_only" if scope == "all_articles" else "attribution_and_gate",
        }
    candidate_fingerprint = _sha256(rows)
    manifest = _manifest_sha256(
        rows=rows,
        rule_version=rule_version,
        term_version=term_version,
        gold_version=gold_version,
        settings_sha256=settings_sha256,
        term_snapshot_sha256=term_snapshot_sha256,
        gold_snapshot_sha256=resolved_gold_snapshot_sha256,
        metrics=resolved_metrics,
    )
    return create_attribution_run(
        mode="dry_run",
        selectors={**(selectors or {}), "article_ids": [row["article_id"] for row in rows]},
        status=MultiregionAttributionRunStatus.COMPLETED,
        rule_version=rule_version,
        term_version=term_version,
        gold_version=gold_version,
        settings_sha256=settings_sha256,
        term_snapshot_sha256=term_snapshot_sha256,
        gold_snapshot_sha256=resolved_gold_snapshot_sha256,
        candidate_payload=rows,
        outcomes=rows,
        metrics=resolved_metrics,
        candidate_fingerprint=candidate_fingerprint,
        manifest_sha256=manifest,
        finished_at=timezone.now(),
    )


def build_attribution_review_report(
    run: MultiregionAttributionRun,
    *,
    include_gate_validation: bool = False,
    review_sample_per_region: int | None = None,
) -> dict:
    """Build an audit report from a persisted run without repeating attribution inference."""
    rows = list(run.candidate_payload or [])
    article_ids = [int(row["article_id"]) for row in rows]
    articles_by_id = NewsArticle.objects.in_bulk(article_ids)
    selectors = dict(run.selectors or {})
    run_contract = dict((run.metrics or {}).get("_run_contract") or {})
    scope = str(run_contract.get("scope") or selectors.get("scope") or "gate_candidates")
    scope_complete = bool(
        run_contract.get(
            "scope_complete",
            selectors.get("scope_complete", scope != "all_articles"),
        )
    )
    sample_size = max(
        0,
        int(
            selectors.get("review_sample_per_region", 5)
            if review_sample_per_region is None
            else review_sample_per_region
        ),
    )

    primary_change_ids: list[int] = []
    needs_review_ids: list[int] = []
    locked_skip_ids: list[int] = []
    validation_passed_ids: list[int] = []
    validation_blocked_ids: list[int] = []
    validation_skipped_ids: list[int] = []
    restored_ids: list[int] = []
    still_blocked_ids: list[int] = []
    missing_article_ids: list[int] = []
    drifted_article_ids: list[int] = []
    outcomes: list[dict] = []

    for row in rows:
        article_id = int(row["article_id"])
        before = dict(row.get("before") or {})
        after = dict(row.get("after") or {})
        proposed = dict(row.get("proposed") or after)
        if before.get("primary") != after.get("primary"):
            primary_change_ids.append(article_id)
        if after.get("status") == AttributionStatus.NEEDS_REVIEW:
            needs_review_ids.append(article_id)
        if after.get("status") == AttributionStatus.LOCKED_SKIP:
            locked_skip_ids.append(article_id)

        article = articles_by_id.get(article_id)
        if article is None:
            missing_article_ids.append(article_id)
            validation_skipped_ids.append(article_id)
            outcomes.append(
                {
                    "article_id": article_id,
                    "article_missing": True,
                    "fingerprint_matches": False,
                    "old_regions": before,
                    "new_regions": {
                        "primary": after.get("primary"),
                        "related": list(after.get("related") or []),
                    },
                    "inferred_regions": {
                        "primary": proposed.get("primary"),
                        "related": list(proposed.get("related") or []),
                    },
                    "attribution_status": after.get("status"),
                    "attribution_reason": after.get("reason"),
                    "attribution_confidence": after.get("confidence"),
                    "attribution_evidence": after.get("evidence") or {},
                    "content_category": after.get("content_category"),
                    "validation_evaluated": False,
                    "validation_passed": None,
                    "validation_reason": "article_missing",
                    "blockers": [],
                }
            )
            continue

        fingerprint_matches = _fingerprint(article) == row.get("fingerprint")
        if not fingerprint_matches:
            drifted_article_ids.append(article_id)
        validation = None
        validation_skip_reason = "not_evaluated"
        if include_gate_validation and fingerprint_matches:
            article._attribution_region_override = {
                after.get("primary"),
                *list(after.get("related") or []),
            } - {None, ""}
            try:
                validation = validate_rewrite(article)
            finally:
                delattr(article, "_attribution_region_override")
            if validation.passed:
                validation_passed_ids.append(article_id)
                if scope == "gate_candidates":
                    restored_ids.append(article_id)
            else:
                validation_blocked_ids.append(article_id)
                if scope == "gate_candidates":
                    still_blocked_ids.append(article_id)
        else:
            validation_skipped_ids.append(article_id)
            if include_gate_validation:
                validation_skip_reason = "article_fingerprint_drift"

        outcomes.append(
            {
                "article_id": article_id,
                "article_missing": False,
                "fingerprint_matches": fingerprint_matches,
                "title": article.title_ja,
                "source_url": article.source_url,
                "source_site": article.source_site,
                "published_at": article.published_at,
                "first_seen_at": article.first_seen_at,
                "old_regions": before,
                "new_regions": {
                    "primary": after.get("primary"),
                    "related": list(after.get("related") or []),
                },
                "inferred_regions": {
                    "primary": proposed.get("primary"),
                    "related": list(proposed.get("related") or []),
                },
                "attribution_status": after.get("status"),
                "attribution_reason": after.get("reason"),
                "attribution_confidence": after.get("confidence"),
                "attribution_evidence": after.get("evidence") or {},
                "attribution_locked": article.attribution_locked,
                "attribution_applied": not article.attribution_locked,
                "content_category": after.get("content_category"),
                "validation_evaluated": validation is not None,
                "validation_passed": validation.passed if validation is not None else None,
                "validation_reason": validation.reason if validation is not None else validation_skip_reason,
                "blockers": (
                    [issue for issue in validation.issues if issue.get("severity") == "blocker"]
                    if validation is not None
                    else []
                ),
            }
        )

    required_review_ids = (
        set(primary_change_ids)
        | set(needs_review_ids)
        | set(locked_skip_ids)
        | set(missing_article_ids)
        | set(drifted_article_ids)
    )
    review_sample_ids_by_region: dict[str, list[int]] = {}
    for region in OPERATIONAL_REGIONS:
        sample_pool = [
            row
            for row in rows
            if (row.get("before") or {}).get("primary") == region
            and int(row["article_id"]) not in required_review_ids
        ]
        sample_pool.sort(
            key=lambda row: hashlib.sha256(
                f"{row['article_id']}:{row['fingerprint']}".encode()
            ).hexdigest()
        )
        review_sample_ids_by_region[region] = [
            int(row["article_id"]) for row in sample_pool[:sample_size]
        ]
    review_checklist_ids = list(
        dict.fromkeys(
            [
                *primary_change_ids,
                *needs_review_ids,
                *locked_skip_ids,
                *missing_article_ids,
                *drifted_article_ids,
                *[
                    article_id
                    for region in OPERATIONAL_REGIONS
                    for article_id in review_sample_ids_by_region[region]
                ],
            ]
        )
    )
    return {
        "run_id": run.id,
        "run_status": run.status,
        "manifest_sha256": run.manifest_sha256,
        "scope": scope,
        "scope_complete": scope_complete,
        "regions": list(selectors.get("regions") or []),
        "lookback_hours": selectors.get("lookback_hours"),
        "window_start": selectors.get("window_start"),
        "candidate_count": len(rows),
        "candidate_ids": article_ids,
        "restored_candidate_ids": restored_ids,
        "still_blocked_ids": still_blocked_ids,
        "validation_included": include_gate_validation,
        "validation_passed_ids": validation_passed_ids,
        "validation_blocked_ids": validation_blocked_ids,
        "validation_skipped_ids": validation_skipped_ids,
        "primary_change_ids": primary_change_ids,
        "needs_review_ids": needs_review_ids,
        "locked_skip_ids": locked_skip_ids,
        "review_sample_ids_by_region": review_sample_ids_by_region,
        "review_checklist_ids": review_checklist_ids,
        "missing_article_ids": missing_article_ids,
        "drifted_article_ids": drifted_article_ids,
        "metrics": run.metrics or {},
        "outcomes": outcomes,
    }
def apply_run_outcome(article: NewsArticle, outcome: dict) -> None:
    after = outcome.get("after") or {}
    set_article_regions(
        article,
        primary_region=after.get("primary"),
        related_regions=after.get("related") or [],
        attribution_source=after.get("source") or "auto",
        reason=after.get("reason") or "manifest_commit",
        evidence=after.get("evidence") or {},
        content_category=after.get("content_category"),
        status=after.get("status") or "applied",
        confidence=after.get("confidence"),
        rule_version=after.get("rule_version") or ATTRIBUTION_RULE_VERSION,
        save=True,
    )


def commit_attribution_run(
    run_id: int,
    *,
    manifest_sha256: str,
    resume: bool = False,
    expected_gold_version: str | None = None,
    expected_gold_snapshot_sha256: str | None = None,
) -> AttributionCommitResult:
    run = MultiregionAttributionRun.objects.get(pk=run_id)
    if run.status not in {MultiregionAttributionRunStatus.COMPLETED, MultiregionAttributionRunStatus.PARTIAL}:
        raise ValidationError("只有成功或可续跑的 dry-run 才能 commit")
    if run.mode != "dry_run" or run.manifest_sha256 != manifest_sha256:
        raise ValidationError("run 或 manifest 不匹配")
    if not verify_attribution_run_manifest(run):
        raise ValidationError("run 内容已偏离审核 manifest，请重新 dry-run")
    if run.status == MultiregionAttributionRunStatus.PARTIAL and not resume:
        raise ValidationError("部分完成的 run 必须使用 --resume")
    if run.rule_version != ATTRIBUTION_RULE_VERSION:
        raise ValidationError("归属规则版本已漂移，请重新 dry-run")
    if run.settings_sha256 != build_attribution_settings_sha256():
        raise ValidationError("归属配置已漂移，请重新 dry-run")
    if run.term_snapshot_sha256 != build_attribution_term_snapshot_sha256():
        raise ValidationError("术语快照已漂移，请重新 dry-run")
    if expected_gold_version is not None and run.gold_version != expected_gold_version:
        raise ValidationError("gold 版本已漂移，请重新 dry-run")
    if expected_gold_snapshot_sha256 is not None and run.gold_snapshot_sha256 != expected_gold_snapshot_sha256:
        raise ValidationError("gold 快照已漂移，请重新 dry-run")
    if run.gold_version in {"", "pending-review"}:
        raise ValidationError("gold set 尚未完成审核，禁止 commit")
    if len(run.gold_snapshot_sha256 or "") != 64:
        raise ValidationError("gold 快照 SHA-256 无效，禁止 commit")
    if not bool((run.metrics or {}).get("qualified")):
        raise ValidationError("gold 质量门槛未通过，禁止 commit")
    run_contract = dict((run.metrics or {}).get("_run_contract") or {})
    if not run_contract:
        legacy_scope = (run.selectors or {}).get("scope")
        run_contract = {
            "scope": legacy_scope or "gate_candidates",
            "scope_complete": bool((run.selectors or {}).get("scope_complete", legacy_scope != "all_articles")),
            "commit_policy": "attribution_only" if legacy_scope == "all_articles" else "attribution_and_gate",
        }
    if run_contract.get("scope") == "all_articles" and not run_contract.get("scope_complete", False):
        raise ValidationError("全量近期文章 run 已截断，禁止 commit")
    if run_contract.get("commit_policy") not in {"attribution_only", "attribution_and_gate"}:
        raise ValidationError("归属 run commit policy 无效，请重新 dry-run")
    owner_token = uuid.uuid4().hex
    lease = acquire_attribution_lease(run, owner_token=owner_token)
    if not lease.acquired:
        raise ValidationError("已有归属 run 正在提交，请稍后重试")
    completed = list(run.completed_article_ids or [])
    attribution_only = run_contract["commit_policy"] == "attribution_only"
    already_completed = list(completed)
    applied: list[int] = []
    drifted: dict[int, str] = {}
    restored: list[int] = []
    still_blocked: list[int] = []
    try:
        for outcome in run.candidate_payload or []:
            article_id = int(outcome["article_id"])
            if article_id in completed:
                continue
            try:
                if not renew_attribution_lease(run, owner_token=owner_token).acquired:
                    raise RuntimeError("归属 lease 已丢失，停止 commit")
                with transaction.atomic():
                    article = NewsArticle.objects.select_for_update().get(pk=article_id)
                    if article.attribution_locked:
                        drifted[article_id] = "attribution_locked"
                        continue
                    if _fingerprint(article) != outcome["fingerprint"]:
                        drifted[article_id] = "article_fingerprint"
                        continue
                    apply_run_outcome(article, outcome)
                    if not attribution_only:
                        validation = validate_rewrite(article)
                        apply_validation_outcome(article, validation)
                        if validation.passed:
                            article.ranked_revived_at = timezone.now()
                            article.save(update_fields=["ranked_revived_at", "updated_at"])
                            restored.append(article_id)
                        else:
                            still_blocked.append(article_id)
                    completed.append(article_id)
                    applied.append(article_id)
                run.cursor = len(completed)
                run.completed_article_ids = completed
                run.save(update_fields=["cursor", "completed_article_ids", "updated_at"])
            except Exception as exc:
                run.status = MultiregionAttributionRunStatus.PARTIAL
                run.cursor = len(completed)
                run.completed_article_ids = completed
                run.error_message = str(exc)
                run.save(update_fields=["status", "cursor", "completed_article_ids", "error_message", "updated_at"])
                return AttributionCommitResult(
                    status=MultiregionAttributionRunStatus.PARTIAL,
                    applied_ids=applied,
                    already_completed_ids=already_completed,
                    drifted=drifted,
                    restored_ids=restored,
                    still_blocked_ids=still_blocked,
                )
        run.status = MultiregionAttributionRunStatus.COMPLETED
        run.cursor = len(completed)
        run.completed_article_ids = completed
        run.error_message = ""
        run.finished_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "cursor",
                "completed_article_ids",
                "error_message",
                "finished_at",
                "updated_at",
            ]
        )
        return AttributionCommitResult(
            status=MultiregionAttributionRunStatus.COMPLETED,
            applied_ids=applied,
            already_completed_ids=already_completed,
            drifted=drifted,
            restored_ids=restored,
            still_blocked_ids=still_blocked,
        )
    finally:
        release_attribution_lease(run, owner_token=owner_token)
