"""
Race news exposure governance: identity resolution, hard duplicate detection,
angle classification, and the two-slot state machine for homepage and QQ.

This module provides the core policy layer for limiting same-race article
exposure on the homepage and in QQ group messages to a maximum of two
articles per event, with a mandatory 15-minute delay between the first
and second slot.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from stable.models import (
    ArticleRaceLink,
    ArticleRaceLinkStatus,
    NewsArticle,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RaceEvent,
    RaceNewsAngle,
    RaceNewsExposure,
    RaceNewsExposureChannel,
    RaceNewsExposureStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUTO_CONFIDENCE_THRESHOLD = 70  # Minimum confidence for auto links to be trusted
YEAR_VALIDATION_RANGE = 1  # Adjacent years allowed

# ---------------------------------------------------------------------------
# 1. RaceIdentityResolver
# ---------------------------------------------------------------------------


def _validate_identity_context(
    article: NewsArticle,
    event: RaceEvent,
) -> bool:
    """Validate that *event* is in a reasonable context for *article*.

    Checks:
    1. Event year vs article published_at (same year or adjacent year).
    2. If article has a ``racing_region``, it must match the event's
       ``country_region``.

    Returns True if all checks pass, False otherwise.
    """
    # Year validation: event year should be same as or adjacent to
    # the article's publish year
    pub_date = article.published_at
    if pub_date:
        pub_year = pub_date.year
        if abs(pub_year - event.year) > YEAR_VALIDATION_RANGE:
            return False

    # Region validation: if article has a racing_region, it must match
    article_region = article.racing_region
    if article_region:
        if article_region != event.country_region:
            return False

    return True


def resolve_race_identity(article: NewsArticle) -> dict | None:
    """Resolve the primary race event for an article.

    Priority:
    1. Unique ``status=manual`` link -> that event.
    2. No manual conflict, unique ``status=auto`` with confidence >= threshold
       and no other qualified auto to a different event -> that event.
    3. Otherwise -> None (unresolved).

    ``candidate`` and ``removed`` links do not form identity.
    Multiple manual links, multiple qualified auto links to different events,
    or manual+auto conflict all return None.

    Returns
    -------
    dict or None
        ``{"event_id": int, "method": "manual"|"auto"}`` or ``None``.
    """
    links = list(
        ArticleRaceLink.objects.filter(article=article)
        .select_related("event")
        .order_by("id")
    )

    # --- Step 1: Check manual links ---
    manual_links = [
        link for link in links
        if link.status == ArticleRaceLinkStatus.MANUAL
    ]
    if len(manual_links) == 1:
        return {"event_id": manual_links[0].event_id, "method": "manual"}
    if len(manual_links) > 1:
        # Multiple manual links to possibly different events — unresolved
        return None

    # --- Step 2: Check auto links (only when no manual links exist) ---
    qualified_auto = [
        link for link in links
        if link.status == ArticleRaceLinkStatus.AUTO
        and link.confidence >= AUTO_CONFIDENCE_THRESHOLD
    ]
    if len(qualified_auto) == 1:
        link = qualified_auto[0]
        # Additional validation for unique qualified auto link
        event = link.event
        if _validate_identity_context(article=article, event=event):
            return {"event_id": event.id, "method": "auto"}
        return None
    if len(qualified_auto) > 1:
        # Check if all qualified auto links point to the same event
        unique_events = {link.event_id for link in qualified_auto}
        if len(unique_events) == 1:
            event = qualified_auto[0].event
            if _validate_identity_context(article=article, event=event):
                return {"event_id": event.id, "method": "auto"}
        return None

    return None


# ---------------------------------------------------------------------------
# 2. RaceNewsDuplicateClassifier
# ---------------------------------------------------------------------------


def _normalized_title(article: NewsArticle) -> str:
    """Return a normalized version of the article's effective title."""
    title = article.effective_title or ""
    return " ".join(title.casefold().split())


def classify_hard_duplicate(
    article_a: NewsArticle,
    article_b: NewsArticle,
    event: RaceEvent,
) -> dict:
    """Classify whether *article_b* is a hard duplicate of *article_a*
    within the context of *event*.

    Rules:
    1. Same source article ID (unique constraint).
    2. Same event, same normalized source title.
    3. Same content fingerprint.

    *article_a* and *article_b* must belong to the same event for rules 2-3
    to apply; the caller is expected to only pass same-event pairs.

    Returns
    -------
    dict
        ``{"is_duplicate": bool, "reason": str | None}``.
    """
    # Rule 1: Same source article ID
    if (
        article_a.source_site == article_b.source_site
        and article_a.source_article_id
        and article_a.source_article_id == article_b.source_article_id
    ):
        return {"is_duplicate": True, "reason": "same_source_article_id"}

    # Check if the articles are linked to DIFFERENT events via explicit links.
    # If one article belongs to a different event than the provided one,
    # they cannot be hard duplicates within this event context.
    a_events = set(
        ArticleRaceLink.objects.filter(
            article=article_a,
            status__in=[ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL],
        ).values_list("event_id", flat=True)
    )
    b_events = set(
        ArticleRaceLink.objects.filter(
            article=article_b,
            status__in=[ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL],
        ).values_list("event_id", flat=True)
    )

    # Guard: if neither article has ANY event links, and neither has a link to
    # the provided event, the articles don't share a confirmed event context.
    # A same normalized title across unrelated events is NOT a hard duplicate.
    a_has_event = event.id in a_events
    b_has_event = event.id in b_events

    if not a_has_event and not b_has_event:
        # Neither article is linked to the provided event — no shared context
        return {"is_duplicate": False, "reason": None}

    if a_has_event and not b_has_event and b_events and event.id not in b_events:
        # article_b is linked to a different event than the provided one
        return {"is_duplicate": False, "reason": None}
    if b_has_event and not a_has_event and a_events and event.id not in a_events:
        # article_a is linked to a different event than the provided one
        return {"is_duplicate": False, "reason": None}

    # If exactly one has links to the provided event and the other has zero
    # links, we have no evidence of a shared event — reject duplicate claim.
    if a_has_event and not b_has_event and not b_events:
        return {"is_duplicate": False, "reason": None}
    if b_has_event and not a_has_event and not a_events:
        return {"is_duplicate": False, "reason": None}

    if a_events and b_events and a_events != b_events and not (a_has_event and b_has_event):
        # Both have links but to different events, and neither provides
        # a shared event context with the function parameter
        return {"is_duplicate": False, "reason": None}

    # Rule 2: Same event (implicit via caller), same normalized source title
    if (
        article_a.source_site == article_b.source_site
        and _normalized_title(article_a) == _normalized_title(article_b)
    ):
        return {"is_duplicate": True, "reason": "same_normalized_title"}

    # Rule 3: Same content fingerprint
    try:
        fp_a = article_a.content_fingerprint()
        fp_b = article_b.content_fingerprint()
        if fp_a and fp_b and fp_a == fp_b:
            return {"is_duplicate": True, "reason": "same_content_fingerprint"}
    except Exception:
        pass

    return {"is_duplicate": False, "reason": None}


# ---------------------------------------------------------------------------
# 3. AngleClassifier
# ---------------------------------------------------------------------------


def classify_angle(article: NewsArticle, event: RaceEvent) -> dict:
    """Classify the article's angle relative to its race event.

    Uses structured evidence from the article's title, body, and race links
    to determine the angle within the fixed ``RaceNewsAngle`` enum.

    When confidence is low or ambiguous, returns ``"other"``.

    Returns
    -------
    dict
        ``{"angle": str, "evidence": dict}``.
    """
    title = (article.effective_title or "").lower()
    body = (article.effective_body or "").lower()
    summary = (article.effective_summary or "").lower()

    evidence = {"signals": [], "fallback": False}

    # Check for result keywords in title
    # NOTE: single-character Chinese keywords (e.g. "马", "胜") are excluded
    # because they match too many unrelated contexts.
    result_keywords = ["result", "赛果", "finish", "order of finish",
                       "全着顺", "着顺"]
    winner_keywords = ["win", "winner", "冠军", "victory", "triumph",
                       "captures", "claims"]
    connections_keywords = ["trainer", "jockey", "rider", "owner", "handler",
                            "练马师", "骑师", "马主", "调教师"]
    runner_keywords = ["horse", "runner", "马匹", "参赛马", "出赛"]
    analysis_keywords = ["analysis", "review", "分析", "复盘",
                         "replay", "sectional"]
    market_keywords = ["market", "odds", "betting", "price", "赔率", "投注",
                       "favourite", "favorite"]

    # Title-based signals (strongest)
    title_has_result = any(kw in title for kw in result_keywords)
    title_has_winner = any(kw in title for kw in winner_keywords)
    title_has_connections = any(kw in title for kw in connections_keywords)
    title_has_runner = any(kw in title for kw in runner_keywords)
    title_has_analysis = any(kw in title for kw in analysis_keywords)
    title_has_market = any(kw in title for kw in market_keywords)

    if title_has_result and not title_has_connections and not title_has_runner:
        evidence["signals"].append("title_result_keywords")
        return {"angle": RaceNewsAngle.COMPREHENSIVE_RESULT, "evidence": evidence}

    if title_has_winner and not title_has_connections:
        evidence["signals"].append("title_winner_keywords")
        return {"angle": RaceNewsAngle.WINNER, "evidence": evidence}

    if title_has_connections:
        evidence["signals"].append("title_connections_keywords")
        return {"angle": RaceNewsAngle.CONNECTIONS, "evidence": evidence}

    if title_has_analysis:
        evidence["signals"].append("title_analysis_keywords")
        return {"angle": RaceNewsAngle.ANALYSIS, "evidence": evidence}

    if title_has_market:
        evidence["signals"].append("title_market_keywords")
        return {"angle": RaceNewsAngle.MARKET, "evidence": evidence}

    # Body-based signals (weaker)
    body_has_result = any(kw in body for kw in result_keywords)
    body_has_winner = any(kw in body for kw in winner_keywords)
    body_has_connections = any(kw in body for kw in connections_keywords)

    if body_has_result and body_has_winner and not body_has_connections:
        evidence["signals"].append("body_result_winner")
        return {"angle": RaceNewsAngle.COMPREHENSIVE_RESULT, "evidence": evidence}

    if body_has_connections and not body_has_result:
        evidence["signals"].append("body_connections")
        return {"angle": RaceNewsAngle.CONNECTIONS, "evidence": evidence}

    # Low confidence — fall through to other
    evidence["fallback"] = True
    return {"angle": RaceNewsAngle.OTHER, "evidence": evidence}


# ---------------------------------------------------------------------------
# 4. RaceNewsExposurePolicy — the two-slot state machine
# ---------------------------------------------------------------------------


def _is_shadow_mode() -> bool:
    """Return True when shadow mode is active (record but don't enforce)."""
    return getattr(settings, "RACE_NEWS_EXPOSURE_SHADOW", True)


def _enabled() -> bool:
    """Return True when the exposure policy is enabled."""
    return getattr(settings, "RACE_NEWS_EXPOSURE_ENABLED", False)


def _delay_minutes() -> int:
    """Return the second-slot delay in minutes."""
    return getattr(settings, "RACE_NEWS_SECOND_SLOT_DELAY_MINUTES", 15)


def promote_waiting_slots(
    event: RaceEvent,
    channel: str,
    scope_key: str,
) -> list[dict]:
    """Promote slot-2 ``waiting`` exposures whose delay has elapsed to ``active``.

    Queries for ``status="waiting"`` records whose ``created_at + delay >= now``
    and upgrades them to ``active``, setting ``activated_at``.

    Returns a list of dicts for the promoted exposures (empty list if none).
    """
    now = timezone.now()
    delay = timedelta(minutes=_delay_minutes())
    promoted: list[RaceNewsExposure] = []

    with transaction.atomic():
        waiting = list(
            RaceNewsExposure.objects.select_for_update().filter(
                event=event,
                channel=channel,
                scope_key=scope_key,
                slot=2,
                status=RaceNewsExposureStatus.WAITING,
            ).order_by("id")
        )
        for exp in waiting:
            eligible_since = exp.created_at + delay
            if eligible_since <= now:
                exp.status = RaceNewsExposureStatus.ACTIVE
                exp.activated_at = exp.activated_at or now
                exp.save(update_fields=["status", "activated_at", "updated_at"])
                promoted.append(exp)

    return [_exposure_to_dict(exp) for exp in promoted]


def reserve_exposure(
    event: RaceEvent,
    article: NewsArticle,
    channel: str,
    scope_key: str,
    angle: str,
    *,
    activated_at=None,
    published_at=None,
) -> dict:
    """Reserve an exposure slot for *article* on a given *channel*/*scope*.

    First-slot logic:
      - If no active slot-1 exists, create it as ``active`` immediately.

    Second-slot logic:
      - If slot-1 is present but not yet ``active`` for >= *delay* minutes,
        slot-2 is created as ``waiting``.
      - If slot-1 has been active for >= *delay* minutes and *angle* differs
        from slot-1's angle (neither is ``other``), slot-2 is created as ``active``.
      - ``other`` angle cannot prove difference from slot-1.

    Returns
    -------
    dict
        Keys: ``slot``, ``status``, ``activated_at``, etc.
        Returns ``{"slot": None, "status": "no_slot"}`` when no slot available.
    """
    if not _enabled() and not _is_shadow_mode():
        return {"slot": None, "status": "disabled"}

    now = timezone.now()
    policy_version = "1.0"

    with transaction.atomic():
        # Promote eligible waiting slot-2 exposures BEFORE locking,
        # so the subsequent select_for_update sees the promoted state.
        promote_waiting_slots(event=event, channel=channel, scope_key=scope_key)

        # Lock all exposures for this event+channel+scope
        existing = list(
            RaceNewsExposure.objects.select_for_update().filter(
                event=event,
                channel=channel,
                scope_key=scope_key,
            ).order_by("slot", "id")
        )

        # Check if we already have an exposure for this exact article.
        # Only a LIVE exposure (waiting/active/sent) makes this idempotent:
        # a suppressed/replaced row means the article currently has no
        # effective slot — fall through and reactivate that row in place
        # (the per-article unique constraint forbids a second row) instead
        # of reporting a stale status as success.
        existing_for_article: RaceNewsExposure | None = None
        for exp in existing:
            if exp.article_id == article.id:
                existing_for_article = exp
                break
        if existing_for_article is not None and existing_for_article.status in (
            RaceNewsExposureStatus.WAITING,
            RaceNewsExposureStatus.ACTIVE,
            RaceNewsExposureStatus.SENT,
        ):
            return _exposure_to_dict(existing_for_article)

        slot1 = _find_slot(existing, 1)
        slot2 = _find_slot(existing, 2)

        # If both slots occupied with active/waiting/sent — no room
        if slot1 and slot2 and slot2.status not in (
            RaceNewsExposureStatus.REPLACED,
            RaceNewsExposureStatus.SUPPRESSED,
        ):
            return {"slot": None, "status": "no_slot_available"}

        # Determine slot and status
        if not slot1:
            # First slot: create active immediately
            effective_activated_at = activated_at or now
            if existing_for_article is not None:
                # Reactivate the stale row as slot 1
                existing_for_article.slot = 1
                existing_for_article.status = RaceNewsExposureStatus.ACTIVE
                existing_for_article.angle = angle
                existing_for_article.policy_version = policy_version
                existing_for_article.reason = "first_slot"
                existing_for_article.activated_at = effective_activated_at
                existing_for_article.save(update_fields=[
                    "slot", "status", "angle", "policy_version",
                    "reason", "activated_at", "updated_at",
                ])
                return _exposure_to_dict(existing_for_article)
            exposure = RaceNewsExposure.objects.create(
                event=event,
                article=article,
                channel=channel,
                scope_key=scope_key,
                slot=1,
                status=RaceNewsExposureStatus.ACTIVE,
                angle=angle,
                policy_version=policy_version,
                reason="first_slot",
                activated_at=effective_activated_at,
            )
            return _exposure_to_dict(exposure)

        # Slot 1 exists — determining slot 2
        # Check if slot 1 has been active long enough
        slot1_active_at = slot1.activated_at or now
        if angle == RaceNewsAngle.OTHER or slot1.angle == RaceNewsAngle.OTHER:
            # other cannot prove difference from slot-1
            return {"slot": None, "status": "angle_other_cannot_differ"}

        if angle == slot1.angle:
            # Same angle — not eligible for slot 2
            return {"slot": None, "status": "same_angle_as_slot1"}

        delay = timedelta(minutes=_delay_minutes())
        time_elapsed = now - slot1_active_at

        if time_elapsed >= delay:
            slot_status = RaceNewsExposureStatus.ACTIVE
        else:
            slot_status = RaceNewsExposureStatus.WAITING

        # Create or update slot 2
        if slot2 and slot2.status in (
            RaceNewsExposureStatus.REPLACED,
            RaceNewsExposureStatus.SUPPRESSED,
        ) and slot2 is not existing_for_article:
            # Slot 2 already exists but is inactive — replace it
            slot2.status = RaceNewsExposureStatus.REPLACED
            slot2.replaced_at = now
            slot2.save(update_fields=["status", "replaced_at", "updated_at"])

        # An ACTIVE slot must always carry an activation timestamp — an
        # active row with activated_at=None is an inconsistent state
        # (downstream maturity checks and probes rely on it).
        effective_activated_at = (activated_at or now) if slot_status == RaceNewsExposureStatus.ACTIVE else None
        if existing_for_article is not None:
            # Reactivate the stale row as slot 2
            existing_for_article.slot = 2
            existing_for_article.status = slot_status
            existing_for_article.angle = angle
            existing_for_article.policy_version = policy_version
            existing_for_article.reason = "second_slot"
            existing_for_article.activated_at = effective_activated_at
            existing_for_article.save(update_fields=[
                "slot", "status", "angle", "policy_version",
                "reason", "activated_at", "updated_at",
            ])
            return _exposure_to_dict(existing_for_article)
        exposure = RaceNewsExposure.objects.create(
            event=event,
            article=article,
            channel=channel,
            scope_key=scope_key,
            slot=2,
            status=slot_status,
            angle=angle,
            policy_version=policy_version,
            reason="second_slot",
            activated_at=effective_activated_at,
        )
        return _exposure_to_dict(exposure)


def replace_slot2(
    event: RaceEvent,
    channel: str,
    scope_key: str,
    old_article: NewsArticle,
    new_article: NewsArticle,
    reason: str,
) -> dict:
    """Atomically replace slot 2 with a new article.

    Only slot 2 on the homepage channel can be replaced.  Slot 1 is never
    replaced by automatic policy.  The replacement must pass:

    - Channel is ``homepage`` (QQ sent slots are permanent).
    - Slot 1 has been active for at least ``_delay_minutes()``.
    - The new article has a different angle from slot 1.
    - The new article has higher ``score_total`` than the current slot 2 article.

    Returns
    -------
    dict
        ``{"replaced_article_id": int, "new_article_id": int, "slot": 2}``
        or ``{"slot": None, "status": "<reason>"}`` when replacement is blocked.
    """
    # Only homepage supports slot-2 replacement
    if channel != RaceNewsExposureChannel.HOMEPAGE:
        return {"slot": None, "status": "replacement_only_for_homepage"}

    now = timezone.now()

    with transaction.atomic():
        # Lock all exposures for this event+channel+scope to read slot 1 state
        all_exposures = list(
            RaceNewsExposure.objects.select_for_update().filter(
                event=event,
                channel=channel,
                scope_key=scope_key,
            ).order_by("slot", "id")
        )

        slot1 = _find_slot(all_exposures, 1)
        if not slot1:
            return {"slot": None, "status": "no_slot1_to_compare"}

        # Wait period: slot 1 must have been active for >= _delay_minutes
        slot1_active_at = slot1.activated_at or now
        if now - slot1_active_at < timedelta(minutes=_delay_minutes()):
            return {"slot": None, "status": "slot1_not_matured"}

        # Angle: new article must differ from slot 1
        new_angle = classify_angle(new_article, event)["angle"]
        if new_angle == RaceNewsAngle.OTHER or new_angle == slot1.angle:
            return {"slot": None, "status": "angle_not_different_from_slot1"}

        # Quality: new article must have higher score than current slot 2
        slot2_existing = _find_slot(all_exposures, 2)
        if slot2_existing:
            old_score = old_article.score_total or 0
            new_score = new_article.score_total or 0
            if new_score <= old_score:
                return {"slot": None, "status": "new_article_not_higher_quality"}

        # Find the old_article's exposure in slot 2 and mark as replaced
        old_exposure = None
        slot2_exposures = [e for e in all_exposures if e.slot == 2]
        for exp in slot2_exposures:
            if exp.article_id == old_article.id:
                old_exposure = exp
                break

        if old_exposure:
            old_exposure.status = RaceNewsExposureStatus.REPLACED
            old_exposure.replaced_at = now
            old_exposure.save(update_fields=["status", "replaced_at", "updated_at"])

        # Check if new_article already has an exposure here
        for exp in all_exposures:
            if exp.article_id == new_article.id and exp.slot != 1:
                if exp.status in (
                    RaceNewsExposureStatus.ACTIVE,
                    RaceNewsExposureStatus.SENT,
                ):
                    return {
                        "replaced_article_id": old_article.id,
                        "new_article_id": new_article.id,
                        "slot": 2,
                    }
                # Stale (suppressed/replaced) or not-yet-live (waiting) row
                # for the new article: activate it as slot 2 in place so a
                # success result always means the article actually holds an
                # ACTIVE slot — otherwise a manual headline could commit
                # while the article stays invisible on the homepage.
                exp.slot = 2
                exp.status = RaceNewsExposureStatus.ACTIVE
                exp.angle = new_angle
                exp.reason = reason
                exp.activated_at = now
                exp.replaced_by = old_exposure if old_exposure else None
                exp.save(update_fields=[
                    "slot", "status", "angle", "reason",
                    "activated_at", "replaced_by", "updated_at",
                ])
                return {
                    "replaced_article_id": old_article.id,
                    "new_article_id": new_article.id,
                    "slot": 2,
                }

        # Create new slot 2 exposure
        new_exposure = RaceNewsExposure.objects.create(
            event=event,
            article=new_article,
            channel=channel,
            scope_key=scope_key,
            slot=2,
            status=RaceNewsExposureStatus.ACTIVE,
            angle=new_angle,
            policy_version="1.0",
            reason=reason,
            activated_at=now,
            replaced_by=old_exposure if old_exposure else None,
        )

    return {
        "replaced_article_id": old_article.id,
        "new_article_id": new_article.id,
        "slot": 2,
    }


def reserve_qq_exposure(
    event: RaceEvent,
    article: NewsArticle,
    target,
    angle: str,
) -> dict | None:
    """Reserve an exposure slot for QQ delivery to *target*.

    Semantics are similar to homepage reservation, with the additional
    constraint that ``QQPushDelivery`` creation (or reuse) is handled
    atomically.

    Returns
    -------
    dict or None
        Exposure dict (same shape as ``reserve_exposure``) or None when
        the limit for this event+target is reached.
    """
    if not _enabled() and not _is_shadow_mode():
        return None

    target_id = target.id if hasattr(target, "id") else target
    scope_key = f"target:{target_id}"

    result = reserve_exposure(
        event=event,
        article=article,
        channel=RaceNewsExposureChannel.QQ,
        scope_key=scope_key,
        angle=angle,
    )

    if result.get("slot") is None:
        return None

    return result


def force_activate_exposure(exposure_id: int, *, reason: str) -> dict:
    """Activate a ``waiting`` exposure immediately (manual editorial override).

    The second-slot delay exists to space out automatic exposure.  A manual
    homepage headline is an explicit editorial decision to show the article
    NOW, so the headline flow uses this to convert a not-yet-matured waiting
    slot into an active one instead of committing an invisible headline.

    Raises
    ------
    ValueError
        When the exposure does not exist or is not in ``waiting``/``active``
        status (activating a suppressed/replaced row must go through
        ``reserve_exposure`` / ``replace_slot2`` so policy checks apply).
    """
    now = timezone.now()
    with transaction.atomic():
        try:
            exp = RaceNewsExposure.objects.select_for_update().get(pk=exposure_id)
        except RaceNewsExposure.DoesNotExist:
            raise ValueError(f"exposure {exposure_id} not found")
        if exp.status == RaceNewsExposureStatus.ACTIVE:
            return _exposure_to_dict(exp)
        if exp.status != RaceNewsExposureStatus.WAITING:
            raise ValueError(
                f"cannot force-activate exposure {exposure_id} in status {exp.status}"
            )
        exp.status = RaceNewsExposureStatus.ACTIVE
        exp.activated_at = exp.activated_at or now
        exp.reason = reason
        exp.save(update_fields=["status", "activated_at", "reason", "updated_at"])
    return _exposure_to_dict(exp)


def reclaim_expired_lease(exposure_id: int) -> dict | None:
    """Attempt to reclaim an expired lease on an exposure.

    When the delivery has no ``message_id`` and the lease is expired,
    the exposure is reset to ``waiting`` so another worker may pick it up.

    When the delivery has a ``message_id`` or the result is uncertain,
    the lease is preserved (fail-closed).

    Returns
    -------
    dict or None
        Updated exposure dict on successful reclaim, or None if the
        exposure should be left in place (fail-closed).
    """
    try:
        exposure = RaceNewsExposure.objects.select_related("delivery").get(
            pk=exposure_id
        )
    except RaceNewsExposure.DoesNotExist:
        return None

    now = timezone.now()

    # If lease hasn't expired, don't touch it
    if exposure.lease_expires_at and exposure.lease_expires_at > now:
        return None

    delivery = exposure.delivery
    if delivery:
        # If there's a message_id, we consider it sent — preserve
        if delivery.message_id:
            return None
        # If the delivery is in sending or sent state, preserve
        if delivery.status in (
            QQPushDeliveryStatus.SENDING,
            QQPushDeliveryStatus.SENT,
        ):
            return None

    with transaction.atomic():
        exposure = RaceNewsExposure.objects.select_for_update().get(
            pk=exposure_id
        )
        exposure.status = RaceNewsExposureStatus.WAITING
        exposure.lease_expires_at = None
        exposure.save(update_fields=["status", "lease_expires_at", "updated_at"])

    return _exposure_to_dict(exposure)


# ---------------------------------------------------------------------------
# 5. Homepage filtering helpers
# ---------------------------------------------------------------------------


def get_featured_articles():
    """Return a queryset of articles that should appear on the homepage.

    When the exposure policy is active, only articles with an active
    homepage exposure for the ``"site"`` scope are eligible,
    limited to 2 per event.

    When the policy is inactive, returns the full public queryset.

    Note: "waiting" exposures are NOT included here so that waiting slot-2
    articles do NOT appear on the homepage until they are promoted to active.
    """
    from stable.views import _public_published_articles

    if not _enabled() and not _is_shadow_mode():
        return _public_published_articles()

    queryset = _public_published_articles()

    if _enabled():
        # Only include articles with an active homepage exposure for "site"
        # or articles with no race identity at all.
        from django.db.models import Exists, OuterRef

        active_exposure = RaceNewsExposure.objects.filter(
            article=OuterRef("pk"),
            channel=RaceNewsExposureChannel.HOMEPAGE,
            scope_key="site",
            status=RaceNewsExposureStatus.ACTIVE,
        )

        # Articles without race links (ordinary news) are always eligible
        # Articles with race links must have an active exposure
        has_race_link = ArticleRaceLink.objects.filter(
            article=OuterRef("pk"),
            status__in=(
                ArticleRaceLinkStatus.AUTO,
                ArticleRaceLinkStatus.MANUAL,
            ),
        )
        queryset = queryset.annotate(
            _has_race_link=Exists(has_race_link),
            _has_active_exposure=Exists(active_exposure),
        ).filter(
            Q(_has_race_link=False) | Q(_has_active_exposure=True),
        )

    return queryset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_slot(
    exposures: list[RaceNewsExposure],
    slot: int,
) -> RaceNewsExposure | None:
    """Return the first active/waiting/sent exposure for *slot*."""
    for exp in exposures:
        if exp.slot == slot and exp.status in (
            RaceNewsExposureStatus.WAITING,
            RaceNewsExposureStatus.ACTIVE,
            RaceNewsExposureStatus.SENT,
        ):
            return exp
    return None


def _exposure_to_dict(exposure: RaceNewsExposure) -> dict:
    """Convert an ``RaceNewsExposure`` instance to a plain dict."""
    return {
        "slot": exposure.slot,
        "status": exposure.status,
        "activated_at": exposure.activated_at,
        "article_id": exposure.article_id,
        "event_id": exposure.event_id,
        "angle": exposure.angle,
        "reason": exposure.reason,
        "policy_version": exposure.policy_version,
        "id": exposure.id,
    }
