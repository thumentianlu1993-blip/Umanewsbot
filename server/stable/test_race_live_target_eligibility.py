from __future__ import annotations

import importlib
import importlib.util
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json

from django.test import SimpleTestCase

from stable import models


class RaceLiveTargetEligibilityTests(SimpleTestCase):
    """RED contract for the shared prepare/initializer target matrix."""

    MODULE = "stable.services.race_live_target_eligibility"
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def _service(self):
        self.assertIsNotNone(
            importlib.util.find_spec(self.MODULE),
            "共同赛事资格模块尚未实现",
        )
        module = importlib.import_module(self.MODULE)
        service = getattr(
            module,
            "evaluate_race_live_target_eligibility",
            None,
        )
        self.assertTrue(
            callable(service),
            "共同赛事资格 pure function 尚未实现",
        )
        return service

    def _evaluate(
        self,
        service,
        *,
        event_id: int = 1001,
        year: int,
        region: str,
        grade: str,
    ):
        return service(
            event_id=event_id,
            year=year,
            region=region,
            normalized_grade=grade,
            exception_artifact=None,
        )

    def _field(self, decision, name):
        if isinstance(decision, dict):
            self.assertIn(name, decision)
            return decision[name]
        self.assertTrue(
            hasattr(decision, name),
            f"eligibility decision 缺少 {name}",
        )
        return getattr(decision, name)

    def test_uk_france_and_us_require_2025_plus_group_one_to_three(self):
        service = self._service()
        for region in (
            models.RacingRegion.UNITED_KINGDOM,
            models.RacingRegion.FRANCE,
            models.RacingRegion.UNITED_STATES,
        ):
            for grade in (
                models.RaceGrade.G1,
                models.RaceGrade.G2,
                models.RaceGrade.G3,
            ):
                with self.subTest(region=region, grade=grade):
                    decision = self._evaluate(
                        service,
                        year=2025,
                        region=region,
                        grade=grade,
                    )
                    self.assertIs(self._field(decision, "eligible"), True)
                    self.assertTrue(self._field(decision, "matrix_version"))

            with self.subTest(region=region, year=2024):
                decision = self._evaluate(
                    service,
                    year=2024,
                    region=region,
                    grade=models.RaceGrade.G1,
                )
                self.assertIs(self._field(decision, "eligible"), False)
                self.assertTrue(self._field(decision, "reason"))

    def test_hong_kong_accepts_g_jpn_and_jg_one_to_three(self):
        service = self._service()
        for grade in (
            models.RaceGrade.G1,
            models.RaceGrade.G2,
            models.RaceGrade.G3,
            models.RaceGrade.JPN1,
            models.RaceGrade.JPN2,
            models.RaceGrade.JPN3,
            models.RaceGrade.JG1,
            models.RaceGrade.JG2,
            models.RaceGrade.JG3,
        ):
            with self.subTest(grade=grade):
                decision = self._evaluate(
                    service,
                    year=2024,
                    region=models.RacingRegion.HONG_KONG,
                    grade=grade,
                )
                self.assertIs(self._field(decision, "eligible"), True)

        for grade in (
            models.RaceGrade.LISTED,
            models.RaceGrade.OPEN,
            models.RaceGrade.OTHER,
        ):
            with self.subTest(grade=grade):
                decision = self._evaluate(
                    service,
                    year=2026,
                    region=models.RacingRegion.HONG_KONG,
                    grade=grade,
                )
                self.assertIs(self._field(decision, "eligible"), False)

    def test_japan_accepts_g_jpn_and_jg_one_to_three(self):
        service = self._service()
        accepted = (
            models.RaceGrade.G1,
            models.RaceGrade.G2,
            models.RaceGrade.G3,
            models.RaceGrade.JPN1,
            models.RaceGrade.JPN2,
            models.RaceGrade.JPN3,
            models.RaceGrade.JG1,
            models.RaceGrade.JG2,
            models.RaceGrade.JG3,
        )
        versions = set()
        for grade in accepted:
            with self.subTest(grade=grade):
                decision = self._evaluate(
                    service,
                    year=2026,
                    region=models.RacingRegion.JAPAN,
                    grade=grade,
                )
                self.assertIs(self._field(decision, "eligible"), True)
                versions.add(self._field(decision, "matrix_version"))
        self.assertEqual(len(versions), 1)

    def test_listed_open_ordinary_and_unknown_regions_fail_closed(self):
        service = self._service()
        for region in (
            models.RacingRegion.UNITED_KINGDOM,
            models.RacingRegion.FRANCE,
            models.RacingRegion.UNITED_STATES,
            models.RacingRegion.HONG_KONG,
            models.RacingRegion.JAPAN,
        ):
            for grade in (
                models.RaceGrade.LISTED,
                models.RaceGrade.OPEN,
                models.RaceGrade.OTHER,
            ):
                with self.subTest(region=region, grade=grade):
                    decision = self._evaluate(
                        service,
                        year=2026,
                        region=region,
                        grade=grade,
                    )
                    self.assertIs(self._field(decision, "eligible"), False)

        decision = self._evaluate(
            service,
            year=2026,
            region=models.RacingRegion.OTHER,
            grade=models.RaceGrade.G1,
        )
        self.assertIs(self._field(decision, "eligible"), False)

    def test_normal_matrix_never_fabricates_an_exception_digest(self):
        service = self._service()
        decision = self._evaluate(
            service,
            year=2026,
            region=models.RacingRegion.JAPAN,
            grade=models.RaceGrade.JPN2,
        )
        self.assertEqual(self._field(decision, "exception_digest"), "")

    def _exception(self, *, event_ids=None, approved_commit="a" * 40):
        scoped = {
            "schema_version": 1,
            "approved_commit": approved_commit,
            "event_ids": event_ids or [1001],
            "reason": "用户批准的精确赛事资格例外",
            "approval_evidence_sha256": "b" * 64,
            "generated_at": self.NOW.isoformat(),
            "valid_until": (self.NOW + timedelta(days=7)).isoformat(),
        }
        return {
            **scoped,
            "scope_digest": hashlib.sha256(
                json.dumps(
                    scoped,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }

    def test_exact_exception_requires_matching_commit_event_scope_and_time(self):
        service = self._service()
        artifact = self._exception()

        accepted = service(
            event_id=1001,
            year=2026,
            region=models.RacingRegion.FRANCE,
            normalized_grade=models.RaceGrade.LISTED,
            exception_artifact=artifact,
            expected_approved_commit="a" * 40,
            now=self.NOW,
        )

        self.assertIs(self._field(accepted, "eligible"), True)
        self.assertEqual(
            self._field(accepted, "reason"),
            "exception_approved",
        )
        self.assertTrue(self._field(accepted, "exception_digest"))

        rejected_inputs = (
            {
                "event_id": 1002,
                "artifact": artifact,
                "commit": "a" * 40,
                "now": self.NOW,
            },
            {
                "event_id": 1001,
                "artifact": artifact,
                "commit": "c" * 40,
                "now": self.NOW,
            },
            {
                "event_id": 1001,
                "artifact": artifact,
                "commit": "a" * 40,
                "now": self.NOW + timedelta(days=8),
            },
            {
                "event_id": 1001,
                "artifact": {
                    **artifact,
                    "scope_digest": "0" * 64,
                },
                "commit": "a" * 40,
                "now": self.NOW,
            },
        )
        for case in rejected_inputs:
            with self.subTest(case=case):
                decision = service(
                    event_id=case["event_id"],
                    year=2026,
                    region=models.RacingRegion.FRANCE,
                    normalized_grade=models.RaceGrade.LISTED,
                    exception_artifact=case["artifact"],
                    expected_approved_commit=case["commit"],
                    now=case["now"],
                )
                self.assertIs(self._field(decision, "eligible"), False)
