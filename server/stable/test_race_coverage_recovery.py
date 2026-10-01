"""固定历史恢复包：无网络、先验证、单事务、写入者 CAS。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import TestCase
from stable import models
from stable.services import race_coverage_recovery as recovery
from stable.services.scheduled_race_result_review import (
    compute_event_baseline,
    compute_reviewed_row_digest,
)

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


class CoverageRecoveryTests(TestCase):
    def setUp(self):
        self.payloads = []
        for event_id in sorted(recovery.EVENT_IDS):
            e = models.RaceEvent.objects.create(
                id=event_id,
                year=2026,
                slug=f"recovery-{event_id}",
                original_name="Recovery",
                country_region="france",
                racecourse="Auteuil",
                local_date=NOW.date() - timedelta(days=10),
                timezone_name="Europe/Paris",
                status="finished",
                visibility_status="published",
            )
            models.RaceEventProjectionControl.objects.create(
                event=e,
                write_owner="data_sync",
                owner_generation=1,
                owner_manifest_sha256="a" * 64,
            )
            models.RaceEventLiveTracking.objects.create(event=e, tracking_enabled=True)
            source = models.RaceResultSourceIdentity.objects.create(
                event=e,
                source_key="the_racing_api",
                region_code="france",
                identity_namespace="test",
                external_race_id=str(event_id),
            )
            models.RaceDataSyncEnrollment.objects.create(
                event=e,
                source_identity=source,
                state="enrolled",
                standing_policy_digest="a" * 64,
                route_digest="a" * 64,
                event_snapshot_sha256="a" * 64,
                projection_owner_generation=1,
                manifest_sha256="a" * 64,
                entry_sha256="a" * 64,
            )
            rows = [
                dict(
                    finish_position=1,
                    horse_number="1",
                    horse_name="Horse A",
                    running_status="declared",
                ),
                dict(
                    finish_position=2,
                    horse_number="2",
                    horse_name="Horse B",
                    running_status="fell",
                ),
            ]
            for row in rows:
                models.RaceEventRunner.objects.create(
                    event=e,
                    horse_number=row["horse_number"],
                    horse_name=row["horse_name"],
                )
            self.payloads.append(
                dict(
                    event_id=event_id,
                    baseline_sha256=compute_event_baseline(e),
                    owner_generation=1,
                    owner_manifest_sha256="a" * 64,
                    results=rows,
                    reviewed_row_digest=compute_reviewed_row_digest(rows),
                    proofs=[dict(url="https://www.zeturf.fr/example", sha256="b" * 64)],
                )
            )

    def run_batch(self, apply=False, payloads=None):
        return recovery.recover_events(
            payloads=payloads or self.payloads,
            manifest_sha256="c" * 64,
            now=NOW,
            apply=apply,
        )

    def test_dry_run_does_not_mutate(self):
        self.assertEqual(self.run_batch()["status"], "ready")
        self.assertFalse(models.RaceEventResult.objects.exists())
        self.assertFalse(models.OperationLog.objects.exists())
        self.assertEqual(
            set(
                models.RaceEventProjectionControl.objects.values_list(
                    "write_owner", flat=True
                )
            ),
            {"data_sync"},
        )

    def test_apply_retire_then_handoff_and_idempotence(self):
        self.assertEqual(self.run_batch(apply=True)["status"], "applied")
        self.assertEqual(
            set(models.RaceDataSyncEnrollment.objects.values_list("state", flat=True)),
            {"retired"},
        )
        self.assertFalse(
            models.RaceEventLiveTracking.objects.filter(tracking_enabled=True).exists()
        )
        self.assertEqual(
            set(
                models.RaceEventProjectionControl.objects.values_list(
                    "write_owner", flat=True
                )
            ),
            {"historical"},
        )
        self.assertEqual(models.RaceEventResult.objects.count(), 14)
        fallen = models.RaceEventResult.objects.filter(running_status="fell").first()
        self.assertIsNone(fallen.official_finish_position)
        self.assertIsNone(fallen.reported_finish_position)
        self.assertEqual(fallen.source_refs["public_label"], "参考赛果（完整性已核验）")
        self.assertEqual(self.run_batch(apply=True)["status"], "already_applied")
        self.assertEqual(models.RaceResultReviewApproval.objects.count(), 7)

    def test_partial_rows_and_stale_baseline_fail_before_any_write(self):
        for mode in ("partial", "baseline", "digest"):
            p = deepcopy(self.payloads)
            if mode == "partial":
                p[-1]["results"].pop()
                p[-1]["reviewed_row_digest"] = compute_reviewed_row_digest(
                    p[-1]["results"]
                )
            elif mode == "baseline":
                p[-1]["baseline_sha256"] = "d" * 64
            else:
                p[-1]["reviewed_row_digest"] = "e" * 64
            with self.assertRaises(recovery.RecoveryBlocked):
                self.run_batch(apply=True, payloads=p)
            self.assertFalse(models.RaceEventResult.objects.exists())

    def test_active_claim_and_manual_pause_fail_closed(self):
        e = self.payloads[-1]["event_id"]
        models.RaceEventLiveTracking.objects.filter(event_id=e).update(
            active_attempt_token="busy", claim_expires_at=NOW + timedelta(minutes=10)
        )
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "active_claim"):
            self.run_batch(apply=True)
        models.RaceEventLiveTracking.objects.filter(event_id=e).update(
            active_attempt_token="", claim_expires_at=None
        )
        models.RaceEventLifecycleControl.objects.create(
            event_id=e, manual_pause_reason="review"
        )
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "manual_pause"):
            self.run_batch(apply=True)
        self.assertFalse(models.RaceEventResult.objects.exists())

    def test_writer_failure_rolls_back_entire_batch_and_ownership(self):
        with patch.object(
            recovery,
            "apply_reviewed_event_payloads",
            return_value={"events": [{"status": "blocked"}]},
        ):
            with self.assertRaises(recovery.RecoveryBlocked):
                self.run_batch(apply=True)
        self.assertEqual(
            set(
                models.RaceEventProjectionControl.objects.values_list(
                    "write_owner", flat=True
                )
            ),
            {"data_sync"},
        )
        self.assertEqual(
            set(models.RaceDataSyncEnrollment.objects.values_list("state", flat=True)),
            {"enrolled"},
        )

    def test_already_applied_modified_row_rejected(self):
        self.run_batch(apply=True)
        models.RaceEventResult.objects.filter(horse_number="1").update(
            horse_name="Changed"
        )
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "applied_result_drift"):
            self.run_batch(apply=True)

    def test_idempotence_checks_reported_position_and_owner_generation(self):
        self.run_batch(apply=True)
        row = models.RaceEventResult.objects.filter(running_status="fell").first()
        row.reported_finish_position = 2
        row.save(update_fields=["reported_finish_position"])
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "applied_result_drift"):
            self.run_batch(apply=True)
        row.reported_finish_position = None
        row.save(update_fields=["reported_finish_position"])
        models.RaceEventProjectionControl.objects.filter(event_id=row.event_id).update(
            owner_generation=999
        )
        with self.assertRaisesRegex(recovery.RecoveryBlocked, "applied_result_drift"):
            self.run_batch(apply=True)
