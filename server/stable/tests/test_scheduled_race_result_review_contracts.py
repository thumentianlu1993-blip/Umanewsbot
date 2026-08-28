"""RED contracts for the scheduled race-result review workflow.

The new scheduler must keep the already-reviewed one-off recovery guarantees,
while replacing its hand-written target map with a deterministic selector,
durable delivery state and an exact reviewed-bundle apply boundary.
"""

from __future__ import annotations

import csv
import importlib
import io
import tempfile
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from stable import models
from stable.services import race_event_crawl_orchestration as orchestration


NOW = datetime(2026, 7, 27, 10, 30, tzinfo=dt_timezone.utc)
BUNDLE_SHA = "a" * 64
ROW_DIGEST_ONE = "b" * 64
ROW_DIGEST_TWO = "c" * 64


def _scheduled_service(test_case):
    try:
        return importlib.import_module(
            "stable.services.scheduled_race_result_review"
        )
    except ModuleNotFoundError:
        test_case.fail(
            "缺少 stable.services.scheduled_race_result_review；"
            "RED 要求实现已审核方案中的定时 selector、bundle、delivery 与 apply 服务"
        )


class ScheduledRaceResultReviewPureContractTests(SimpleTestCase):
    maxDiff = None

    def test_missed_slots_coalesce_to_latest_due_slot_with_one_budget(self):
        service = _scheduled_service(self)
        due_slots = [
            NOW - timedelta(hours=12 * offset)
            for offset in range(27, -1, -1)
        ]

        result = service.coalesce_due_schedule_slots(
            due_slots=due_slots,
            now=NOW,
            max_catchup_days=14,
        )

        self.assertEqual(result["execute_slot"], NOW)
        self.assertEqual(result["request_budget_count"], 1)
        self.assertEqual(
            result["coalesced_slots"],
            [
                {
                    "schedule_slot": slot,
                    "terminal_state": "coalesced_to_latest_due_slot",
                }
                for slot in due_slots[:-1]
            ],
        )
        self.assertEqual(result["expired_slots"], [])

    def test_canonical_route_is_selected_and_alias_drift_has_zero_transport(self):
        service = _scheduled_service(self)
        manifest = {
            "canonical_adapter": "uk_sporting_life_detail",
            "region": models.RacingRegion.UNITED_KINGDOM,
            "provider": "sporting_life",
            "source_authority": "third_party_high_access",
            "modules": ["results"],
        }
        canonical_route = {
            "key": "uk-sporting-life-results-v1",
            "region": models.RacingRegion.UNITED_KINGDOM,
            "provider": "sporting_life",
            "adapter": "uk_sporting_life_detail",
            "source_authority": "third_party_high_access",
            "candidate_permission": "internal_reference",
            "identity_namespaces": ["sporting_life"],
            "modules": ["results"],
            "automation_allowed": True,
            "valid_until": "2026-12-31T23:59:59Z",
        }
        event_identity = {
            "event_id": 426,
            "country_region": models.RacingRegion.UNITED_KINGDOM,
            "provider": "sporting_life",
            "identity_namespace": "sporting_life",
        }
        transport = mock.Mock(return_value={"status": "ok"})

        selected = service.prepare_target_with_route(
            event_identity=event_identity,
            routes=[canonical_route],
            adapter_manifests={"uk_sporting_life_detail": manifest},
            now=NOW,
            transport=transport,
        )
        self.assertEqual(selected["route_key"], canonical_route["key"])
        self.assertEqual(selected["authority"], "third_party_high_access")
        self.assertEqual(transport.call_count, 1)

        alias_route = {
            **canonical_route,
            "adapter": "uk_sporting_life_results",
        }
        transport.reset_mock()
        blocked = service.prepare_target_with_route(
            event_identity=event_identity,
            routes=[alias_route],
            adapter_manifests={"uk_sporting_life_detail": manifest},
            now=NOW,
            transport=transport,
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason_code"], "route_adapter_contract_mismatch")
        transport.assert_not_called()

    def test_complete_numeric_order_passes_but_also_ran_is_never_a_position(self):
        complete = {
            "event_id": 426,
            "modules": {
                models.RaceEventModule.RUNNERS: {
                    "items": [
                        {"horse_number": "1", "horse_name": "Alpha"},
                        {"horse_number": "2", "horse_name": "Beta"},
                    ]
                },
                models.RaceEventModule.RESULTS: {
                    "items": [
                        {
                            "finish_position": 1,
                            "horse_number": "1",
                            "horse_name": "Alpha",
                        },
                        {
                            "finish_position": 2,
                            "horse_number": "2",
                            "horse_name": "Beta",
                        },
                    ]
                },
            },
        }
        orchestration._annotate_recovery_result_order(complete)
        self.assertTrue(complete["metadata"]["result_order_complete"])

        also_ran = {
            "event_id": 426,
            "modules": {
                models.RaceEventModule.RUNNERS: {
                    "items": [
                        {"horse_number": "1", "horse_name": "Alpha"},
                        {"horse_number": "2", "horse_name": "Beta"},
                    ]
                },
                models.RaceEventModule.RESULTS: {
                    "items": [
                        {
                            "finish_position": 1,
                            "horse_number": "1",
                            "horse_name": "Alpha",
                        },
                        {
                            "finish_position": "Also ran",
                            "horse_number": "2",
                            "horse_name": "Beta",
                        },
                    ]
                },
            },
        }
        orchestration._annotate_recovery_result_order(also_ran)
        self.assertFalse(also_ran["metadata"]["result_order_complete"])
        self.assertEqual(
            also_ran["metadata"]["result_order_check"]["reason"],
            "missing_or_invalid_finish_position",
        )
        self.assertEqual(
            also_ran["metadata"]["result_order_check"]["invalid_positions"],
            ["Also ran"],
        )

    def test_review_payload_csv_and_reviewed_digest_are_bidirectionally_equal(self):
        service = _scheduled_service(self)
        candidate_events = [
            {
                "event_id": 426,
                "event_name": "Eddie Read Stakes",
                "race_datetime": "2026-07-27T01:30:00Z",
                "source_authority": "third_party_high_access",
                "approval_authority": "human_reviewed_reference",
                "result_order_complete": True,
                "results": [
                    {
                        "finish_position": 1,
                        "horse_number": "5",
                        "horse_name": "Gold Phoenix",
                        "running_status": "finished",
                    },
                    {
                        "finish_position": 2,
                        "horse_number": "3",
                        "horse_name": "Cabo Spirit",
                        "running_status": "finished",
                    },
                ],
            }
        ]

        payload = service.build_review_payload(candidate_events=candidate_events)
        csv_bytes = service.render_review_csv(payload=payload)
        verified = service.verify_review_payload_csv(
            payload=payload,
            csv_bytes=csv_bytes,
        )

        self.assertTrue(verified["equivalent"])
        event_payload = payload["events"][0]
        self.assertEqual(
            event_payload["reviewed_row_digest"],
            service.compute_reviewed_row_digest(event_payload["results"]),
        )
        rows = list(
            csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row["horse_name"] for row in rows],
            ["Gold Phoenix", "Cabo Spirit"],
        )

        tampered = csv_bytes.replace(b"Cabo Spirit", b"Hidden Runner")
        with self.assertRaises(service.ReviewBundleDrift) as caught:
            service.verify_review_payload_csv(
                payload=payload,
                csv_bytes=tampered,
            )
        self.assertEqual(caught.exception.reason_code, "review_csv_payload_drift")

    def test_delivery_lease_reuses_message_id_and_is_at_least_once(self):
        service = _scheduled_service(self)
        message_id = f"<{BUNDLE_SHA}@umafans.run>"

        first = service.plan_delivery_attempt(
            bundle_sha256=BUNDLE_SHA,
            recipient="754652181@qq.com",
            current_state={
                "status": "queued",
                "attempt_count": 0,
                "message_id": "",
                "lease_expires_at": None,
            },
            now=NOW,
            lease_seconds=300,
        )
        self.assertEqual(first["action"], "send")
        self.assertEqual(first["attempt_count"], 1)
        self.assertEqual(first["message_id"], message_id)

        stale_unknown = service.plan_delivery_attempt(
            bundle_sha256=BUNDLE_SHA,
            recipient="754652181@qq.com",
            current_state={
                "status": "sending",
                "attempt_count": 1,
                "message_id": message_id,
                "lease_expires_at": NOW - timedelta(seconds=1),
            },
            now=NOW,
            lease_seconds=300,
        )
        self.assertEqual(stale_unknown["action"], "send")
        self.assertEqual(stale_unknown["attempt_count"], 2)
        self.assertEqual(stale_unknown["message_id"], message_id)
        self.assertEqual(stale_unknown["delivery_semantics"], "at_least_once")

        sent = service.plan_delivery_attempt(
            bundle_sha256=BUNDLE_SHA,
            recipient="754652181@qq.com",
            current_state={
                "status": "sent",
                "attempt_count": 2,
                "message_id": message_id,
                "lease_expires_at": None,
            },
            now=NOW,
            lease_seconds=300,
        )
        self.assertEqual(sent["action"], "already_notified")

    def test_authority_planner_never_promotes_reference_to_official(self):
        service = _scheduled_service(self)
        result_rows = [
            {
                "finish_position": 1,
                "horse_number": "5",
                "horse_name": "Gold Phoenix",
            }
        ]

        reviewed = service.plan_reviewed_event_write(
            authority="human_reviewed_reference",
            source_authority="third_party_high_access",
            result_rows=result_rows,
        )
        self.assertEqual(reviewed["public_label"], "已人工审核赛果")
        self.assertFalse(reviewed["create_official_receipt"])
        self.assertEqual(reviewed["result_rows"][0]["official_finish_position"], None)
        self.assertEqual(
            reviewed["source_authority"],
            "third_party_high_access",
        )

        official = service.plan_reviewed_event_write(
            authority="official",
            source_authority="official",
            result_rows=result_rows,
        )
        self.assertEqual(official["public_label"], "官方赛果")
        self.assertTrue(official["create_official_receipt"])
        self.assertEqual(
            official["result_rows"][0]["official_finish_position"],
            1,
        )


class ScheduledRaceResultReviewDatabaseContractTests(TestCase):
    maxDiff = None

    def _event(
        self,
        slug: str,
        *,
        race_datetime: datetime,
        status: str = models.RaceEventStatus.SCHEDULED,
    ):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Goodwood",
            grade_text="G2",
            surface=models.RaceEventSurface.TURF,
            timezone_name="Europe/London",
            local_date=race_datetime.date(),
            race_datetime=race_datetime,
            status=status,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            source_refs={
                "provider": "sporting_life",
                "sporting_life": f"race-{slug}",
            },
        )

    def test_selector_includes_72h_boundary_pending_and_status_repair(self):
        service = _scheduled_service(self)
        at_boundary = self._event(
            "at-boundary",
            race_datetime=NOW - timedelta(hours=72),
        )
        outside = self._event(
            "outside",
            race_datetime=NOW - timedelta(hours=72, microseconds=1),
        )
        pending_outside = self._event(
            "pending-outside",
            race_datetime=NOW - timedelta(days=5),
        )
        status_repair = self._event(
            "status-repair",
            race_datetime=NOW - timedelta(hours=3),
        )
        models.RaceEventResult.objects.create(
            event=status_repair,
            finish_position=1,
            horse_number="1",
            horse_name="Confirmed Winner",
            is_confirmed=True,
        )
        status_repair.result_confirmed_at = NOW - timedelta(hours=2)
        status_repair.save(update_fields=("result_confirmed_at", "updated_at"))

        snapshot = service.select_due_targets(
            now=NOW,
            pending_event_ids=[pending_outside.pk],
            lookback_hours=72,
            pending_max_age_days=14,
        )
        by_id = {row["event_id"]: row for row in snapshot["targets"]}

        self.assertIn(at_boundary.pk, by_id)
        self.assertNotIn(outside.pk, by_id)
        self.assertIn(pending_outside.pk, by_id)
        self.assertEqual(by_id[pending_outside.pk]["target_reason"], "pending")
        self.assertIn(status_repair.pk, by_id)
        self.assertEqual(
            by_id[status_repair.pk]["result_state"],
            "status_repair_required",
        )
        self.assertFalse(by_id[status_repair.pk]["network_required"])
        self.assertEqual(len(snapshot["selector_sha256"]), 64)

    def test_apply_is_atomic_per_event_and_keeps_authority_split(self):
        service = _scheduled_service(self)
        first = self._event(
            "apply-first",
            race_datetime=NOW - timedelta(hours=4),
        )
        second = self._event(
            "apply-second",
            race_datetime=NOW - timedelta(hours=5),
        )
        payloads = [
            {
                "event_id": first.pk,
                "baseline_sha256": service.compute_event_baseline(first),
                "authority": "human_reviewed_reference",
                "source_authority": "third_party_high_access",
                "reviewed_row_digest": ROW_DIGEST_ONE,
                "result_order_complete": True,
                "results": [
                    {
                        "finish_position": 1,
                        "horse_number": "5",
                        "horse_name": "Gold Phoenix",
                        "running_status": "finished",
                    }
                ],
            },
            {
                "event_id": second.pk,
                "baseline_sha256": service.compute_event_baseline(second),
                "authority": "official",
                "source_authority": "official",
                "reviewed_row_digest": ROW_DIGEST_TWO,
                "result_order_complete": True,
                "results": [
                    {
                        "finish_position": 1,
                        "horse_number": "1",
                        "horse_name": "Official Winner",
                        "running_status": "finished",
                    }
                ],
            },
        ]

        def fault_hook(*, event_id, stage):
            if event_id == second.pk and stage == "after_results":
                raise RuntimeError("injected_after_results")

        summary = service.apply_reviewed_event_payloads(
            bundle_sha256=BUNDLE_SHA,
            approved_event_ids=[first.pk, second.pk],
            reviewer="754652181@qq.com",
            event_payloads=payloads,
            confirmed_at=NOW,
            fault_hook=fault_hook,
        )

        first.refresh_from_db()
        second.refresh_from_db()
        first_result = models.RaceEventResult.objects.get(event=first)
        self.assertEqual(first.status, models.RaceEventStatus.FINISHED)
        self.assertTrue(first_result.is_confirmed)
        self.assertIsNone(first_result.official_finish_position)
        self.assertEqual(
            first_result.source_refs["approval_authority"],
            "human_reviewed_reference",
        )
        self.assertFalse(
            service.has_official_receipt(
                event_id=first.pk,
                bundle_sha256=BUNDLE_SHA,
            )
        )

        self.assertEqual(second.status, models.RaceEventStatus.SCHEDULED)
        self.assertFalse(models.RaceEventResult.objects.filter(event=second).exists())
        self.assertEqual(
            summary["events"],
            [
                {"event_id": first.pk, "status": "applied"},
                {
                    "event_id": second.pk,
                    "status": "blocked",
                    "reason_code": "apply_event_rolled_back",
                },
            ],
        )

    def test_apply_rechecks_baseline_after_event_row_lock(self):
        service = _scheduled_service(self)
        event = self._event(
            "locked-baseline-drift",
            race_datetime=NOW - timedelta(hours=4),
        )
        baseline = service.compute_event_baseline(event)
        event.original_name = "Concurrent writer changed identity"
        event.save(update_fields=("original_name", "updated_at"))
        payload = {
            "event_id": event.pk,
            "authority": "human_reviewed_reference",
            "source_authority": "third_party_high_access",
            "baseline_sha256": baseline,
            "result_order_complete": True,
            "results": [
                {
                    "finish_position": 1,
                    "horse_number": "5",
                    "horse_name": "Gold Phoenix",
                    "running_status": "finished",
                }
            ],
        }
        payload["reviewed_row_digest"] = service.compute_reviewed_row_digest(
            payload["results"]
        )

        summary = service.apply_reviewed_event_payloads(
            bundle_sha256=BUNDLE_SHA,
            approved_event_ids=[event.pk],
            reviewer="reviewer@example.test",
            event_payloads=[payload],
            confirmed_at=NOW,
        )

        event.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.SCHEDULED)
        self.assertFalse(event.results.exists())
        self.assertEqual(
            summary["events"],
            [
                {
                    "event_id": event.pk,
                    "status": "blocked",
                    "reason_code": "database_baseline_drift",
                }
            ],
        )

    @override_settings(RACE_RESULT_REVIEW_ENABLED=True)
    def test_valid_schedule_slot_lease_rejects_second_prepare(self):
        service = _scheduled_service(self)
        models.RaceResultReviewRun.objects.create(
            schedule_slot=NOW,
            status="claimed",
            lease_expires_at=NOW + timedelta(minutes=10),
        )
        with mock.patch.object(service.timezone, "now", return_value=NOW), mock.patch.object(
            service, "prepare_review_bundle"
        ) as prepare:
            result = service.run_scheduled_prepare(schedule_slot=NOW)
        self.assertEqual(result["status"], "already_claimed")
        prepare.assert_not_called()

    @override_settings(RACE_RESULT_REVIEW_ENABLED=True)
    def test_stale_schedule_slot_lease_is_taken_over_once(self):
        service = _scheduled_service(self)
        run = models.RaceResultReviewRun.objects.create(
            schedule_slot=NOW,
            status="claimed",
            lease_expires_at=NOW - timedelta(seconds=1),
        )
        with mock.patch.object(service.timezone, "now", return_value=NOW), mock.patch.object(
            service,
            "prepare_review_bundle",
            return_value={
                "status": "noop",
                "selector_sha256": "d" * 64,
                "target_count": 0,
            },
        ) as prepare:
            result = service.run_scheduled_prepare(schedule_slot=NOW)
        run.refresh_from_db()
        self.assertEqual(result["status"], "noop")
        self.assertEqual(run.status, "noop")
        prepare.assert_called_once()

    @override_settings(RACE_RESULT_REVIEW_ENABLED=True)
    def test_automatic_catchup_persists_json_serializable_terminal_summary(self):
        service = _scheduled_service(self)
        with mock.patch.object(service.timezone, "now", return_value=NOW), mock.patch.object(
            service,
            "prepare_review_bundle",
            return_value={
                "status": "noop",
                "selector_sha256": "d" * 64,
                "target_count": 0,
            },
        ):
            result = service.run_scheduled_prepare()

        coalesced = models.RaceResultReviewRun.objects.filter(
            status="coalesced_to_latest_due_slot"
        ).order_by("schedule_slot")
        self.assertEqual(result["status"], "noop")
        self.assertEqual(coalesced.count(), 27)
        self.assertEqual(
            coalesced.first().terminal_summary["schedule_slot"],
            coalesced.first().schedule_slot.isoformat(),
        )

    @override_settings(RACE_RESULT_REVIEW_ENABLED=True)
    def test_stale_worker_cannot_publish_terminal_state_after_cas_takeover(self):
        service = _scheduled_service(self)

        def lose_lease(**kwargs):
            models.RaceResultReviewRun.objects.filter(schedule_slot=NOW).update(
                cursor={"claim_token": "new-owner"}
            )
            return {
                "status": "noop",
                "selector_sha256": "d" * 64,
                "target_count": 0,
            }

        with mock.patch.object(service.timezone, "now", return_value=NOW), mock.patch.object(
            service,
            "prepare_review_bundle",
            side_effect=lose_lease,
        ):
            result = service.run_scheduled_prepare(schedule_slot=NOW)

        run = models.RaceResultReviewRun.objects.get(schedule_slot=NOW)
        self.assertEqual(result["status"], "lease_lost")
        self.assertEqual(run.status, "claimed")
        self.assertEqual(run.cursor, {"claim_token": "new-owner"})

    def test_apply_verify_and_replay_use_post_write_evidence_not_before_baseline(self):
        service = _scheduled_service(self)
        event = self._event(
            "command-verify-replay",
            race_datetime=NOW - timedelta(hours=4),
        )
        results = [
            {
                "finish_position": 1,
                "horse_number": "5",
                "horse_name": "Gold Phoenix",
                "running_status": "finished",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            artifact = service.write_immutable_bundle(
                root=Path(directory),
                inventory={"selector_sha256": "d" * 64, "targets": []},
                candidates=[
                    {
                        "event_id": event.pk,
                        "event_name": event.chinese_name,
                        "race_datetime": event.race_datetime.isoformat(),
                        "source_authority": "third_party_high_access",
                        "approval_authority": "human_reviewed_reference",
                        "baseline_sha256": service.compute_event_baseline(event),
                        "result_order_complete": True,
                        "results": results,
                    }
                ],
                blockers=[],
                dry_run={"database_writes": 0},
            )
            digest = service.compute_reviewed_row_digest(results)
            common = (
                "--bundle-dir",
                artifact["bundle_dir"],
                "--expected-bundle-sha256",
                artifact["bundle_sha256"],
                "--approve",
                f"{event.pk}:{digest}",
            )
            call_command(
                "apply_reviewed_race_result_bundle",
                *common,
                "--reviewer",
                "reviewer@example.test",
                "--apply",
                "--confirm-apply",
                stdout=io.StringIO(),
            )
            verify_output = io.StringIO()
            call_command(
                "apply_reviewed_race_result_bundle",
                *common,
                "--verify",
                stdout=verify_output,
            )
            replay_output = io.StringIO()
            call_command(
                "apply_reviewed_race_result_bundle",
                *common,
                "--reviewer",
                "reviewer@example.test",
                "--apply",
                "--confirm-apply",
                stdout=replay_output,
            )
        self.assertIn('"status": "verified"', verify_output.getvalue())
        self.assertIn('"status": "already_applied"', replay_output.getvalue())

    def test_verify_rejects_empty_approval_scope(self):
        service = _scheduled_service(self)
        with tempfile.TemporaryDirectory() as directory:
            artifact = service.write_immutable_bundle(
                root=Path(directory),
                inventory={"selector_sha256": "d" * 64, "targets": []},
                candidates=[],
                blockers=[{"event_id": 426, "reason_code": "blocked"}],
                dry_run={"database_writes": 0},
            )
            with self.assertRaisesMessage(
                CommandError,
                "--verify 需要至少一个 --approve",
            ):
                call_command(
                    "apply_reviewed_race_result_bundle",
                    "--bundle-dir",
                    artifact["bundle_dir"],
                    "--expected-bundle-sha256",
                    artifact["bundle_sha256"],
                    "--verify",
                    stdout=io.StringIO(),
                )

    def test_apply_command_emits_summary_but_exits_nonzero_for_any_incomplete_scope(self):
        service = _scheduled_service(self)
        event = self._event(
            "command-blocked-summary",
            race_datetime=NOW - timedelta(hours=4),
        )
        results = [
            {
                "finish_position": 1,
                "horse_number": "5",
                "horse_name": "Gold Phoenix",
                "running_status": "finished",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            artifact = service.write_immutable_bundle(
                root=Path(directory),
                inventory={"selector_sha256": "d" * 64, "targets": []},
                candidates=[
                    {
                        "event_id": event.pk,
                        "event_name": event.chinese_name,
                        "race_datetime": event.race_datetime.isoformat(),
                        "source_authority": "third_party_high_access",
                        "approval_authority": "human_reviewed_reference",
                        "baseline_sha256": service.compute_event_baseline(event),
                        "result_order_complete": True,
                        "results": results,
                    }
                ],
                blockers=[],
                dry_run={"database_writes": 0},
            )
            digest = service.compute_reviewed_row_digest(results)
            cases = (
                {
                    "bundle_sha256": artifact["bundle_sha256"],
                    "events": [
                        {
                            "event_id": event.pk,
                            "status": "blocked",
                            "reason_code": "database_baseline_drift",
                        }
                    ],
                    "unexpected": [],
                },
                {
                    "bundle_sha256": artifact["bundle_sha256"],
                    "events": [],
                    "unexpected": [],
                },
                {
                    "bundle_sha256": artifact["bundle_sha256"],
                    "events": [{"event_id": event.pk, "status": "applied"}],
                    "unexpected": [999],
                },
            )
            for result in cases:
                with self.subTest(result=result):
                    output = io.StringIO()
                    with mock.patch(
                        "stable.management.commands.apply_reviewed_race_result_bundle.apply_reviewed_event_payloads",
                        return_value=result,
                    ), self.assertRaises(CommandError):
                        call_command(
                            "apply_reviewed_race_result_bundle",
                            "--bundle-dir",
                            artifact["bundle_dir"],
                            "--expected-bundle-sha256",
                            artifact["bundle_sha256"],
                            "--approve",
                            f"{event.pk}:{digest}",
                            "--reviewer",
                            "reviewer@example.test",
                            "--apply",
                            "--confirm-apply",
                            stdout=output,
                        )
                    self.assertIn(
                        f'"bundle_sha256": "{artifact["bundle_sha256"]}"',
                        output.getvalue(),
                    )

    def test_public_detail_does_not_label_result_source_class(self):
        service = _scheduled_service(self)
        human = self._event(
            "human-reviewed-public-label",
            race_datetime=NOW - timedelta(hours=4),
            status=models.RaceEventStatus.FINISHED,
        )
        official = self._event(
            "official-public-label",
            race_datetime=NOW - timedelta(hours=5),
            status=models.RaceEventStatus.FINISHED,
        )
        human_result = models.RaceEventResult.objects.create(
            event=human,
            finish_position=1,
            official_finish_position=None,
            horse_name="Human Winner",
            is_confirmed=True,
            source_refs={"approval_authority": "human_reviewed_reference"},
        )
        models.RaceEventResult.objects.create(
            event=official,
            finish_position=1,
            official_finish_position=1,
            horse_name="Official Winner",
            is_confirmed=True,
            source_refs={"approval_authority": "official"},
        )
        human_digest = service.compute_reviewed_row_digest(
            [
                {
                    "finish_position": human_result.finish_position,
                    "horse_number": human_result.horse_number,
                    "horse_name": human_result.horse_name,
                    "running_status": human_result.running_status,
                }
            ]
        )
        models.RaceResultReviewApproval.objects.create(
            bundle_sha256=BUNDLE_SHA,
            event=human,
            reviewed_row_digest=human_digest,
            authority="human_reviewed_reference",
            reviewer="reviewer@example.test",
            confirmed_at=NOW,
        )

        human_response = self.client.get(human.public_path)
        official_response = self.client.get(official.public_path)

        for response in (human_response, official_response):
            self.assertContains(response, "<h2>赛果</h2>", html=True)
            self.assertNotContains(response, "正式赛果")
            self.assertNotContains(response, "已人工审核赛果")


class ScheduledRaceResultReviewGreenIntegrationTests(TestCase):
    def _bundle(self, root: Path):
        service = _scheduled_service(self)
        return service.write_immutable_bundle(
            root=root,
            inventory={"selector_sha256": "d" * 64, "targets": []},
            candidates=[
                {
                    "event_id": 426,
                    "event_name": "Review Race",
                    "race_datetime": "2026-07-27T01:30:00Z",
                    "source_authority": "third_party_high_access",
                    "approval_authority": "human_reviewed_reference",
                    "result_order_complete": True,
                    "results": [
                        {
                            "finish_position": 1,
                            "horse_number": "5",
                            "horse_name": "Gold Phoenix",
                            "running_status": "finished",
                        }
                    ],
                }
            ],
            blockers=[],
            dry_run={"database_writes": 0},
        )

    def test_immutable_bundle_round_trip_and_file_drift_block(self):
        service = _scheduled_service(self)
        with tempfile.TemporaryDirectory() as directory:
            artifact = self._bundle(Path(directory))
            verified = service.verify_bundle(
                bundle_dir=Path(artifact["bundle_dir"]),
                expected_bundle_sha256=artifact["bundle_sha256"],
            )
            self.assertTrue(verified["verified"])
            csv_path = Path(artifact["bundle_dir"]) / "review.csv"
            csv_path.chmod(0o640)
            csv_path.write_bytes(csv_path.read_bytes() + b"tamper")
            with self.assertRaises(service.ReviewBundleDrift) as caught:
                service.verify_bundle(
                    bundle_dir=Path(artifact["bundle_dir"]),
                    expected_bundle_sha256=artifact["bundle_sha256"],
                )
            self.assertEqual(caught.exception.reason_code, "bundle_file_drift")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="review@example.test",
    )
    def test_delivery_writes_intent_attaches_allowlist_and_deduplicates_sent(self):
        service = _scheduled_service(self)
        with tempfile.TemporaryDirectory() as directory:
            artifact = self._bundle(Path(directory))
            sent = service.deliver_bundle_email(
                bundle_dir=Path(artifact["bundle_dir"]),
                bundle_sha256=artifact["bundle_sha256"],
                recipient="reviewer@example.test",
                now=NOW,
            )
            replay = service.deliver_bundle_email(
                bundle_dir=Path(artifact["bundle_dir"]),
                bundle_sha256=artifact["bundle_sha256"],
                recipient="reviewer@example.test",
                now=NOW + timedelta(minutes=10),
            )
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(replay["status"], "already_notified")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            {attachment[0] for attachment in mail.outbox[0].attachments},
            {"review_payload.json", "review.csv", "dry_run.json", "manifest.json"},
        )
        delivery = models.RaceResultReviewDelivery.objects.get()
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(
            delivery.message_id,
            f"<{artifact['bundle_sha256']}@umafans.run>",
        )

    def test_schedule_and_release_defaults_are_fail_closed(self):
        schedule = settings.CELERY_BEAT_SCHEDULE["scheduled-race-result-review"]
        self.assertEqual(str(schedule["schedule"]), "<crontab: 30 6,18 * * * (m/h/dM/MY/d)>")
        self.assertEqual(
            settings.CELERY_TASK_ROUTES[
                "stable.tasks.scheduled_race_result_review_task"
            ]["queue"],
            "celery",
        )
        self.assertFalse(settings.RACE_RESULT_REVIEW_ENABLED)
        self.assertFalse(settings.RACE_RESULT_REVIEW_ALLOW_NETWORK)
