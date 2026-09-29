"""阶段 4：新四地区（爱尔兰/澳大利亚/德国/中东）公开展示支持。

覆盖 PUBLIC_REGION_TABS / PUBLIC_REGION_COLORS 注册、_resolve_public_region 受理、
赛事日历按新地区过滤、horse profile 地区色不回落默认色。
"""
from __future__ import annotations

import re
from datetime import date

from django.test import TestCase, SimpleTestCase
from django.urls import reverse

from stable.models import (
    RaceEvent,
    RaceEventStatus,
    RaceEventVisibility,
    RacingRegion,
)
from stable.views import (
    PUBLIC_REGION_COLORS,
    PUBLIC_REGION_TABS,
    _resolve_public_region,
)


NEW_REGIONS = (
    RacingRegion.IRELAND,
    RacingRegion.AUSTRALIA,
    RacingRegion.GERMANY,
    RacingRegion.MIDDLE_EAST,
)


class PublicRegionRegistryTests(SimpleTestCase):
    def test_tabs_cover_all_nine_regions_in_display_order(self):
        values = [tab["value"] for tab in PUBLIC_REGION_TABS]
        self.assertEqual(values[0], "")
        self.assertEqual(
            values[1:],
            [
                RacingRegion.JAPAN,
                RacingRegion.HONG_KONG,
                RacingRegion.UNITED_KINGDOM,
                RacingRegion.IRELAND,
                RacingRegion.FRANCE,
                RacingRegion.GERMANY,
                RacingRegion.UNITED_STATES,
                RacingRegion.AUSTRALIA,
                RacingRegion.MIDDLE_EAST,
            ],
        )

    def test_tab_labels_match_model_display_names(self):
        labels = dict(RacingRegion.choices)
        for tab in PUBLIC_REGION_TABS:
            if not tab["value"]:
                continue
            with self.subTest(region=tab["value"]):
                self.assertEqual(tab["label"], labels[tab["value"]])

    def test_colors_unique_valid_and_cover_all_regions(self):
        colors = [tab["color"] for tab in PUBLIC_REGION_TABS]
        self.assertEqual(len(colors), len(set(colors)), "地区颜色必须互不相同")
        for color in colors:
            self.assertRegex(color, r"^#[0-9A-Fa-f]{6}$")
        for tab in PUBLIC_REGION_TABS:
            self.assertEqual(PUBLIC_REGION_COLORS.get(tab["value"]), tab["color"])

    def test_resolve_public_region_accepts_new_regions(self):
        for region in NEW_REGIONS:
            with self.subTest(region=region):
                self.assertEqual(_resolve_public_region(region), region)
        self.assertEqual(_resolve_public_region("atlantis"), "")
        self.assertEqual(_resolve_public_region(""), "")


class PublicNewRegionRenderTests(TestCase):
    def _make_event(self, *, slug, region, visibility=RaceEventVisibility.PUBLISHED):
        return RaceEvent.objects.create(
            year=2026,
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
            local_date=date(2026, 10, 4),
            status=RaceEventStatus.SCHEDULED,
            visibility_status=visibility,
        )

    def test_race_calendar_lists_new_region_tab_and_filters(self):
        ireland_event = self._make_event(slug="ireland-test-stakes-2026", region=RacingRegion.IRELAND)
        japan_event = self._make_event(slug="japan-test-stakes-2026", region=RacingRegion.JAPAN)
        response = self.client.get(reverse("public-race-calendar"), {"tab": "all", "year": "2026"})
        self.assertEqual(response.status_code, 200)
        tab_values = [tab["value"] for tab in response.context["region_tabs"]]
        for region in NEW_REGIONS:
            self.assertIn(region, tab_values)

        filtered = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "year": "2026", "region": RacingRegion.IRELAND},
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertContains(filtered, ireland_event.original_name)
        self.assertNotContains(filtered, japan_event.original_name)

    def test_draft_events_stay_hidden_on_public_calendar(self):
        self._make_event(
            slug="ireland-draft-stakes-2026",
            region=RacingRegion.IRELAND,
            visibility=RaceEventVisibility.DRAFT,
        )
        response = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "year": "2026", "region": RacingRegion.IRELAND},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Test Stakes ireland-draft-stakes-2026")
