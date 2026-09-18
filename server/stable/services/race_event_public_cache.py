from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

from stable.models import RaceEvent, RaceEventVisibility


RACE_SITEMAP_COUNT_CACHE_KEY = "race-events:public:sitemap-count:v1"
RACE_CALENDAR_YEARS_CACHE_KEY = "race-events:public:calendar-years:v2"


def _timeout() -> int:
    return max(0, int(getattr(settings, "RACE_EVENT_PUBLIC_CACHE_SECONDS", 300)))


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value) -> None:
    try:
        cache.set(key, value, _timeout())
    except Exception:
        return


def public_race_sitemap_count(queryset) -> int:
    cached = _cache_get(RACE_SITEMAP_COUNT_CACHE_KEY)
    if cached is not None:
        return int(cached)
    count = queryset.count()
    _cache_set(RACE_SITEMAP_COUNT_CACHE_KEY, count)
    return count


def public_race_calendar_years() -> list[int]:
    cached = _cache_get(RACE_CALENDAR_YEARS_CACHE_KEY)
    if cached is not None:
        return list(cached)
    from .race_public_time import annotate_public_time
    from django.db.models import IntegerField
    from django.db.models.functions import Coalesce, ExtractYear
    years = list(annotate_public_time(RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED)
        .exclude(canonical_product_links__is_active=True))
        .annotate(beijing_year=Coalesce(ExtractYear('public_date'),'year',output_field=IntegerField()))
        .order_by('-beijing_year').values_list('beijing_year', flat=True).distinct())
    _cache_set(RACE_CALENDAR_YEARS_CACHE_KEY, years)
    return years


def invalidate_public_race_cache() -> None:
    try:
        cache.delete_many([RACE_SITEMAP_COUNT_CACHE_KEY, RACE_CALENDAR_YEARS_CACHE_KEY])
    except Exception:
        return
