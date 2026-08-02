from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import importlib
import json
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable.services import race_events
from stable.services import race_live_fixtures
from stable.services import race_live_racecard_sync
from stable.services import race_live_runner


REPO_ROOT = Path(__file__).resolve().parents[2]
TRA_REGISTRY = (
    REPO_ROOT
    / "docs"
    / "changes"
    / "realtime-race-results"
    / "source_registry_the_racing_api_free.json"
)
SHA_A = "a" * 64


class TheRacingApiRegistryV2ContractTests(SimpleTestCase):
    def _payload(self):
        return json.loads(TRA_REGISTRY.read_text(encoding="utf-8"))

    def test_registry_v2_has_exact_five_region_codes_and_route_contracts(self):
        payload = self._payload()

        self.assertEqual(payload.get("schema_version"), 2)
        self.assertEqual(
            payload.get("allowed_region_codes"),
            {
                "united_kingdom": "gb",
                "france": "fr",
                "hong_kong": "hk",
                "japan": "jpn",
                "united_states": "usa",
            },
        )
        self.assertEqual(
            payload.get("route_contracts"),
            {
                "racecards_free": {
                    "path": "/v1/racecards/free",
                    "day": ["today", "tomorrow"],
                    "limit": [500],
                    "skip": [0],
                },
                "results_today_free": {
                    "path": "/v1/results/today/free",
                    "limit": [50],
                    "skip": list(range(0, 500, 50)),
                },
            },
        )

    def test_url_builder_rejects_unknown_regions_and_noncontract_pagination(self):
        builder = getattr(
            importlib.import_module("stable.services.race_live_source_proof"),
            "build_the_racing_api_route_url",
            None,
        )
        self.assertTrue(
            callable(builder),
            "TRA registry v2 URL builder 尚未实现",
        )
        payload = self._payload()

        self.assertEqual(
            builder(
                registry=payload,
                route_name="racecards_free",
                region=models.RacingRegion.FRANCE,
                day="today",
                limit=500,
                skip=0,
            ),
            (
                "https://api.theracingapi.com/v1/racecards/free"
                "?day=today&region_codes=fr&limit=500&skip=0"
            ),
        )
        self.assertEqual(
            builder(
                registry=payload,
                route_name="results_today_free",
                region=models.RacingRegion.JAPAN,
                limit=50,
                skip=450,
            ),
            (
                "https://api.theracingapi.com/v1/results/today/free"
                "?limit=50&skip=450"
            ),
        )
        for overrides in (
            {"region": "other"},
            {"day": "yesterday"},
            {"skip": 25},
            {"skip": 500},
            {"limit": 500},
        ):
            values = {
                "registry": payload,
                "route_name": "results_today_free",
                "region": models.RacingRegion.JAPAN,
                "limit": 50,
                "skip": 0,
            }
            values.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaises((ValueError, PermissionError)):
                    builder(**values)


class RaceLiveTimezoneAndRacecardRefreshContractTests(SimpleTestCase):
    def test_five_region_timezone_contract_keeps_us_event_specific(self):
        mapping = getattr(
            race_live_racecard_sync,
            "RACE_LIVE_REGION_TIMEZONES",
            None,
        )
        self.assertEqual(
            mapping,
            {
                models.RacingRegion.UNITED_KINGDOM: "Europe/London",
                models.RacingRegion.FRANCE: "Europe/Paris",
                models.RacingRegion.HONG_KONG: "Asia/Hong_Kong",
                models.RacingRegion.JAPAN: "Asia/Tokyo",
                models.RacingRegion.UNITED_STATES: None,
            },
        )

    def test_off_time_normalizer_uses_event_timezone_and_rejects_cross_date(self):
        normalizer = getattr(
            race_live_racecard_sync,
            "normalize_race_live_source_off_time",
            None,
        )
        self.assertTrue(
            callable(normalizer),
            "五地区 off time normalizer 尚未实现",
        )

        new_york = normalizer(
            source_off_time="2026-07-20T18:00:00+00:00",
            event_timezone_name="America/New_York",
            expected_local_date=date(2026, 7, 20),
        )
        los_angeles = normalizer(
            source_off_time="2026-07-20T18:00:00+00:00",
            event_timezone_name="America/Los_Angeles",
            expected_local_date=date(2026, 7, 20),
        )
        self.assertEqual(new_york.tzinfo.key, "America/New_York")
        self.assertEqual(los_angeles.tzinfo.key, "America/Los_Angeles")
        self.assertNotEqual(new_york.timetz(), los_angeles.timetz())

        with self.assertRaises((ValueError, PermissionError)):
            normalizer(
                source_off_time="2026-07-20T18:00:00",
                event_timezone_name="America/New_York",
                expected_local_date=date(2026, 7, 20),
            )
        with self.assertRaises((ValueError, PermissionError)):
            normalizer(
                source_off_time="2026-07-20T01:00:00+00:00",
                event_timezone_name="America/Los_Angeles",
                expected_local_date=date(2026, 7, 20),
            )

    def test_pre_off_refresh_is_a_first_class_racecard_capability(self):
        refresh = getattr(
            race_live_racecard_sync,
            "refresh_race_live_racecard",
            None,
        )
        self.assertTrue(
            callable(refresh),
            "赛前 immutable racecard refresh 尚未实现",
        )

    def test_refresh_merge_preserves_missing_runner_as_declared_source_gap(self):
        merge = getattr(
            race_live_racecard_sync,
            "merge_race_live_racecard_participants",
            None,
        )
        self.assertTrue(
            callable(merge),
            "racecard participant source-gap merge 尚未实现",
        )
        previous = (
            {
                "external_runner_id": "runner-1",
                "number": "1",
                "draw": "2",
                "jockey_name": "Old Jockey",
                "carried_weight": "56",
                "status": "declared",
            },
            {
                "external_runner_id": "runner-2",
                "number": "2",
                "draw": "5",
                "jockey_name": "Second Jockey",
                "carried_weight": "55",
                "status": "declared",
            },
        )
        incoming = (
            {
                "external_runner_id": "runner-1",
                "number": "1",
                "draw": "3",
                "jockey_name": "New Jockey",
                "carried_weight": "56",
                "status": "declared",
            },
            {
                "external_runner_id": "runner-3",
                "number": "3",
                "draw": "7",
                "jockey_name": "Third Jockey",
                "carried_weight": "54",
                "status": "declared",
            },
        )

        merged = merge(previous=previous, incoming=incoming)

        rows = {
            row["external_runner_id"]: row for row in merged["participants"]
        }
        self.assertEqual(set(rows), {"runner-1", "runner-2", "runner-3"})
        self.assertEqual(rows["runner-1"]["draw"], "3")
        self.assertEqual(rows["runner-1"]["jockey_name"], "New Jockey")
        self.assertEqual(rows["runner-2"]["status"], "declared")
        self.assertEqual(
            tuple(merged["missing_runner_source_gaps"]),
            ("runner-2",),
        )
        self.assertNotIn(
            "withdrawn",
            {row["status"] for row in rows.values()},
        )

    def test_explicit_result_nr_is_objective_but_racecard_has_no_inferred_withdrawal(self):
        result = race_live_fixtures.parse_the_racing_api_live_results_payload(
            {
                "results": [
                    {
                        "race_id": "jp-race-1",
                        "off_dt": "2026-07-20T14:40:00+09:00",
                        "region": "JPN",
                        "course": "Tokyo",
                        "race_name": "Japan Grade One",
                        "race_status": "Results",
                        "runners": [
                            {
                                "horse_id": "horse-1",
                                "horse": "Horse One",
                                "number": "1",
                                "position": "NR",
                            }
                        ],
                    }
                ],
                "total": 1,
                "limit": 50,
                "skip": 0,
            }
        )
        self.assertEqual(result.races[0]["participants"][0]["status"], "non_runner")

        racecard = race_live_fixtures.parse_the_racing_api_live_racecards_payload(
            {
                "racecards": [
                    {
                        "race_id": "jp-race-1",
                        "off_dt": "2026-07-20T14:40:00+09:00",
                        "region": "JPN",
                        "course": "Tokyo",
                        "race_name": "Japan Grade One",
                        "race_status": "Racecard",
                        "runners": [
                            {
                                "horse_id": "horse-1",
                                "horse": "Horse One",
                                "number": "1",
                            }
                        ],
                    }
                ],
                "total": 1,
                "limit": 500,
                "skip": 0,
            }
        )
        self.assertEqual(racecard.races[0]["participants"][0]["status"], "declared")


class RaceLiveRegionResultsSnapshotContractTests(SimpleTestCase):
    def test_snapshot_service_and_cache_key_are_region_scoped_capabilities(self):
        snapshot_service = getattr(
            race_live_runner,
            "get_or_fetch_region_results_snapshot",
            None,
        )
        cache_key_builder = getattr(
            race_live_runner,
            "build_race_live_results_snapshot_cache_key",
            None,
        )
        self.assertTrue(
            callable(snapshot_service),
            "地区 results snapshot 复用服务尚未实现",
        )
        self.assertTrue(
            callable(cache_key_builder),
            "地区 results cache key builder 尚未实现",
        )

        common = {
            "source_key": "the_racing_api",
            "provider_date": date(2026, 7, 20),
            "registry_digest": SHA_A,
            "endpoint_contract_version": "results-free-v2",
        }
        gb_key = cache_key_builder(region_code="gb", **common)
        fr_key = cache_key_builder(region_code="fr", **common)
        self.assertNotEqual(gb_key, fr_key)
        self.assertIn(":gb:", gb_key)
        self.assertIn(":fr:", fr_key)
        self.assertNotIn("password", gb_key.casefold())

    def test_page_plan_is_strictly_bounded_to_ten_pages(self):
        planner = getattr(
            race_live_runner,
            "build_the_racing_api_results_page_skips",
            None,
        )
        self.assertTrue(
            callable(planner),
            "TRA results 严格分页 planner 尚未实现",
        )
        self.assertEqual(tuple(planner(total=0)), (0,))
        self.assertEqual(tuple(planner(total=51)), (0, 50))
        self.assertEqual(tuple(planner(total=500)), tuple(range(0, 500, 50)))
        for total in (-1, 501, True, "51"):
            with self.subTest(total=total):
                with self.assertRaises((TypeError, ValueError, PermissionError)):
                    planner(total=total)

    def test_region_snapshot_fetches_required_pages_once_then_reuses_cache(self):
        cache_values = {}
        page_calls = []

        class FakeCache:
            def get(self, key):
                return cache_values.get(key)

            def set(self, key, value, timeout):
                cache_values[key] = value
                self.timeout = timeout

        def fetch_page(*, skip, limit):
            page_calls.append(skip)
            return {
                "total": 51,
                "skip": skip,
                "limit": limit,
                "payload_sha256": (
                    ("a" if skip == 0 else "b") * 64
                ),
                "races": (
                    {
                        "external_race_id": f"race-{skip}",
                        "participants": (),
                    },
                ),
            }

        kwargs = {
            "source_key": "the_racing_api",
            "provider_date": date(2026, 7, 20),
            "registry_digest": SHA_A,
            "endpoint_contract_version": "results-free-v2",
            "region_code": "fr",
            "fetch_page": fetch_page,
            "cache_backend": FakeCache(),
            "fetched_at": datetime(
                2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc
            ),
        }
        first = race_live_runner.get_or_fetch_region_results_snapshot(**kwargs)
        second = race_live_runner.get_or_fetch_region_results_snapshot(**kwargs)

        self.assertEqual(page_calls, [0, 50])
        self.assertEqual(first, second)
        self.assertEqual(first["total"], 51)
        self.assertEqual(first["pages"], 2)
        self.assertEqual(set(first["races"]), {"race-0", "race-50"})
        self.assertEqual(kwargs["cache_backend"].timeout, 150)

    def test_corrupted_region_cache_is_ignored_and_refetched(self):
        cache_key = race_live_runner.build_race_live_results_snapshot_cache_key(
            source_key="the_racing_api",
            provider_date=date(2026, 7, 20),
            registry_digest=SHA_A,
            endpoint_contract_version="results-free-v2",
            region_code="jpn",
        )
        cache_values = {
            cache_key: {
                "schema_version": 2,
                "region_code": "fr",
                "races": {"target": {"external_race_id": "other"}},
            }
        }
        calls = []

        class FakeCache:
            def get(self, key):
                return cache_values.get(key)

            def set(self, key, value, timeout):
                cache_values[key] = value

        def fetch_page(*, skip, limit):
            calls.append(skip)
            return {
                "total": 1,
                "skip": skip,
                "limit": limit,
                "payload_sha256": "d" * 64,
                "races": (
                    {
                        "external_race_id": "target",
                        "participants": (),
                    },
                ),
            }

        snapshot = race_live_runner.get_or_fetch_region_results_snapshot(
            source_key="the_racing_api",
            provider_date=date(2026, 7, 20),
            registry_digest=SHA_A,
            endpoint_contract_version="results-free-v2",
            region_code="jpn",
            fetch_page=fetch_page,
            fetched_at=datetime(
                2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc
            ),
            cache_backend=FakeCache(),
        )

        self.assertEqual(calls, [0])
        self.assertEqual(snapshot["region_code"], "jpn")
        self.assertEqual(set(snapshot["races"]), {"target"})

    def test_region_racecard_snapshot_is_reused_for_multiple_due_events(self):
        cache_values = {}
        calls = []

        class FakeCache:
            def get(self, key):
                return cache_values.get(key)

            def set(self, key, value, timeout):
                cache_values[key] = value
                self.timeout = timeout

        def fetch_snapshot():
            calls.append("fetch")
            return {
                "payload_sha256": "e" * 64,
                "races": (
                    {"external_race_id": "fr-race-1"},
                    {"external_race_id": "fr-race-2"},
                ),
            }

        kwargs = {
            "source_key": "the_racing_api",
            "provider_date": date(2026, 7, 20),
            "registry_digest": SHA_A,
            "endpoint_contract_version": "racecards-free-v2",
            "region_code": "fr",
            "day": "today",
            "fetch_snapshot": fetch_snapshot,
            "fetched_at": datetime(
                2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc
            ),
            "cache_backend": FakeCache(),
        }
        first = race_live_runner.get_or_fetch_region_racecard_snapshot(
            **kwargs
        )
        second = race_live_runner.get_or_fetch_region_racecard_snapshot(
            **kwargs
        )

        self.assertEqual(calls, ["fetch"])
        self.assertEqual(first, second)
        self.assertEqual(
            set(first["races"]),
            {"fr-race-1", "fr-race-2"},
        )
        self.assertEqual(kwargs["cache_backend"].timeout, 150)


@override_settings(
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("france",),
    RACE_DATA_SYNC_ENABLED_FIELDS=(
        "off_time",
        "local_start_time",
        "participants.draw",
        "participants.horse_name",
        "participants.jockey_name",
        "participants.number",
        "participants.status",
    ),
)
class RaceLiveRacecardRefreshBehaviorTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.event = models.RaceEvent.objects.create(
            year=2026,
            slug="france-racecard-refresh",
            original_name="France Racecard Refresh",
            chinese_name="法国出马表刷新测试",
            country_region=models.RacingRegion.FRANCE,
            racecourse="ParisLongchamp",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            race_datetime=datetime(
                2026, 7, 20, 13, 0, tzinfo=dt_timezone.utc
            ),
            timezone_name="Europe/Paris",
            local_date=date(2026, 7, 20),
        )
        self.control = models.RaceEventProjectionControl.objects.create(
            event=self.event,
            write_owner=models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=3,
            next_racecard_revision_no=2,
        )
        models.RaceEventLiveTracking.objects.create(
            event=self.event,
            state=models.RaceEventLiveState.RACECARD_READY,
            tracking_enabled=True,
            next_poll_at=self.NOW,
            claim_generation=4,
            active_attempt_token="racecard-refresh-token",
            claim_expires_at=self.NOW + timedelta(minutes=5),
        )
        self.source = models.RaceResultSourceIdentity.objects.create(
            event=self.event,
            source_key="the_racing_api",
            external_race_id="fr-refresh-1",
            host="api.theracingapi.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
        )
        participant = models.RaceEventParticipant.objects.create(
            event=self.event,
            stable_key="runner-1",
            canonical_name="Alpha",
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=participant,
            source_identity=self.source,
            external_runner_id="runner-1",
        )
        initial = models.RaceEventRevision.objects.create(
            event=self.event,
            kind=models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=models.RaceResultPhase.RACECARD,
            content_sha256="a" * 64,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        models.RaceEventRevisionItem.objects.create(
            revision=initial,
            participant=participant,
            source_order=1,
            internal_order=1,
            status=models.RaceEventRevisionItemStatus.DECLARED,
            horse_number="1",
            jockey_name="Old Jockey",
        )
        self.control.current_racecard_revision = initial
        self.control.last_known_good_racecard_revision = initial
        self.control.save(
            update_fields=(
                "current_racecard_revision",
                "last_known_good_racecard_revision",
                "updated_at",
            )
        )

    def test_refresh_creates_immutable_revision_and_releases_claim(self):
        decision = race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token="racecard-refresh-token",
            now=self.NOW,
            raw_sha256="b" * 64,
            normalized_racecard={
                "external_race_id": "fr-refresh-1",
                "off_time": "2026-07-20T13:05:00+00:00",
                "region": "FR",
                "course": "ParisLongchamp",
                "race_name": "France Racecard Refresh",
                "race_status": "Racecard",
                "participants": (
                    {
                        "external_runner_id": "runner-1",
                        "horse_name": "Alpha",
                        "number": "1",
                        "draw": "3",
                        "jockey_name": "New Jockey",
                        "status": "declared",
                    },
                    {
                        "external_runner_id": "runner-2",
                        "horse_name": "Beta",
                        "number": "2",
                        "draw": "5",
                        "jockey_name": "Second Jockey",
                        "status": "declared",
                    },
                ),
            },
        )

        self.assertTrue(decision.applied)
        self.assertEqual(decision.reason, "racecard_refreshed")
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_racecard_revision.revision_no,
            2,
        )
        self.assertEqual(
            self.control.last_known_good_racecard_revision.revision_no,
            1,
        )
        refreshed = self.control.current_racecard_revision
        self.assertEqual(refreshed.items.count(), 2)
        self.assertEqual(
            refreshed.items.get(horse_number="1").jockey_name,
            "New Jockey",
        )
        tracking = models.RaceEventLiveTracking.objects.get(event=self.event)
        self.assertEqual(tracking.active_attempt_token, "")
        self.assertIsNone(tracking.claim_expires_at)
        self.assertEqual(
            tracking.checkpoint_payload["status"],
            "racecard_refreshed",
        )

    def test_refresh_rejects_naive_source_off_time_without_projection_write(self):
        decision = race_live_racecard_sync.refresh_race_live_racecard(
            event_id=self.event.pk,
            expected_owner_generation=3,
            expected_claim_generation=4,
            attempt_token="racecard-refresh-token",
            now=self.NOW,
            raw_sha256="c" * 64,
            normalized_racecard={
                "external_race_id": "fr-refresh-1",
                "off_time": "2026-07-20T15:05:00",
                "region": "FR",
                "course": "ParisLongchamp",
                "race_name": "France Racecard Refresh",
                "race_status": "Racecard",
                "participants": (
                    {
                        "external_runner_id": "runner-1",
                        "horse_name": "Alpha",
                        "number": "1",
                        "status": "declared",
                    },
                ),
            },
        )

        self.assertFalse(decision.applied)
        self.assertEqual(decision.reason, "off_time_change_rejected")
        self.control.refresh_from_db()
        self.assertEqual(self.control.current_racecard_revision.revision_no, 1)


class RaceLiveHostBudgetReuseRegressionTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def test_same_host_reservations_retain_the_1050ms_floor(self):
        models.RaceLiveHostBudget.objects.create(
            host="api.theracingapi.com",
            min_interval_ms=1050,
        )

        first = race_events.reserve_race_live_host_request(
            host="api.theracingapi.com",
            now=self.NOW,
        )
        blocked = race_events.reserve_race_live_host_request(
            host="api.theracingapi.com",
            now=self.NOW,
        )

        self.assertIs(first.reserved, True)
        self.assertIs(blocked.reserved, False)
        self.assertEqual(blocked.reason, "rate_limited")
        self.assertEqual(
            blocked.next_allowed_at,
            self.NOW + timedelta(milliseconds=1050),
        )


class RaceLiveRegistryImageContractTests(SimpleTestCase):
    def test_registry_sha_is_frozen_in_env_and_all_three_compose_files(self):
        registry_sha = __import__("hashlib").sha256(
            TRA_REGISTRY.read_bytes()
        ).hexdigest()
        self.assertEqual(
            registry_sha,
            "7aca49ff1df7573ebfe6a9e403eefca5c9e64d8ee18d8d3be383d67803db550a",
        )
        for relative_path in (
            ".env.example",
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "docker-compose.prod.lowcost.yml",
        ):
            with self.subTest(path=relative_path):
                self.assertIn(
                    registry_sha,
                    (REPO_ROOT / relative_path).read_text(encoding="utf-8"),
                )
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "source_registry_the_racing_api_free.json",
            dockerfile,
        )
        self.assertIn("COPY scripts /app/scripts", dockerfile)
        env_example = (REPO_ROOT / ".env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "CELERY_RACE_LIVE_WORKER_SOFT_TIME_LIMIT=180",
            env_example,
        )
        self.assertIn(
            "CELERY_RACE_LIVE_WORKER_TIME_LIMIT=210",
            env_example,
        )
        worker_script = (
            REPO_ROOT / "deploy" / "docker" / "start-race-live-worker.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'CELERY_RACE_LIVE_WORKER_SOFT_TIME_LIMIT:-180',
            worker_script,
        )
        self.assertIn(
            'CELERY_RACE_LIVE_WORKER_TIME_LIMIT:-210',
            worker_script,
        )
