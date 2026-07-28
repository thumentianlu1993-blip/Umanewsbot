"""Application RED contracts for canonical public race pages.

OpenSpec task: 1.5.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from stable import models


TODAY = date(2026, 7, 27)
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=dt_timezone.utc)


class RaceResultRecoveryPublicPageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username=f"page-reviewer-{self._testMethodName}",
            password="unused",
        )
        today_patcher = patch("stable.views.timezone.localdate", return_value=TODAY)
        today_patcher.start()
        self.addCleanup(today_patcher.stop)

    def _canonical_model(self):
        model = getattr(models, "RaceEventProductCanonicalLink", None)
        self.assertIsNotNone(
            model,
            "公开页面接入前必须实现 RaceEventProductCanonicalLink",
        )
        return model

    def _event(
        self,
        slug,
        *,
        name=None,
        status=models.RaceEventStatus.SCHEDULED,
        local_date=date(2026, 7, 20),
    ):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=name or slug.replace("-", " ").title(),
            chinese_name=name or f"页面 {slug}",
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            timezone_name="Asia/Tokyo",
            local_date=local_date,
            status=status,
            data_quality_status=models.RaceEventDataQuality.COMPLETE,
            priority=models.RaceEventPriority.P0,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )

    def _link(self, duplicate, canonical, *, active=True, suffix="1"):
        return self._canonical_model().objects.create(
            duplicate_event=duplicate,
            canonical_event=canonical,
            identity_sha256=suffix * 64,
            manifest_sha256="a" * 64,
            approved_by=self.user,
            approved_at=NOW,
            is_active=active,
        )

    def _winner(self, event, name="Confirmed Winner"):
        return models.RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            official_finish_position=1,
            horse_number="1",
            horse_name=name,
            is_confirmed=True,
        )

    def test_calendar_shows_only_active_canonical_event_once(self):
        canonical = self._event(
            "calendar-canonical",
            name="唯一产品赛事",
            status=models.RaceEventStatus.FINISHED,
        )
        duplicate = self._event(
            "calendar-duplicate",
            name="重复底层赛事",
            status=models.RaceEventStatus.FINISHED,
        )
        self._winner(canonical)
        self._winner(duplicate, "Ledger Winner")
        self._link(duplicate, canonical)

        response = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "year": "2026"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, canonical.public_path, count=1)
        self.assertNotContains(response, duplicate.public_path)
        self.assertContains(response, "唯一产品赛事", count=1)
        self.assertNotContains(response, "重复底层赛事")

    def test_old_duplicate_detail_url_stays_200_and_links_to_canonical(self):
        canonical = self._event("detail-canonical", name="正式展示赛事")
        duplicate = self._event("detail-duplicate", name="旧赛事入口")
        self._link(duplicate, canonical)

        response = self.client.get(duplicate.public_path)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "旧赛事入口")
        self.assertContains(response, canonical.public_path)
        self.assertContains(response, "正式展示赛事")

    def test_inactive_link_restores_pre_link_calendar_selection(self):
        canonical = self._event("rollback-canonical", name="回滚正式赛事")
        duplicate = self._event("rollback-duplicate", name="回滚重复赛事")
        link = self._link(duplicate, canonical)
        link.is_active = False
        link.save(update_fields=("is_active", "updated_at"))

        response = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "year": "2026"},
        )

        self.assertContains(response, canonical.public_path)
        self.assertContains(response, duplicate.public_path)

    def test_finished_filter_shows_recovered_canonical_and_confirmed_winner(self):
        canonical = self._event(
            "recovered-finished",
            name="已恢复赛事",
            status=models.RaceEventStatus.FINISHED,
        )
        duplicate = self._event(
            "recovered-finished-duplicate",
            name="不应展示的重复赛事",
            status=models.RaceEventStatus.FINISHED,
        )
        self._winner(canonical, "Official Recovery Winner")
        self._link(duplicate, canonical)

        calendar = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "when": "finished", "year": "2026"},
        )
        detail = self.client.get(canonical.public_path)

        self.assertContains(calendar, "已恢复赛事")
        self.assertContains(calendar, "冠军 Official Recovery Winner")
        self.assertNotContains(calendar, "不应展示的重复赛事")
        self.assertContains(detail, "已结束")
        self.assertContains(detail, "WINNER · 冠军")
        self.assertContains(detail, "Official Recovery Winner")

    def test_cancelled_and_postponed_never_enter_finished_or_show_champion(self):
        cancelled = self._event(
            "recovery-cancelled",
            name="取消赛事",
            status=models.RaceEventStatus.CANCELLED,
        )
        postponed = self._event(
            "recovery-postponed",
            name="延期赛事",
            status=models.RaceEventStatus.POSTPONED,
        )
        # Defensive regression: even stale rows must not create a champion for
        # a non-finished terminal status.
        self._winner(cancelled, "Must Not Be Champion")
        self._winner(postponed, "Also Not Champion")

        finished = self.client.get(
            reverse("public-race-calendar"),
            {"tab": "all", "when": "finished", "year": "2026"},
        )
        cancelled_detail = self.client.get(cancelled.public_path)
        postponed_detail = self.client.get(postponed.public_path)

        self.assertNotContains(finished, cancelled.chinese_name)
        self.assertNotContains(finished, postponed.chinese_name)
        self.assertNotContains(cancelled_detail, "WINNER · 冠军")
        self.assertNotContains(postponed_detail, "WINNER · 冠军")
        self.assertContains(cancelled_detail, "取消")
        self.assertContains(postponed_detail, "延期")

    def test_overdue_blocked_event_does_not_invent_a_champion(self):
        blocked = self._event(
            "recovery-blocked",
            name="仍有证据阻断",
            status=models.RaceEventStatus.SCHEDULED,
            local_date=date(2026, 7, 8),
        )
        response = self.client.get(blocked.public_path)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "WINNER · 冠军")
        self.assertNotContains(response, "赛果已确认")
        self.assertNotContains(response, "正式赛果")

    def test_calendar_canonical_resolution_is_batched_for_40_cards(self):
        for index in range(20):
            canonical = self._event(
                f"query-canonical-{index}",
                name=f"查询正式赛事 {index}",
            )
            duplicate = self._event(
                f"query-duplicate-{index}",
                name=f"查询重复赛事 {index}",
            )
            self._link(duplicate, canonical, suffix=str((index % 9) + 1))
        for index in range(20, 40):
            self._event(
                f"query-single-{index}",
                name=f"查询单一赛事 {index}",
            )

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                reverse("public-race-calendar"),
                {"tab": "all", "year": "2026"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(captured),
            12,
            f"40 张 canonical 赛事卡必须批量解析，实际 SQL={len(captured)}",
        )
        for index in range(20):
            self.assertContains(response, f"查询正式赛事 {index}")
            self.assertNotContains(response, f"查询重复赛事 {index}")
