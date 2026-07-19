from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import inspect
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable import tasks
from stable.services import race_events


class RaceLiveEnabledRegionSelectorTests(TestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def test_settings_define_a_fail_closed_empty_region_ceiling(self):
        self.assertTrue(
            hasattr(settings, "RACE_LIVE_ENABLED_REGIONS"),
            "RACE_LIVE_ENABLED_REGIONS 设置尚未实现",
        )
        self.assertEqual(tuple(settings.RACE_LIVE_ENABLED_REGIONS), ())

    @override_settings(
        RACE_LIVE_SCHEDULER_ENABLED=True,
        RACE_LIVE_ENABLED_REGIONS=(),
        RACE_LIVE_SELECTOR_BATCH_SIZE=20,
        RACE_LIVE_CLAIM_TTL_SECONDS=120,
    )
    @patch("stable.tasks.poll_race_live_event_task.apply_async")
    @patch("stable.tasks.claim_due_race_event_live_tracking")
    def test_scheduler_true_with_empty_regions_claims_and_dispatches_nothing(
        self,
        claim_due,
        apply_async,
    ):
        result = tasks.select_due_race_live_events_task.run()

        claim_due.assert_not_called()
        apply_async.assert_not_called()
        self.assertIs(result["enabled"], False)
        self.assertEqual(result["claimed"], 0)
        self.assertEqual(result["dispatched"], 0)

    @override_settings(
        RACE_LIVE_SCHEDULER_ENABLED=True,
        RACE_LIVE_ENABLED_REGIONS=(models.RacingRegion.FRANCE,),
        RACE_LIVE_SELECTOR_BATCH_SIZE=20,
        RACE_LIVE_CLAIM_TTL_SECONDS=120,
    )
    @patch("stable.tasks.poll_race_live_event_task.apply_async")
    @patch("stable.tasks.claim_due_race_event_live_tracking")
    @patch("stable.tasks.timezone.now")
    def test_selector_passes_the_exact_enabled_region_set_into_the_claim(
        self,
        now,
        claim_due,
        apply_async,
    ):
        now.return_value = self.NOW
        claim_due.return_value = ()

        result = tasks.select_due_race_live_events_task.run()

        claim_due.assert_called_once_with(
            now=self.NOW,
            batch_size=20,
            ttl_seconds=120,
            enabled_regions=(models.RacingRegion.FRANCE,),
        )
        apply_async.assert_not_called()
        self.assertEqual(
            result,
            {"enabled": True, "claimed": 0, "dispatched": 0},
        )

    def test_claim_service_exposes_an_enabled_region_hard_gate(self):
        parameter_names = inspect.signature(
            race_events.claim_due_race_event_live_tracking
        ).parameters
        self.assertIn(
            "enabled_regions",
            parameter_names,
            "claim service 尚未接受 enabled_regions 上限",
        )

    def test_worker_preflight_is_a_separate_network_admission_capability(self):
        preflight = getattr(
            race_events,
            "resolve_race_live_worker_network_admission",
            None,
        )
        self.assertTrue(
            callable(preflight),
            "worker 网络前二次准入尚未实现",
        )

    @override_settings(
        RACE_LIVE_RUNNER_MODE="the_racing_api_free",
        RACE_LIVE_ENABLED_REGIONS=(),
    )
    @patch("stable.tasks.complete_race_event_live_checkpoint")
    @patch("stable.tasks.resolve_race_live_worker_network_admission")
    @patch(
        "stable.services.race_live_runner.run_race_live_the_racing_api_free"
    )
    def test_stale_task_with_empty_region_ceiling_fails_before_runner_network(
        self,
        runner,
        preflight,
        checkpoint,
    ):
        preflight.return_value = (
            race_events.RaceLiveWorkerNetworkAdmissionDecision(
                False,
                "region_not_enabled",
            )
        )

        result = tasks.poll_race_live_event_task.run(
            event_id=123,
            expected_owner_generation=1,
            expected_claim_generation=2,
            attempt_token="stale-task-token",
        )

        preflight.assert_called_once()
        checkpoint.assert_called_once()
        runner.assert_not_called()
        self.assertEqual(
            result["reason"],
            "network_admission_region_not_enabled",
        )

    def test_claim_hard_filters_due_rows_by_the_enabled_region_ceiling(self):
        for region, slug in (
            (models.RacingRegion.FRANCE, "fr-enabled-claim"),
            (models.RacingRegion.JAPAN, "jp-disabled-claim"),
        ):
            event = models.RaceEvent.objects.create(
                year=2026,
                slug=slug,
                original_name=slug,
                chinese_name=slug,
                country_region=region,
                racecourse="Test",
                grade_text="G1",
                normalized_grade=models.RaceGrade.G1,
                surface=models.RaceEventSurface.TURF,
            )
            models.RaceEventProjectionControl.objects.create(
                event=event,
                write_owner=models.RaceEventProjectionWriteOwner.LIVE,
                owner_generation=1,
            )
            models.RaceEventLiveTracking.objects.create(
                event=event,
                tracking_enabled=True,
                next_poll_at=self.NOW,
            )

        claims = race_events.claim_due_race_event_live_tracking(
            now=self.NOW,
            batch_size=20,
            ttl_seconds=120,
            enabled_regions=(models.RacingRegion.FRANCE,),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(
            models.RaceEvent.objects.get(pk=claims[0].event_id).country_region,
            models.RacingRegion.FRANCE,
        )


class RaceLivePollingWindowContractTests(SimpleTestCase):
    NOW = datetime(2026, 7, 20, 8, 0, tzinfo=dt_timezone.utc)

    def test_pre_off_windows_remain_bounded_instead_of_all_day_scanning(self):
        cases = (
            (timedelta(hours=12), timedelta(hours=1)),
            (timedelta(hours=1), timedelta(minutes=15)),
            (timedelta(minutes=20), timedelta(minutes=5)),
        )
        for until_off, expected_delay in cases:
            with self.subTest(until_off=until_off):
                next_poll = race_events.calculate_race_live_next_poll_at(
                    off_time=self.NOW + until_off,
                    now=self.NOW,
                    state=models.RaceEventLiveState.RACECARD_READY,
                )
                self.assertEqual(next_poll, self.NOW + expected_delay)

    def test_post_off_provisional_search_uses_three_minute_polling(self):
        next_poll = race_events.calculate_race_live_next_poll_at(
            off_time=self.NOW - timedelta(minutes=1),
            now=self.NOW,
            state=models.RaceEventLiveState.AWAITING_RESULT,
        )
        self.assertEqual(next_poll, self.NOW + timedelta(minutes=3))
