"""公开日历 public_time 回退语义：date-only 赛事（无 race_datetime、无开赛时刻）必须
按 local_date 参与公开日期窗口，不限于 Asia/Shanghai（九地区修复）。

根源：原回退只覆盖 Asia/Shanghai，导致其他时区的 date-only 赛事 public_date=NULL，
被"即将开赛"等日期窗口查询静默排除。
"""
from __future__ import annotations

from datetime import date, time

from django.test import TestCase

from stable.models import (
    RaceEvent,
    RaceEventStatus,
    RaceEventVisibility,
    RacingRegion,
)
from stable.services.race_public_time import annotate_public_time


def _make_event(slug: str, *, tz: str, day: date, clock=None, region=RacingRegion.IRELAND):
    return RaceEvent.objects.create(
        year=day.year,
        slug=slug,
        series_key=slug.rsplit("-", 1)[0],
        original_name=f"Test Stakes {slug}",
        chinese_name=f"测试赛 {slug}",
        country_region=region,
        racecourse="Test Course",
        grade_text="G1",
        normalized_grade="g1",
        surface="turf",
        distance_text="2000",
        local_date=day,
        local_start_time=clock,
        timezone_name=tz,
        status=RaceEventStatus.SCHEDULED,
        visibility_status=RaceEventVisibility.PUBLISHED,
    )


class PublicDateFallbackTests(TestCase):
    def test_date_only_non_shanghai_region_falls_back_to_local_date(self):
        event = _make_event("ireland-date-only-2026", tz="Europe/Dublin", day=date(2026, 10, 17))
        row = annotate_public_time(RaceEvent.objects.filter(pk=event.pk)).get()
        self.assertEqual(row.public_date, date(2026, 10, 17))
        self.assertIsNone(row.public_instant)

    def test_date_only_shanghai_fallback_unchanged(self):
        event = _make_event(
            "japan-date-only-2026", tz="Asia/Shanghai", day=date(2026, 10, 17), region=RacingRegion.JAPAN
        )
        row = annotate_public_time(RaceEvent.objects.filter(pk=event.pk)).get()
        self.assertEqual(row.public_date, date(2026, 10, 17))

    def test_clock_without_datetime_stays_unresolved(self):
        # 有当地时间但无 UTC 时刻：保持不推断时区的保守口径（本修复不扩展该分支）
        event = _make_event(
            "ireland-clocked-2026", tz="Europe/Dublin", day=date(2026, 10, 17), clock=time(16, 10)
        )
        row = annotate_public_time(RaceEvent.objects.filter(pk=event.pk)).get()
        self.assertIsNone(row.public_date)

    def test_datetime_driven_resolution_unchanged(self):
        from datetime import datetime, timezone as dt_timezone

        event = _make_event("ireland-with-datetime-2026", tz="Europe/Dublin", day=date(2026, 10, 17))
        event.race_datetime = datetime(2026, 10, 17, 15, 10, tzinfo=dt_timezone.utc)
        event.save(update_fields=["race_datetime"])
        row = annotate_public_time(RaceEvent.objects.filter(pk=event.pk)).get()
        self.assertEqual(row.public_date, date(2026, 10, 17))
        self.assertIsNotNone(row.public_instant)

    def test_upcoming_queryset_includes_date_only_non_shanghai_event(self):
        from django.utils import timezone

        from stable.views import _upcoming_race_queryset

        event = _make_event(
            "ireland-upcoming-2026", tz="Europe/Dublin", day=timezone.localdate() + __import__("datetime").timedelta(days=30)
        )
        qs = _upcoming_race_queryset(
            annotate_public_time(RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED)),
            timezone.now(),
        )
        self.assertIn(event.pk, [row.pk for row in qs])
