"""公开赛事地区边界；后台与采集仍保留全部地区数据。"""
from django.db.models import F, Q
from stable.models import RacingRegion, RaceEventVisibility

PUBLIC_RACE_REGIONS = (
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
    RacingRegion.UNITED_KINGDOM,
)


def public_race_q(prefix=""):
    return Q(**{
        f"{prefix}country_region__in": PUBLIC_RACE_REGIONS,
        f"{prefix}visibility_status": RaceEventVisibility.PUBLISHED,
    })


def is_public_race(event):
    return bool(event and event.country_region in PUBLIC_RACE_REGIONS
                and event.visibility_status == RaceEventVisibility.PUBLISHED)


def public_career_records(queryset):
    """关联赛事优先；相互冲突的关联不公开，无关联时才用记录自身地区。"""
    return queryset.filter(
        (Q(event__country_region__in=PUBLIC_RACE_REGIONS)
         & (Q(result__isnull=True) | Q(result__event_id=F("event_id"))))
        | Q(event__isnull=True, result__event__country_region__in=PUBLIC_RACE_REGIONS)
        | Q(event__isnull=True, result__isnull=True, race_region__in=PUBLIC_RACE_REGIONS)
    )
