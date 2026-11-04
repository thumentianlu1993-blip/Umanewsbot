"""首次公开的内部强句柄协调；默认空scope，不扫描名称或安装许可。"""
from __future__ import annotations

import logging
from collections import Counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from stable.models import HorseProfile, TaskExecutionLog, TaskStatus
from stable.services import horse_article_binding_persistence, queueing


logger = logging.getLogger(__name__)
TASK_NAME = "horse_strong_article_backfill"


def _ids(profile_id, actor_id):
    if not all(type(value) is int and value > 0 for value in (profile_id, actor_id)):
        raise ValueError("profile_actor_ids")


def eligible_profile_binding_handles(profile_id: int, actor_id: int) -> dict:
    """Metadata-only filter. The reviewed writer remains the authority boundary."""
    _ids(profile_id, actor_id)
    registry = getattr(settings, "HORSE_ARTICLE_BINDING_HANDLES", {})
    selected = []
    invalid = 0
    if type(registry) is not dict:
        invalid = 1
    else:
        for handle, scope in registry.items():
            if (type(handle) is not str or not 0 < len(handle) <= 128 or type(scope) is not dict
                    or type(scope.get("profile_id")) is not int or scope["profile_id"] <= 0
                    or type(scope.get("actor_ids")) is not list
                    or not all(type(value) is int and value > 0 for value in scope["actor_ids"])):
                invalid += 1
                continue
            if scope["profile_id"] == profile_id and actor_id in scope["actor_ids"]:
                selected.append(handle)
    status = "config_error" if invalid else ("selected" if selected else "no_eligible_handles")
    return {"status": status, "profile_id": profile_id, "actor_id": actor_id,
            "handle_ids": sorted(selected) if not invalid else [], "invalid_entry_count": invalid}


def backfill_profile_strong_bindings(profile_id: int, actor_id: int) -> dict:
    """One current registered scope per attempt; no cross-handle transaction.

    Repeated success is owned by the existing receipt protocol. These attempt
    logs are neither permits nor a durable message registry/coverage baseline.
    """
    _ids(profile_id, actor_id)
    log = None
    selection = None
    outcomes = []
    try:
        selection = eligible_profile_binding_handles(profile_id, actor_id)
        log = TaskExecutionLog.objects.create(task_name=TASK_NAME, status=TaskStatus.STARTED,
                                              payload={"selection": selection})
        actor = get_user_model().objects.filter(pk=actor_id).first()
        if actor is None or not actor.is_active or not actor.is_staff:
            status = "blocked_actor"
        elif not HorseProfile.objects.filter(pk=profile_id, review_status="published").exists():
            status = "not_public"
        elif selection["status"] != "selected":
            status = selection["status"]
        else:
            for handle in selection["handle_ids"]:
                # Re-read all actual scope/bytes/actor/versions in the writer.
                # Never rebase a draft artifact or substitute another actor.
                outcome = horse_article_binding_persistence.commit_strong_horse_binding(handle, actor)
                if type(outcome) is not dict or type(outcome.get("status")) is not str:
                    raise ValueError("writer_result_shape")
                outcomes.append({"handle_id": handle, **outcome})
            status = "completed"
        counts = dict(Counter(item["status"] for item in outcomes))
        result = {"status": status, "profile_id": profile_id, "actor_id": actor_id,
                  "handle_ids": selection["handle_ids"], "results": outcomes, "counts": counts,
                  "unique_receipts": len({item["receipt_id"] for item in outcomes if "receipt_id" in item}),
                  "coverage_state": "configured_handles_only_not_historical_news_coverage"}
        log.payload = {"selection": selection, "result": result}
        log.status = TaskStatus.FAILED if status == "config_error" else TaskStatus.SUCCESS
        log.detail = "attempt complete; historical coverage unproven"
        log.finished_at = timezone.now()
        log.save(update_fields=["payload", "status", "detail", "finished_at", "updated_at"])
        return result
    except Exception as error:
        logger.exception("strong profile backfill failed profile=%s actor=%s", profile_id, actor_id)
        if log is not None:
            try:
                log.status = TaskStatus.FAILED
                log.detail = "attempt_failed:"+type(error).__name__
                log.payload = {"selection": selection, "completed_handle_results": outcomes}
                log.finished_at = timezone.now()
                log.save(update_fields=["payload", "status", "detail", "finished_at", "updated_at"])
            except Exception:
                logger.exception("strong profile backfill failure audit unavailable profile=%s", profile_id)
        # Preserve the original DB/programming exception for task/caller policy.
        raise


def enqueue_profile_strong_backfill(profile_id: int, actor_id: int) -> dict:
    """Internal caller only; no API, registration or implied publication permit."""
    selection = eligible_profile_binding_handles(profile_id, actor_id)
    if selection["status"] == "config_error":
        raise ValueError("backfill_handle_configuration")
    if selection["status"] != "selected":
        return selection
    # Autodiscovery really imports stable.tasks, not an unregistered new module.
    from stable.tasks import backfill_profile_strong_article_links_task

    dispatched = queueing.dispatch_task(backfill_profile_strong_article_links_task,
                                       profile_id=profile_id, actor_id=actor_id)
    if type(dispatched) is dict:
        return {"status": "executed_direct", "execution": dispatched}
    task_id = getattr(dispatched, "id", None)
    if type(task_id) is not str or not task_id:
        raise RuntimeError("backfill_dispatch_receipt_missing")
    # Client submission is not worker completion or durable delivery proof.
    return {"status": "submitted", "task_id": task_id, "profile_id": profile_id, "actor_id": actor_id}
