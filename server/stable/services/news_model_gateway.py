"""P01 固定任务请求；预算事务不持 article/run 锁，不跨网络调用。"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
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


def request_spec(stage):
    policy = getattr(settings, "NEWS_QUALITY_POLICY", {})
    spec = policy.get("models", {}).get(stage, {})
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
    spec = request_spec(attempt.stage)
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
        budgets = []
        for kind in ("month", "day"):
            budget, _ = NewsModelBudget.objects.get_or_create(
                period_kind=kind, period_start=periods[kind], currency=currency,
                defaults={"cap": caps[kind], "policy_sha": attempt.run.policy_sha},
            )
            budgets.append(NewsModelBudget.objects.select_for_update().get(pk=budget.pk))
        # 预约和核账统一按月→日→attempt锁；此处不取得 article/run 业务锁。
        attempt = NewsStageAttempt.objects.select_for_update().get(pk=attempt_id)
        if attempt.month_budget_id:
            return attempt
        if attempt.state != "reserved":
            raise RequestDenied("attempt_not_reservable")
        if NewsModelBudget.objects.filter(currency=currency, state__in=["blocked_unknown", "blocked_overage"]).exists():
            raise RequestDenied("unreconciled_bill")
        for budget in budgets:
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
        attempt.usage = {**attempt.usage, "price": spec, "currency": currency}
        attempt.save(update_fields=["month_budget", "day_budget", "reservation", "provider", "model", "prompt_version", "reserved_at", "usage"])
        return attempt


def _locked_finance(attempt_id):
    reference = NewsStageAttempt.objects.get(pk=attempt_id)
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
    from stable.services.news_prompts import PROMPTS
    from stable.services.translation import request_json_translation_once
    api_key = getattr(settings, "NEWS_QUALITY_API_KEY", "")
    if not api_key:
        raise KnownRequestRejected("credentials_missing")
    client = OpenAI(api_key=api_key, base_url=getattr(settings, "NEWS_QUALITY_BASE_URL", None) or None,
                    max_retries=0, timeout=60)
    try:
        return request_json_translation_once(
            client, model=attempt.model,
            messages=[{"role": "system", "content": PROMPTS[attempt.stage]},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}],
            max_tokens=attempt.usage["price"]["max_output_tokens"],
        )
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
