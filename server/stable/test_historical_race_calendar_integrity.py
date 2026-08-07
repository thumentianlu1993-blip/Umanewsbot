"""历史赛事赛历完整性修复的 Release A application 合同测试。

这些测试刻意覆盖尚未实现的模型、公开路由和查询合同。生产 census、审批 artifact
以及 PostgreSQL 并发约束由后续 integration/PostgreSQL 套件负责，本模块不把本地
fixture 当作生产数据修复证据。
"""

from __future__ import annotations

from datetime import date, time, timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.management import CommandError, call_command, get_commands
from django.db import IntegrityError, models, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventPriority,
    RaceEventStatus,
    RaceEventVisibility,
    RaceGrade,
    RaceSeries,
    RacingRegion,
)


FIXED_TODAY = date(2026, 7, 31)


def _model_or_none(name: str):
    try:
        return apps.get_model("stable", name)
    except LookupError:
        return None


def _event_ids(response) -> list[int]:
    return [
        event.pk
        for group in response.context["groups"]
        for event in group["events"]
    ]


class HistoricalRaceCalendarFixtureMixin:
    event_sequence = 0

    def make_series(
        self,
        *,
        key: str = "calendar-integrity-series",
        region: str = RacingRegion.JAPAN,
    ) -> RaceSeries:
        return RaceSeries.objects.create(
            key=key,
            country_region=region,
            canonical_name_original=f"Series {key}",
            chinese_name=f"系列 {key}",
        )

    def make_event(
        self,
        *,
        event_date: date,
        name: str,
        region: str = RacingRegion.JAPAN,
        normalized_grade: str = RaceGrade.G1,
        priority: str = RaceEventPriority.P2,
        is_featured: bool = False,
        status: str = RaceEventStatus.FINISHED,
        local_start_time: time | None = None,
        visibility: str = RaceEventVisibility.PUBLISHED,
        data_quality: str = RaceEventDataQuality.COMPLETE,
        series: RaceSeries | None = None,
        edition_year: int | None = None,
        source_refs: dict | None = None,
    ) -> RaceEvent:
        self.event_sequence += 1
        values = {
            "year": event_date.year,
            "slug": f"calendar-integrity-{event_date.isoformat()}-{self.event_sequence}",
            "original_name": name,
            "chinese_name": name,
            "country_region": region,
            "racecourse": "测试马场",
            "grade_text": normalized_grade,
            "normalized_grade": normalized_grade,
            "surface": "turf",
            "local_date": event_date,
            "local_start_time": local_start_time,
            "priority": priority,
            "is_featured": is_featured,
            "status": status,
            "visibility_status": visibility,
            "data_quality_status": data_quality,
            "race_series": series,
            "source_refs": source_refs or {},
        }
        if edition_year is not None and any(
            field.name == "edition_year" for field in RaceEvent._meta.fields
        ):
            values["edition_year"] = edition_year
        return RaceEvent.objects.create(**values)


class RaceEventEditionYearContractTests(
    HistoricalRaceCalendarFixtureMixin,
    TestCase,
):
    def assert_release_a_field(self, model, field_name: str):
        try:
            return model._meta.get_field(field_name)
        except FieldDoesNotExist:
            self.fail(
                f"Release A RED: {model.__name__}.{field_name} 尚未实现"
            )

    def test_release_a_adds_nullable_edition_year(self):
        field = self.assert_release_a_field(RaceEvent, "edition_year")

        self.assertIsInstance(field, models.PositiveSmallIntegerField)
        self.assertTrue(field.null)

    def test_known_local_date_rejects_mismatched_public_year(self):
        event = RaceEvent(
            year=2025,
            slug="hong-kong-cup-wrong-public-year",
            original_name="Hong Kong Cup",
            chinese_name="香港杯",
            country_region=RacingRegion.HONG_KONG,
            racecourse="Sha Tin",
            grade_text="G1",
            normalized_grade=RaceGrade.G1,
            surface="turf",
            local_date=date(2024, 12, 8),
        )
        edition_field = self.assert_release_a_field(RaceEvent, "edition_year")
        self.assertTrue(edition_field.null)
        event.edition_year = 2024

        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_ordinary_hong_kong_season_uses_natural_year_for_both_years(self):
        self.assert_release_a_field(RaceEvent, "edition_year")
        series = self.make_series(
            key="hong-kong-cup-series",
            region=RacingRegion.HONG_KONG,
        )
        event = self.make_event(
            event_date=date(2024, 12, 8),
            name="Hong Kong Cup",
            region=RacingRegion.HONG_KONG,
            series=series,
            edition_year=2024,
        )
        target = HistoricalRaceEventTarget(
            race_series=series,
            year=2024,
            country_region=RacingRegion.HONG_KONG,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=event,
        )

        self.assertEqual(event.year, 2024)
        self.assertEqual(event.edition_year, 2024)
        event.full_clean()
        target.full_clean()

    def test_legitimate_delay_links_target_by_edition_year(self):
        self.assert_release_a_field(RaceEvent, "edition_year")
        series = self.make_series(key="delayed-edition-series")
        event = self.make_event(
            event_date=date(2026, 1, 10),
            name="Delayed 2025 Edition",
            series=series,
            edition_year=2025,
            source_refs={
                "cross_year_evidence": {
                    "actual_year": 2026,
                    "reason": "official_reschedule",
                    "authority_url": "https://official.example.test/reschedule",
                    "approved": True,
                }
            },
        )
        target = HistoricalRaceEventTarget(
            race_series=series,
            year=2025,
            country_region=series.country_region,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=event,
        )

        target.full_clean()

    def test_target_rejects_public_year_match_when_edition_year_differs(self):
        self.assert_release_a_field(RaceEvent, "edition_year")
        series = self.make_series(key="wrong-edition-target-series")
        event = self.make_event(
            event_date=date(2026, 1, 10),
            name="2025 Edition Held In 2026",
            series=series,
            edition_year=2025,
            source_refs={
                "cross_year_evidence": {
                    "actual_year": 2026,
                    "reason": "official_reschedule",
                    "authority_url": "https://official.example.test/reschedule",
                    "approved": True,
                }
            },
        )
        target = HistoricalRaceEventTarget(
            race_series=series,
            year=2026,
            country_region=series.country_region,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=event,
        )

        with self.assertRaises(ValidationError):
            target.full_clean()


class HistoricalTargetSupersessionAndReceiptTests(
    HistoricalRaceCalendarFixtureMixin,
    TestCase,
):
    def assert_model(self, name: str):
        model = _model_or_none(name)
        self.assertIsNotNone(
            model,
            f"Release A RED: stable.{name} 尚未实现",
        )
        return model

    def assert_field(self, model, name: str):
        try:
            return model._meta.get_field(name)
        except FieldDoesNotExist:
            self.fail(f"Release A RED: {model.__name__}.{name} 尚未实现")

    def test_target_exposes_auditable_supersession_fields_and_status(self):
        choices = {
            value
            for value, _label in HistoricalRaceEventTarget._meta.get_field(
                "resolution_status"
            ).choices
        }
        self.assertIn("superseded", choices)
        superseded_by = self.assert_field(
            HistoricalRaceEventTarget,
            "superseded_by",
        )
        self.assertEqual(superseded_by.remote_field.model, HistoricalRaceEventTarget)
        self.assertTrue(superseded_by.null)
        self.assert_field(HistoricalRaceEventTarget, "superseded_at")
        manifest = self.assert_field(
            HistoricalRaceEventTarget,
            "supersession_manifest_sha256",
        )
        self.assertEqual(manifest.max_length, 64)

    def test_superseded_target_must_be_detached_and_audited(self):
        self.assert_field(HistoricalRaceEventTarget, "superseded_by")
        series = self.make_series(key="superseded-target-series")
        survivor = HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=2024,
            country_region=series.country_region,
        )
        event = self.make_event(
            event_date=date(2025, 1, 1),
            name="Duplicate Event",
        )
        duplicate = HistoricalRaceEventTarget(
            race_series=series,
            year=2024,
            country_region=series.country_region,
            resolution_status="superseded",
            event=event,
            superseded_by=survivor,
            superseded_at=timezone.now(),
            supersession_manifest_sha256="a" * 64,
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

        duplicate.event = None
        duplicate.full_clean()

    def test_repair_receipt_schema_is_exactly_once_and_auditable(self):
        receipt = self.assert_model("HistoricalRaceCalendarRepairReceipt")
        manifest = self.assert_field(receipt, "manifest_sha256")
        self.assertTrue(manifest.unique)
        actor = self.assert_field(receipt, "actor")
        self.assertEqual(actor.remote_field.on_delete, models.PROTECT)
        required_fields = {
            "approval_sha256",
            "action_scope_sha256",
            "status",
            "rollback_sha256",
            "applied_at",
            "verified_at",
            "rolled_back_at",
            "verifier_result_sha256",
        }
        self.assertTrue(
            required_fields.issubset(
                {field.name for field in receipt._meta.get_fields()}
            )
        )
        status_choices = {
            value
            for value, _label in receipt._meta.get_field("status").choices
        }
        self.assertEqual(
            status_choices,
            {
                "applied",
                "verified",
                "verification_failed",
                "rolled_back",
            },
        )

    def test_repair_receipt_rejects_duplicate_manifest(self):
        receipt = self.assert_model("HistoricalRaceCalendarRepairReceipt")
        actor = get_user_model().objects.create_user(
            username="repair-receipt-actor"
        )
        values = {
            "manifest_sha256": "c" * 64,
            "approval_sha256": "d" * 64,
            "action_scope_sha256": "e" * 64,
            "actor": actor,
            "status": "applied",
            "rollback_sha256": "f" * 64,
            "applied_at": timezone.now(),
        }
        receipt.objects.create(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            receipt.objects.create(**values)

    def test_apply_command_is_registered(self):
        self.assertIn(
            "repair_historical_race_calendar_integrity",
            get_commands(),
            "Release A RED: census/apply 管理命令尚未注册",
        )

    def test_apply_rejects_missing_independent_approval(self):
        with self.assertRaisesMessage(CommandError, "approval"):
            call_command(
                "repair_historical_race_calendar_integrity",
                "--apply",
                "--artifact",
                "/tmp/nonexistent-integrity-manifest.json",
                "--expected-manifest-sha256",
                "a" * 64,
                "--actor",
                "calendar-integrity-test",
                "--confirm-reviewed-artifact",
            )


@override_settings(SITE_URL="https://example.test", RACE_EVENT_SITEMAP_SHARD_SIZE=100)
class RaceEventPublicPathRegistryTests(
    HistoricalRaceCalendarFixtureMixin,
    TestCase,
):
    def registry_model(self):
        registry = _model_or_none("RaceEventPublicPath")
        self.assertIsNotNone(
            registry,
            "Release A RED: 统一 RaceEventPublicPath registry 尚未实现",
        )
        return registry

    def registry_row(
        self,
        *,
        event: RaceEvent,
        year: int,
        slug: str,
        path_kind: str,
        actor=None,
    ):
        values = {
            "event": event,
            "year": year,
            "slug": slug,
            "path_kind": path_kind,
            "reason": "calendar_integrity_test",
            "manifest_sha256": "b" * 64,
        }
        if actor is not None:
            values["created_by"] = actor
        if path_kind == "canonical":
            row = self.registry_model().objects.get(
                event=event, path_kind="canonical"
            )
            row.reason = values["reason"]
            row.manifest_sha256 = values["manifest_sha256"]
            row.created_by = actor
            row.save(
                update_fields={
                    "reason",
                    "manifest_sha256",
                    "created_by",
                    "updated_at",
                }
            )
            return row
        return self.registry_model().objects.create(**values)

    def test_registry_has_global_path_and_per_event_canonical_constraints(self):
        registry = self.registry_model()
        fields = {field.name for field in registry._meta.get_fields()}
        self.assertTrue(
            {
                "year",
                "slug",
                "event",
                "path_kind",
                "reason",
                "manifest_sha256",
                "created_by",
                "created_at",
            }.issubset(fields)
        )
        constraints = registry._meta.constraints
        self.assertTrue(
            any(
                isinstance(constraint, models.UniqueConstraint)
                and tuple(constraint.fields) == ("year", "slug")
                for constraint in constraints
            ),
            "registry 必须全局唯一占用 (year, slug)",
        )
        self.assertTrue(
            any(
                isinstance(constraint, models.UniqueConstraint)
                and tuple(constraint.fields) == ("event",)
                and constraint.condition is not None
                for constraint in constraints
            ),
            "registry 必须保证每个 event 仅一个 canonical path",
        )

    def test_legacy_path_redirects_permanently_to_canonical_path(self):
        actor = get_user_model().objects.create_user(username="path-registry-test")
        event = self.make_event(
            event_date=date(2024, 12, 8),
            name="Hong Kong Cup",
            region=RacingRegion.HONG_KONG,
        )
        self.registry_row(
            event=event,
            year=2024,
            slug=event.slug,
            path_kind="canonical",
            actor=actor,
        )
        self.registry_row(
            event=event,
            year=2025,
            slug="hong-kong-cup-2025",
            path_kind="legacy",
            actor=actor,
        )

        response = self.client.get("/races/2025/hong-kong-cup-2025/")
        canonical = self.client.get(event.public_path)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], event.public_path)
        self.assertEqual(canonical.status_code, 200)

    def test_legacy_path_does_not_redirect_to_draft_event(self):
        actor = get_user_model().objects.create_user(username="draft-path-test")
        event = self.make_event(
            event_date=date(2024, 12, 8),
            name="Draft Hong Kong Cup",
            region=RacingRegion.HONG_KONG,
            visibility=RaceEventVisibility.DRAFT,
        )
        self.registry_row(
            event=event,
            year=2024,
            slug=event.slug,
            path_kind="canonical",
            actor=actor,
        )
        self.registry_row(
            event=event,
            year=2025,
            slug="draft-hong-kong-cup-2025",
            path_kind="legacy",
            actor=actor,
        )

        response = self.client.get("/races/2025/draft-hong-kong-cup-2025/")

        self.assertEqual(response.status_code, 404)

    def test_sitemap_contains_only_canonical_registry_path(self):
        actor = get_user_model().objects.create_user(username="sitemap-path-test")
        event = self.make_event(
            event_date=date(2024, 12, 8),
            name="Sitemap Hong Kong Cup",
            region=RacingRegion.HONG_KONG,
        )
        self.registry_row(
            event=event,
            year=2024,
            slug=event.slug,
            path_kind="canonical",
            actor=actor,
        )
        self.registry_row(
            event=event,
            year=2025,
            slug="sitemap-hong-kong-cup-2025",
            path_kind="legacy",
            actor=actor,
        )

        response = self.client.get(
            reverse("public-race-sitemap-shard", args=[1])
        )
        xml = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(event.public_path, xml)
        self.assertNotIn("/races/2025/sitemap-hong-kong-cup-2025/", xml)


@override_settings(TIME_ZONE="Asia/Shanghai")
class HistoricalKeyRaceFilterTests(
    HistoricalRaceCalendarFixtureMixin,
    TestCase,
):
    def setUp(self):
        super().setUp()
        today_patcher = patch(
            "stable.views.timezone.localdate",
            return_value=FIXED_TODAY,
        )
        today_patcher.start()
        self.addCleanup(today_patcher.stop)

    def test_historical_key_uses_g1_g2_families_and_excludes_featured_g3(self):
        expected = {
            RaceGrade.G1: "Historical G1",
            RaceGrade.JG1: "Historical JG1",
            RaceGrade.JPN1: "Historical JPN1",
            RaceGrade.G2: "Historical G2",
            RaceGrade.JG2: "Historical JG2",
            RaceGrade.JPN2: "Historical JPN2",
        }
        for grade, name in expected.items():
            self.make_event(
                event_date=date(2024, 6, 1),
                name=name,
                normalized_grade=grade,
                priority=RaceEventPriority.P2,
            )
        self.make_event(
            event_date=date(2024, 6, 2),
            name="Historical Featured G3",
            normalized_grade=RaceGrade.G3,
            priority=RaceEventPriority.P0,
            is_featured=True,
        )

        response = self.client.get(
            reverse("public-race-calendar"),
            {"year": "2024", "tab": "key"},
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        for name in expected.values():
            self.assertIn(name, html)
        self.assertNotIn("Historical Featured G3", html)

    def test_historical_key_and_grade_filters_use_intersection(self):
        self.make_event(
            event_date=date(2024, 6, 1),
            name="Intersection G1",
            normalized_grade=RaceGrade.G1,
        )
        self.make_event(
            event_date=date(2024, 6, 2),
            name="Intersection G2",
            normalized_grade=RaceGrade.G2,
        )
        self.make_event(
            event_date=date(2024, 6, 3),
            name="Intersection G3",
            normalized_grade=RaceGrade.G3,
            priority=RaceEventPriority.P0,
        )

        g1_response = self.client.get(
            reverse("public-race-calendar"),
            {"year": "2024", "tab": "key", "grade": "g1"},
        )
        g3_response = self.client.get(
            reverse("public-race-calendar"),
            {"year": "2024", "tab": "key", "grade": "g3"},
        )

        self.assertContains(g1_response, "Intersection G1")
        self.assertNotContains(g1_response, "Intersection G2")
        self.assertNotContains(g1_response, "Intersection G3")
        self.assertNotContains(g3_response, "Intersection G3")

    def test_current_year_key_preserves_operational_priority_semantics(self):
        self.make_event(
            event_date=date(2026, 8, 1),
            name="Current Operational P0",
            normalized_grade=RaceGrade.G3,
            priority=RaceEventPriority.P0,
        )
        self.make_event(
            event_date=date(2026, 8, 2),
            name="Current Operational Featured",
            normalized_grade=RaceGrade.G3,
            is_featured=True,
        )
        self.make_event(
            event_date=date(2026, 8, 3),
            name="Current Grade Only G1",
            normalized_grade=RaceGrade.G1,
            priority=RaceEventPriority.P2,
        )

        response = self.client.get(
            reverse("public-race-calendar"),
            {"year": "2026", "tab": "key"},
        )

        self.assertContains(response, "Current Operational P0")
        self.assertContains(response, "Current Operational Featured")
        self.assertNotContains(response, "Current Grade Only G1")


@override_settings(TIME_ZONE="Asia/Shanghai")
class HistoricalRaceCalendarPaginationTests(
    HistoricalRaceCalendarFixtureMixin,
    TestCase,
):
    def setUp(self):
        super().setUp()
        today_patcher = patch(
            "stable.views.timezone.localdate",
            return_value=FIXED_TODAY,
        )
        today_patcher.start()
        self.addCleanup(today_patcher.stop)

    def make_paged_events(self, *, count: int = 95, prefix: str = "Paged"):
        created = []
        for index in range(count):
            created.append(
                self.make_event(
                    event_date=date(2024, 1, 1) + timedelta(days=index // 3),
                    local_start_time=(
                        None
                        if index % 5 == 0
                        else time(12 + (index % 3), index % 60)
                    ),
                    name=f"{prefix} {index:03d}",
                    normalized_grade=RaceGrade.G1,
                    priority=RaceEventPriority.P2,
                )
            )
        return created

    def test_year_query_traverses_40_40_15_without_duplicates_or_omissions(self):
        created = self.make_paged_events()
        expected_ids = {event.pk for event in created}
        url = reverse("public-race-calendar") + "?tab=all&year=2024"
        page_sizes = []
        seen_ids = []
        previous_urls = []

        while url:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            ids = _event_ids(response)
            page_sizes.append(len(ids))
            seen_ids.extend(ids)
            previous_urls.append(response.context["previous_url"])
            url = response.context["next_url"]

        self.assertEqual(page_sizes, [40, 40, 15])
        self.assertEqual(len(seen_ids), len(set(seen_ids)))
        self.assertEqual(set(seen_ids), expected_ids)
        self.assertTrue(previous_urls[-1])

        previous = self.client.get(previous_urls[-1])
        self.assertEqual(_event_ids(previous), seen_ids[40:80])

    def test_search_pagination_preserves_every_filter(self):
        self.make_paged_events(count=45, prefix="Filter Keeper")
        response = self.client.get(
            reverse("public-race-calendar"),
            {
                "tab": "all",
                "year": "2024",
                "q": "Filter Keeper",
                "region": RacingRegion.JAPAN,
                "grade": "g1",
                "when": "finished",
            },
        )

        next_url = response.context["next_url"]
        self.assertTrue(next_url)
        params = parse_qs(urlparse(next_url).query)
        self.assertEqual(params["tab"], ["all"])
        self.assertEqual(params["year"], ["2024"])
        self.assertEqual(params["q"], ["Filter Keeper"])
        self.assertEqual(params["region"], [RacingRegion.JAPAN])
        self.assertEqual(params["grade"], ["g1"])
        self.assertEqual(params["when"], ["finished"])
        self.assertIn("cursor", params)
        self.assertIn("direction", params)

        second = self.client.get(next_url)
        self.assertEqual(len(_event_ids(second)), 5)

    def test_search_without_year_paginates_across_natural_years(self):
        for index in range(45):
            event_year = 2023 if index < 20 else 2024
            self.make_event(
                event_date=date(event_year, 1, 1)
                + timedelta(days=index % 20),
                name=f"Cross Year Search {index:03d}",
                normalized_grade=RaceGrade.G2,
            )
        url = (
            reverse("public-race-calendar")
            + "?tab=all&q=Cross+Year+Search"
        )
        seen_ids = []
        page_sizes = []

        while url:
            response = self.client.get(url)
            ids = _event_ids(response)
            page_sizes.append(len(ids))
            seen_ids.extend(ids)
            url = response.context["next_url"]

        self.assertEqual(page_sizes, [40, 5])
        self.assertEqual(len(seen_ids), 45)
        self.assertEqual(len(set(seen_ids)), 45)

    def test_invalid_cursor_and_direction_fall_back_to_filtered_first_page(self):
        self.make_paged_events(count=45, prefix="Invalid Cursor")
        filters = {
            "tab": "all",
            "year": "2024",
            "q": "Invalid Cursor",
            "region": RacingRegion.JAPAN,
        }
        first = self.client.get(reverse("public-race-calendar"), filters)
        tampered = self.client.get(
            reverse("public-race-calendar"),
            {
                **filters,
                "cursor": "v1.tampered-signature",
                "direction": "future",
            },
        )

        self.assertEqual(tampered.status_code, 200)
        self.assertEqual(_event_ids(tampered), _event_ids(first))
        self.assertEqual(tampered.context["filters"]["cursor"], "")
        self.assertEqual(tampered.context["filters"]["direction"], "")
