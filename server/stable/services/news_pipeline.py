"""P01 新闻版本与认领。已接管文章停用后仍隔离旧 writer。"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from django.conf import settings
from django.db import transaction

from stable.models import NewsArticle, NewsProcessingRun

REGIONS = ("japan", "hong_kong", "united_kingdom", "france", "united_states")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def is_pipeline_article(article):
    # 即使调用者持有认领前的旧 ORM 实例，也必须读取已持久化的归属。
    return bool(getattr(article, "active_news_run_id", None)) or bool(
        article.pk and NewsArticle.objects.filter(pk=article.pk, active_news_run__isnull=False).exists()
    )


def policy_sha():
    return digest(getattr(settings, "NEWS_QUALITY_POLICY", {}))


def article_revision(article):
    fields = (
        "title_ja", "body_ja_raw", "body_ja_normalized", "original_content_html", "source_url",
        "published_at", "published_at_verified", "published_at_evidence", "racing_region",
        "attribution_locked", "title_zh", "body_zh", "summary_zh", "translated_title_zh",
        "translated_body_zh", "translated_summary_zh", "rewrite_title_zh", "rewrite_body_zh",
        "rewrite_summary_zh", "manually_edited_fields", "workflow_status", "withdrawn_at",
        "published_to_web_at", "active_news_run_id", "news_generation",
    )
    return digest({name: getattr(article, name) for name in fields})


def source_snapshot(article, draft=None):
    if draft is None:
        return {
            "source_config_id": article.source_config_id,
            "source_site": article.source_site, "source_mode": article.source_mode,
            "source_id": article.source_article_id, "url": article.source_url,
            "title": article.title_ja, "body": article.body_ja_raw,
            "normalized_body": article.body_ja_normalized, "html": article.original_content_html,
            "language": article.source_language, "region": article.racing_region,
            "attribution_locked": article.attribution_locked,
            "source_time": article.published_at.isoformat(), "time_verified": article.published_at_verified,
            "time_evidence": article.published_at_evidence,
        }
    from stable.services.sources import find_builtin_source
    source = find_builtin_source(draft.source_site, draft.source_mode)
    return {
        "source_config_id": source.pk if source else None,
        "source_site": str(draft.source_site), "source_mode": str(draft.source_mode),
        "source_id": draft.source_article_id, "url": draft.source_url,
        "title": draft.title_ja, "body": draft.body_ja_raw,
        "normalized_body": draft.body_ja_normalized, "html": getattr(draft, "original_content_html", ""),
        "language": draft.source_language or article.source_language,
        "region": article.racing_region if article.attribution_locked else (draft.racing_region or article.racing_region),
        "attribution_locked": article.attribution_locked,
        "source_time": draft.published_at.isoformat() if draft.published_at else None,
        "time_verified": draft.metadata.get("published_at_verified"),
        "time_evidence": draft.metadata.get("published_at_evidence", {}),
    }


def target_revision_digest(target, binding=None):
    if binding:
        return digest({"target": target, "event_binding": binding})
    return digest(target) if target else "machine"


@transaction.atomic
def start_revision(article, *, snapshot=None, manual_target=None, editor=None, event_binding=None, reason=""):
    from django.utils import timezone
    article = NewsArticle.objects.select_for_update().get(pk=article.pk)
    snapshot = deepcopy(snapshot if snapshot is not None else source_snapshot(article))
    target = deepcopy(manual_target or {})
    binding = deepcopy(event_binding or {})
    target_sha = target_revision_digest(target, binding)
    run, created = NewsProcessingRun.objects.get_or_create(
        article=article, input_sha=digest(snapshot), policy_sha=policy_sha(), target_revision_sha=target_sha,
        defaults={"generation": article.news_generation + 1, "next_attempt_at": timezone.now(), "source_snapshot": snapshot, "manual_target": target,
                  "editor_provenance": {"user_id": editor.pk, "event_binding": binding, "reason": reason} if editor else {},
                  "primary_region": snapshot["region"], "parent_run_id": article.active_news_run_id},
    )
    if not created:
        return run  # 重投不能复活终态、刷新预算、切回旧源文。
    if article.active_news_run_id:
        NewsProcessingRun.objects.filter(pk=article.active_news_run_id).exclude(
            state__in=["published", "duplicate", "rejected", "shadow"]
        ).update(state="stale", reason="new_revision")
    article.news_generation += 1
    article.active_news_run = run
    article.save(update_fields=["active_news_run", "news_generation"])
    run.generation = article.news_generation
    run.expected_article_sha = article_revision(article)
    run.save(update_fields=["generation", "expected_article_sha"])
    transaction.on_commit(lambda: enqueue_news_run(run.pk))
    return run


def can_enroll(article):
    from django.utils.dateparse import parse_datetime
    policy = getattr(settings, "NEWS_QUALITY_POLICY", {})
    boundary = parse_datetime(policy.get("activated_at", ""))
    source = article.source_config
    return bool(
        getattr(settings, "NEWS_QUALITY_MODE", "off") in {"shadow", "enforce"}
        and boundary and boundary.tzinfo and article.first_seen_at >= boundary
        and source and source.enabled and source.production_approved and not source.deleted_at
        and source.pk in policy.get("source_ids", []) and article.racing_region in REGIONS
        and not article.published_to_web_at and not article.withdrawn_at
    )


@transaction.atomic
def submit_manual_target(article, fields, *, editor):
    article = NewsArticle.objects.select_for_update().get(pk=article.pk)
    active = article.active_news_run
    if active is None:
        raise ValueError("pipeline_owner_required")
    previous = active.manual_target or active.translation_snapshot or {
        "title": article.effective_title, "body": article.effective_body, "summary": article.effective_summary,
    }
    target = {key: fields.get(key + "_zh", previous.get(key, "")) for key in ("title", "body", "summary")}
    if any(not isinstance(value, str) for value in target.values()) or not target["title"].strip() or not target["body"].strip():
        raise ValueError("manual_target_invalid")
    return start_revision(article, snapshot=active.source_snapshot, manual_target=target, editor=editor,
        event_binding=active.editor_provenance.get("event_binding"))


def _current_run(article, run):
    return (
        article.active_news_run_id == run.pk and article.news_generation == run.generation
        and run.policy_sha == policy_sha() and not article.withdrawn_at
        and article_revision(article) == run.expected_article_sha
    )


@transaction.atomic
def claim_stage(run_id, payload):
    from datetime import timedelta
    from django.db.models import Max
    from django.utils import timezone
    from stable.models import NewsStageAttempt
    if getattr(settings, "NEWS_QUALITY_MODE", "off") not in {"shadow", "enforce"}:
        return None
    reference = NewsProcessingRun.objects.get(pk=run_id)
    article = NewsArticle.objects.select_for_update(skip_locked=True).filter(pk=reference.article_id).first()
    if article is None:
        return None
    run = NewsProcessingRun.objects.select_for_update(skip_locked=True).filter(pk=run_id).first()
    if run is None or run.state not in {"pending", "running"}:
        return None
    now = timezone.now()
    if not _current_run(article, run):
        run.state, run.reason = "stale", "revision_changed"
        run.save(update_fields=["state", "reason"])
        return None
    if run.state == "running" or run.next_attempt_at > now:
        return None  # 到期由专门恢复器核对外部请求；不能当成免费重试。
    requests = run.attempts.exclude(provider="")
    if requests.count() >= 10 or requests.filter(stage=run.stage, state="failed").count() >= 3:
        run.state, run.reason = "review", "request_limit"
        run.save(update_fields=["state", "reason"])
        return None
    seq = (run.attempts.filter(stage=run.stage).aggregate(n=Max("seq"))["n"] or 0) + 1
    article.news_generation += 1
    article.save(update_fields=["news_generation"])
    run.generation = article.news_generation
    run.expected_article_sha = article_revision(article)
    run.state, run.lease_until = "running", now + timedelta(seconds=180)
    run.save(update_fields=["generation", "expected_article_sha", "state", "lease_until"])
    return NewsStageAttempt.objects.create(run=run, stage=run.stage, seq=seq,
        generation=run.generation, input_sha=digest(payload), usage={"input": deepcopy(payload)})


def _event_candidates(run):
    import re
    from django.db.models import Q
    from stable.models import NewsEditorialEvent
    from stable.services.news_content import ContentBlocked
    event_id = run.event_id or (run.parent_run.event_id if run.parent_run_id else None)
    # 仅以来源中确实出现的公告/赛事编号与已知同源前版作有界召回。
    text = run.clean_snapshot.get("title", "") + " " + " ".join(row["text"] for row in run.clean_snapshot.get("blocks", []))
    tokens = set(re.findall(r"[\w./-]{2,128}", text))
    query = Q(pk=event_id) if event_id else Q(pk__in=[])
    for field in ("document_id", "source_race_id", "organization", "organizer", "venue"):
        query |= Q(**{f"identity_evidence__fields__{field}__in": list(tokens)})
    binding = run.editor_provenance.get("event_binding", {})
    if binding:
        query = Q(pk=binding["event_id"])
    events = list(NewsEditorialEvent.objects.filter(query).order_by("id")[:21])
    if len(events) > 20:
        raise ContentBlocked("recall_overflow")
    result = []
    for event in events:
        receipt_query = event.receipts.all()
        if binding.get("receipt_id"):
            receipt_query = receipt_query.filter(pk=binding["receipt_id"])
        receipts = list(receipt_query.order_by("-published_at", "-id")[:21])
        if len(receipts) > 20:
            raise ContentBlocked("receipt_recall_overflow")
        result.append({"id": str(event.pk), "identity_key": event.identity_key, "version": event.version,
            "kind": event.event_kind, "identity": event.identity_evidence,
            "primary_region": event.primary_region, "facts": event.published_facts,
            "receipts": [{"id": str(row.pk), "body": row.content["body"],
                          "fact_ids": [fact["id"] for fact in row.evidence.get("editorial", {}).get("facts", [])]} for row in receipts]})
    return result


def stage_payload(run):
    from stable.services.news_content import protect_source
    from stable.services.news_editorial import RESPONSE_SCHEMA
    source = deepcopy(run.clean_snapshot)
    if run.stage == "event_classify":
        return {"source": source, "candidates": _event_candidates(run),
                "response_schema": RESPONSE_SCHEMA, "source_scope": run.source_snapshot["source_site"],
                "manual_target": run.manual_target, "event_binding": run.editor_provenance.get("event_binding", {})}
    if run.stage == "body_review":
        return {"source": source, "suspicious_block_ids": source.get("suspicious_block_ids", [])}
    if run.stage == "entity_check":
        return {"source": source}
    if run.stage == "translate_full":
        return {"source": protect_source(source, run.entity_snapshot["occurrences"]),
                "repair": run.quality_snapshot if run.repair_count else {}}
    if run.stage == "fact_audit":
        return {"source": source, "target": run.translation_snapshot,
                "entities": run.entity_snapshot["occurrences"], "editorial": run.editorial_snapshot}
    raise ValueError("stage_not_registered")


def _stage_projection(run, attempt):
    from stable.models import NewsEditorialEvent
    from stable.services.news_content import (ContentBlocked, validate_entities, resolve_known_entities,
        restore_translation, validate_audit, manual_translation)
    from stable.services.news_editorial import validate_editorial
    from stable.services.news_model_gateway import request_spec
    payload = attempt.usage.get("input")
    if payload is None or digest(payload) != attempt.input_sha:
        raise ContentBlocked("attempt_input_missing")
    if attempt.stage in {"entity_check", "fact_audit"} and request_spec(attempt.stage).get("quality_tier") != "strong":
        raise ContentBlocked("strong_model_not_configured")
    update = {"state": "pending", "reason": "", "lease_until": None}
    if attempt.stage == "event_classify":
        value = validate_editorial(run.clean_snapshot, attempt.result,
            source_scope=run.source_snapshot["source_site"], candidates=payload["candidates"],
            aliases=getattr(settings, "NEWS_QUALITY_POLICY", {}).get("identity_aliases", {}),
            binding=run.editor_provenance.get("event_binding"))
        update.update(editorial_snapshot=value, priority=value["priority"], primary_region=value["primary_region"])
        if value["priority"] in {"reject", "uncertain"}:
            return {**update, "state": "rejected" if value["priority"] == "reject" else "review", "reason": value["reason"]}
        if run.source_snapshot["attribution_locked"] and value["primary_region"] != run.source_snapshot["region"]:
            raise ContentBlocked("primary_region_locked")
        event, _ = NewsEditorialEvent.objects.get_or_create(identity_key=value["identity_key"], defaults={
            "event_kind": value["identity"]["kind"], "primary_region": value["primary_region"],
            "identity_evidence": value["identity"],
        })
        update.update(event_id=event.pk, event_version=event.version, primary_region=event.primary_region)
        if value["comparison"]["version"] != event.version or (event.version and value["comparison"]["event_id"] != str(event.pk)):
            return {**update, "stage": "event_classify", "reason": "event_recompare"}
        old_ids = {fact["id"] for fact in event.published_facts}
        material = [fact for fact in value["facts"] if fact["importance"] == "major"
                    and (fact["relation"] == "correction" or (fact["relation"] == "new" and fact["id"] not in old_ids))]
        if event.version and not material:
            return {**update, "state": "duplicate", "reason": "no_material_new_fact"}
        return {**update, "stage": "entity_check"}
    if attempt.stage == "body_review":
        from stable.services.news_content import validate_body_review
        reviewed = validate_body_review(run.clean_snapshot, attempt.result)
        reviewed["body_review_attempt_id"] = attempt.pk
        return {**update, "clean_snapshot": reviewed, "stage": "event_classify"}
    if attempt.stage == "entity_check":
        rows = validate_entities(run.clean_snapshot, attempt.result)
        rows = resolve_known_entities(run.clean_snapshot, rows, language=run.source_snapshot["language"])
        update["entity_snapshot"] = {"occurrences": rows, "strong_attempt_id": attempt.pk,
            "input_sha": attempt.input_sha, "clean_sha": run.clean_snapshot["clean_sha"]}
        if run.manual_target:
            update.update(translation_snapshot=manual_translation(run.manual_target), stage="fact_audit")
        else:
            update["stage"] = "translate_full"
        return update
    if attempt.stage == "translate_full":
        target = restore_translation(run.clean_snapshot, run.entity_snapshot["occurrences"], attempt.result)
        return {**update, "translation_snapshot": target, "stage": "fact_audit"}
    if attempt.stage == "fact_audit":
        from stable.services.news_editorial import audit_corrections
        response = audit_corrections(run.editorial_snapshot, attempt.result)
        quality = validate_audit(run.clean_snapshot, run.translation_snapshot, response)
        quality.update(strong_attempt_id=attempt.pk, input_sha=attempt.input_sha, policy_sha=run.policy_sha)
        update["quality_snapshot"] = quality
        if quality["passed"]:
            return {**update, "state": "ready", "stage": "publish"}
        if run.repair_count == 0 and not run.manual_target:
            return {**update, "stage": "translate_full", "repair_count": 1, "reason": "one_bounded_repair"}
        return {**update, "state": "review", "reason": "quality_failed"}
    raise ContentBlocked("stage_not_registered")


@transaction.atomic
def _transition(run_id, update, *, generation=None):
    reference = NewsProcessingRun.objects.get(pk=run_id)
    article = NewsArticle.objects.select_for_update().get(pk=reference.article_id)
    run = NewsProcessingRun.objects.select_for_update().get(pk=run_id)
    if generation is not None and run.generation != generation:
        return False
    if not _current_run(article, run):
        if run.state not in {"published", "rejected", "duplicate"}:
            run.state, run.reason = "stale", "revision_changed"
            run.save(update_fields=["state", "reason"])
        return False
    for key, value in update.items():
        setattr(run, key, value)
    run.save(update_fields=list(update))
    return True


def commit_stage(attempt_id, generation):
    from django.utils import timezone
    from stable.models import NewsStageAttempt, NewsEditorialEvent
    from stable.services.news_content import ContentBlocked
    reference = NewsStageAttempt.objects.select_related("run__article").get(pk=attempt_id)
    if not _current_run(reference.run.article, reference.run):
        _transition(reference.run_id, {}, generation=generation)
        return False
    if (reference.state != "completed" or reference.output_sha != digest(reference.result)
            or reference.generation != generation):
        return False
    try:
        projection = _stage_projection(reference.run, reference)
    except ContentBlocked as error:
        return _transition(reference.run_id, {"state": "review", "reason": str(error), "lease_until": None}, generation=generation)
    with transaction.atomic():
        # 若涉及事件，先锁事件，再锁 article→run→attempt；不持预算锁。
        if projection.get("event_id"):
            event = NewsEditorialEvent.objects.select_for_update().get(pk=projection["event_id"])
            if event.version != projection["event_version"]:
                projection.update(stage="event_classify", state="pending", reason="event_recompare")
        article = NewsArticle.objects.select_for_update().get(pk=reference.run.article_id)
        run = NewsProcessingRun.objects.select_for_update().get(pk=reference.run_id)
        attempt = NewsStageAttempt.objects.select_for_update().get(pk=attempt_id)
        if not _current_run(article, run):
            if run.state not in {"published", "duplicate", "rejected"}:
                run.state, run.reason = "stale", "revision_changed"
                run.save(update_fields=["state", "reason"])
            return False
        if (run.state != "running" or attempt.generation != generation or run.generation != generation
                or not run.lease_until or timezone.now() >= run.lease_until
                or attempt.state != "completed" or attempt.output_sha != reference.output_sha):
            return False
        for key, value in projection.items():
            setattr(run, key, value)
        run.save(update_fields=list(projection))
        return True


def source_eligible(run):
    from stable.models import NewsSource
    from django.utils.dateparse import parse_datetime
    policy = getattr(settings, "NEWS_QUALITY_POLICY", {})
    source_id = run.source_snapshot.get("source_config_id")
    boundary = parse_datetime(policy.get("activated_at", ""))
    return bool(source_id in policy.get("source_ids", []) and boundary and boundary.tzinfo
        and run.article.first_seen_at >= boundary
        and NewsSource.objects.filter(pk=source_id, enabled=True, production_approved=True, deleted_at__isnull=True).exists())


def publish_news_web(run_id):
    from stable.services.news_publication import publish
    return publish(run_id)


def process_news_run(run_id):
    from datetime import timedelta
    from django.utils import timezone
    from stable.services.news_content import ContentBlocked, clean_source
    from stable.services.news_model_gateway import execute_request, RequestDenied
    run = NewsProcessingRun.objects.select_related("article").get(pk=run_id)
    mode = getattr(settings, "NEWS_QUALITY_MODE", "off")
    if mode not in {"shadow", "enforce"} or run.state in {"published", "rejected", "duplicate", "review", "stale"}:
        return {"run_id": run.pk, "state": run.state}
    if not source_eligible(run):
        _transition(run.pk, {"state": "review", "reason": "source_not_eligible"}, generation=run.generation)
    elif run.state in {"ready", "shadow"}:
        if mode == "enforce":
            publish_news_web(run.pk)
        elif run.state == "ready":
            _transition(run.pk, {"state": "shadow"}, generation=run.generation)
    elif run.state == "pending":
        try:
            if run.stage == "clean":
                selectors = getattr(settings, "NEWS_QUALITY_POLICY", {}).get("body_selectors", {}).get(run.source_snapshot["source_site"])
                clean = clean_source(run.source_snapshot, selectors=selectors)
                _transition(run.pk, {"clean_snapshot": clean, "stage": "body_review" if clean.get("suspicious_block_ids") else "event_classify"}, generation=run.generation)
            else:
                payload = stage_payload(run)
                attempt = claim_stage(run.pk, payload)
                if attempt:
                    result = execute_request(attempt.pk, payload)
                    if result.state == "completed":
                        budgets = (result.month_budget, result.day_budget)
                        if any(budget and budget.state != "open" for budget in budgets):
                            _transition(run.pk, {"state": "review", "reason": "budget_unreconciled"}, generation=attempt.generation)
                        else:
                            commit_stage(attempt.pk, attempt.generation)
                    elif result.state == "unknown":
                        _transition(run.pk, {"state": "review", "reason": "provider_unknown"}, generation=attempt.generation)
                    elif result.state == "failed":
                        retries = run.attempts.filter(stage=attempt.stage, state="failed").exclude(provider="").count()
                        if result.error == "rate_limited" and retries <= 2:
                            _transition(run.pk, {"state": "pending", "lease_until": None,
                                "next_attempt_at": timezone.now() + timedelta(minutes=(1, 5)[retries - 1]),
                                "reason": "known_retry"}, generation=attempt.generation)
                        else:
                            _transition(run.pk, {"state": "review", "reason": result.error or "provider_failed"}, generation=attempt.generation)
        except (ContentBlocked, RequestDenied) as error:
            current = NewsProcessingRun.objects.get(pk=run.pk)
            from stable.models import NewsStageAttempt
            NewsStageAttempt.objects.filter(run=current, generation=current.generation, state="reserved", provider="").update(state="failed", error="never_dispatched")
            if str(error).startswith("budget_exhausted_"):
                from zoneinfo import ZoneInfo
                tomorrow = timezone.now().astimezone(ZoneInfo("Asia/Shanghai")).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                if str(error) == "budget_exhausted_month":
                    tomorrow = (timezone.now().astimezone(ZoneInfo("Asia/Shanghai")).replace(day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=32)).replace(day=1)
                _transition(run.pk, {"state": "pending", "reason": str(error), "lease_until": None, "next_attempt_at": tomorrow}, generation=current.generation)
            else:
                _transition(run.pk, {"state": "review", "reason": str(error)[:255], "lease_until": None}, generation=current.generation)
    run.refresh_from_db()
    return {"run_id": run.pk, "state": run.state, "stage": run.stage, "reason": run.reason}


def recover_expired_run(run_id):
    """先冻结过期认领，再独立核账；绝不在业务锁内调用供应商或取得预算锁。"""
    from datetime import timedelta
    from django.utils import timezone
    from stable.models import NewsStageAttempt
    from stable.services.news_model_gateway import settle_request, mark_unknown
    reference = NewsProcessingRun.objects.get(pk=run_id)
    now = timezone.now()
    attempt = None
    with transaction.atomic():
        article = NewsArticle.objects.select_for_update().get(pk=reference.article_id)
        run = NewsProcessingRun.objects.select_for_update().get(pk=run_id)
        if run.state != "running" or not run.lease_until or run.lease_until > now:
            return False
        attempt = run.attempts.select_for_update().filter(generation=run.generation).order_by("-pk").first()
        if attempt and attempt.state == "completed" and _current_run(article, run):
            # 只延长这次已完成回执的提交窗口，不分配新请求。
            run.lease_until = now + timedelta(seconds=30)
            run.save(update_fields=["lease_until"])
        elif attempt and attempt.state == "reserved":
            attempt.state, attempt.error = "failed", "never_dispatched"
            attempt.save(update_fields=["state", "error"])
        elif attempt is None:
            run.state, run.reason, run.lease_until = "pending", "claim_without_attempt", None
            run.save(update_fields=["state", "reason", "lease_until"])
            return True
    if attempt.state == "completed":
        return commit_stage(attempt.pk, attempt.generation)
    if attempt.state in {"inflight", "unknown"}:
        attempt = mark_unknown(attempt.pk, "expired_provider_claim")
        if attempt.state == "completed":
            # worker 恰好落了完整回执；下次扫描提交，不重发。
            return recover_expired_run(run_id)
        return _transition(run_id, {"state": "review", "reason": "provider_unknown", "lease_until": None}, generation=attempt.generation)
    if attempt.error == "never_dispatched":
        if attempt.month_budget_id:
            settle_request(attempt.pk, actual_cost=0)
        return _transition(run_id, {"state": "pending", "reason": "recovered_before_dispatch", "lease_until": None,
            "next_attempt_at": now}, generation=attempt.generation)
    return _transition(run_id, {"state": "review", "reason": "expired_failed_attempt", "lease_until": None}, generation=attempt.generation)


def enqueue_news_run(run_id):
    """broker 失败不在 web/抓取进程里降级执行付费模型；扫描器重投。"""
    import logging
    if not getattr(settings, "NEWS_QUALITY_DISPATCH_ENABLED", False) or getattr(settings, "NEWS_QUALITY_MODE", "off") not in {"shadow", "enforce"}:
        return False
    try:
        from stable.tasks import process_news_quality_run_task
        process_news_quality_run_task.apply_async(args=[run_id], retry=False)
        return True
    except Exception as error:
        logging.getLogger(__name__).warning("P01 broker dispatch failed run=%s type=%s", run_id, type(error).__name__)
        return False


def scan_news_runs(*, now=None, limit=100):
    from datetime import timedelta
    from django.utils import timezone
    from stable.models import NewsStageAttempt
    from stable.services.news_model_gateway import mark_unknown, settle_request
    from stable.services.news_feed import regional_slot_seconds
    now = now or timezone.now()
    if not getattr(settings, "NEWS_QUALITY_DISPATCH_ENABLED", False) or getattr(settings, "NEWS_QUALITY_MODE", "off") not in {"shadow", "enforce"}:
        return {"dispatched": 0, "recovered": 0, "enabled": False}
    limit = max(1, min(100, limit))
    recovered = 0
    for pk in NewsProcessingRun.objects.filter(state="running", lease_until__lte=now).values_list("pk", flat=True)[:limit]:
        recovered += int(bool(recover_expired_run(pk)))
    # 已被新版本取代的旧 worker 也必须核账，不能遗留可被遗忘的 reservation。
    orphaned = NewsStageAttempt.objects.filter(state__in=["reserved", "inflight"], reserved_at__lt=now-timedelta(seconds=180)).exclude(run__state="running")
    for reference in list(orphaned[:limit]):
        with transaction.atomic():
            attempt = NewsStageAttempt.objects.select_for_update().get(pk=reference.pk)
            if attempt.state == "reserved":
                attempt.state, attempt.error = "failed", "never_dispatched"
                attempt.save(update_fields=["state", "error"])
        if attempt.state == "inflight":
            mark_unknown(attempt.pk, "orphaned_provider_claim")
        elif attempt.error == "never_dispatched" and attempt.month_budget_id and not attempt.settlement_version:
            settle_request(attempt.pk, actual_cost=0)
    due = NewsProcessingRun.objects.filter(state__in=["pending", "ready", "shadow"], next_attempt_at__lte=now, policy_sha=policy_sha())
    if getattr(settings, "NEWS_QUALITY_MODE", "off") == "shadow":
        due = due.exclude(state="shadow")
    selected = list(due.filter(priority="major").order_by("article__published_at", "pk").values_list("pk", flat=True)[:limit])
    slots = regional_slot_seconds(now)
    regions = sorted(REGIONS, key=lambda region: (slots.get(region, 0), REGIONS.index(region)))
    queues = {region: list(due.exclude(priority="major").filter(primary_region=region).order_by("created_at", "pk").values_list("pk", flat=True)[:min(20, limit)]) for region in regions}
    while len(selected) < limit and any(queues.values()):
        for region in regions:
            if queues[region] and len(selected) < limit:
                selected.append(queues[region].pop(0))
    return {"enabled": True, "dispatched": sum(enqueue_news_run(pk) for pk in selected), "recovered": recovered}
