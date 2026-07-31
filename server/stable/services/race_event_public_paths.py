from __future__ import annotations

from django.db import IntegrityError


def sync_canonical_public_path(event, *, previous_identity=None) -> None:
    """Reserve the event canonical path; rotate an old canonical to legacy.

    The caller must already be inside the same transaction as the RaceEvent save.
    Global path uniqueness intentionally makes canonical-vs-legacy collisions fail
    closed and roll the event write back.
    """

    from stable.models import RaceEventPublicPath, RaceEventPublicPathKind

    canonical = (
        RaceEventPublicPath.objects.select_for_update()
        .filter(event=event, path_kind=RaceEventPublicPathKind.CANONICAL)
        .first()
    )
    desired = (event.year, event.slug)
    if canonical is None:
        RaceEventPublicPath.objects.create(
            event=event,
            year=event.year,
            slug=event.slug,
            path_kind=RaceEventPublicPathKind.CANONICAL,
            reason="race_event_writer",
        )
        return
    current = (canonical.year, canonical.slug)
    if current == desired:
        return
    if RaceEventPublicPath.objects.filter(
        year=event.year, slug=event.slug
    ).exclude(pk=canonical.pk).exists():
        raise IntegrityError("public race path is already reserved")
    canonical.path_kind = RaceEventPublicPathKind.LEGACY
    canonical.reason = "race_event_identity_changed"
    canonical.save(update_fields={"path_kind", "reason", "updated_at"})
    RaceEventPublicPath.objects.create(
        event=event,
        year=event.year,
        slug=event.slug,
        path_kind=RaceEventPublicPathKind.CANONICAL,
        reason="race_event_writer",
    )
