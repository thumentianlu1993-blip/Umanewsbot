from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import get_commands
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from stable import models
from stable.services import race_events


class TheRacingApiLiveRacecardPayloadTests(SimpleTestCase):
    def _parse(self, payload):
        module = importlib.import_module("stable.services.race_live_fixtures")
        parser = getattr(
            module,
            "parse_the_racing_api_live_racecards_payload",
            None,
        )
        self.assertTrue(
            callable(parser),
            "The Racing API live racecard parser 尚未实现",
        )
        return parser(payload)

    @staticmethod
    def _race(**overrides):
        race = {
            "race_id": "race-gb-1",
            "off_dt": "2026-07-20T14:40:00+01:00",
            "region": "GB",
            "course": "Ascot",
            "race_name": "King George Stakes",
            "race_status": "Racecard",
            "runners": [
                {
                    "horse_id": "horse-1",
                    "horse": "Objective Horse",
                    "number": "4",
                    "draw": "7",
                    "jockey": "Objective Jockey",
                    "jockey_id": "jockey-1",
                    "form": "11111",
                    "ofr": "123",
                    "rating": "123",
                    "odds": "7/4",
                    "prize": "100000",
                    "pedigree": {"sire": "Copyright Sire"},
                    "comments": "Copyright comment",
                }
            ],
            "prize": "200000",
            "comments": "Copyright race comment",
        }
        race.update(overrides)
        return race

    def test_normalizes_only_the_objective_allowlist_and_accepts_empty_collection(self):
        parsed = self._parse(
            {
                "racecards": [self._race()],
                "total": 1,
                "limit": 500,
                "skip": 0,
            }
        )

        self.assertEqual(parsed.endpoint, "/v1/racecards/free")
        self.assertEqual(parsed.phase, "racecard")
        self.assertEqual(len(parsed.races), 1)
        self.assertEqual(
            set(parsed.races[0]),
            {
                "external_race_id",
                "off_time",
                "region",
                "course",
                "race_name",
                "race_status",
                "participants",
            },
        )
        self.assertEqual(
            parsed.races[0]["participants"],
            (
                {
                    "external_runner_id": "horse-1",
                    "horse_name": "Objective Horse",
                    "number": "4",
                    "draw": "7",
                    "jockey_name": "Objective Jockey",
                    "jockey_id": "jockey-1",
                    "status": "declared",
                },
            ),
        )
        normalized_text = json.dumps(parsed.races, ensure_ascii=False, sort_keys=True)
        for forbidden in (
            "form",
            "ofr",
            "rating",
            "odds",
            "prize",
            "pedigree",
            "comments",
            "Copyright",
        ):
            self.assertNotIn(forbidden, normalized_text)

        empty = self._parse(
            {"racecards": [], "total": 0, "limit": 500, "skip": 0}
        )
        self.assertEqual(empty.races, ())

    def test_rejects_naive_time_missing_identity_and_duplicate_ids_or_numbers(self):
        cases = []
        for missing in (
            "race_id",
            "off_dt",
            "region",
            "course",
            "race_name",
            "runners",
        ):
            race = self._race()
            race.pop(missing)
            cases.append((f"missing_{missing}", {"racecards": [race]}))
        cases.append(
            (
                "naive_off_time",
                {"racecards": [self._race(off_dt="2026-07-20T14:40:00")]},
            )
        )
        duplicate_race = self._race()
        cases.append(
            (
                "duplicate_race_id",
                {"racecards": [duplicate_race, self._race(course="Newbury")]},
            )
        )
        for field in ("horse_id", "number"):
            race = self._race()
            duplicate = dict(race["runners"][0])
            duplicate["horse"] = "Second Horse"
            if field == "horse_id":
                duplicate["number"] = "5"
            else:
                duplicate["horse_id"] = "horse-2"
            race["runners"] = [race["runners"][0], duplicate]
            cases.append((f"duplicate_{field}", {"racecards": [race]}))

        for label, payload in cases:
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    self._parse(payload)

    def test_caps_races_and_runners_and_preserves_existing_results_parser(self):
        with self.assertRaises(ValueError):
            self._parse({"racecards": [self._race()] * 501})
        with self.assertRaises(ValueError):
            self._parse(
                {
                    "racecards": [
                        self._race(
                            runners=[
                                {
                                    "horse_id": f"horse-{index}",
                                    "horse": f"Horse {index}",
                                    "number": str(index),
                                }
                                for index in range(101)
                            ]
                        )
                    ]
                }
            )

        module = importlib.import_module("stable.services.race_live_fixtures")
        results_parser = getattr(
            module,
            "parse_the_racing_api_live_results_payload",
            None,
        )
        self.assertTrue(callable(results_parser))
        results = results_parser({"results": []})
        self.assertEqual(results.phase, "provisional")
        self.assertEqual(results.races, ())


class RaceLiveRacecardPrepareTests(TestCase):
    NOW = datetime(2026, 7, 18, 10, 0, tzinfo=dt_timezone.utc)
    APPROVED_COMMIT = "c" * 40
    COVERAGE_DIGEST = "b" * 64
    TERMS_DIGEST = "d" * 64
    OFFICIAL_EVIDENCE_DIGEST = "e" * 64

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifact_root = self.root / "artifacts"
        self.artifact_root.mkdir(mode=0o700)
        self.secret_path = self.root / "the-racing-api.env"
        self.secret_path.write_text(
            "THE_RACING_API_USERNAME=test-user\n"
            "THE_RACING_API_PASSWORD=test-password\n",
            encoding="utf-8",
        )
        self.secret_path.chmod(0o600)
        self.registry_path, self.registry_digest = self._registry()
        self.event = self._event()

    def _service(self):
        try:
            return importlib.import_module(
                "stable.services.race_live_racecard_sync"
            )
        except ModuleNotFoundError:
            self.fail("准实时 racecard prepare service 尚未实现")

    def _event(self, **overrides):
        values = {
            "year": 2026,
            "slug": "king-george-stakes-2026",
            "original_name": "King George Stakes",
            "chinese_name": "英王乔治锦标",
            "country_region": models.RacingRegion.UNITED_KINGDOM,
            "racecourse": "Ascot",
            "grade_text": "G1",
            "surface": models.RaceEventSurface.TURF,
            "timezone_name": "Europe/London",
            "local_date": date(2026, 7, 18),
            "status": models.RaceEventStatus.SCHEDULED,
            "priority": models.RaceEventPriority.P0,
        }
        values.update(overrides)
        return models.RaceEvent.objects.create(**values)

    def _registry(self):
        payload = {
            "schema_version": 1,
            "source_key": "the_racing_api",
            "host": "api.theracingapi.com",
            "terms_status": "approved",
            "proof_network_allowed": True,
            "automation_allowed": True,
            "valid_until": "2026-08-17T00:00:00+00:00",
            "max_requests": 3,
            "evidence": {
                "documentation_url": "https://api.theracingapi.com/documentation",
                "terms_url": "https://www.theracingapi.com/terms-of-service",
                "verified_at": "2026-07-17T00:00:00+00:00",
                "authorization_basis": "user_confirmed_automation_permission",
            },
            "endpoints": [
                {"name": "regions", "path": "/v1/courses/regions"},
                {
                    "name": "racecards_today",
                    "path": "/v1/racecards/free?day=today&limit=500&skip=0",
                },
                {
                    "name": "results_today",
                    "path": "/v1/results/today/free?limit=50&skip=0",
                },
                {
                    "name": "racecards_sync_today",
                    "path": "/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
                },
                {
                    "name": "racecards_sync_tomorrow",
                    "path": "/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
                },
            ],
        }
        path = self.root / "registry.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _racecard(
        *,
        race_id="race-gb-1",
        off_dt="2026-07-18T14:40:00+01:00",
        region="GB",
        course="Ascot",
        race_name="King George Stakes",
    ):
        return {
            "race_id": race_id,
            "off_dt": off_dt,
            "region": region,
            "course": course,
            "race_name": race_name,
            "race_status": "Racecard",
            "runners": [
                {
                    "horse_id": "horse-1",
                    "horse": "First Horse",
                    "number": "1",
                    "draw": "3",
                    "jockey": "First Jockey",
                    "jockey_id": "jockey-1",
                    "form": "11111",
                    "ofr": "121",
                },
                {
                    "horse_id": "horse-2",
                    "horse": "Second Horse",
                    "number": "2",
                    "draw": "7",
                    "jockey": "Second Jockey",
                    "jockey_id": "jockey-2",
                },
            ],
        }

    def _response(self, body):
        response_type = importlib.import_module(
            "stable.services.race_live_source_proof"
        ).RaceLiveProofHttpResponse
        return response_type(
            status_code=200,
            content_type="application/json",
            body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            elapsed_ms=25,
            redirect_url=None,
        )

    def _run(
        self,
        transport,
        *,
        run_id="valid-run",
        sleep=None,
        clock=None,
        confirm_real_network=True,
        expected_registry_sha256=None,
        policy_valid_until=None,
    ):
        service = self._service()
        prepare = getattr(service, "prepare_race_live_racecards", None)
        self.assertTrue(
            callable(prepare),
            "prepare_race_live_racecards 尚未实现",
        )
        return prepare(
            event_ids=[self.event.pk],
            run_id=run_id,
            artifact_root=self.artifact_root,
            secret_env_file=self.secret_path,
            registry_file=self.registry_path,
            expected_registry_sha256=(
                expected_registry_sha256 or self.registry_digest
            ),
            approved_commit=self.APPROVED_COMMIT,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            terms_evidence_sha256=self.TERMS_DIGEST,
            policy_valid_until=(
                policy_valid_until or self.NOW + timedelta(days=20)
            ),
            official_verification_route="bha_manual_verification",
            official_verification_route_version="bha-manual-v1",
            official_verification_evidence_sha256=(
                self.OFFICIAL_EVIDENCE_DIGEST
            ),
            official_verification_valid_until=self.NOW + timedelta(days=20),
            now=self.NOW,
            transport=transport,
            sleep=sleep or (lambda _seconds: None),
            clock=clock or (lambda: self.NOW),
            confirm_real_network=confirm_real_network,
        )

    def test_exact_today_tomorrow_prepare_bootstraps_budget_and_writes_bound_artifact(self):
        calls = []
        current = [self.NOW]
        sleeps = []

        def transport(**kwargs):
            calls.append(kwargs)
            if kwargs["endpoint_name"] == "racecards_sync_today":
                return self._response({"racecards": [self._racecard()]})
            return self._response({"racecards": []})

        def sleep(seconds):
            sleeps.append(seconds)
            current[0] += timedelta(seconds=seconds)

        result = self._run(
            transport,
            sleep=sleep,
            clock=lambda: current[0],
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.request_count, 2)
        self.assertEqual(tuple(result.blocker_codes), ())
        self.assertEqual(
            [call["endpoint_name"] for call in calls],
            ["racecards_sync_today", "racecards_sync_tomorrow"],
        )
        self.assertEqual(
            [call["url"] for call in calls],
            [
                "https://api.theracingapi.com/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
                "https://api.theracingapi.com/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
            ],
        )
        self.assertTrue(all(call["timeout_seconds"] == 15 for call in calls))
        self.assertTrue(all(call["allow_redirects"] is False for call in calls))
        self.assertEqual(sleeps, [1.05])

        output = self.artifact_root / "valid-run"
        self.assertEqual(result.output_dir, output)
        self.assertEqual(
            {path.name for path in output.iterdir()},
            {"manifest.json", "report.json", "requests.jsonl"},
        )
        self.assertTrue(
            all(
                (path.stat().st_mode & 0o777) == 0o600
                for path in output.iterdir()
            )
        )
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report_path = output / "report.json"
        requests_path = output / "requests.jsonl"
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(
            manifest["requests_sha256"],
            hashlib.sha256(requests_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["report_sha256"],
            hashlib.sha256(report_path.read_bytes()).hexdigest(),
        )
        event = manifest["events"][0]
        self.assertEqual(event["event_id"], self.event.pk)
        self.assertEqual(event["external_race_id"], "race-gb-1")
        self.assertEqual(event["expected_timezone_name"], "Europe/London")
        self.assertEqual(event["local_date"], "2026-07-18")
        self.assertEqual(event["race_datetime"], "2026-07-18T14:40:00+01:00")
        self.assertEqual(
            datetime.fromisoformat(event["source_off_dt"])
            .astimezone(ZoneInfo("Europe/London"))
            .time()
            .isoformat(),
            "14:40:00",
        )
        self.assertEqual(
            event["participants"][0]["stable_key"],
            "tra:" + hashlib.sha256(b"horse-1").hexdigest(),
        )
        self.assertEqual(event["participants"][0]["country_region"], "")
        self.assertEqual(event["participants"][0]["barrier"], "3")
        self.assertEqual(event["participants"][0]["jockey_id"], "jockey-1")
        self.assertEqual(event["tracking_state"], "racecard_ready")
        expected_next_poll = race_events.calculate_race_live_next_poll_at(
            off_time=datetime.fromisoformat(event["source_off_dt"]),
            now=self.NOW,
            state="racecard_ready",
        )
        self.assertEqual(
            datetime.fromisoformat(event["next_poll_at"]),
            expected_next_poll,
        )

        requests_text = requests_path.read_text(encoding="utf-8")
        for forbidden in (
            "test-user",
            "test-password",
            "race-gb-1",
            "horse-1",
            "First Horse",
            "King George Stakes",
            "form",
            "ofr",
            "raw",
        ):
            self.assertNotIn(forbidden, requests_text)
        self.assertNotIn("form", json.dumps(manifest, sort_keys=True))
        self.assertNotIn("ofr", json.dumps(manifest, sort_keys=True))

        budget = models.RaceLiveHostBudget.objects.get(
            host="api.theracingapi.com"
        )
        self.assertEqual(budget.min_interval_ms, 1050)
        self.assertGreaterEqual(budget.lock_version, 4)

    def test_matching_uses_london_instant_and_active_alias_but_never_substring(self):
        self.event.original_name = "Canonical Name That Does Not Match"
        self.event.save(update_fields=("original_name", "updated_at"))
        models.RaceEventAlias.objects.create(
            event=self.event,
            text="Ｋｉｎｇ—George   Stakes",
            source_language="en",
            is_active=True,
        )
        responses = iter(
            (
                self._response(
                    {
                        "racecards": [
                            self._racecard(
                                off_dt="2026-07-19T00:30:00+02:00",
                                race_name="King George Stakes",
                            )
                        ]
                    }
                ),
                self._response({"racecards": []}),
            )
        )
        current = [self.NOW]

        result = self._run(
            lambda **_kwargs: next(responses),
            run_id="alias-run",
            sleep=lambda seconds: current.__setitem__(
                0, current[0] + timedelta(seconds=seconds)
            ),
            clock=lambda: current[0],
        )

        self.assertTrue(result.completed)
        manifest = json.loads(
            (self.artifact_root / "alias-run" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            datetime.fromisoformat(manifest["events"][0]["source_off_dt"])
            .astimezone(ZoneInfo("Europe/London"))
            .time()
            .isoformat(),
            "23:30:00",
        )
        self.assertEqual(manifest["events"][0]["local_date"], "2026-07-18")

        models.RaceEventAlias.objects.filter(event=self.event).update(
            is_active=False
        )
        responses = iter(
            (
                self._response(
                    {
                        "racecards": [
                            self._racecard(
                                race_name="The King George Stakes Sponsored",
                            )
                        ]
                    }
                ),
                self._response({"racecards": []}),
            )
        )
        models.RaceLiveHostBudget.objects.all().delete()
        result = self._run(
            lambda **_kwargs: next(responses),
            run_id="substring-run",
            sleep=lambda _seconds: None,
        )
        self.assertFalse(result.completed)
        self.assertIn("racecard_not_found", result.blocker_codes)
        self.assertFalse(
            (self.artifact_root / "substring-run" / "manifest.json").exists()
        )

    def test_g3_event_original_name_matches_exact_source_group_suffix(self):
        self.event.original_name = (
            "Hallgarten And Novum Wines Hackwood Stakes"
        )
        self.event.racecourse = "Newbury"
        self.event.grade_text = "G3"
        self.event.normalized_grade = models.RaceGrade.G3
        self.event.save(
            update_fields=(
                "original_name",
                "racecourse",
                "grade_text",
                "normalized_grade",
                "updated_at",
            )
        )
        responses = iter(
            (
                self._response(
                    {
                        "racecards": [
                            self._racecard(
                                race_id="rac_13000002795",
                                course="Newbury",
                                race_name=(
                                    "Hallgarten And Novum Wines "
                                    "Hackwood Stakes (Group 3)"
                                ),
                            )
                        ]
                    }
                ),
                self._response({"racecards": []}),
            )
        )
        current = [self.NOW]

        result = self._run(
            lambda **_kwargs: next(responses),
            run_id="g3-original-suffix",
            sleep=lambda seconds: current.__setitem__(
                0, current[0] + timedelta(seconds=seconds)
            ),
            clock=lambda: current[0],
        )

        self.assertTrue(result.completed, result.blocker_codes)
        self.assertEqual(result.blocker_codes, ())
        manifest_path = (
            self.artifact_root / "g3-original-suffix" / "manifest.json"
        )
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["events"][0]["external_race_id"],
            "rac_13000002795",
        )

    def test_group_suffix_variants_are_grade_exact_and_fail_closed(self):
        service = self._service()
        approved_names = getattr(service, "_event_names", None)
        self.assertTrue(callable(approved_names))

        for grade, group_number in (
            (models.RaceGrade.G1, 1),
            (models.RaceGrade.G2, 2),
            (models.RaceGrade.G3, 3),
        ):
            with self.subTest(grade=grade):
                self.event.original_name = f"Exact Grade {grade} Stakes"
                self.event.normalized_grade = grade
                self.event.save(
                    update_fields=(
                        "original_name",
                        "normalized_grade",
                        "updated_at",
                    )
                )
                names = approved_names(self.event)
                self.assertIn(
                    f"exact grade {grade.casefold()} stakes "
                    f"group {group_number}",
                    names,
                )

        self.event.original_name = "Already Decorated (Group 3)"
        self.event.normalized_grade = models.RaceGrade.G3
        self.event.save(
            update_fields=(
                "original_name",
                "normalized_grade",
                "updated_at",
            )
        )
        names = approved_names(self.event)
        self.assertIn("already decorated group 3", names)
        self.assertNotIn("already decorated group 3 group 3", names)

        self.event.original_name = "Wrong Grade (Group 2)"
        self.event.save(update_fields=("original_name", "updated_at"))
        names = approved_names(self.event)
        self.assertNotIn("wrong grade group 2", names)
        self.assertNotIn("wrong grade group 2 group 3", names)

        self.event.original_name = "Boundary Stakes"
        self.event.save(update_fields=("original_name", "updated_at"))
        names = approved_names(self.event)
        self.assertNotIn("boundary stakes group 3 sponsored", names)
        self.assertNotIn("boundary stakes listed race", names)
        self.assertNotIn("the boundary stakes group 3", names)

        for grade in (
            "",
            models.RaceGrade.LISTED,
            models.RaceGrade.OPEN,
            models.RaceGrade.JPN3,
            models.RaceGrade.JG3,
        ):
            with self.subTest(non_group_grade=grade):
                self.event.normalized_grade = grade
                self.event.save(
                    update_fields=("normalized_grade", "updated_at")
                )
                names = approved_names(self.event)
                self.assertEqual(names, {"boundary stakes"})

    def test_group_tokens_outside_the_only_terminal_suffix_are_excluded(self):
        service = self._service()
        approved_names = getattr(service, "_event_names", None)
        self.assertTrue(callable(approved_names))
        self.event.normalized_grade = models.RaceGrade.G3

        for original_name, normalized_name in (
            ("Foo (Group 2) Stakes", "foo group 2 stakes"),
            ("Foo (Group 2) (Group 3)", "foo group 2 group 3"),
            ("Foo (Group 3) Stakes", "foo group 3 stakes"),
        ):
            with self.subTest(original_name=original_name):
                self.event.original_name = original_name
                self.event.save(
                    update_fields=(
                        "original_name",
                        "normalized_grade",
                        "updated_at",
                    )
                )

                names = approved_names(self.event)

                self.assertNotIn(normalized_name, names)
                self.assertNotIn(f"{normalized_name} group 3", names)

    def test_group_suffix_variants_cover_alias_and_series_name_paths(self):
        service = self._service()
        approved_names = getattr(service, "_event_names", None)
        self.assertTrue(callable(approved_names))
        series = models.RaceSeries.objects.create(
            key="grade-variant-series",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            canonical_name_original="Series Canonical Only",
        )
        self.event.original_name = "Event Original Only"
        self.event.normalized_grade = models.RaceGrade.G3
        self.event.race_series = series
        self.event.save(
            update_fields=(
                "original_name",
                "normalized_grade",
                "race_series",
                "series_key",
                "updated_at",
            )
        )
        models.RaceEventAlias.objects.create(
            event=self.event,
            text="Active Alias Only",
            source_language="en",
            is_active=True,
        )
        models.RaceEventAlias.objects.create(
            event=self.event,
            text="Inactive Alias Only",
            source_language="en",
            is_active=False,
        )
        models.RaceEventAlias.objects.create(
            event=self.event,
            text="含汉字 Alias Only",
            source_language="en",
            is_active=True,
        )
        models.RaceSeriesName.objects.create(
            series=series,
            text="Valid Series Name Only",
            source_language="en",
            valid_from_year=2026,
            valid_to_year=2026,
            is_active=True,
        )
        models.RaceSeriesName.objects.create(
            series=series,
            text="Expired Series Name Only",
            source_language="en",
            valid_from_year=2020,
            valid_to_year=2025,
            is_active=True,
        )
        models.RaceSeriesName.objects.create(
            series=series,
            text="Inactive Series Name Only",
            source_language="en",
            valid_from_year=2026,
            valid_to_year=2026,
            is_active=False,
        )

        names = approved_names(self.event)

        for expected in (
            "active alias only group 3",
            "series canonical only group 3",
            "valid series name only group 3",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, names)
        for rejected in (
            "inactive alias only group 3",
            "含汉字 alias only group 3",
            "expired series name only group 3",
            "inactive series name only group 3",
        ):
            with self.subTest(rejected=rejected):
                self.assertNotIn(rejected, names)

    def test_group_suffix_variants_cover_major_event_names_and_gates(self):
        service = self._service()
        approved_names = getattr(service, "_event_names", None)
        self.assertTrue(callable(approved_names))
        major = models.MajorRaceEvent.objects.create(
            name="Major Name Only",
            normalized_name="Major Normalized Only",
            year=2026,
            racing_region=models.RacingRegion.UNITED_KINGDOM,
            race_grade=models.RaceGrade.G3,
            aliases=["Major Alias Only"],
            timezone_name="Europe/London",
            local_date=date(2026, 7, 18),
            is_active=True,
        )
        self.event.original_name = "Event Original Only"
        self.event.normalized_grade = models.RaceGrade.G3
        self.event.major_race_event = major
        self.event.save(
            update_fields=(
                "original_name",
                "normalized_grade",
                "major_race_event",
                "updated_at",
            )
        )

        names = approved_names(self.event)
        for expected in (
            "major name only group 3",
            "major normalized only group 3",
            "major alias only group 3",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, names)

        major.is_active = False
        major.save(update_fields=("is_active", "updated_at"))
        names = approved_names(self.event)
        self.assertNotIn("major name only group 3", names)
        self.assertNotIn("major normalized only group 3", names)
        self.assertNotIn("major alias only group 3", names)

        major.is_active = True
        major.year = 2025
        major.save(update_fields=("is_active", "year", "updated_at"))
        names = approved_names(self.event)
        self.assertNotIn("major name only group 3", names)

        major.year = 2026
        major.name = "含汉字 Major Name"
        major.normalized_name = "含汉字 Major Normalized"
        major.aliases = ["含汉字 Major Alias"]
        major.save(
            update_fields=(
                "year",
                "name",
                "normalized_name",
                "aliases",
                "updated_at",
            )
        )
        names = approved_names(self.event)
        self.assertNotIn("含汉字 major name group 3", names)
        self.assertNotIn("含汉字 major normalized group 3", names)
        self.assertNotIn("含汉字 major alias group 3", names)

    def test_mismatched_group_tokens_from_all_approved_paths_are_excluded(self):
        service = self._service()
        approved_names = getattr(service, "_event_names", None)
        self.assertTrue(callable(approved_names))
        series = models.RaceSeries.objects.create(
            key="wrong-grade-series",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            canonical_name_original="Wrong Canonical (Group 2)",
        )
        models.RaceSeriesName.objects.create(
            series=series,
            text="Wrong Series Name (Group 2)",
            source_language="en",
            valid_from_year=2026,
            valid_to_year=2026,
            is_active=True,
        )
        major = models.MajorRaceEvent.objects.create(
            name="Wrong Major Name (Group 2)",
            normalized_name="Wrong Major Normalized (Group 2)",
            year=2026,
            racing_region=models.RacingRegion.UNITED_KINGDOM,
            race_grade=models.RaceGrade.G3,
            aliases=["Wrong Major Alias (Group 2)"],
            timezone_name="Europe/London",
            local_date=date(2026, 7, 18),
            is_active=True,
        )
        self.event.original_name = "Wrong Original (Group 2)"
        self.event.normalized_grade = models.RaceGrade.G3
        self.event.race_series = series
        self.event.major_race_event = major
        self.event.save(
            update_fields=(
                "original_name",
                "normalized_grade",
                "race_series",
                "series_key",
                "major_race_event",
                "updated_at",
            )
        )
        models.RaceEventAlias.objects.create(
            event=self.event,
            text="Wrong Alias (Group 2)",
            source_language="en",
            is_active=True,
        )

        names = approved_names(self.event)

        for base in (
            "wrong original",
            "wrong alias",
            "wrong canonical",
            "wrong series name",
            "wrong major name",
            "wrong major normalized",
            "wrong major alias",
        ):
            with self.subTest(base=base):
                self.assertNotIn(f"{base} group 2", names)
                self.assertNotIn(f"{base} group 2 group 3", names)

    def test_two_group_suffix_candidates_remain_ambiguous(self):
        self.event.normalized_grade = models.RaceGrade.G3
        self.event.save(
            update_fields=("normalized_grade", "updated_at")
        )
        payload = {
            "racecards": [
                self._racecard(
                    race_id="race-gb-group-1",
                    race_name="King George Stakes (Group 3)",
                ),
                self._racecard(
                    race_id="race-gb-group-2",
                    race_name="King George Stakes (Group 3)",
                ),
            ]
        }
        responses = iter(
            (self._response(payload), self._response({"racecards": []}))
        )
        current = [self.NOW]

        result = self._run(
            lambda **_kwargs: next(responses),
            run_id="group-suffix-ambiguous",
            sleep=lambda seconds: current.__setitem__(
                0, current[0] + timedelta(seconds=seconds)
            ),
            clock=lambda: current[0],
        )

        self.assertFalse(result.completed)
        self.assertIn("racecard_ambiguous", result.blocker_codes)
        self.assertFalse(
            (
                self.artifact_root
                / "group-suffix-ambiguous"
                / "manifest.json"
            ).exists()
        )

    def test_ambiguous_match_outputs_report_only(self):
        payload = {
            "racecards": [
                self._racecard(race_id="race-gb-1"),
                self._racecard(race_id="race-gb-2"),
            ]
        }
        responses = iter(
            (self._response(payload), self._response({"racecards": []}))
        )
        current = [self.NOW]

        result = self._run(
            lambda **_kwargs: next(responses),
            run_id="ambiguous-run",
            sleep=lambda seconds: current.__setitem__(
                0, current[0] + timedelta(seconds=seconds)
            ),
            clock=lambda: current[0],
        )

        self.assertFalse(result.completed)
        self.assertIn("racecard_ambiguous", result.blocker_codes)
        output = self.artifact_root / "ambiguous-run"
        self.assertTrue((output / "report.json").is_file())
        self.assertTrue((output / "requests.jsonl").is_file())
        self.assertFalse((output / "manifest.json").exists())

    def test_series_name_must_be_active_and_valid_for_the_event_year(self):
        series = models.RaceSeries.objects.create(
            key="king-george-series",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            canonical_name_original="Series Canonical Name",
        )
        self.event.race_series = series
        self.event.original_name = "Event Name That Does Not Match"
        self.event.save(
            update_fields=(
                "race_series",
                "original_name",
                "series_key",
                "updated_at",
            )
        )
        models.RaceSeriesName.objects.create(
            series=series,
            text="Expired Sponsored Name",
            source_language="en",
            valid_from_year=2020,
            valid_to_year=2025,
            is_active=True,
        )
        models.RaceSeriesName.objects.create(
            series=series,
            text="Approved 2026 Name",
            source_language="en",
            valid_from_year=2026,
            valid_to_year=2026,
            is_active=True,
        )

        def run_for_name(name, run_id):
            responses = iter(
                (
                    self._response(
                        {
                            "racecards": [
                                self._racecard(race_name=name)
                            ]
                        }
                    ),
                    self._response({"racecards": []}),
                )
            )
            current = [self.NOW]
            return self._run(
                lambda **_kwargs: next(responses),
                run_id=run_id,
                sleep=lambda seconds: current.__setitem__(
                    0, current[0] + timedelta(seconds=seconds)
                ),
                clock=lambda: current[0],
            )

        matched = run_for_name("Approved 2026 Name", "series-valid")
        self.assertTrue(matched.completed)

        models.RaceLiveHostBudget.objects.all().delete()
        expired = run_for_name("Expired Sponsored Name", "series-expired")
        self.assertFalse(expired.completed)
        self.assertIn("racecard_not_found", expired.blocker_codes)
        self.assertFalse(
            (self.artifact_root / "series-expired" / "manifest.json").exists()
        )

    def test_host_budget_wait_is_bounded_and_never_bypassed(self):
        models.RaceLiveHostBudget.objects.create(
            host="api.theracingapi.com",
            min_interval_ms=1050,
            next_allowed_at=self.NOW + timedelta(seconds=3),
            lock_version=9,
        )
        calls = []
        sleeps = []

        result = self._run(
            lambda **kwargs: calls.append(kwargs),
            run_id="rate-limited-run",
            sleep=lambda seconds: sleeps.append(seconds),
        )

        self.assertFalse(result.completed)
        self.assertEqual(calls, [])
        self.assertEqual(sleeps, [])
        self.assertIn("host_budget_wait_exceeded", result.blocker_codes)
        budget = models.RaceLiveHostBudget.objects.get(
            host="api.theracingapi.com"
        )
        self.assertEqual(budget.lock_version, 9)

    def test_confirmation_registry_and_policy_gates_fail_before_transport_or_budget(self):
        cases = (
            {
                "run_id": "confirmation-denied",
                "confirm_real_network": False,
            },
            {
                "run_id": "registry-denied",
                "expected_registry_sha256": "0" * 64,
            },
            {
                "run_id": "policy-after-registry",
                "policy_valid_until": self.NOW + timedelta(days=31),
            },
        )
        for case in cases:
            with self.subTest(case=case["run_id"]):
                calls = []
                with self.assertRaises((ValueError, PermissionError)):
                    self._run(
                        lambda **kwargs: calls.append(kwargs),
                        **case,
                    )
                self.assertEqual(calls, [])
                self.assertFalse(
                    (self.artifact_root / case["run_id"]).exists()
                )
                self.assertEqual(models.RaceLiveHostBudget.objects.count(), 0)

    def test_invalid_root_run_id_and_fsync_failure_leave_no_apply_ready_directory(self):
        calls = []
        symlink_root = self.root / "artifact-link"
        symlink_root.symlink_to(self.artifact_root, target_is_directory=True)
        original_root = self.artifact_root
        self.artifact_root = symlink_root
        with self.assertRaises((ValueError, PermissionError)):
            self._run(
                lambda **kwargs: calls.append(kwargs),
                run_id="unsafe-root",
            )
        self.assertEqual(calls, [])

        self.artifact_root = original_root
        for run_id in ("../escape", "nested/run", ".", ""):
            with self.subTest(run_id=run_id):
                with self.assertRaises((ValueError, PermissionError)):
                    self._run(
                        lambda **kwargs: calls.append(kwargs),
                        run_id=run_id,
                    )
        self.assertEqual(calls, [])

        service = self._service()
        responses = iter(
            (
                self._response({"racecards": [self._racecard()]}),
                self._response({"racecards": []}),
            )
        )
        current = [self.NOW]
        with patch.object(
            service.os,
            "fsync",
            side_effect=OSError("simulated fsync failure"),
        ):
            with self.assertRaisesRegex(OSError, "simulated fsync failure"):
                self._run(
                    lambda **_kwargs: next(responses),
                    run_id="fsync-failure",
                    sleep=lambda seconds: current.__setitem__(
                        0, current[0] + timedelta(seconds=seconds)
                    ),
                    clock=lambda: current[0],
                )
        self.assertFalse((self.artifact_root / "fsync-failure").exists())
        self.assertEqual(
            [
                path.name
                for path in self.artifact_root.iterdir()
                if "fsync-failure" in path.name
            ],
            [],
        )

    def test_losing_atomic_publish_never_deletes_an_existing_winner(self):
        service = self._service()
        final = self.artifact_root / "publish-race"

        def losing_rename(_temporary, target):
            self.assertEqual(Path(target), final)
            final.mkdir(mode=0o700)
            winner = final / "winner.json"
            winner.write_text('{"winner":true}\n', encoding="utf-8")
            winner.chmod(0o600)
            raise FileExistsError("simulated concurrent winner")

        with patch.object(Path, "rename", new=losing_rename):
            with self.assertRaisesRegex(
                FileExistsError,
                "simulated concurrent winner",
            ):
                service._write_artifact(
                    root=self.artifact_root,
                    run_id="publish-race",
                    requests=[],
                    report={"blockers": []},
                    manifest_base=None,
                )

        self.assertEqual(
            (final / "winner.json").read_text(encoding="utf-8"),
            '{"winner":true}\n',
        )
        self.assertEqual(
            [
                path.name
                for path in self.artifact_root.iterdir()
                if path.name.startswith(".publish-race.")
                and path.name.endswith(".tmp")
            ],
            [],
        )

    def test_event_baseline_occupancy_uses_a_fixed_query_budget(self):
        events = [
            self._event(
                slug=f"query-budget-{index}",
                original_name=f"Query Budget Stakes {index}",
            )
            for index in range(40)
        ]
        models.RaceEventProjectionControl.objects.create(event=events[0])
        models.RaceEventLiveTracking.objects.create(event=events[1])
        models.RaceResultSourceIdentity.objects.create(
            event=events[2],
            source_key="query-budget-source",
            external_race_id="query-budget-race-2",
        )
        models.RaceLiveEventPublicationAllowlist.objects.create(
            event=events[3],
            source_key="query-budget-source",
        )
        models.RaceEventParticipant.objects.create(
            event=events[4],
            stable_key="query-budget-participant",
            canonical_name="Query Budget Runner",
        )
        models.RaceEventRevision.objects.create(
            event=events[5],
            kind=models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=models.RaceResultPhase.RACECARD,
            content_sha256="1" * 64,
        )
        models.RaceEventResult.objects.create(
            event=events[6],
            finish_position=1,
            horse_name="Query Budget Winner",
        )
        observation_source = models.RaceResultSourceIdentity.objects.create(
            event=events[7],
            source_key="query-budget-observation",
            external_race_id="query-budget-race-7",
        )
        models.RaceResultObservation.objects.create(
            source_identity=observation_source,
            parser_version="query-budget-v1",
            raw_sha256="2" * 64,
            normalized_sha256="3" * 64,
            result_phase=models.RaceResultPhase.PROVISIONAL,
        )

        service = self._service()
        with CaptureQueriesContext(connection) as queries:
            loaded, blockers = service._load_target_events(
                [event.pk for event in events],
                generated_at=self.NOW,
            )

        self.assertEqual(len(loaded), 40)
        self.assertEqual(blockers.count("event_baseline_rejected"), 8)
        self.assertLessEqual(
            len(queries),
            20,
            "赛事占用检查必须按表批量查询，不能按 event 执行 exists",
        )

    def test_prepare_management_command_is_registered(self):
        self.assertIn(
            "prepare_race_live_racecards",
            get_commands(),
            "受控 racecard prepare 管理命令尚未注册",
        )
