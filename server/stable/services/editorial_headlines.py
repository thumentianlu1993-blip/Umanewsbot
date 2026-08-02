"""
Service layer for editorial headline control: manual selection, AI recommendation,
and automatic fallback for the homepage primary headline.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from stable.models import (
    HomepageHeadlineRecommendation,
    HomepageHeadlineSelection,
    NewsArticle,
    NewsImage,
    RaceEvent,
    RaceNewsExposure,
    RaceNewsExposureChannel,
    RaceNewsExposureStatus,
    WorkflowStatus,
)
from stable.services.operations import log_operation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SCAN_PER_WINDOW = 192
MAX_ELIGIBLE_PER_WINDOW = 48
RECOMMENDATION_ENGINE_VERSION = "homepage-headline-recommendation.v1"

# ---------------------------------------------------------------------------
# Permission check
# ---------------------------------------------------------------------------


def _check_headline_permission(user) -> None:
    """Raise PermissionError if *user* cannot modify headline selection."""
    if user is None:
        raise PermissionError("User must be authenticated")
    if not (user.is_superuser or user.has_perm("stable.change_homepageheadlineselection")):
        raise PermissionError(
            f"User {user} lacks 'stable.change_homepageheadlineselection' permission"
        )


# ---------------------------------------------------------------------------
# Sort-key helpers (equivalent to views._race_priority_score / _headline_sort_key)
# ---------------------------------------------------------------------------


def _race_priority_score(article: NewsArticle) -> int:
    """Return 3 for P0, 2 for P1, 0 otherwise."""
    signals = (
        article.decision_reason.get("signals")
        if isinstance(article.decision_reason, dict)
        else {}
    )
    priority = signals.get("race_priority") if isinstance(signals, dict) else ""
    return {"P0": 3, "P1": 2}.get(priority, 0)


def _article_has_cover(article: NewsArticle) -> bool:
    """Return True if *article* has a usable cover image, using prefetched
    data when available to avoid N+1 queries."""
    # Cover media asset (already select_related)
    if article.cover_media_asset_id and article.cover_media_asset:
        if article.cover_media_asset.public_url:
            return True
    # Prefetched images (to_attr="prefetched_images" — from headline_candidate_queryset)
    prefetched = getattr(article, "prefetched_images", None)
    if prefetched is not None:
        for img in prefetched:
            if getattr(img, "public_url", None):
                return True
        return False
    # Default prefetch cache (used by _public_published_articles / public queryset)
    cache = getattr(article, "_prefetched_objects_cache", None)
    if isinstance(cache, dict) and "images" in cache:
        for img in cache["images"]:
            if getattr(img, "public_url", None):
                return True
        return False
    # Fallback: related-manager query (only when not prefetched)
    return bool(article.cover_image_url)


def _headline_sort_key(article: NewsArticle) -> tuple:
    """Sort tuple: (race_priority, score_total, has_cover, timestamp, id)."""
    published_at = article.published_to_web_at or article.published_at
    return (
        _race_priority_score(article),
        article.score_total or 0,
        1 if _article_has_cover(article) else 0,
        published_at.timestamp() if published_at else 0,
        article.id,
    )


# ---------------------------------------------------------------------------
# 1. Eligibility
# ---------------------------------------------------------------------------


def is_headline_eligible(article, *, now=None) -> bool:
    """Return True iff *article* may be used as the homepage headline."""
    now = now or timezone.now()

    if article.pk is None:
        return False
    if article.workflow_status != WorkflowStatus.PUBLISHED:
        return False
    if article.published_to_web_at is None:
        return False
    if article.published_to_web_at > now:
        return False
    if not article.effective_title.strip():
        return False
    if not article.effective_summary.strip():
        return False
    if not article.effective_body.strip():
        return False
    return True


# ---------------------------------------------------------------------------
# 2. Candidate queryset (database-level superset)
# ---------------------------------------------------------------------------


def headline_candidate_queryset(*, now=None):
    """Return a QuerySet of potentially-eligible articles (DB pre-filter)."""
    now = now or timezone.now()
    return (
        NewsArticle.objects.select_related("cover_media_asset")
        .prefetch_related(
            Prefetch(
                "images",
                queryset=NewsImage.objects.order_by("sort_order", "id"),
                to_attr="prefetched_images",
            )
        )
        .filter(
            workflow_status=WorkflowStatus.PUBLISHED,
            published_to_web_at__isnull=False,
            published_to_web_at__lte=now,
        )
        .filter(
            Q(title_zh__gt="")
            | Q(translated_title_zh__gt="")
            | Q(title_ja__gt="")
            | Q(rewrite_title_zh__gt="")
        )
        .filter(
            Q(body_zh__gt="")
            | Q(translated_body_zh__gt="")
            | Q(body_ja_normalized__gt="")
            | Q(body_ja_raw__gt="")
            | Q(rewrite_body_zh__gt="")
        )
        .order_by("-published_to_web_at", "-id")
    )


# ---------------------------------------------------------------------------
# 3. get_or_create helper for the singleton selection
# ---------------------------------------------------------------------------


def _ensure_selection() -> tuple[HomepageHeadlineSelection, bool]:
    """Get or create the singleton ``HomepageHeadlineSelection`` row.

    Uses a savepoint so that a concurrent ``IntegrityError`` is handled
    gracefully — the savepoint is rolled back and the row is re-read.
    """
    try:
        with transaction.atomic():
            selection, created = HomepageHeadlineSelection.objects.get_or_create(
                slot=HomepageHeadlineSelection.SLOT_HOMEPAGE_PRIMARY,
            )
            return selection, created
    except IntegrityError:
        return (
            HomepageHeadlineSelection.objects.get(
                slot=HomepageHeadlineSelection.SLOT_HOMEPAGE_PRIMARY,
            ),
            False,
        )


# ---------------------------------------------------------------------------
# 4. State reader
# ---------------------------------------------------------------------------


def get_headline_state(*, now=None) -> dict:
    """Return the current headline selection state.

    Returns
    -------
    dict
        Keys include ``selection``, ``manual_article``, ``is_manual_active``,
        ``active_recommendation``, ``article_id``, and ``version``.
    """
    now = now or timezone.now()
    try:
        selection = HomepageHeadlineSelection.objects.select_related("article").get(
            slot=HomepageHeadlineSelection.SLOT_HOMEPAGE_PRIMARY,
        )
    except HomepageHeadlineSelection.DoesNotExist:
        return {
            "selection": None,
            "manual_article": None,
            "is_manual_active": False,
            "active_recommendation": None,
            "article_id": None,
            "version": 0,
        }

    article = selection.article
    is_manual_active = (
        article is not None and is_headline_eligible(article, now=now)
    )

    try:
        active_rec = HomepageHeadlineRecommendation.objects.select_related("article").get(
            slot=HomepageHeadlineRecommendation.SLOT_HOMEPAGE_PRIMARY,
            status=HomepageHeadlineRecommendation.Status.ACTIVE,
        )
    except HomepageHeadlineRecommendation.DoesNotExist:
        active_rec = None

    return {
        "selection": selection,
        "manual_article": article if is_manual_active else None,
        "is_manual_active": is_manual_active,
        "active_recommendation": active_rec,
        "article_id": selection.article_id,
        "version": selection.version,
    }


# ---------------------------------------------------------------------------
# 5. Window-scanning helper
# ---------------------------------------------------------------------------


def _scan_window_candidates(
    queryset,
    *,
    threshold,
    now,
    max_scan=MAX_SCAN_PER_WINDOW,
    max_collect=MAX_ELIGIBLE_PER_WINDOW,
) -> list[NewsArticle]:
    """Scan a single time window for eligible headline candidates.

    Parameters
    ----------
    queryset : QuerySet
        Pre-filtered (published, non-null ``published_to_web_at``).
    threshold : datetime | None
        If not None, only articles with ``published_to_web_at >= threshold``
        are considered.
    now : datetime
        Reference time for eligibility.
    max_scan : int
        Maximum rows to iterate from the database.
    max_collect : int
        Stop after collecting this many eligible candidates.

    Returns
    -------
    list[NewsArticle]
        Eligible candidates in database order (newest first).
    """
    candidates = queryset
    if threshold is not None:
        candidates = candidates.filter(published_to_web_at__gte=threshold)

    eligible: list[NewsArticle] = []
    for article in candidates[:max_scan]:
        if is_headline_eligible(article, now=now):
            eligible.append(article)
            if len(eligible) >= max_collect:
                break
    return eligible


# ---------------------------------------------------------------------------
# 6. Automatic headline selection (weekly-headline algorithm)
# ---------------------------------------------------------------------------


def select_automatic_headline(
    public_queryset, *, now=None
) -> NewsArticle | None:
    """Pick the best eligible headline using the three-window algorithm.

    Each window (72h → 7d → all) is scanned for up to *MAX_ELIGIBLE_PER_WINDOW*
    candidates; the article with the highest ``_headline_sort_key`` wins.
    Returns ``None`` when no candidate is found.
    """
    now = now or timezone.now()
    for threshold in (
        now - timedelta(hours=72),
        now - timedelta(days=7),
        None,
    ):
        eligible = _scan_window_candidates(
            public_queryset, threshold=threshold, now=now
        )
        if eligible:
            return max(eligible, key=_headline_sort_key)
    return None


# ---------------------------------------------------------------------------
# 7. Composite resolution (manual → automatic)
# ---------------------------------------------------------------------------


def resolve_homepage_headline(public_queryset, *, now=None) -> NewsArticle | None:
    """Resolve the homepage headline, preferring a valid manual selection.

    1.  If the selection points to an **eligible** article, return it.
    2.  Otherwise fall back to ``select_automatic_headline``.
    3.  **Never** writes to the database or creates audit logs.
    """
    now = now or timezone.now()
    try:
        selection = HomepageHeadlineSelection.objects.select_related("article").get(
            slot=HomepageHeadlineSelection.SLOT_HOMEPAGE_PRIMARY,
        )
    except HomepageHeadlineSelection.DoesNotExist:
        selection = None

    if selection and selection.article_id and is_headline_eligible(selection.article, now=now):
        return selection.article

    return select_automatic_headline(public_queryset, now=now)


# ---------------------------------------------------------------------------
# 8. Manual set / replace
# ---------------------------------------------------------------------------


def set_manual_headline(
    article_id, *, user, expected_version
) -> dict:
    """Atomically set (or replace) the homepage headline to *article_id*.

    Parameters
    ----------
    article_id : int
    user : User
    expected_version : int
        Version expected by the caller; a mismatch raises ``ValueError``.

    Returns
    -------
    dict
        ``{"success": True, "selection": selection, "action": "set"|"replaced", "version": N}``
        or ``{"success": False, "reason": "..."}``.
    """
    _check_headline_permission(user)

    with transaction.atomic():
        selection, _ = _ensure_selection()

        # Lock the selection row
        selection = HomepageHeadlineSelection.objects.select_for_update().get(
            pk=selection.pk
        )

        # Version check
        if selection.version != expected_version:
            logger.warning(
                "set_manual_headline version conflict: expected=%d actual=%d",
                expected_version,
                selection.version,
            )
            raise ValueError(
                f"Version conflict: expected {expected_version}, "
                f"actual {selection.version}"
            )

        # Lock and re-validate the target article
        try:
            article = NewsArticle.objects.select_for_update().get(pk=article_id)
        except NewsArticle.DoesNotExist:
            return {"success": False, "reason": f"Article {article_id} does not exist"}

        if not is_headline_eligible(article):
            return {
                "success": False,
                "reason": f"Article {article_id} is not eligible as headline",
            }

        # Determine action
        already_selected = selection.article_id == article_id
        old_article_id = selection.article_id
        had_previous = old_article_id is not None
        action = "replaced" if had_previous else "set"

        if not already_selected:
            # Update selection
            selection.article = article
            selection.selected_by = user
            selection.selected_at = timezone.now()
            selection.version += 1
            selection.save(
                update_fields=["article", "selected_by", "selected_at", "version", "updated_at"]
            )
            selection.refresh_from_db()

            # Audit — include old article ID so the full transition is reconstructable.
            detail_parts = [
                f"new_article={article_id}",
                f"title={article.effective_title!r}",
                f"version={selection.version}",
            ]
            if had_previous:
                detail_parts.append(f"old_article={old_article_id}")
            detail = " ".join(detail_parts)
            log_operation(
                action_type=f"headline_{action}",
                target_type="headline_selection",
                target_id=selection.pk,
                detail=detail,
                admin=user,
            )
            logger.info("headline_%s: %s", action, detail)

        # When exposure governance is enabled, ensure the new headline article
        # gets a homepage slot. If the same event already has slot 2 occupied,
        # replace it with the headline article (slot 1 is never replaced).
        # This block runs inside the same transaction.atomic() as the headline
        # selection update above: any failure propagates and rolls back the
        # whole operation, so a headline is never committed without its
        # exposure state.  It also runs when the selection ALREADY points to
        # this article (idempotent re-set): the exposure state may have
        # degraded to waiting/suppressed since the headline was first set,
        # and a headline without an ACTIVE exposure is invisible.
        if getattr(settings, "RACE_NEWS_EXPOSURE_ENABLED", False):
            from stable.services.race_news_exposure import (
                classify_angle,
                force_activate_exposure,
                reserve_exposure,
                replace_slot2,
                resolve_race_identity,
            )
            identity = resolve_race_identity(article)
            if identity:
                event = RaceEvent.objects.filter(pk=identity["event_id"]).first()
                if event:
                    # Use the article's REAL classified angle.  Hardcoding
                    # "comprehensive_result" here would falsely collide with
                    # a comprehensive-result slot 1 and reject the headline
                    # (or its re-activation) as same-angle.
                    headline_angle = classify_angle(article=article, event=event)["angle"]
                    # Check if this event already has slot 2 with a DIFFERENT article
                    existing_slot2 = RaceNewsExposure.objects.filter(
                        event=event,
                        channel=RaceNewsExposureChannel.HOMEPAGE,
                        scope_key="site",
                        slot=2,
                        status=RaceNewsExposureStatus.ACTIVE,
                    ).exclude(article=article).first()
                    if existing_slot2:
                        sync_result = replace_slot2(
                            event=event,
                            channel=RaceNewsExposureChannel.HOMEPAGE,
                            scope_key="site",
                            old_article=existing_slot2.article,
                            new_article=article,
                            reason="manual_headline_replacement",
                        )
                    else:
                        # No slot 2 yet — reserve a slot for the headline article
                        sync_result = reserve_exposure(
                            event=event,
                            article=article,
                            channel=RaceNewsExposureChannel.HOMEPAGE,
                            scope_key="site",
                            angle=headline_angle,
                        )
                    # Policy rejections return {"slot": None, "status": ...}
                    # WITHOUT raising.  Honor them explicitly: committing the
                    # headline anyway would leave a low-quality or
                    # policy-blocked article on the homepage with no valid
                    # exposure slot, so roll back the whole operation.
                    if sync_result.get("slot") is None:
                        raise ValueError(
                            "headline exposure policy rejected: "
                            f"{sync_result.get('status', 'unknown')}"
                        )
                    if sync_result.get("status") == "waiting":
                        # A waiting slot-2 would leave the headline invisible
                        # until promotion.  A manual headline is an editorial
                        # override of the second-slot delay: activate now.
                        sync_result = force_activate_exposure(
                            sync_result["id"],
                            reason="manual_headline_activate",
                        )

        if already_selected:
            # Idempotency: already pointing to this article — the selection is
            # unchanged; only the exposure sync above may have run.
            return {
                "success": True,
                "selection": selection,
                "action": "set",
                "version": selection.version,
            }

    return {
        "success": True,
        "selection": selection,
        "action": action,
        "version": selection.version,
    }


# ---------------------------------------------------------------------------
# 9. Manual cancel
# ---------------------------------------------------------------------------


def cancel_manual_headline(*, user, expected_version) -> dict:
    """Cancel (clear) the manual homepage headline selection.

    Returns
    -------
    dict
        ``{"success": True, "selection": ..., "action": "cancelled", "version": N}``
        or ``{"success": False, "reason": "..."}``.
    """
    _check_headline_permission(user)

    with transaction.atomic():
        selection, _ = _ensure_selection()

        selection = HomepageHeadlineSelection.objects.select_for_update().get(
            pk=selection.pk
        )

        if selection.version != expected_version:
            logger.warning(
                "cancel_manual_headline version conflict: expected=%d actual=%d",
                expected_version,
                selection.version,
            )
            raise ValueError(
                f"Version conflict: expected {expected_version}, "
                f"actual {selection.version}"
            )

        # Idempotency: already cancelled
        if selection.article_id is None:
            return {
                "success": True,
                "selection": selection,
                "action": "cancelled",
                "version": selection.version,
            }

        old_article_id = selection.article_id
        selection.article = None
        selection.selected_by = None
        selection.selected_at = None
        selection.version += 1
        selection.save(
            update_fields=["article", "selected_by", "selected_at", "version", "updated_at"]
        )
        selection.refresh_from_db()

        log_operation(
            action_type="headline_cancelled",
            target_type="headline_selection",
            target_id=selection.pk,
            detail=f"old_article={old_article_id} version={selection.version}",
            admin=user,
        )
        logger.info("headline_cancelled: old_article=%d version=%d", old_article_id, selection.version)

    return {
        "success": True,
        "selection": selection,
        "action": "cancelled",
        "version": selection.version,
    }


# ---------------------------------------------------------------------------
# 10. AI recommendation generation
# ---------------------------------------------------------------------------


def generate_headline_recommendation(*, user, now=None) -> dict | None:
    """Generate an AI headline recommendation without changing the homepage.

    Scans candidates using the same three-window algorithm.  The single best
    article is recorded as an active ``HomepageHeadlineRecommendation``.

    Parameters
    ----------
    user : User
    now : datetime | None

    Returns
    -------
    dict | None
        ``None`` when no eligible candidate exists.  Otherwise a dict with keys
        ``id``, ``article_id``, ``reason``, ``evidence``, ``engine_version``.
    """
    _check_headline_permission(user)

    now = now or timezone.now()
    queryset = headline_candidate_queryset(now=now)

    # Scan windows
    chosen_article: NewsArticle | None = None
    candidates_info: list[int] = []
    used_threshold = None

    for threshold in (
        now - timedelta(hours=72),
        now - timedelta(days=7),
        None,
    ):
        eligible = _scan_window_candidates(
            queryset, threshold=threshold, now=now
        )
        if eligible:
            chosen_article = max(eligible, key=_headline_sort_key)
            candidates_info = [a.pk for a in eligible]
            used_threshold = threshold
            break

    if chosen_article is None:
        logger.info("generate_headline_recommendation: no eligible candidates")
        return None

    # Collect per-candidate signal snapshots for evidence (before the
    # transaction — the scan objects are still valid for read-only data).
    candidate_signals: list[dict] = []
    for a in eligible:
        candidate_signals.append({
            "id": a.pk,
            "race_priority": _race_priority_score(a),
            "score_total": a.score_total or 0,
            "has_cover": _article_has_cover(a),
            "sort_key": list(_headline_sort_key(a)),
        })

    # Human-readable reason — computed outside the transaction from scan data.
    priority_label = {3: "P0", 2: "P1"}.get(_race_priority_score(chosen_article))
    reason_parts = []
    if used_threshold is None or used_threshold < now - timedelta(days=7):
        reason_parts.append("全量候选")
    elif used_threshold >= now - timedelta(hours=72):
        reason_parts.append("近72小时")
    else:
        reason_parts.append("近7天")

    if priority_label:
        reason_parts.append(f"{priority_label}赛事稿")

    reason_parts.append(f"自动化分数{chosen_article.score_total or 0}")
    if _article_has_cover(chosen_article):
        reason_parts.append("且有封面")

    reason = "，".join(reason_parts)
    threshold_label = (
        "72h" if used_threshold is not None and used_threshold >= now - timedelta(hours=72)
        else "7d" if used_threshold is not None
        else "all"
    )

    with transaction.atomic():
        # Lock selection as the slot mutual-exclusion point
        selection, _ = _ensure_selection()
        selection = HomepageHeadlineSelection.objects.select_for_update().get(
            pk=selection.pk
        )

        # Re-fetch and re-validate the chosen article under lock to close
        # the TOCTOU window between scan and insert.
        try:
            locked_article = NewsArticle.objects.select_for_update().get(
                pk=chosen_article.pk
            )
        except NewsArticle.DoesNotExist:
            return None
        if not is_headline_eligible(locked_article, now=now):
            return None

        # Lock current active recommendation and supersede it
        superseded_id = None
        try:
            old_active = HomepageHeadlineRecommendation.objects.select_for_update().get(
                slot=HomepageHeadlineRecommendation.SLOT_HOMEPAGE_PRIMARY,
                status=HomepageHeadlineRecommendation.Status.ACTIVE,
            )
            superseded_id = old_active.pk
            old_active.status = HomepageHeadlineRecommendation.Status.SUPERSEDED
            old_active.save(update_fields=["status", "updated_at"])
        except HomepageHeadlineRecommendation.DoesNotExist:
            pass

        evidence = {
            "generated_at": timezone.now().isoformat(),
            "engine_version": RECOMMENDATION_ENGINE_VERSION,
            "threshold": threshold_label,
            "candidate_ids": [a["id"] for a in candidate_signals],
            "candidate_limit": MAX_ELIGIBLE_PER_WINDOW,
            "candidate_signals": candidate_signals,
            "selected_article_id": chosen_article.pk,
            "selected_article_sort_key": list(_headline_sort_key(chosen_article)),
            "manual_selection_article_id": selection.article_id,
        }

        rec = HomepageHeadlineRecommendation.objects.create(
            slot=HomepageHeadlineRecommendation.SLOT_HOMEPAGE_PRIMARY,
            article=locked_article,
            status=HomepageHeadlineRecommendation.Status.ACTIVE,
            reason=reason,
            evidence=evidence,
            engine_version=RECOMMENDATION_ENGINE_VERSION,
            generated_by=user,
        )

        if superseded_id is not None:
            log_operation(
                action_type="headline_recommendation_superseded",
                target_type="headline_recommendation",
                target_id=superseded_id,
                detail=(
                    f"superseded_by={rec.pk} "
                    f"article={locked_article.pk} "
                    f"title={locked_article.effective_title!r}"
                ),
                admin=user,
            )

        log_operation(
            action_type="headline_recommendation_generated",
            target_type="headline_recommendation",
            target_id=rec.pk,
            detail=(
                f"article={locked_article.pk} "
                f"title={locked_article.effective_title!r} "
                f"reason={reason}"
            ),
            admin=user,
        )
        logger.info(
            "headline_recommendation_generated: article=%d reason=%s",
            locked_article.pk,
            reason,
        )

    return {
        "id": rec.pk,
        "article_id": locked_article.pk,
        "reason": reason,
        "evidence": evidence,
        "engine_version": RECOMMENDATION_ENGINE_VERSION,
    }


# ---------------------------------------------------------------------------
# 11. Accept recommendation
# ---------------------------------------------------------------------------


def accept_headline_recommendation(
    recommendation_id, *, user, expected_selection_version
) -> dict:
    """Accept an active recommendation — updates the selection atomically.

    Returns
    -------
    dict
        Keys: ``success``, ``action`` (``"set"`` / ``"replaced"``), ``version``.
    """
    _check_headline_permission(user)

    with transaction.atomic():
        selection, _ = _ensure_selection()
        selection = HomepageHeadlineSelection.objects.select_for_update().get(
            pk=selection.pk
        )

        if selection.version != expected_selection_version:
            raise ValueError(
                f"Selection version conflict: expected {expected_selection_version}, "
                f"actual {selection.version}"
            )

        try:
            rec = HomepageHeadlineRecommendation.objects.select_for_update().get(
                pk=recommendation_id
            )
        except HomepageHeadlineRecommendation.DoesNotExist:
            raise ValueError(f"Recommendation {recommendation_id} does not exist")

        if rec.status != HomepageHeadlineRecommendation.Status.ACTIVE:
            raise ValueError(
                f"Recommendation {recommendation_id} has status "
                f"'{rec.status}', expected 'active'"
            )

        # Lock and re-validate the recommended article
        try:
            article = NewsArticle.objects.select_for_update().get(pk=rec.article_id)
        except NewsArticle.DoesNotExist:
            raise ValueError(
                f"Recommended article {rec.article_id} does not exist"
            )

        if not is_headline_eligible(article):
            raise ValueError(
                f"Recommended article {rec.article_id} is no longer eligible"
            )

        had_previous = selection.article_id is not None
        action = "replaced" if had_previous else "set"

        selection.article = article
        selection.selected_by = user
        selection.selected_at = timezone.now()
        selection.version += 1
        selection.save(
            update_fields=["article", "selected_by", "selected_at", "version", "updated_at"]
        )

        rec.status = HomepageHeadlineRecommendation.Status.ACCEPTED
        rec.accepted_by = user
        rec.accepted_at = timezone.now()
        rec.save(
            update_fields=["status", "accepted_by", "accepted_at", "updated_at"]
        )

        detail = (
            f"recommendation={recommendation_id} article={article.pk} "
            f"title={article.effective_title!r} version={selection.version}"
        )
        log_operation(
            action_type="headline_recommendation_accepted",
            target_type="headline_recommendation",
            target_id=recommendation_id,
            detail=detail,
            admin=user,
        )
        log_operation(
            action_type=f"headline_{action}",
            target_type="headline_selection",
            target_id=selection.pk,
            detail=detail,
            admin=user,
        )
        logger.info(
            "headline_recommendation_accepted: %s action=%s", detail, action
        )

    return {"success": True, "action": action, "version": selection.version}


# ---------------------------------------------------------------------------
# 12. Invalidation
# ---------------------------------------------------------------------------


def invalidate_headline_state_for_article(
    article_id, *, reason="article_became_ineligible"
) -> int:
    """Check and clear headline state that references an ineligible article.

    Idempotent — repeated calls are safe.

    Parameters
    ----------
    article_id : int
    reason : str
        Reason logged in the audit trail.

    Returns
    -------
    int
        Number of records modified (0, 1, or 2).
    """
    changes = 0
    with transaction.atomic():
        # Lock selection (singleton row via get_or_create, then lock it)
        try:
            selection = HomepageHeadlineSelection.objects.select_for_update().get(
                slot=HomepageHeadlineSelection.SLOT_HOMEPAGE_PRIMARY,
            )
        except HomepageHeadlineSelection.DoesNotExist:
            selection = None

        # Lock recommendation (if an active one exists)
        try:
            active_rec = (
                HomepageHeadlineRecommendation.objects.select_for_update().get(
                    slot=HomepageHeadlineRecommendation.SLOT_HOMEPAGE_PRIMARY,
                    status=HomepageHeadlineRecommendation.Status.ACTIVE,
                )
            )
        except HomepageHeadlineRecommendation.DoesNotExist:
            active_rec = None

        # Lock the article so eligibility check is consistent with the write
        try:
            article = NewsArticle.objects.select_for_update().get(pk=article_id)
        except NewsArticle.DoesNotExist:
            article = None

        # --- Selection ---
        if selection and selection.article_id == article_id:
            eligible = article is not None and is_headline_eligible(article)
            if not eligible:
                selection.article = None
                selection.selected_by = None
                selection.selected_at = None
                selection.version += 1
                selection.save(
                    update_fields=[
                        "article",
                        "selected_by",
                        "selected_at",
                        "version",
                        "updated_at",
                    ]
                )
                log_operation(
                    action_type="headline_invalidated",
                    target_type="headline_selection",
                    target_id=selection.pk,
                    detail=(
                        f"article={article_id} reason={reason} "
                        f"version={selection.version}"
                    ),
                )
                changes += 1
                logger.info(
                    "headline_invalidated: selection %d article=%d",
                    selection.pk,
                    article_id,
                )

        # --- Recommendation ---
        if active_rec and active_rec.article_id == article_id:
            eligible = article is not None and is_headline_eligible(article)
            if not eligible:
                active_rec.status = HomepageHeadlineRecommendation.Status.INVALIDATED
                active_rec.save(update_fields=["status", "updated_at"])
                log_operation(
                    action_type="headline_recommendation_invalidated",
                    target_type="headline_recommendation",
                    target_id=active_rec.pk,
                    detail=f"article={article_id} reason={reason}",
                )
                changes += 1
                logger.info(
                    "headline_recommendation_invalidated: rec %d article=%d",
                    active_rec.pk,
                    article_id,
                )

    return changes
