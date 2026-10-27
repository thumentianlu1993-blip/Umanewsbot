"""P01 固定任务请求；预算事务不持 article/run 锁，不跨网络调用。"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from stable.models import NewsModelBudget, NewsStageAttempt
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
                raise RequestDenied("budget_exhausted")
        for budget in budgets:
            budget.reserved += amount
            budget.save(update_fields=["reserved"])
        attempt.month_budget, attempt.day_budget = budgets
        attempt.reservation = amount
        attempt.provider = spec["provider"]
        attempt.model = spec["model"]
        attempt.prompt_version = spec["prompt_version"]
        attempt.reserved_at = now
        attempt.usage = {"price": spec, "currency": currency}
        attempt.save(update_fields=["month_budget", "day_budget", "reservation", "provider", "model", "prompt_version", "reserved_at", "usage"])
        return attempt


def settle_request(attempt_id, *, actual_cost, result=None, version=1, usage=None):
    return NewsStageAttempt.objects.get(pk=attempt_id)


def mark_unknown(attempt_id, reason):
    return NewsStageAttempt.objects.get(pk=attempt_id)
