"""带日期库存 target 物化为 RaceEvent 草稿的测试。

覆盖 `materialize_scheduled_historical_event` 服务函数与
`materialize_dated_race_targets` 门禁命令（dry-run / apply / verify）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_batches import (
    materialize_historical_event,
    materialize_scheduled_historical_event,
)
from stable.services.historical_race_inventory import InventoryValidationError


INVENTORY_SHA = "a" * 64
FOREIGN_INVENTORY_SHA = "b" * 64


class DatedTargetFixtures:
    """共享fixture：动态计算过去/未来日期，避免测试依赖真实日历日。"""

    def setUp(self):
        super().setUp()
        self.operator = get_user_model().objects.create_user(username="operator", password="unused")
        self.today = timezone.localdate()
        self.past = self.today - timedelta(days=60)
        self.future = self.today + timedelta(days=60)

    def _series(self, suffix, *, region=RacingRegion.IRELAND, approved=True) -> RaceSeries:
        return RaceSeries.objects.create(
            key=f"{region}-{suffix}",
            country_region=region,
            canonical_name_original=f"{region} {suffix}",
            chinese_name=f"{region} {suffix}",
            review_status=(
                RaceSeriesReviewStatus.APPROVED if approved else RaceSeriesReviewStatus.PENDING
            ),
        )

    def _target(
        self,
        series: RaceSeries,
        local_date,
        *,
        expectation=HistoricalRaceExpectationStatus.HELD,
        resolution=HistoricalRaceResolutionStatus.PENDING,
        artifact_sha256=INVENTORY_SHA,
        event=None,
    ) -> HistoricalRaceEventTarget:
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=local_date.year,
            expectation_status=expectation,
            resolution_status=resolution,
            original_name=series.canonical_name_original,
            chinese_name=series.chinese_name,
            racecourse="Test Course",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            local_date=local_date,
            source_refs={"catalog": "official"},
            artifact_sha256=artifact_sha256,
            event=event,
        )

    def _event(self, series: RaceSeries, local_date, *, status=RaceEventStatus.SCHEDULED) -> RaceEvent:
        return RaceEvent.objects.create(
            race_series=series,
            year=local_date.year,
            edition_year=local_date.year,
            slug=f"{series.key}-{local_date.year}",
            series_key=series.key,
            original_name=series.canonical_name_original,
            chinese_name=series.chinese_name,
            country_region=series.country_region,
            racecourse="Test Course",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            local_date=local_date,
            status=status,
            visibility_status=RaceEventVisibility.DRAFT,
            source_refs={"official": True},
        )


class ScheduledHistoricalMaterializeTests(DatedTargetFixtures, TestCase):
    """materialize_scheduled_historical_event 服务函数语义。"""

    def test_scheduled_materialize_creates_scheduled_draft_and_is_idempotent(self):
        series = self._series("scheduled-basic")
        target = self._target(
            series, self.future, resolution=HistoricalRaceResolutionStatus.READY
        )

        event = materialize_scheduled_historical_event(target)
        event.visibility_status = RaceEventVisibility.PUBLISHED
        event.save(update_fields={"visibility_status"})
        repeated = materialize_scheduled_historical_event(target)

        self.assertEqual(event.slug, f"{series.key}-{self.future.year}")
        self.assertEqual(event.status, RaceEventStatus.SCHEDULED)
        self.assertEqual(event.data_quality_status, RaceEventDataQuality.INCOMPLETE)
        self.assertEqual(event.local_date, self.future)
        self.assertEqual(event.race_series_id, series.pk)
        self.assertEqual(repeated.pk, event.pk)
        self.assertEqual(repeated.visibility_status, RaceEventVisibility.PUBLISHED)
        self.assertEqual(RaceEvent.objects.count(), 1)
        target.refresh_from_db()
        self.assertEqual(target.event_id, event.pk)
        self.assertEqual(event.source_refs["historical_target_id"], target.pk)
        self.assertEqual(event.source_refs["inventory_artifact_sha256"], INVENTORY_SHA)
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="historical_race_event_materialized",
                target_type="race_event",
                target_id=str(event.pk),
            ).exists()
        )

    def test_scheduled_materialize_requires_future_local_date(self):
        for label, local_date in (
            ("past", self.past),
            ("today", self.today),
            ("missing", None),
        ):
            with self.subTest(label=label):
                series = self._series(f"scheduled-guard-{label}")
                target = HistoricalRaceEventTarget.objects.create(
                    race_series=series,
                    year=(local_date or self.today).year,
                    expectation_status=HistoricalRaceExpectationStatus.HELD,
                    resolution_status=HistoricalRaceResolutionStatus.READY,
                    original_name=series.canonical_name_original,
                    chinese_name=series.chinese_name,
                    racecourse="Test Course",
                    grade_text="G1",
                    surface=RaceEventSurface.TURF,
                    local_date=local_date,
                    source_refs={"catalog": "official"},
                    artifact_sha256=INVENTORY_SHA,
                )
                with self.assertRaisesMessage(
                    InventoryValidationError, "future local_date"
                ):
                    materialize_scheduled_historical_event(target)
        self.assertFalse(RaceEvent.objects.exists())

    def test_scheduled_materialize_requires_ready_resolution(self):
        series = self._series("scheduled-pending")
        target = self._target(
            series, self.future, resolution=HistoricalRaceResolutionStatus.PENDING
        )

        with self.assertRaisesMessage(InventoryValidationError, "not ready"):
            materialize_scheduled_historical_event(target)
        self.assertFalse(RaceEvent.objects.exists())

    def test_scheduled_materialize_not_held_and_not_due_never_create(self):
        not_held = self._target(
            self._series("scheduled-not-held"),
            self.future,
            expectation=HistoricalRaceExpectationStatus.NOT_HELD,
        )
        not_due_series = self._series("scheduled-not-due")
        not_due = self._target(
            not_due_series,
            self.future,
            expectation=HistoricalRaceExpectationStatus.NOT_DUE,
        )

        self.assertIsNone(materialize_scheduled_historical_event(not_held))
        self.assertIsNone(materialize_scheduled_historical_event(not_due))
        self.assertFalse(RaceEvent.objects.exists())

        existing = self._event(not_due_series, self.future)
        not_due.event = existing
        not_due.save(update_fields={"event"})
        self.assertEqual(materialize_scheduled_historical_event(not_due).pk, existing.pk)
        self.assertEqual(RaceEvent.objects.count(), 1)

    def test_scheduled_materialize_adopts_matching_existing_event(self):
        series = self._series("scheduled-adopt")
        target = self._target(
            series, self.future, resolution=HistoricalRaceResolutionStatus.READY
        )
        existing = self._event(series, self.future)

        event = materialize_scheduled_historical_event(target)

        self.assertEqual(event.pk, existing.pk)
        target.refresh_from_db()
        self.assertEqual(target.event_id, existing.pk)
        self.assertEqual(RaceEvent.objects.count(), 1)

    def test_scheduled_materialize_cancelled_future_target_creates_cancelled_draft(self):
        series = self._series("scheduled-cancelled")
        target = self._target(
            series,
            self.future,
            expectation=HistoricalRaceExpectationStatus.CANCELLED,
            resolution=HistoricalRaceResolutionStatus.READY,
        )

        event = materialize_scheduled_historical_event(target)

        self.assertEqual(event.status, RaceEventStatus.CANCELLED)
        self.assertEqual(event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(event.data_quality_status, RaceEventDataQuality.INCOMPLETE)

    def test_finished_materializer_still_marks_past_target_finished(self):
        series = self._series("finished-regression")
        target = self._target(
            series, self.past, resolution=HistoricalRaceResolutionStatus.READY
        )

        event = materialize_historical_event(target)

        self.assertEqual(event.status, RaceEventStatus.FINISHED)
        self.assertEqual(event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(event.data_quality_status, RaceEventDataQuality.INCOMPLETE)


class MaterializeDatedRaceTargetsCommandTests(DatedTargetFixtures, TestCase):
    """materialize_dated_race_targets 门禁命令语义。"""

    def _write_manifest(
        self,
        root: Path,
        name: str = "manifest.json",
        *,
        regions=(RacingRegion.IRELAND,),
        years=None,
        approved_by="operator",
        inventory_sha=INVENTORY_SHA,
        extra=None,
        drop=(),
    ):
        if years is None:
            years = sorted({self.past.year, self.future.year})
        payload = {
            "schema_version": "1.0",
            "inventory_artifact_sha256": inventory_sha,
            "regions": list(regions),
            "years": list(years),
            "approval": {"approved_by": approved_by, "approved_at": "2026-01-01T00:00:00+00:00"},
            "generated_at": "2026-01-01T00:00:00+00:00",
        }
        if extra:
            payload.update(extra)
        for key in drop:
            payload.pop(key, None)
        path = root / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _run(self, mode, manifest_path, manifest_sha, output: Path, *, actor=None):
        args = [
            "materialize_dated_race_targets",
            mode,
            "--manifest",
            str(manifest_path),
            "--expected-manifest-sha256",
            manifest_sha,
            "--output",
            str(output),
        ]
        if actor is not None:
            args += ["--actor-username", actor]
        stdout = StringIO()
        call_command(*args, stdout=stdout, verbosity=0)
        return json.loads(Path(output).read_text(encoding="utf-8"))

    def test_dry_run_plans_actions_without_writes_and_filters_scope(self):
        ireland_past = self._target(self._series("plan-past"), self.past)
        ireland_future = self._target(self._series("plan-future"), self.future)
        # 地区不在 manifest 白名单范围内：不应出现在计划中
        self._target(self._series("plan-outside", region=RacingRegion.AUSTRALIA), self.past)
        # 年份不在 manifest 范围内：不应出现在计划中
        outside_year = self.past.year - 1
        self._target(
            self._series("plan-outside-year"),
            self.past.replace(year=outside_year),
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root)
            result = self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

        rows = {row["target_id"]: row for row in result["targets"]}
        self.assertEqual(set(rows), {ireland_past.pk, ireland_future.pk})
        self.assertEqual(rows[ireland_past.pk]["action"], "materialize_finished")
        self.assertEqual(rows[ireland_future.pk]["action"], "materialize_scheduled")
        self.assertEqual(rows[ireland_past.pk]["event_id"], None)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["manifest_sha256"], manifest_sha)
        self.assertEqual(
            result["summary"]["action_counts"],
            {"materialize_finished": 1, "materialize_scheduled": 1},
        )
        self.assertEqual(
            result["summary"]["by_region"],
            {RacingRegion.IRELAND: {"materialize_finished": 1, "materialize_scheduled": 1}},
        )
        self.assertEqual(
            result["summary"]["by_year"][str(self.past.year)]["materialize_finished"], 1
        )
        self.assertEqual(
            result["summary"]["by_year"][str(self.future.year)]["materialize_scheduled"], 1
        )
        self.assertFalse(RaceEvent.objects.exists())
        self.assertFalse(OperationLog.objects.exists())
        ireland_past.refresh_from_db()
        self.assertEqual(ireland_past.resolution_status, HistoricalRaceResolutionStatus.PENDING)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_materializes_past_target_as_finished_draft(self):
        series = self._series("apply-past")
        target = self._target(series, self.past)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.past.year])
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        target.refresh_from_db()
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        event = target.event
        self.assertIsNotNone(event)
        self.assertEqual(event.status, RaceEventStatus.FINISHED)
        self.assertEqual(event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(event.data_quality_status, RaceEventDataQuality.INCOMPLETE)
        self.assertEqual(event.race_series_id, series.pk)
        self.assertEqual(event.local_date, self.past)
        self.assertEqual(event.slug, f"{series.key}-{self.past.year}")
        self.assertEqual(event.source_refs["historical_target_id"], target.pk)
        materialize_log = OperationLog.objects.get(
            action_type="historical_race_event_materialized", target_id=str(event.pk)
        )
        self.assertEqual(materialize_log.admin, self.operator)
        batch_log = OperationLog.objects.get(
            action_type="dated_race_targets_materialized", target_id=manifest_sha
        )
        self.assertEqual(batch_log.admin, self.operator)
        self.assertEqual(json.loads(batch_log.detail)["manifest_sha256"], manifest_sha)

        row = result["targets"][0]
        self.assertEqual(row["target_id"], target.pk)
        self.assertEqual(row["action"], "materialize_finished")
        self.assertEqual(row["event_id"], event.pk)
        self.assertTrue(row["created"])
        self.assertNotEqual(row["target_sha256_before"], row["target_sha256_after"])
        self.assertEqual(result["summary"]["created_count"], 1)
        self.assertTrue(result["verifier"]["ok"])

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_materializes_future_target_as_scheduled_draft(self):
        series = self._series("apply-future")
        target = self._target(series, self.future)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.future.year])
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        target.refresh_from_db()
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        event = target.event
        self.assertIsNotNone(event)
        self.assertEqual(event.status, RaceEventStatus.SCHEDULED)
        self.assertEqual(event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(event.data_quality_status, RaceEventDataQuality.INCOMPLETE)
        self.assertEqual(event.race_series_id, series.pk)
        self.assertEqual(event.local_date, self.future)
        row = result["targets"][0]
        self.assertEqual(row["action"], "materialize_scheduled")
        self.assertTrue(row["created"])

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_skips_not_held_without_event(self):
        eligible = self._target(self._series("skip-not-held-eligible"), self.past)
        not_held = self._target(
            self._series("skip-not-held"),
            self.past.replace(day=min(self.past.day, 28)),
            expectation=HistoricalRaceExpectationStatus.NOT_HELD,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.past.year])
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        rows = {row["target_id"]: row for row in result["targets"]}
        self.assertEqual(rows[not_held.pk]["action"], "skip_not_held")
        self.assertIsNone(rows[not_held.pk]["event_id"])
        not_held.refresh_from_db()
        self.assertIsNone(not_held.event_id)
        self.assertEqual(not_held.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertEqual(RaceEvent.objects.count(), 1)
        eligible.refresh_from_db()
        self.assertIsNotNone(eligible.event_id)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_skips_not_due_without_ready_transition_or_event(self):
        eligible = self._target(self._series("skip-not-due-eligible"), self.past)
        not_due = self._target(
            self._series("skip-not-due"),
            self.future,
            expectation=HistoricalRaceExpectationStatus.NOT_DUE,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root)
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        rows = {row["target_id"]: row for row in result["targets"]}
        self.assertEqual(rows[not_due.pk]["action"], "skip_not_due")
        self.assertIsNone(rows[not_due.pk]["event_id"])
        not_due.refresh_from_db()
        self.assertEqual(not_due.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertIsNone(not_due.event_id)
        self.assertEqual(RaceEvent.objects.count(), 1)
        self.assertEqual(result["summary"]["action_counts"]["skip_not_due"], 1)

    def test_dry_run_fails_closed_when_series_not_approved(self):
        self._target(self._series("valid-scope"), self.past)
        self._target(self._series("unapproved", approved=False), self.future)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root)
            with self.assertRaisesMessage(CommandError, "series is not approved"):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

        self.assertFalse(RaceEvent.objects.exists())

    def test_dry_run_fails_closed_when_resolution_outside_scope(self):
        self._target(self._series("valid-resolution"), self.past)
        self._target(
            self._series("unavailable-resolution"),
            self.future,
            resolution=HistoricalRaceResolutionStatus.SOURCE_UNAVAILABLE,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root)
            with self.assertRaisesMessage(CommandError, "resolution is outside"):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    def test_dry_run_fails_closed_when_pending_target_already_has_event(self):
        series = self._series("inconsistent-binding")
        event = self._event(series, self.future)
        self._target(series, self.future, event=event)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.future.year])
            with self.assertRaisesMessage(CommandError, "event bound while still pending"):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    def test_dry_run_excludes_drifted_artifact_and_fails_closed_when_empty(self):
        self._target(self._series("valid-artifact"), self.past)
        self._target(
            self._series("drifted-artifact"),
            self.future,
            artifact_sha256=FOREIGN_INVENTORY_SHA,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 混合范围：漂移 target 被排除，有效 target 正常进入计划
            manifest_path, manifest_sha = self._write_manifest(root)
            result = self._run("dry-run", manifest_path, manifest_sha, root / "mixed.json")
            self.assertEqual(
                [row["target_id"] for row in result["targets"]],
                [HistoricalRaceEventTarget.objects.get(race_series__key="ireland-valid-artifact").pk],
            )
            # 仅含漂移 target 的范围：空选择集 fail closed
            drifted_path = root / "drifted.json"
            drifted_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "inventory_artifact_sha256": FOREIGN_INVENTORY_SHA,
                        "regions": [RacingRegion.GERMANY],
                        "years": [self.future.year],
                        "approval": {
                            "approved_by": "operator",
                            "approved_at": "2026-01-01T00:00:00+00:00",
                        },
                        "generated_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            drifted_sha = hashlib.sha256(drifted_path.read_bytes()).hexdigest()
            with self.assertRaisesMessage(CommandError, "selection is empty"):
                self._run("dry-run", drifted_path, drifted_sha, root / "drifted-out.json")

    def test_dry_run_excludes_undated_targets_and_fails_closed_when_empty(self):
        HistoricalRaceEventTarget.objects.create(
            race_series=self._series("undated"),
            year=self.past.year,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.PENDING,
            original_name="Undated",
            racecourse="Test Course",
            source_refs={"catalog": "official"},
            artifact_sha256=INVENTORY_SHA,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.past.year])
            with self.assertRaisesMessage(CommandError, "selection is empty"):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

        self.assertFalse(RaceEvent.objects.exists())

    def test_apply_rejects_when_backfill_disabled(self):
        self._target(self._series("backfill-off"), self.past)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.past.year])
            with self.assertRaisesMessage(
                CommandError, "historical race backfill is disabled"
            ):
                self._run(
                    "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
                )

        self.assertFalse(RaceEvent.objects.exists())

    def test_manifest_sha_mismatch_fails(self):
        self._target(self._series("sha-mismatch"), self.past)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest_sha = self._write_manifest(root, years=[self.past.year])
            with self.assertRaisesMessage(CommandError, "manifest SHA-256 mismatch"):
                self._run("dry-run", manifest_path, "0" * 64, root / "out.json")

    def test_apply_requires_existing_approver_actor(self):
        self._target(self._series("ghost-approver"), self.past)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(
                root, years=[self.past.year], approved_by="ghost"
            )
            with override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True):
                with self.assertRaisesMessage(CommandError, "执行人不存在"):
                    self._run(
                        "apply", manifest_path, manifest_sha, root / "ghost.json", actor="ghost"
                    )
                with self.assertRaisesMessage(CommandError, "--actor-username"):
                    self._run("apply", manifest_path, manifest_sha, root / "no-actor.json")

        self.assertFalse(RaceEvent.objects.exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_requires_actor_matching_manifest_approval(self):
        get_user_model().objects.create_user(username="other", password="unused")
        self._target(self._series("actor-mismatch"), self.past)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.past.year])
            with self.assertRaisesMessage(CommandError, "审批人一致"):
                self._run("apply", manifest_path, manifest_sha, root / "out.json", actor="other")

        self.assertFalse(RaceEvent.objects.exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_is_idempotent_and_second_run_claims_existing(self):
        past_target = self._target(self._series("idem-past"), self.past)
        future_target = self._target(self._series("idem-future"), self.future)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root)
            first = self._run(
                "apply", manifest_path, manifest_sha, root / "first.json", actor="operator"
            )
            self.assertEqual(first["summary"]["created_count"], 2)
            event_count = RaceEvent.objects.count()
            self.assertEqual(event_count, 2)

            second = self._run(
                "apply", manifest_path, manifest_sha, root / "second.json", actor="operator"
            )
            dry = self._run("dry-run", manifest_path, manifest_sha, root / "dry.json")

        self.assertEqual(RaceEvent.objects.count(), event_count)
        self.assertEqual(second["summary"]["created_count"], 0)
        self.assertEqual(second["summary"]["claimed_count"], 2)
        actions = {row["target_id"]: row["action"] for row in second["targets"]}
        self.assertEqual(
            actions, {past_target.pk: "claim_existing", future_target.pk: "claim_existing"}
        )
        self.assertTrue(all(row["created"] is False for row in second["targets"]))
        self.assertTrue(second["verifier"]["ok"])
        self.assertEqual(
            {row["action"] for row in dry["targets"]}, {"claim_existing"}
        )
        self.assertEqual(
            OperationLog.objects.filter(action_type="historical_race_event_materialized").count(),
            2,
        )
        self.assertEqual(
            OperationLog.objects.filter(action_type="dated_race_targets_materialized").count(),
            1,
        )

    def test_empty_selection_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root)
            with self.assertRaisesMessage(CommandError, "selection is empty"):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_verify_ok_after_apply_and_detects_deleted_binding(self):
        past_target = self._target(self._series("verify-past"), self.past)
        self._target(self._series("verify-future"), self.future)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root)
            self._run("apply", manifest_path, manifest_sha, root / "apply.json", actor="operator")

            verified = self._run("verify", manifest_path, manifest_sha, root / "verify-ok.json")
            self.assertTrue(verified["verifier"]["ok"])
            self.assertEqual(verified["verifier"]["checked_count"], 2)

            # 人为删除绑定（模拟运维事故）后 verify 必须发现
            past_target.refresh_from_db()
            past_target.event = None
            past_target.save(update_fields={"event"})
            broken = self._run("verify", manifest_path, manifest_sha, root / "verify-broken.json")

        self.assertFalse(broken["verifier"]["ok"])
        rows = {row["target_id"]: row for row in broken["verifier"]["targets"]}
        self.assertIn("event_missing", rows[past_target.pk]["errors"])

    def test_manifest_schema_validation(self):
        self._target(self._series("schema-validation"), self.past)
        cases = (
            ("bad-version", {"extra": {"schema_version": "2.0"}}, "schema_version"),
            ("bad-region", {"regions": (RacingRegion.JAPAN,)}, "regions"),
            ("missing-approval", {"drop": ("approval",)}, "approval"),
            ("duplicate-years", {"years": (self.past.year, self.past.year)}, "years"),
            ("bad-inventory-sha", {"inventory_sha": "not-a-sha"}, "inventory_artifact_sha256"),
        )
        for label, kwargs, message in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                kwargs.setdefault("years", [self.past.year])
                manifest_path, manifest_sha = self._write_manifest(root, **kwargs)
                with self.assertRaisesMessage(CommandError, message):
                    self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    def test_output_refuses_overwrite(self):
        self._target(self._series("overwrite-guard"), self.past)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = self._write_manifest(root, years=[self.past.year])
            output = root / "out.json"
            self._run("dry-run", manifest_path, manifest_sha, output)
            with self.assertRaisesMessage(CommandError, "输出文件已存在"):
                self._run("dry-run", manifest_path, manifest_sha, output)


class MaterializeTimezoneTests(DatedTargetFixtures, TestCase):
    """物化赛事的 timezone_name 必须按地区真实时区（不再落到模型默认 Asia/Tokyo）。"""

    def test_region_timezone_mapping_on_materialize(self):
        cases = [
            (RacingRegion.JAPAN, "Asia/Tokyo"),
            (RacingRegion.HONG_KONG, "Asia/Hong_Kong"),
            (RacingRegion.UNITED_KINGDOM, "Europe/London"),
            (RacingRegion.IRELAND, "Europe/Dublin"),
            (RacingRegion.FRANCE, "Europe/Paris"),
            (RacingRegion.GERMANY, "Europe/Berlin"),
            (RacingRegion.UNITED_STATES, "America/New_York"),
            (RacingRegion.AUSTRALIA, "Australia/Sydney"),
            (RacingRegion.MIDDLE_EAST, "Asia/Dubai"),
        ]
        for region, expected_tz in cases:
            with self.subTest(region=region):
                series = self._series(f"tz-{region}", region=region)
                target = self._target(
                    series, self.past, resolution=HistoricalRaceResolutionStatus.READY
                )
                event = materialize_historical_event(target, actor=self.operator)
                self.assertEqual(event.timezone_name, expected_tz)

    def test_saudi_series_uses_riyadh_not_dubai(self):
        # 生产 middle_east 系列键按国家前缀（saudi-arabia-/united-arab-emirates-/qatar-/bahrain-）
        series = RaceSeries.objects.create(
            key="saudi-arabia-saudi-cup",
            country_region=RacingRegion.MIDDLE_EAST,
            canonical_name_original="Saudi Cup",
            chinese_name="沙特杯",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        target = self._target(
            series, self.past, resolution=HistoricalRaceResolutionStatus.READY
        )
        event = materialize_historical_event(target, actor=self.operator)
        self.assertEqual(event.timezone_name, "Asia/Riyadh")
