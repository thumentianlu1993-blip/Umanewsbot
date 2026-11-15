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


class PublicTimeQueryPerformanceTests(TestCase):
    """真实 PG 查询计划与 ORM 组合，SQLite 另有冷连接测试。"""

    @classmethod
    def setUpTestData(cls):
        from datetime import datetime, timedelta, timezone
        for i in range(80):
            event = _make_event(
                f"public-time-perf-{i}", tz="Europe/London",
                day=date(2026, 11, 15), clock=time(12, i % 60),
            )
            event.race_datetime = datetime(2026, 11, 15, 12, i % 60, tzinfo=timezone.utc)
            event.save(update_fields=["race_datetime"])

    def queryset(self):
        return annotate_public_time(RaceEvent.objects.all()).filter(
            public_date__gte=date(2026, 11, 1),
            public_date__lte=date(2026, 11, 30),
        ).order_by("public_date", "public_start_time", "pk")

    def test_timezone_directory_evaluated_once(self):
        import json
        from django.db import connection
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL 执行计划；SQLite 由独立兼容测试覆盖")
        query = self.queryset().values("id", "public_instant", "public_date", "public_start_time")
        plan = json.loads(query.explain(format="json", analyze=True))[0]["Plan"]
        def scans(node):
            found = [node] if node.get("Function Name") == "pg_timezone_names" else []
            return found + [item for child in node.get("Plans", []) for item in scans(child)]
        actual = scans(plan)
        self.assertEqual(len(actual), 1, f"重复目录 Function Scan: {len(actual)}")
        self.assertEqual(actual[0]["Actual Loops"], 1)

    def test_query_combinations_and_fresh_data(self):
        from django.db.models import Count, Max, OuterRef, Subquery
        query = self.queryset()
        ids = list(query.values_list("pk", flat=True))
        self.assertEqual(query.count(), 80)
        self.assertTrue(query.exists())
        self.assertEqual(query.aggregate(total=Count("pk"), latest=Max("public_date")),
                         {"total": 80, "latest": date(2026, 11, 15)})
        self.assertEqual(query[:10].count(), 10)
        self.assertEqual(list(query[:40].values_list("pk", flat=True)) +
                         list(query[40:].values_list("pk", flat=True)), ids)
        self.assertEqual(query.none().count(), 0)
        self.assertFalse(query.none().exists())
        left = query.filter(pk__in=ids[:40]).order_by().values_list("pk", flat=True)
        right = query.filter(pk__in=ids[40:]).order_by().values_list("pk", flat=True)
        self.assertEqual(set(left.union(right)), set(ids))
        inner = query.filter(pk=OuterRef("pk")).values("public_date")[:1]
        self.assertEqual(set(query.annotate(inner_day=Subquery(inner)).values_list("inner_day", flat=True)),
                         {date(2026, 11, 15)})
        # 普通 Query 外包专用子查询；CTE 仍在正确词法作用域。
        self.assertEqual(RaceEvent.objects.annotate(inner_day=Subquery(inner)).filter(
            inner_day=date(2026, 11, 15)).count(), 80)
        first = ids[0]
        RaceEvent.objects.filter(pk=first).update(timezone_name="Invalid/Zone")
        self.assertEqual(query.count(), 79)
        self.assertNotIn(first, query.values_list("pk", flat=True))

    def test_sql_python_time_boundaries_and_legacy_equivalence(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        from zoneinfo import ZoneInfo
        from stable.services.race_public_time import _PublicInstant, public_time
        from django.db import connection
        RaceEvent.objects.all().delete()
        values = []
        for zone, moments in {
            "America/New_York": ["2026-03-08T06:59:59+00:00", "2026-03-08T07:00:00+00:00",
                                 "2026-11-01T05:30:00+00:00", "2026-11-01T06:30:00+00:00"],
            "Europe/London": ["2026-03-29T00:59:59+00:00", "2026-03-29T01:00:00+00:00",
                              "2026-10-25T00:30:00+00:00", "2026-10-25T01:30:00+00:00"],
            "Asia/Tokyo": ["2026-12-31T16:00:00+00:00"],
        }.items():
            for moment in moments:
                instant = datetime.fromisoformat(moment)
                local = instant.astimezone(ZoneInfo(zone))
                values.append((zone, local.date(), local.time(), instant))
        instant = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
        values.extend([
            ("Invalid/Zone", date(2026, 11, 15), time(12), instant),
            ("", date(2026, 11, 15), time(12), instant),
            ("Europe/London", date(2026, 11, 14), time(12), instant),
            ("Europe/London", date(2026, 11, 15), time(13), instant),
            ("Europe/London", date(2026, 11, 15), None, None),
            ("Invalid/Zone", date(2026, 11, 15), None, None),
            ("Asia/Shanghai", date(1991, 12, 31), time(12), None),
            ("Asia/Shanghai", date(1992, 1, 1), time(12), None),
            ("Europe/London", date(2026, 11, 15), time(12), None),
        ])
        expected = []
        for i, (zone, day, clock, moment) in enumerate(values):
            event = _make_event(f"boundary-{i}", tz=zone, day=day, clock=clock)
            event.race_datetime = moment
            event.save(update_fields=["race_datetime"])
            result = public_time(event)
            expected.append((event.pk, result.instant, result.day, result.clock))
        def rows():
            return list(annotate_public_time(RaceEvent.objects.all()).order_by("pk").values_list(
                "pk", "public_instant", "public_date", "public_start_time"))
        self.assertEqual(rows(), expected)
        if connection.vendor == "postgresql":
            # 固定旧实现作为等价性 oracle；保留原始验证与转换全部分支。
            def legacy(expression, compiler, connection, **kwargs):
                instant, day, clock, zone = [compiler.compile(e)[0] for e in expression.source_expressions]
                known = f"{zone} IN (SELECT name FROM pg_timezone_names)"
                local = f"({instant} AT TIME ZONE (CASE WHEN {known} THEN {zone} ELSE 'UTC' END))"
                return f"""CASE WHEN {instant} IS NOT NULL THEN
                  CASE WHEN {known} AND ({day} IS NULL OR {local}::date = {day})
                    AND ({clock} IS NULL OR {local}::time = {clock}) THEN {instant} END
                  WHEN {zone} = 'Asia/Shanghai' AND {day} >= DATE '1992-01-01'
                    AND {clock} IS NOT NULL THEN ({day} + {clock}) AT TIME ZONE 'Asia/Shanghai' END""", []
            actual = rows()
            with patch.object(_PublicInstant, "as_postgresql", legacy):
                self.assertEqual(rows(), actual)
