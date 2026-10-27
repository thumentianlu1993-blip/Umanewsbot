"""P01 唯一网页 writer：所有公开字段、稿件回执与索引同一事务提交。"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    NewsArticle, NewsProcessingRun, NewsStageAttempt, NewsPublicationReceipt,
    NewsEditorialEvent, ArticleHorseLink, ArticleRaceLink, TermEntry, QuotaLedger,
)
from stable.services.news_pipeline import digest, policy_sha, _current_run, article_revision, source_eligible, target_revision_digest
from stable.services.news_content import ContentBlocked, validate_audit, validate_entities
from stable.services.news_editorial import validate_editorial, audit_corrections
from stable.services.news_feed import publication_lock, append_public_entry


def _validated_attempt(run, attempt_id, stage):
    attempt = NewsStageAttempt.objects.filter(pk=attempt_id, run=run, stage=stage, state="completed").first()
    if not attempt or attempt.output_sha != digest(attempt.result) or attempt.input_sha != digest(attempt.usage.get("input")):
        raise ContentBlocked("stage_receipt_invalid")
    spec = getattr(settings, "NEWS_QUALITY_POLICY", {}).get("models", {}).get(stage, {})
    if attempt.model != spec.get("model") or attempt.prompt_version != spec.get("prompt_version") or attempt.usage.get("price") != spec:
        raise ContentBlocked("model_policy_changed")
    if stage in {"entity_check", "fact_audit"} and spec.get("quality_tier") != "strong":
        raise ContentBlocked("strong_model_receipt_missing")
    return attempt


def check_publication_evidence(run):
    if run.policy_sha != policy_sha() or digest(run.source_snapshot) != run.input_sha or not source_eligible(run):
        raise ContentBlocked("source_or_policy_changed")
    clean = run.clean_snapshot
    from stable.services.news_content import clean_source, validate_body_review
    selectors = getattr(settings, "NEWS_QUALITY_POLICY", {}).get("body_selectors", {}).get(run.source_snapshot["source_site"])
    expected_clean = clean_source(run.source_snapshot, selectors=selectors)
    if expected_clean.get("suspicious_block_ids"):
        body_review = _validated_attempt(run, clean.get("body_review_attempt_id"), "body_review")
        if body_review.usage["input"].get("source") != expected_clean:
            raise ContentBlocked("body_review_input_changed")
        expected_clean = validate_body_review(expected_clean, body_review.result)
        expected_clean["body_review_attempt_id"] = body_review.pk
    if clean != expected_clean:
        raise ContentBlocked("clean_source_evidence_changed")
    if clean.get("source_sha") != run.input_sha or clean.get("clean_sha") != digest({"title": clean.get("title"), "blocks": clean.get("blocks")}):
        raise ContentBlocked("clean_snapshot_changed")
    if run.priority not in {"major", "regional"} or run.primary_region != run.editorial_snapshot.get("primary_region"):
        raise ContentBlocked("editorial_selection_missing")
    entity = _validated_attempt(run, run.entity_snapshot.get("strong_attempt_id"), "entity_check")
    if entity.usage["input"].get("source") != clean:
        raise ContentBlocked("entity_input_changed")
    raw_entities = validate_entities(clean, entity.result)
    frozen = run.entity_snapshot.get("occurrences", [])
    keys = ("block_id", "start", "end", "text", "type", "token", "source_sha")
    if [{key: row[key] for key in keys} for row in raw_entities] != [{key: row.get(key) for key in keys} for row in frozen]:
        raise ContentBlocked("entity_snapshot_changed")
    for row in frozen:
        if row.get("term_id"):
            term = TermEntry.objects.filter(pk=row["term_id"], is_active=True).first()
            if not term or not term.has_translation or term.target_zh != row["replacement"]:
                raise ContentBlocked("term_revision_changed")
        elif row["replacement"] != row["text"]:
            raise ContentBlocked("invented_entity_translation")
    audit = _validated_attempt(run, run.quality_snapshot.get("strong_attempt_id"), "fact_audit")
    if audit.usage["input"].get("source") != clean or audit.usage["input"].get("target") != run.translation_snapshot:
        raise ContentBlocked("audit_input_changed")
    if audit.usage["input"].get("editorial") != run.editorial_snapshot:
        raise ContentBlocked("audit_editorial_changed")
    quality = validate_audit(clean, run.translation_snapshot, audit_corrections(run.editorial_snapshot, audit.result))
    if not quality["passed"] or run.quality_snapshot.get("target_sha") != quality["target_sha"] or run.quality_snapshot.get("policy_sha") != run.policy_sha:
        raise ContentBlocked("target_not_audited")
    if run.manual_target and (target_revision_digest(run.manual_target, run.editor_provenance.get("event_binding")) != run.target_revision_sha
            or any(run.manual_target[key] != run.translation_snapshot[key] for key in ("title", "body", "summary"))):
        raise ContentBlocked("manual_target_changed")
    editorial = run.attempts.filter(stage="event_classify", state="completed").order_by("-seq").first()
    if not editorial:
        raise ContentBlocked("editorial_receipt_missing")
    editorial = _validated_attempt(run, editorial.pk, "event_classify")
    value = validate_editorial(clean, editorial.result, source_scope=run.source_snapshot["source_site"],
        candidates=editorial.usage["input"].get("candidates", []),
        aliases=getattr(settings, "NEWS_QUALITY_POLICY", {}).get("identity_aliases", {}),
        binding=run.editor_provenance.get("event_binding"))
    if value != run.editorial_snapshot or value["identity_key"] != run.event.identity_key:
        raise ContentBlocked("editorial_evidence_changed")
    if run.attempts.filter(state__in=["reserved", "inflight", "unknown"]).exists():
        raise ContentBlocked("request_unresolved")
    if run.attempts.exclude(provider="").filter(~Q(month_budget__state="open") | ~Q(day_budget__state="open")).exists():
        raise ContentBlocked("budget_unreconciled")
    if urlsplit(run.source_snapshot.get("url", "")).scheme not in {"http", "https"}:
        raise ContentBlocked("source_url_invalid")


def verified_relations(run):
    occurrences = run.entity_snapshot["occurrences"]
    term_occurrences = {row["term_id"]: row for row in occurrences if row.get("term_id") and row["type"] == "horse"}
    result = {"horse_ids": [], "race_ids": [], "evidence": [], "gaps": []}
    links = ArticleHorseLink.objects.filter(article=run.article, status__in=["auto", "manual"],
        horse_profile__primary_term_id__in=term_occurrences).select_related("horse_profile")
    for link in links:
        occurrence = term_occurrences[link.horse_profile.primary_term_id]
        result["horse_ids"].append(link.horse_profile_id)
        result["evidence"].append({"kind": "horse", "id": link.horse_profile_id, "link_id": link.pk,
            "link_version": link.updated_at.isoformat(), "source_sha": run.input_sha,
            "occurrence": {key: occurrence[key] for key in ("block_id", "start", "end", "text", "term_id")}})
    canonical_race = run.editorial_snapshot.get("identity", {}).get("fields", {}).get("canonical_race_id")
    if canonical_race and any(row["type"] == "race" for row in occurrences):
        for link in ArticleRaceLink.objects.filter(article=run.article, event_id=canonical_race, status__in=["auto", "manual"]):
            result["race_ids"].append(link.event_id)
            result["evidence"].append({"kind": "race", "id": link.event_id, "link_id": link.pk,
                "link_version": link.updated_at.isoformat(), "source_sha": run.input_sha,
                "identity": run.editorial_snapshot["identity"]})
    if len(result["evidence"]) > 128:
        return {"horse_ids": [], "race_ids": [], "evidence": [], "gaps": ["relation_limit"]}
    return result


def _reserve_quota(run, now):
    cap = int(getattr(settings, "MULTIREGION_PUBLISH_SITE_HOURLY_MAX_DAILY", 60))
    ledger, _ = QuotaLedger.objects.get_or_create(kind="web_publish", scope="site_hour", scope_key="site",
        window_start=now.replace(minute=0, second=0, microsecond=0), defaults={"limit": cap, "used": 0})
    ledger = QuotaLedger.objects.select_for_update().get(pk=ledger.pk)
    if ledger.used >= min(cap, ledger.limit):
        return False
    limits = getattr(settings, "MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS", {})
    if run.primary_region in limits:
        start = now.astimezone(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0)
        count = NewsPublicationReceipt.objects.filter(published_at__gte=start, run__primary_region=run.primary_region).count()
        count += NewsArticle.objects.filter(active_news_run__isnull=True, racing_region=run.primary_region,
            published_by_mode="auto", auto_publish_at__gte=start).count()
        if count >= int(limits[run.primary_region]):
            return False
    ledger.used += 1
    ledger.save(update_fields=["used", "updated_at"])
    return True


def _primary_candidate(event, run):
    rows = list(NewsProcessingRun.objects.filter(event=event, state__in=["ready", "shadow"], policy_sha=run.policy_sha)
        .select_related("article__source_config").order_by("article__first_seen_at", "id")[:21])
    if len(rows) > 20:
        return None
    qualified = []
    for row in rows:
        if not _current_run(row.article, row):
            continue
        try:
            check_publication_evidence(row)
        except ContentBlocked:
            continue
        qualified.append(row)
    qualified.sort(key=lambda row: (
        0 if row.article.source_config and row.article.source_config.source_kind == "official" else 1,
        row.article.first_seen_at, row.pk))
    return qualified[0].pk if qualified else None


@transaction.atomic
def publish(run_id):
    if getattr(settings, "NEWS_QUALITY_MODE", "off") != "enforce":
        return None
    publication_lock()
    reference = NewsProcessingRun.objects.get(pk=run_id)
    if not reference.event_id:
        return None
    event = NewsEditorialEvent.objects.select_for_update().get(pk=reference.event_id)
    article = NewsArticle.objects.select_for_update().get(pk=reference.article_id)
    run = NewsProcessingRun.objects.select_for_update().get(pk=run_id)
    run.article, run.event = article, event
    existing = NewsPublicationReceipt.objects.filter(run=run).first()
    if existing:
        return existing
    if run.state not in {"ready", "shadow"}:
        return None
    if not _current_run(article, run):
        run.state, run.reason = "stale", "revision_changed"
        run.save(update_fields=["state", "reason"])
        return None
    try:
        if not getattr(settings, "NEWS_QUALITY_FEED_ENABLED", False):
            raise ContentBlocked("feed_not_enabled")
        check_publication_evidence(run)
    except ContentBlocked as error:
        run.state, run.reason = "review", str(error)
        run.save(update_fields=["state", "reason"])
        return None
    if run.event_version != event.version:
        run.state, run.stage, run.reason = "pending", "event_classify", "event_recompare"
        run.save(update_fields=["state", "stage", "reason"])
        return None
    if event.version == 0 and _primary_candidate(event, run) != run.pk:
        run.reason = "await_primary_or_selection_overflow"
        run.next_attempt_at = timezone.now() + timedelta(minutes=1)
        run.save(update_fields=["reason", "next_attempt_at"])
        return None
    old_ids = {fact["id"] for fact in event.published_facts}
    facts = run.editorial_snapshot["facts"]
    delta = [fact for fact in facts if fact["relation"] == "new" and fact["id"] not in old_ids
             and (event.version == 0 or fact["importance"] == "major")]
    corrections = [fact for fact in facts if fact["relation"] == "correction" and fact["importance"] == "major"]
    previous = article.news_receipts.order_by("-published_at", "-id").first() or event.receipts.order_by("-published_at", "-id").first()
    if not delta and not corrections:
        run.state, run.reason = "duplicate", "no_material_new_fact"
        run.save(update_fields=["state", "reason"])
        return None
    kind = "correction_story" if corrections else "new_story"
    if corrections:
        target_ids = {fact["correction"]["receipt_id"] for fact in corrections}
        if len(target_ids) != 1:
            run.state, run.reason = "review", "correction_multiple_targets"
            run.save(update_fields=["state", "reason"])
            return None
        previous = event.receipts.filter(pk=next(iter(target_ids))).first()
    if corrections and not previous:
        run.state, run.reason = "review", "correction_target_missing"
        run.save(update_fields=["state", "reason"])
        return None
    key = digest({"kind": kind, "new_facts": sorted(fact["id"] for fact in delta),
        "corrections": sorted((str(previous.pk), tuple(sorted(fact["prior_fact_ids"])), fact["id"], digest(fact["correction"])) for fact in corrections)})
    if event.receipts.filter(publication_key=key).exists():
        run.state, run.reason = "duplicate", "publication_already_recorded"
        run.save(update_fields=["state", "reason"])
        return None
    now = timezone.now()
    if not _reserve_quota(run, now):
        run.reason, run.next_attempt_at = "publication_capacity", now + timedelta(minutes=5)
        run.save(update_fields=["reason", "next_attempt_at"])
        return None
    target = run.translation_snapshot
    content = {name: target[name] for name in ("title", "body", "summary")}
    content.update(source_url=run.source_snapshot["url"], source_title=run.source_snapshot["title"],
        source_site=run.source_snapshot["source_site"], source_language=run.source_snapshot["language"],
        cover_url=article.cover_image_url or "", tags=list(article.tags_json or []))
    relations = verified_relations(run)
    if not article.published_to_web_at:
        values = {"title_zh": target["title"], "body_zh": target["body"], "summary_zh": target["summary"],
            "translated_title_zh": target["title"], "translated_body_zh": target["body"], "translated_summary_zh": target["summary"],
            "rewrite_title_zh": "", "rewrite_body_zh": "", "rewrite_summary_zh": "", "push_summary_zh": target["summary"],
            "workflow_status": "published", "published_to_web_at": now, "auto_publish_at": now,
            "published_by_mode": "manual" if run.manual_target else "auto", "automation_status": "auto_published",
            "translation_status": "translated", "status": "reviewed"}
        if run.manual_target:
            values["manually_edited_fields"] = sorted(set(article.manually_edited_fields) | {"title_zh", "body_zh", "summary_zh"})
        NewsArticle.objects.filter(pk=article.pk).update(**values)
        article.refresh_from_db()
        if (article.effective_title, article.effective_body, article.effective_summary) != (target["title"], target["body"], target["summary"]):
            raise RuntimeError("first_projection_mismatch")
    receipt = NewsPublicationReceipt.objects.create(run=run, article=article, event=event,
        source_revision_sha=run.input_sha, target_revision_sha=run.quality_snapshot["target_sha"], delta_sha=digest(delta + corrections),
        content=content, source_snapshot=deepcopy(run.source_snapshot),
        evidence={"quality": run.quality_snapshot, "editorial": run.editorial_snapshot, "policy_sha": run.policy_sha,
                  "editor": run.editor_provenance},
        verified_occurrences=run.entity_snapshot["occurrences"], verified_relations=relations,
        previous_receipt=previous, kind=kind, publication_key=key, published_at=now)
    append_public_entry(article=article, receipt=receipt, now=now, priority=run.priority, region=run.primary_region)
    if corrections:
        # 旧稿仍可在详情/档案访问；新首页不再把被更正稿作为优先候选。
        from stable.models import NewsPublicEntry
        NewsPublicEntry.objects.filter(receipt=previous, superseded_at__isnull=True).update(superseded_at=now)
    by_id = {fact["id"]: fact for fact in event.published_facts}
    for fact in delta + corrections:
        by_id[fact["id"]] = fact
    event.published_facts, event.version = list(by_id.values()), event.version + 1
    event.save(update_fields=["published_facts", "version", "updated_at"])
    run.state, run.reason, run.lease_until = "published", "", None
    run.expected_article_sha = article_revision(article)
    run.save(update_fields=["state", "reason", "lease_until", "expected_article_sha"])
    transaction.on_commit(lambda: cache.delete("p01:latest-feed"))
    return receipt
