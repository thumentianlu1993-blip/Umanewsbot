"""P01 固定任务请求；预算事务不持 article/run 锁，不跨网络调用。"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction, connection
from django.utils import timezone

from stable.models import NewsModelBudget, NewsStageAttempt, NewsArticle, NewsProcessingRun
from stable.services.news_pipeline import digest, policy_sha

STAGES = frozenset({"event_classify", "entity_check", "translate_full", "fact_audit", "body_review"})
MONEY_UNIT = Decimal("0.00000001")


class RequestDenied(ValueError):
    pass


def money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise RequestDenied("invalid_amount") from None
    if not amount.is_finite() or amount < 0:
        raise RequestDenied("invalid_amount")
    return amount.quantize(MONEY_UNIT, rounding=ROUND_CEILING)


def request_spec(stage, *, profile="base", payload=None):
    policy = getattr(settings, "NEWS_QUALITY_POLICY", {})
    from copy import deepcopy
    spec = deepcopy(policy.get("models", {}).get(stage, {}))
    v2 = policy.get("contract_version") == "context-v2"
    if v2:
        if profile not in {"base", "deep"}:
            raise RequestDenied("profile_invalid")
        deep = spec.pop("deep", None)
        if profile == "deep":
            if type(deep) is not dict:
                raise RequestDenied("deep_profile_missing")
            spec = deep
        if (spec.get("thinking") != ("enabled" if profile == "deep" else "disabled")
                or type(spec.get("http_timeout_seconds")) is not int
                or not 1 <= spec["http_timeout_seconds"] <= 120
                or stage in {"entity_check", "fact_audit"} and spec.get("quality_tier") != "strong"):
            raise RequestDenied("profile_not_qualified")
        spec.update(contract_version="context-v2", profile=profile)
        if stage == "translate_full" and payload is not None:
            floor = spec.pop("min_output_tokens", spec.get("max_output_tokens"))
            factor = spec.pop("output_tokens_per_byte", 1)
            if type(floor) is not int or type(factor) not in (int, float) or not 0 < factor <= 4:
                raise RequestDenied("output_budget_invalid")
            limit = spec.get("max_output_tokens", 0)
            if not 0 < floor <= limit:
                raise RequestDenied("output_budget_invalid")
            import math
            size = len(json.dumps(payload.get("source", {}), ensure_ascii=False).encode())
            spec["max_output_tokens"] = min(limit, max(floor, math.ceil(size * factor)))
    required = {"provider", "model", "prompt_version", "input_per_million", "output_per_million", "max_output_tokens", "max_input_bytes"}
    if stage not in STAGES or not required <= set(spec) or spec["provider"] != "openai":
        raise RequestDenied("model_or_price_missing")
    if not spec["model"] or not spec["prompt_version"]:
        raise RequestDenied("model_or_prompt_missing")
    for key in ("max_output_tokens", "max_input_bytes"):
        if type(spec[key]) is not int or not 0 < spec[key] <= 200000:
            raise RequestDenied("unbounded_request")
    money(spec["input_per_million"])
    money(spec["output_per_million"])
    return spec


def reservation_amount(payload, spec):
    size = len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
    if size > spec["max_input_bytes"]:
        raise RequestDenied("oversized")
    # UTF-8 字节数给内容 token 保守上界；固定指令和 chat envelope 另保留 2048。
    return money((Decimal(size + 2048) * money(spec["input_per_million"]) + Decimal(spec["max_output_tokens"]) * money(spec["output_per_million"])) / Decimal(1000000))


def validate_attempt(attempt, payload):
    run = attempt.run
    now = timezone.now()
    if getattr(settings, "NEWS_QUALITY_MODE", "off") not in {"shadow", "enforce"}:
        raise RequestDenied("pipeline_paused")
    if run.policy_sha != policy_sha() or attempt.input_sha != digest(payload):
        raise RequestDenied("request_revision_changed")
    if (run.state != "running" or not run.lease_until or now >= run.lease_until
            or run.generation != attempt.generation
            or run.article.active_news_run_id != run.pk
            or run.article.news_generation != run.generation
            or run.article.withdrawn_at):
        raise RequestDenied("claim_stale")


def reserve_request(attempt_id, payload):
    attempt = NewsStageAttempt.objects.select_related("run__article").get(pk=attempt_id)
    validate_attempt(attempt, payload)
    from stable.services.news_pipeline import required_profile
    spec = request_spec(attempt.stage, profile=required_profile(attempt.run), payload=payload)
    amount = reservation_amount(payload, spec)
    policy = getattr(settings, "NEWS_QUALITY_POLICY", {})
    currency = policy.get("currency", "")
    if not re.fullmatch(r"[A-Z]{3,8}", currency):
        raise RequestDenied("currency_missing")
    caps = {kind: money(policy.get(kind + "_cap", 0)) for kind in ("month", "day")}
    if not all(caps.values()):
        raise RequestDenied("budget_disabled")
    now = timezone.now()
    day = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    periods = {"day": day, "month": day.replace(day=1)}
    with transaction.atomic():
        _article_finance_lock(attempt)
        budgets = []
        for kind in ("month", "day"):
            budget, _ = NewsModelBudget.objects.get_or_create(
                period_kind=kind, period_start=periods[kind], currency=currency,
                defaults={"cap": caps[kind], "policy_sha": attempt.run.policy_sha},
            )
            budgets.append(NewsModelBudget.objects.select_for_update().get(pk=budget.pk))
        # 预约和核账统一按月→日→attempt锁；此处不取得 article/run 业务锁。
        attempt = NewsStageAttempt.objects.select_for_update().get(pk=attempt_id)
        validate_attempt(attempt, payload)
        if attempt.month_budget_id:
            return attempt
        if attempt.state != "reserved":
            raise RequestDenied("attempt_not_reservable")
        if NewsModelBudget.objects.filter(currency=currency, state__in=["blocked_unknown", "blocked_overage"]).exists():
            raise RequestDenied("unreconciled_bill")
        if policy.get("contract_version") == "context-v2":
            totals = article_cost(attempt.run.article_id, currency=currency)
            cap = money(policy.get("article_cap", 0))
            if not cap or totals["spent"] + totals["reserved"] + amount > cap:
                raise RequestDenied("article_budget_exhausted")
        for budget in budgets:
            if policy.get("contract_version") == "context-v2":
                budget.cap, budget.policy_sha = caps[budget.period_kind], policy_sha()
                budget.save(update_fields=["cap", "policy_sha"])
            if budget.policy_sha != policy_sha() or budget.cap != caps[budget.period_kind]:
                raise RequestDenied("budget_policy_changed")
            if budget.state != "open" or budget.spent + budget.reserved + amount > budget.cap:
                raise RequestDenied("budget_exhausted_" + budget.period_kind)
        for budget in budgets:
            budget.reserved += amount
            budget.save(update_fields=["reserved"])
        attempt.month_budget, attempt.day_budget = budgets
        attempt.reservation = amount
        attempt.provider = spec["provider"]
        attempt.model = spec["model"]
        attempt.prompt_version = spec["prompt_version"]
        attempt.reserved_at = now
        from stable.services.news_prompts import prompt_for
        attempt.usage = {**attempt.usage, "price": spec, "currency": currency}
        if spec.get("contract_version") == "context-v2":
            attempt.usage["prompt_sha"] = digest(prompt_for(attempt.stage, "context-v2"))
        attempt.save(update_fields=["month_budget", "day_budget", "reservation", "provider", "model", "prompt_version", "reserved_at", "usage"])
        return attempt


def _locked_finance(attempt_id):
    reference = NewsStageAttempt.objects.select_related("run").get(pk=attempt_id)
    _article_finance_lock(reference)
    if not reference.month_budget_id or not reference.day_budget_id:
        raise RequestDenied("reservation_missing")
    month = NewsModelBudget.objects.select_for_update().get(pk=reference.month_budget_id)
    day = NewsModelBudget.objects.select_for_update().get(pk=reference.day_budget_id)
    return NewsStageAttempt.objects.select_for_update().get(pk=attempt_id), (month, day)


@transaction.atomic
def settle_request(attempt_id, *, actual_cost, result=None, version=1, usage=None):
    cost = money(actual_cost)
    if type(version) is not int or version < 1:
        raise RequestDenied("settlement_version_invalid")
    attempt, budgets = _locked_finance(attempt_id)
    if version <= attempt.settlement_version:
        if version == attempt.settlement_version and cost != attempt.actual_cost:
            raise RequestDenied("settlement_revision_conflict")
        return attempt
    released = attempt.reservation if attempt.settlement_version == 0 else Decimal(0)
    delta = cost - attempt.actual_cost
    if not attempt.settlement_version:
        attempt.state = "completed" if result is not None else "failed"
        attempt.result = result if result is not None else {}
        attempt.output_sha = digest(result) if result is not None else ""
        attempt.completed_at = timezone.now()
    attempt.actual_cost = cost
    attempt.settlement_version = version
    attempt.usage = {**attempt.usage, "reported": usage or {}}
    attempt.save(update_fields=["state", "result", "output_sha", "completed_at", "actual_cost", "settlement_version", "usage"])
    for budget in budgets:
        if budget.reserved < released or budget.spent + delta < 0:
            raise RequestDenied("ledger_mismatch")
        budget.reserved -= released
        budget.spent += delta
        budget.overage = max(Decimal(0), budget.spent - budget.cap)
        if cost > attempt.reservation or budget.spent + budget.reserved > budget.cap:
            budget.state = "blocked_overage"
        elif budget.state == "blocked_unknown":
            relation = "month_budget_id" if budget.period_kind == "month" else "day_budget_id"
            if not NewsStageAttempt.objects.filter(**{relation: budget.pk}, state="unknown").exists():
                budget.state = "open"
        budget.save(update_fields=["reserved", "spent", "overage", "state"])
    return attempt


@transaction.atomic
def mark_unknown(attempt_id, reason):
    attempt, budgets = _locked_finance(attempt_id)
    if attempt.settlement_version:
        return attempt
    attempt.state = "unknown"
    attempt.error = reason[:255]
    attempt.save(update_fields=["state", "error"])
    for budget in budgets:
        if budget.state == "open":
            budget.state = "blocked_unknown"
            budget.save(update_fields=["state"])
    return attempt


class KnownRequestRejected(Exception):
    """供应商明确在处理请求前拒绝；与发送后结果未知区分。"""


def _single_request(attempt, payload):
    from openai import OpenAI, RateLimitError
    from stable.services.news_prompts import prompt_for
    from stable.services.translation import request_json_translation_once
    api_key = getattr(settings, "NEWS_QUALITY_API_KEY", "")
    if not api_key:
        raise KnownRequestRejected("credentials_missing")
    client = OpenAI(api_key=api_key, base_url=getattr(settings, "NEWS_QUALITY_BASE_URL", None) or None,
                    max_retries=0, timeout=attempt.usage["price"].get("http_timeout_seconds", 60))
    try:
        spec = attempt.usage["price"]
        messages = [{"role": "system", "content": prompt_for(attempt.stage, spec.get("contract_version"))},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
        if spec.get("contract_version") == "context-v2":
            return client.chat.completions.create(model=attempt.model, messages=messages,
                max_tokens=spec["max_output_tokens"], response_format={"type": "json_object"},
                extra_body={"thinking": {"type": spec["thinking"]}})
        return request_json_translation_once(client, model=attempt.model, messages=messages,
                                             max_tokens=spec["max_output_tokens"])
    except RateLimitError:
        raise KnownRequestRejected("rate_limited") from None
    finally:
        client.close()


def execute_request(attempt_id, payload):
    from django.db import connection
    from stable.services.news_content import bounded_json, ContentBlocked
    if connection.in_atomic_block:
        raise RequestDenied("network_inside_transaction")
    existing = NewsStageAttempt.objects.get(pk=attempt_id)
    if existing.state != "reserved":
        return existing
    cached = reuse_completed(existing, payload)
    if cached is not None:
        return cached
    attempt = reserve_request(attempt_id, payload)
    # 先写 inflight 再调用；即使进程在两者之间退出也按未知核账，不猜测免费重发。
    try:
        with transaction.atomic():
            article = NewsArticle.objects.select_for_update().get(pk=attempt.run.article_id)
            run = NewsProcessingRun.objects.select_for_update().get(pk=attempt.run_id)
            attempt = NewsStageAttempt.objects.select_for_update().get(pk=attempt_id)
            if attempt.state != "reserved":
                return attempt
            run.article = article
            attempt.run = run
            validate_attempt(attempt, payload)
            from stable.services.news_pipeline import source_eligible, _current_run
            if not source_eligible(run) or not _current_run(article, run):
                raise RequestDenied("source_or_revision_changed")
            attempt.state = "inflight"
            attempt.save(update_fields=["state"])
    except RequestDenied as error:
        # 尚未发出的请求可明确结算零费用；发送后的异常走 unknown。
        settled = settle_request(attempt_id, actual_cost=0)
        NewsStageAttempt.objects.filter(pk=attempt_id).update(error=str(error)[:255])
        settled.refresh_from_db()
        return settled
    try:
        response = _single_request(attempt, payload)
    except KnownRequestRejected as error:
        settled = settle_request(attempt_id, actual_cost=0)
        NewsStageAttempt.objects.filter(pk=attempt_id).update(error=str(error)[:255])
        settled.refresh_from_db()
        return settled
    except Exception as error:
        return mark_unknown(attempt_id, type(error).__name__)
    usage = getattr(response, "usage", None)
    tokens_in, tokens_out = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
    if type(tokens_in) is not int or type(tokens_out) is not int or tokens_in < 0 or tokens_out < 0:
        return mark_unknown(attempt_id, "usage_unknown")
    spec = attempt.usage["price"]
    cost = money((Decimal(tokens_in) * money(spec["input_per_million"]) + Decimal(tokens_out) * money(spec["output_per_million"])) / Decimal(1000000))
    result, error = None, ""
    try:
        if len(response.choices) != 1 or getattr(response.choices[0].message, "tool_calls", None):
            raise ContentBlocked("unexpected_model_action")
        if spec.get("contract_version") == "context-v2" and getattr(response.choices[0], "finish_reason", None) != "stop":
            raise ContentBlocked("response_truncated")
        content = response.choices[0].message.content
        if type(content) is not str or len(content.encode()) > 1000000:
            raise ContentBlocked("invalid_model_response")
        result = json.loads(content)
        bounded_json(result)
        if type(result) is not dict:
            raise ContentBlocked("model_response_not_object")
    except (AttributeError, TypeError, ValueError, IndexError, ContentBlocked):
        result, error = None, "invalid_model_response"
    settled = settle_request(attempt_id, actual_cost=cost, result=result,
        usage={"input_tokens": tokens_in, "output_tokens": tokens_out, "request_id": str(getattr(response, "id", ""))[:128]})
    if error:
        NewsStageAttempt.objects.filter(pk=attempt_id).update(error=error)
        settled.refresh_from_db()
    return settled



def _article_finance_lock(attempt):
    """金融互斥不锁业务行；旧请求迟到结算也参与同一锁序。"""
    if connection.vendor != "postgresql":
        if getattr(settings, "NEWS_QUALITY_POLICY", {}).get("contract_version") == "context-v2":
            raise RequestDenied("postgres_required")
        return
    import hashlib
    key = int.from_bytes(hashlib.sha256(f"p01-finance:{attempt.run.article_id}".encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def article_cost(article_id, *, currency):
    spent, reserved, unknown = Decimal(0), Decimal(0), Decimal(0)
    attempts = NewsStageAttempt.objects.filter(run__article_id=article_id).exclude(month_budget=None)
    for attempt in attempts.iterator():
        if attempt.usage.get("currency") != currency:
            raise RequestDenied("article_currency_changed")
        spent += attempt.actual_cost
        if not attempt.settlement_version:
            reserved += attempt.reservation
            if attempt.state == "unknown":
                unknown += attempt.reservation
    return {"spent": spent, "reserved": reserved, "unknown": unknown}


def validate_paid_or_cache(attempt):
    """回执必须有原始付费账证；派生缓存只允许单级。"""
    from stable.services.news_content import ContentBlocked
    from stable.services.news_prompts import prompt_for
    if attempt.provider == 'cache':
        origin = NewsStageAttempt.objects.select_related('run', 'month_budget', 'day_budget').filter(
            pk=attempt.usage.get('cache_origin'), run__article_id=attempt.run.article_id,
            run__input_sha=attempt.run.input_sha, run__policy_sha=attempt.run.policy_sha,
            stage=attempt.stage, input_sha=attempt.input_sha, state='completed').first()
        if (attempt.stage not in {'body_review', 'entity_check'} or not origin or origin.provider in {'', 'cache'}
                or attempt.month_budget_id or attempt.day_budget_id or attempt.actual_cost or attempt.reservation
                or attempt.result != origin.result or attempt.output_sha != origin.output_sha
                or attempt.usage.get('price') != origin.usage.get('price')
                or attempt.usage.get('input') != origin.usage.get('input')):
            raise ContentBlocked('cache_origin_invalid')
        validate_paid_or_cache(origin)
    else:
        if (attempt.provider != 'openai' or attempt.state != 'completed' or not attempt.settlement_version
                or not attempt.month_budget_id or not attempt.day_budget_id
                or attempt.month_budget.state != 'open' or attempt.day_budget.state != 'open'
                or attempt.output_sha != digest(attempt.result) or attempt.input_sha != digest(attempt.usage.get('input'))):
            raise ContentBlocked('paid_receipt_invalid')
    spec = attempt.usage.get('price', {})
    if (attempt.usage.get('prompt_sha') != digest(prompt_for(attempt.stage, spec.get('contract_version')))
            or spec != request_spec(attempt.stage, profile=spec.get('profile', 'base'), payload=attempt.usage.get('input'))):
        raise ContentBlocked('cache_policy_changed')


def reuse_completed(attempt, payload):
    from stable.services.news_pipeline import context_enabled, _current_run, source_eligible
    from stable.services.news_content import ContentBlocked
    if not context_enabled() or attempt.stage not in {'body_review', 'entity_check'}:
        return None
    spec = request_spec(attempt.stage, payload=payload)
    currency = getattr(settings, 'NEWS_QUALITY_POLICY', {}).get('currency')
    if NewsModelBudget.objects.filter(currency=currency, state__in=['blocked_unknown', 'blocked_overage']).exists():
        raise RequestDenied('unreconciled_bill')
    candidates = NewsStageAttempt.objects.select_related('run', 'month_budget', 'day_budget').filter(
        run__article_id=attempt.run.article_id, run__input_sha=attempt.run.input_sha,
        run__policy_sha=attempt.run.policy_sha, stage=attempt.stage, input_sha=attempt.input_sha,
        state='completed', provider='openai').exclude(run_id=attempt.run_id).order_by('-pk')[:20]
    for origin in candidates:
        try:
            validate_paid_or_cache(origin)
            # completed 仅代表供应商账证完成；缓存还须重放阶段内容校验。
            from stable.services.news_content import validate_entities, validate_body_review
            if origin.stage == "entity_check":
                validate_entities(origin.run.clean_snapshot, origin.result, contract_version="context-v2")
            else:
                validate_body_review(origin.run.clean_snapshot, origin.result)
        except (ContentBlocked, RequestDenied):
            continue
        if origin.usage.get('price') != spec or origin.usage.get('input') != payload:
            continue
        with transaction.atomic():
            article = NewsArticle.objects.select_for_update().get(pk=attempt.run.article_id)
            run = NewsProcessingRun.objects.select_for_update().get(pk=attempt.run_id)
            current = NewsStageAttempt.objects.select_for_update().get(pk=attempt.pk)
            current.run = run
            run.article = article
            validate_attempt(current, payload)
            if not _current_run(article, run) or not source_eligible(run):
                raise RequestDenied('claim_stale')
            if current.state != 'reserved' or current.month_budget_id:
                return None
            current.provider, current.model, current.prompt_version = 'cache', origin.model, origin.prompt_version
            current.state, current.result, current.output_sha = 'completed', origin.result, origin.output_sha
            current.completed_at = timezone.now()
            current.usage = {**current.usage, 'price': spec, 'prompt_sha': origin.usage['prompt_sha'],
                             'cache_origin': origin.pk, 'currency': currency}
            current.save(update_fields=['provider', 'model', 'prompt_version', 'state', 'result', 'output_sha', 'completed_at', 'usage'])
            return current
    return None
