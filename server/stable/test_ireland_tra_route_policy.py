"""新地区 TRA 路线注册的 standing policy 校验测试（阶段 3c）。

范围：ireland 直接注册 TRA 路线（allowed_region_codes 已含 ire）；
australia/germany/middle_east 的 TRA 扩展属 G3（扩大付费调用覆盖），不在本文件。
"""
from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable.services import race_data_sync_enrollment
from stable.services import race_data_sync_pipeline
from stable.services import race_data_sync_providers
from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS


REPO_ROOT = Path(__file__).resolve().parents[2]
STANDING_POLICY = REPO_ROOT / "runtime" / "policies" / "race_data_sync" / "standing_policy.json"
TRA_REGISTRY = REPO_ROOT / "runtime" / "policies" / "race_live" / "source_registry_the_racing_api_free.json"

# 与生产钉扎一致的 roster 闭集（registry 续期发布包 #222 的两枚 SHA）。
# 渲染或消费 standing policy 时 route_digest 只有在这组闭集下才等于生产值 3e1af727…。
RENDER_SETTINGS = dict(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=(
        "the_racing_api",
        "sporting_life",
        "zeturf",
        "horse_racing_nation",
    ),
    RACE_DATA_SYNC_ENABLED_REGIONS=(
        "france",
        "hong_kong",
        "ireland",
        "japan_jra",
        "japan_nar",
        "united_kingdom",
        "united_states",
    ),
    RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_ROSTER_ALLOWED_FIELDS),
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
    RACE_LIVE_TRA_REGISTRY_SHA256=(
        "0e1cdff89052b7b5f482b4761f1e39e3f38eefdf30405ae6a5d45b64e737b322"
    ),
    RACE_DATA_SYNC_REFERENCE_REGISTRY_SHA256=(
        "740a93774927765f9c848cc97e4b87b78ab36d473c4c3e2e644d56a6f856cff2"
    ),
)

# (country_region, provider, region_code, identity_namespace, enrollment_eligible, tiebreak_order)
# 既有 13 条路线一条不丢；唯一新增是 ireland 一等路线（other/ireland 存量兼容行保留）。
EXPECTED_RENDERED_ROUTES = {
    ("france", "the_racing_api", "france", "the_racing_api-race-v1", True, 1),
    ("france", "zeturf", "france", "zeturf", False, 2),
    ("france", "zeturf", "france", "zeturf-race-v1", False, 3),
    ("hong_kong", "the_racing_api", "hong_kong", "the_racing_api-race-v1", True, 1),
    ("ireland", "the_racing_api", "ireland", "the_racing_api-race-v1", True, 1),
    ("japan", "the_racing_api", "japan_jra", "the_racing_api-race-v1", True, 1),
    ("japan", "the_racing_api", "japan_nar", "the_racing_api-race-v1", True, 2),
    ("other", "the_racing_api", "ireland", "the_racing_api-race-v1", True, 1),
    ("united_kingdom", "sporting_life", "united_kingdom", "sporting_life", False, 2),
    ("united_kingdom", "sporting_life", "united_kingdom", "sporting_life-race-v1", False, 3),
    ("united_kingdom", "the_racing_api", "united_kingdom", "the_racing_api-race-v1", True, 1),
    ("united_states", "horse_racing_nation", "united_states", "horse_racing_nation", False, 2),
    ("united_states", "horse_racing_nation", "united_states", "horse_racing_nation-race-v1", False, 3),
    ("united_states", "the_racing_api", "united_states", "the_racing_api-race-v1", True, 1),
}


class IrelandTraRouteRegistrationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy = json.loads(STANDING_POLICY.read_text(encoding="utf-8"))
        cls.registry = json.loads(TRA_REGISTRY.read_text(encoding="utf-8"))

    def test_ireland_has_enrollment_eligible_tra_route(self):
        parsed = race_data_sync_enrollment.parse_standing_policy(self.policy)
        ireland_routes = [
            route
            for route in parsed.routes
            if route.country_region == "ireland" and route.provider == "the_racing_api"
        ]
        self.assertEqual(len(ireland_routes), 1)
        route = ireland_routes[0]
        self.assertEqual(route.region_code, "ireland")
        self.assertEqual(route.identity_namespace, "the_racing_api-race-v1")
        self.assertTrue(route.enrollment_eligible)
        self.assertEqual(route.tiebreak_order, 1)

    def test_ireland_region_code_allowed_by_tra_registry(self):
        self.assertEqual(
            self.registry["allowed_region_codes"].get("ireland"),
            "ire",
            "TRA free registry 已允许 ire；若被移除则 ireland 路线失锚",
        )

    def test_new_region_tra_expansion_not_present_without_g3(self):
        # 澳/德/中东不在 TRA free allowed_region_codes 内：扩大付费调用覆盖属 G3，
        # 未经用户批准不得在 standing policy 出现这些地区的 TRA enrollment 路线
        allowed = set(self.registry["allowed_region_codes"])
        parsed = race_data_sync_enrollment.parse_standing_policy(self.policy)
        for route in parsed.routes:
            if route.provider != "the_racing_api":
                continue
            with self.subTest(region=route.country_region):
                if route.country_region in {"australia", "germany", "middle_east"}:
                    self.assertIn(
                        route.country_region,
                        allowed,
                        f"{route.country_region} 的 TRA 路线未经 G3 批准",
                    )

    def test_standing_policy_still_parses_cleanly(self):
        parsed = race_data_sync_enrollment.parse_standing_policy(self.policy)
        self.assertTrue(parsed.policy_id)
        self.assertGreater(len(parsed.routes), 5)


class IrelandContractRegionMappingTests(SimpleTestCase):
    """合同地区 -> 赛事地区映射：ireland 一等化，other 存量桶保留兼容。"""

    def test_ireland_contract_region_maps_to_first_class_ireland(self):
        self.assertEqual(
            race_data_sync_pipeline._EVENT_REGION_BY_CONTRACT_REGION["ireland"],
            models.RacingRegion.IRELAND,
        )

    def test_ireland_accepts_legacy_other_bucket_for_existing_events(self):
        accepted = race_data_sync_pipeline._EVENT_REGIONS_BY_CONTRACT_REGION["ireland"]
        self.assertEqual(accepted[0], models.RacingRegion.IRELAND)
        self.assertIn(models.RacingRegion.OTHER, accepted)

    def test_other_contract_regions_keep_single_mapping(self):
        expected = {
            "hong_kong": models.RacingRegion.HONG_KONG,
            "japan_jra": models.RacingRegion.JAPAN,
            "japan_nar": models.RacingRegion.JAPAN,
            "united_kingdom": models.RacingRegion.UNITED_KINGDOM,
            "france": models.RacingRegion.FRANCE,
            "united_states": models.RacingRegion.UNITED_STATES,
        }
        for contract_region, event_region in expected.items():
            with self.subTest(contract_region=contract_region):
                self.assertEqual(
                    race_data_sync_pipeline._EVENT_REGION_BY_CONTRACT_REGION[
                        contract_region
                    ],
                    event_region,
                )
                self.assertEqual(
                    race_data_sync_pipeline._EVENT_REGIONS_BY_CONTRACT_REGION[
                        contract_region
                    ],
                    (event_region,),
                )


class IrelandEventContractRegionTests(SimpleTestCase):
    """providers._event_contract_region：一等 ireland 与存量 other+标记都解析到 ireland。"""

    def _event(self, country_region, source_refs=None):
        return SimpleNamespace(
            country_region=country_region,
            source_refs=source_refs or {},
        )

    def test_first_class_ireland_event_resolves_ireland_contract(self):
        event = self._event(models.RacingRegion.IRELAND)
        self.assertEqual(
            race_data_sync_providers._event_contract_region(event), "ireland"
        )

    def test_legacy_other_event_with_ireland_marker_still_resolves(self):
        event = self._event(
            models.RacingRegion.OTHER, {"race_data_region": "ireland"}
        )
        self.assertEqual(
            race_data_sync_providers._event_contract_region(event), "ireland"
        )

    def test_unmarked_other_event_still_fail_closed(self):
        event = self._event(models.RacingRegion.OTHER)
        self.assertEqual(race_data_sync_providers._event_contract_region(event), "")


class IrelandTraRouteRenderTests(SimpleTestCase):
    """渲染器必须同时产出 ireland 一等路线与 other 存量兼容路线，且与 policy 文件一致。"""

    def _render(self) -> str:
        policy = json.loads(STANDING_POLICY.read_text(encoding="utf-8"))
        output = StringIO()
        with override_settings(**RENDER_SETTINGS):
            call_command(
                "render_race_data_sync_standing_policy",
                policy_id=policy["policy_id"],
                approved_by=policy["approved_by"],
                approved_at=policy["approved_at"],
                valid_from=policy["valid_from"],
                valid_until=policy["valid_until"],
                stdout=output,
            )
        return output.getvalue()

    def test_renderer_emits_first_class_ireland_and_keeps_legacy_other_route(self):
        payload = json.loads(self._render())
        tra_ireland = [
            route
            for route in payload["routes"]
            if route["provider"] == "the_racing_api"
            and route["region_code"] == "ireland"
        ]
        by_region = {route["country_region"]: route for route in tra_ireland}
        self.assertEqual(set(by_region), {"ireland", "other"})
        first_class = by_region["ireland"]
        legacy = by_region["other"]
        self.assertTrue(first_class["enrollment_eligible"])
        self.assertEqual(first_class["tiebreak_order"], 1)
        self.assertEqual(legacy["tiebreak_order"], 1)
        self.assertEqual(first_class["route_digest"], legacy["route_digest"])
        self.assertEqual(
            first_class["data_kinds"], ["race_time", "racecard", "result"]
        )

    def test_renderer_keeps_all_existing_routes_plus_ireland(self):
        payload = json.loads(self._render())
        rendered = {
            (
                route["country_region"],
                route["provider"],
                route["region_code"],
                route["identity_namespace"],
                route["enrollment_eligible"],
                route["tiebreak_order"],
            )
            for route in payload["routes"]
        }
        self.assertEqual(rendered, EXPECTED_RENDERED_ROUTES)

    def test_standing_policy_file_matches_renderer_output(self):
        self.assertEqual(
            self._render(),
            STANDING_POLICY.read_text(encoding="utf-8"),
            "standing_policy.json 必须由渲染器产出（单行 sort_keys JSON）；"
            "不一致时以渲染器为准重渲文件",
        )


class IrelandTraEnrollmentCensusTests(TestCase):
    """登记普查：一等 ireland 赛事与存量 other 赛事都能命中 TRA ireland 路线。"""

    def _event(self, *, slug, country_region, source_refs=None):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=f"Census {slug}",
            country_region=country_region,
            racecourse="Curragh",
            race_datetime=datetime(2026, 10, 6, 12, 0, tzinfo=dt_timezone.utc),
            timezone_name="Europe/Dublin",
            local_date=date(2026, 10, 6),
            status=models.RaceEventStatus.SCHEDULED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            source_refs=source_refs or {},
        )

    def _census(self):
        return race_data_sync_enrollment.build_race_data_enrollment_census(
            standing_policy=json.loads(STANDING_POLICY.read_text(encoding="utf-8")),
            cutoff=datetime(2026, 10, 1, 0, 0, tzinfo=dt_timezone.utc),
            horizon_days=30,
        )

    @override_settings(**RENDER_SETTINGS)
    def test_first_class_ireland_event_matches_tra_route(self):
        event = self._event(
            slug="ireland-first-class",
            country_region=models.RacingRegion.IRELAND,
        )
        census = self._census()
        entry = next(item for item in census.entries if item.event_id == event.pk)
        self.assertEqual(entry.provider, "the_racing_api")
        self.assertEqual(entry.region_code, "ireland")
        self.assertNotEqual(entry.reason_code, "trusted_route_missing")
        self.assertEqual(entry.classification, "awaiting_source_window")

    @override_settings(**RENDER_SETTINGS)
    def test_legacy_other_ireland_event_keeps_tra_route(self):
        event = self._event(
            slug="ireland-legacy-other",
            country_region=models.RacingRegion.OTHER,
            source_refs={"race_data_region": "ireland"},
        )
        census = self._census()
        entry = next(item for item in census.entries if item.event_id == event.pk)
        self.assertEqual(entry.provider, "the_racing_api")
        self.assertEqual(entry.region_code, "ireland")
        self.assertNotEqual(entry.reason_code, "trusted_route_missing")
        self.assertEqual(entry.classification, "awaiting_source_window")
