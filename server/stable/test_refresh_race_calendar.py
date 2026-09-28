"""refresh_race_calendar 门禁命令 + Celery 只读挂载测试。

覆盖：三类 diff 行 apply 语义（new/changed/cancelled/uncovered）、series 新建
PENDING 不自动批准、已完赛 changed 拒绝、幂等重复 apply、门禁（sha/开关/审批人/
锚定/空选择）、verify 检出人为破坏、beat schedule 默认关闭与任务薄壳。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)


INVENTORY_SHA = "a" * 64
TOOLS_ROOT = Path(__file__).resolve().parents[2] / "runtime" / "tools"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RefreshFixtures:
    """共享 fixture：动态日期避免依赖真实日历日。"""

    def setUp(self):
        super().setUp()
        self.operator = get_user_model().objects.create_user(username="operator", password="unused")
        self.today = timezone.localdate()
        self.future = self.today + timedelta(days=60)
        # far_future 与 future 同年（改期）；next_year 跨年（拒绝改期）
        self.far_future = date(self.future.year, 12, 28)
        self.next_year_date = date(self.future.year + 1, 1, 15)
        self.past = self.today - timedelta(days=60)

    def _series(
        self,
        key="ireland-irish-derby",
        *,
        region=RacingRegion.IRELAND,
        review=RaceSeriesReviewStatus.APPROVED,
        name="Irish Derby",
    ) -> RaceSeries:
        return RaceSeries.objects.create(
            key=key,
            country_region=region,
            canonical_name_original=name,
            review_status=review,
        )

    def _target(
        self,
        series: RaceSeries,
        year: int,
        *,
        local_date=None,
        expectation=HistoricalRaceExpectationStatus.HELD,
        resolution=HistoricalRaceResolutionStatus.PENDING,
        racecourse="Curragh",
        grade_text="G1",
        artifact_sha256=INVENTORY_SHA,
        event=None,
    ) -> HistoricalRaceEventTarget:
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=year,
            country_region=series.country_region,
            expectation_status=expectation,
            resolution_status=resolution,
            original_name=series.canonical_name_original,
            racecourse=racecourse,
            grade_text=grade_text,
            surface=RaceEventSurface.TURF,
            local_date=local_date,
            source_refs={"catalog": "official"},
            artifact_sha256=artifact_sha256,
            event=event,
        )

    def _event(
        self,
        series: RaceSeries,
        local_date,
        *,
        status=RaceEventStatus.SCHEDULED,
    ) -> RaceEvent:
        return RaceEvent.objects.create(
            race_series=series,
            year=local_date.year,
            edition_year=local_date.year,
            slug=f"{series.key}-{local_date.year}",
            series_key=series.key,
            original_name=series.canonical_name_original,
            chinese_name=series.chinese_name or series.canonical_name_original,
            country_region=series.country_region,
            racecourse="Curragh",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            local_date=local_date,
            status=status,
            visibility_status=RaceEventVisibility.DRAFT,
            source_refs={"official": True},
        )

    # ── diff 行构造 ──────────────────────────────────────────────

    def _new_row(self, series_key, year, *, local_date="", racecourse="Curragh",
                 grade_text="G1", name="Irish Derby", region="ireland"):
        return {
            "bucket": "new",
            "country_region": region,
            "year": year,
            "series_key": series_key,
            "local_date": local_date,
            "racecourse": racecourse,
            "grade_text": grade_text,
            "original_name": name,
            "canonical_name_original": name,
            "surface": "",
            "distance_text": "2400",
            "expectation_status": "held",
            "series_match_hint": [],
            "evidence": {"source_url": "https://www.hri-ras.ie/pattern"},
        }

    def _changed_row(self, series_key, year, *, before: dict, after: dict, region="ireland"):
        return {
            "bucket": "changed",
            "country_region": region,
            "year": year,
            "series_key": series_key,
            "before": {
                "local_date": before.get("local_date", ""),
                "racecourse": before.get("racecourse", ""),
                "grade_text": before.get("grade_text", ""),
                "expectation_status": before.get("expectation_status", "held"),
                "resolution_status": before.get("resolution_status", "pending"),
            },
            "after": {
                "local_date": after.get("local_date", ""),
                "racecourse": after.get("racecourse", ""),
                "grade_text": after.get("grade_text", ""),
                "original_name": after.get("original_name", "Irish Derby"),
            },
            "changes": {
                field: {"before": before.get(field, ""), "after": after.get(field, "")}
                for field in ("local_date", "racecourse", "grade_text")
                if before.get(field, "") != after.get(field, "")
            },
            "evidence": {"source_url": "https://www.hri-ras.ie/pattern"},
        }

    def _cancelled_row(self, series_key, year, *, region="ireland", local_date="",
                       racecourse="Curragh", grade_text="G1"):
        return {
            "bucket": "cancelled",
            "country_region": region,
            "year": year,
            "series_key": series_key,
            "existing": {
                "local_date": local_date,
                "racecourse": racecourse,
                "grade_text": grade_text,
                "expectation_status": "held",
                "resolution_status": "pending",
            },
            "reason": "absent_from_covered_official_calendar",
        }

    def _uncovered_row(self, series_key, year, *, region="ireland"):
        return {
            "bucket": "uncovered",
            "country_region": region,
            "year": year,
            "series_key": series_key,
            "existing": {
                "local_date": "",
                "racecourse": "Curragh",
                "grade_text": "G1",
                "expectation_status": "held",
                "resolution_status": "pending",
            },
            "reason": "scope_not_covered",
        }

    def _unchanged_row(self, series_key, year, *, region="ireland"):
        return {
            "bucket": "unchanged",
            "country_region": region,
            "year": year,
            "series_key": series_key,
            "values": {"local_date": "", "racecourse": "Curragh", "grade_text": "G1"},
            "evidence": {"source_url": "https://www.hri-ras.ie/pattern"},
        }

    # ── manifest / 命令执行 ──────────────────────────────────────

    def _write_diff(self, root: Path, rows, name="calendar_diff.jsonl"):
        path = root / name
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return path, _sha256(path)

    def _write_manifest(
        self,
        root: Path,
        diff_path: Path,
        diff_sha: str,
        *,
        regions=("ireland",),
        years=(2026,),
        approved_by="operator",
        diff_name="calendar_diff.jsonl",
        extra=None,
        drop=(),
    ):
        payload = {
            "schema_version": "1.0",
            "regions": list(regions),
            "years": list(years),
            "diff_artifact": {"path": diff_name, "sha256": diff_sha},
            "approval": {"approved_by": approved_by, "approved_at": "2026-01-01T00:00:00+00:00"},
            "generated_at": "2026-01-01T00:00:00+00:00",
        }
        if extra:
            payload.update(extra)
        for key in drop:
            payload.pop(key, None)
        path = root / "refresh_manifest.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path, _sha256(path)

    def _run(self, mode, manifest_path: Path, manifest_sha: str, output: Path, *, actor=None):
        args = [
            "refresh_race_calendar",
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


class RefreshRaceCalendarCommandTests(RefreshFixtures, TestCase):
    """refresh_race_calendar 门禁命令语义。"""

    def test_dry_run_plans_actions_without_writes(self):
        series = self._series()
        changed_target = self._target(series, 2026, local_date=self.future)
        cancelled_series = self._series("ireland-retired-race", name="Retired Race")
        self._target(cancelled_series, 2026, local_date=self.future)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._new_row("ireland-brand-new-race", 2026, local_date=self.future.isoformat(),
                              name="Brand New Race"),
                self._changed_row(
                    series.key,
                    2026,
                    before={"local_date": self.future.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1"},
                    after={"local_date": self.far_future.isoformat(), "racecourse": "Curragh",
                           "grade_text": "G1"},
                ),
                self._cancelled_row(cancelled_series.key, 2026,
                                    local_date=self.future.isoformat()),
                self._uncovered_row("ireland-uncovered-race", 2026),
                self._unchanged_row("ireland-untouched-race", 2026),
                self._new_row("japan-out-of-scope", 2025, region="japan",
                              local_date=self.future.isoformat(), name="Out Of Scope"),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            result = self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

        by_key = {row["series_key"]: row for row in result["rows"]}
        self.assertEqual(by_key["ireland-brand-new-race"]["action"], "create_target")
        self.assertEqual(by_key[series.key]["action"], "update_target_event")
        self.assertEqual(by_key[cancelled_series.key]["action"], "mark_cancelled")
        self.assertEqual(by_key["ireland-uncovered-race"]["action"], "record_only")
        self.assertEqual(by_key["ireland-untouched-race"]["action"], "unchanged")
        self.assertNotIn("japan-out-of-scope", by_key)
        self.assertEqual(result["summary"]["row_counts"]["out_of_scope"], 1)
        # dry-run 不落库
        changed_target.refresh_from_db()
        self.assertEqual(changed_target.local_date, self.future)
        self.assertFalse(RaceSeries.objects.filter(key="ireland-brand-new-race").exists())
        self.assertFalse(RaceEvent.objects.exists())
        self.assertFalse(OperationLog.objects.exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_new_creates_series_pending_and_target_pending(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._new_row("ireland-brand-new-race", 2026,
                              local_date=self.future.isoformat(), name="Brand New Race"),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        series = RaceSeries.objects.get(key="ireland-brand-new-race")
        self.assertEqual(series.review_status, RaceSeriesReviewStatus.PENDING)  # 不自动批准
        self.assertEqual(series.country_region, RacingRegion.IRELAND)
        target = HistoricalRaceEventTarget.objects.get(race_series=series, year=2026)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertEqual(target.expectation_status, HistoricalRaceExpectationStatus.HELD)
        self.assertEqual(target.artifact_sha256, diff_sha)  # diff 批次 sha
        self.assertIsNone(target.event)
        evidence = target.source_refs["calendar_refresh"]
        self.assertEqual(evidence["diff_artifact_sha256"], diff_sha)
        self.assertEqual(evidence["bucket"], "new")
        row = result["rows"][0]
        self.assertEqual(row["action"], "create_target")
        self.assertEqual(row["reason"], "series_not_approved")
        # 批次 OperationLog
        log = OperationLog.objects.get(action_type="race_calendar_refresh_applied")
        self.assertEqual(log.target_id, manifest_sha)
        self.assertEqual(log.admin, self.operator)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_new_with_approved_series_materializes_scheduled_draft(self):
        series = self._series("ireland-champions-stakes", name="Champions Stakes")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._new_row(series.key, 2026, local_date=self.future.isoformat(),
                              name="Champions Stakes"),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        row = result["rows"][0]
        self.assertEqual(row["action"], "materialize_scheduled")
        target = HistoricalRaceEventTarget.objects.get(race_series=series, year=2026)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        event = target.event
        self.assertIsNotNone(event)
        self.assertEqual(event.status, RaceEventStatus.SCHEDULED)
        self.assertEqual(event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(event.local_date, self.future)
        self.assertEqual(event.source_refs["historical_target_id"], target.pk)
        self.assertEqual(result["verifier"]["ok"], True)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_new_undated_does_not_materialize(self):
        series = self._series("ireland-undated-race", name="Undated Race")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [self._new_row(series.key, 2026, name="Undated Race")]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        self.assertEqual(result["rows"][0]["action"], "create_target")
        self.assertEqual(result["rows"][0]["reason"], "undated")
        target = HistoricalRaceEventTarget.objects.get(race_series=series, year=2026)
        self.assertIsNone(target.local_date)
        self.assertIsNone(target.event)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.PENDING)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_changed_updates_unmaterialized_target_and_logs(self):
        series = self._series()
        target = self._target(series, 2026, local_date=self.future)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._changed_row(
                    series.key,
                    2026,
                    before={"local_date": self.future.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1"},
                    after={"local_date": self.far_future.isoformat(),
                           "racecourse": "Leopardstown", "grade_text": "G2"},
                ),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        target.refresh_from_db()
        self.assertEqual(target.local_date, self.far_future)
        self.assertEqual(target.racecourse, "Leopardstown")
        self.assertEqual(target.grade_text, "G2")
        self.assertEqual(target.artifact_sha256, INVENTORY_SHA)  # 库存 sha 不被改写
        log = OperationLog.objects.get(action_type="race_calendar_refresh_updated")
        detail = json.loads(log.detail)
        self.assertEqual(detail["target_id"], target.pk)
        self.assertEqual(detail["manifest_sha256"], manifest_sha)
        self.assertEqual(
            detail["changes"]["local_date"],
            {"before": self.future.isoformat(), "after": self.far_future.isoformat()},
        )
        self.assertEqual(result["rows"][0]["action"], "update_target_event")

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_changed_updates_scheduled_event(self):
        series = self._series()
        event = self._event(series, self.future, status=RaceEventStatus.SCHEDULED)
        target = self._target(
            series, 2026, local_date=self.future,
            resolution=HistoricalRaceResolutionStatus.READY, event=event,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._changed_row(
                    series.key,
                    2026,
                    before={"local_date": self.future.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1", "resolution_status": "ready"},
                    after={"local_date": self.far_future.isoformat(),
                           "racecourse": "Leopardstown", "grade_text": "G2"},
                ),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            self._run("apply", manifest_path, manifest_sha, root / "out.json", actor="operator")

        target.refresh_from_db()
        self.assertEqual(target.local_date, self.far_future)
        event.refresh_from_db()
        self.assertEqual(event.local_date, self.far_future)
        self.assertEqual(event.racecourse, "Leopardstown")
        self.assertEqual(event.grade_text, "G2")
        self.assertEqual(event.status, RaceEventStatus.SCHEDULED)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_changed_rejects_finished_event(self):
        series = self._series()
        event = self._event(series, self.past, status=RaceEventStatus.FINISHED)
        target = self._target(
            series, self.past.year, local_date=self.past,
            resolution=HistoricalRaceResolutionStatus.IMPORTED, event=event,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._changed_row(
                    series.key,
                    self.past.year,
                    before={"local_date": self.past.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1", "resolution_status": "imported"},
                    after={"local_date": self.past.isoformat(), "racecourse": "Leopardstown",
                           "grade_text": "G2"},
                ),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(
                root, diff_path, diff_sha, years=(self.past.year,)
            )
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        # 已完赛赛事一律不动，记入拒绝清单
        row = result["rows"][0]
        self.assertEqual(row["action"], "rejected")
        self.assertEqual(row["reason"], "event_already_run")
        target.refresh_from_db()
        self.assertEqual(target.racecourse, "Curragh")
        event.refresh_from_db()
        self.assertEqual(event.racecourse, "Curragh")
        self.assertEqual(event.grade_text, "G1")
        self.assertFalse(
            OperationLog.objects.filter(action_type="race_calendar_refresh_updated").exists()
        )
        self.assertEqual(result["summary"]["rejected_count"], 1)
        self.assertEqual(result["verifier"]["ok"], True)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_changed_rejects_cross_year_move(self):
        series = self._series()
        event = self._event(series, self.future, status=RaceEventStatus.SCHEDULED)
        target = self._target(
            series, self.future.year, local_date=self.future,
            resolution=HistoricalRaceResolutionStatus.READY, event=event,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._changed_row(
                    series.key,
                    self.future.year,
                    before={"local_date": self.future.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1", "resolution_status": "ready"},
                    after={"local_date": self.next_year_date.isoformat(),
                           "racecourse": "Curragh", "grade_text": "G1"},
                ),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(
                root, diff_path, diff_sha, years=(self.future.year,)
            )
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        row = result["rows"][0]
        self.assertEqual(row["action"], "rejected")
        self.assertEqual(row["reason"], "cross_year_move_requires_manual_review")
        target.refresh_from_db()
        self.assertEqual(target.local_date, self.future)
        event.refresh_from_db()
        self.assertEqual(event.local_date, self.future)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_changed_drift_fails_closed(self):
        series = self._series()
        # DB 当前值与 diff before/after 都不一致：快照过期，fail closed
        target = self._target(series, 2026, local_date=self.future, racecourse="Fairyhouse")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._changed_row(
                    series.key,
                    2026,
                    before={"local_date": self.future.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1"},
                    after={"local_date": self.far_future.isoformat(),
                           "racecourse": "Leopardstown", "grade_text": "G1"},
                ),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            with self.assertRaises(CommandError):
                self._run("apply", manifest_path, manifest_sha, root / "out.json", actor="operator")
        target.refresh_from_db()
        self.assertEqual(target.racecourse, "Fairyhouse")

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_cancelled_marks_unmaterialized_only(self):
        series = self._series()
        pending_target = self._target(series, 2026, local_date=self.future)
        bound_series = self._series("ireland-bound-race", name="Bound Race")
        bound_event = self._event(bound_series, self.future, status=RaceEventStatus.SCHEDULED)
        bound_target = self._target(
            bound_series, 2026, local_date=self.future,
            resolution=HistoricalRaceResolutionStatus.READY, event=bound_event,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._cancelled_row(series.key, 2026, local_date=self.future.isoformat()),
                self._cancelled_row(bound_series.key, 2026, local_date=self.future.isoformat()),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        by_key = {row["series_key"]: row for row in result["rows"]}
        self.assertEqual(by_key[series.key]["action"], "mark_cancelled")
        self.assertEqual(by_key[bound_series.key]["action"], "review_required")
        pending_target.refresh_from_db()
        self.assertEqual(
            pending_target.expectation_status, HistoricalRaceExpectationStatus.CANCELLED
        )
        bound_target.refresh_from_db()
        self.assertEqual(
            bound_target.expectation_status, HistoricalRaceExpectationStatus.HELD
        )
        self.assertTrue(
            OperationLog.objects.filter(action_type="race_calendar_refresh_cancelled").exists()
        )

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_uncovered_is_record_only(self):
        series = self._series()
        target = self._target(series, 2026, local_date=self.future)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._uncovered_row(series.key, 2026),
                # 空选择集 fail closed 不触发：搭一条可执行 new 行
                self._new_row("ireland-brand-new-race", 2026,
                              local_date=self.future.isoformat(), name="Brand New Race"),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            result = self._run(
                "apply", manifest_path, manifest_sha, root / "out.json", actor="operator"
            )

        by_key = {row["series_key"]: row for row in result["rows"]}
        self.assertEqual(by_key[series.key]["action"], "record_only")
        target.refresh_from_db()
        self.assertEqual(target.expectation_status, HistoricalRaceExpectationStatus.HELD)
        self.assertEqual(target.local_date, self.future)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_is_idempotent_on_reapply(self):
        series = self._series()
        changed_target = self._target(series, 2026, local_date=self.future)
        cancelled_series = self._series("ireland-retired-race", name="Retired Race")
        cancelled_target = self._target(cancelled_series, 2026, local_date=self.future)

        def build(root: Path):
            rows = [
                self._new_row("ireland-brand-new-race", 2026,
                              local_date=self.future.isoformat(), name="Brand New Race"),
                self._changed_row(
                    series.key,
                    2026,
                    before={"local_date": self.future.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1"},
                    after={"local_date": self.far_future.isoformat(), "racecourse": "Curragh",
                           "grade_text": "G1"},
                ),
                self._cancelled_row(cancelled_series.key, 2026,
                                    local_date=self.future.isoformat()),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            return self._write_manifest(root, diff_path, diff_sha)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest_sha = build(root)
            first = self._run(
                "apply", manifest_path, manifest_sha, root / "apply-1.json", actor="operator"
            )
            snapshot = (
                RaceSeries.objects.count(),
                HistoricalRaceEventTarget.objects.count(),
                RaceEvent.objects.count(),
            )
            second = self._run(
                "apply", manifest_path, manifest_sha, root / "apply-2.json", actor="operator"
            )
            verify = self._run("verify", manifest_path, manifest_sha, root / "verify.json")

        self.assertEqual(
            snapshot,
            (
                RaceSeries.objects.count(),
                HistoricalRaceEventTarget.objects.count(),
                RaceEvent.objects.count(),
            ),
        )
        self.assertEqual(first["summary"]["action_counts"]["create_target"], 1)
        self.assertEqual(first["summary"]["action_counts"]["update_target_event"], 1)
        self.assertEqual(first["summary"]["action_counts"]["mark_cancelled"], 1)
        second_actions = second["summary"]["action_counts"]
        self.assertEqual(second_actions.get("create_target", 0), 0)
        self.assertEqual(second_actions.get("update_target_event", 0), 0)
        self.assertEqual(second_actions.get("mark_cancelled", 0), 0)
        self.assertTrue(all(row["action"].startswith("noop") for row in second["rows"]))
        self.assertEqual(verify["verifier"]["ok"], True)
        changed_target.refresh_from_db()
        self.assertEqual(changed_target.local_date, self.far_future)
        cancelled_target.refresh_from_db()
        self.assertEqual(
            cancelled_target.expectation_status, HistoricalRaceExpectationStatus.CANCELLED
        )
        # 批次日志只写一次
        self.assertEqual(
            OperationLog.objects.filter(action_type="race_calendar_refresh_applied").count(), 1
        )

    def test_manifest_sha_mismatch_fails(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [self._new_row("ireland-brand-new-race", 2026, name="Brand New Race")]
            diff_path, _ = self._write_diff(root, rows)
            manifest_path, _ = self._write_manifest(root, diff_path, "0" * 64)
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, "1" * 64, root / "out.json")

    def test_apply_requires_backfill_enabled(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [self._new_row("ireland-brand-new-race", 2026, name="Brand New Race")]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            with self.assertRaises(CommandError):
                self._run("apply", manifest_path, manifest_sha, root / "out.json", actor="operator")

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_apply_requires_actor_matching_approver(self):
        get_user_model().objects.create_user(username="someone-else", password="unused")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [self._new_row("ireland-brand-new-race", 2026, name="Brand New Race")]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            with self.assertRaises(CommandError):
                self._run(
                    "apply", manifest_path, manifest_sha, root / "out.json",
                    actor="someone-else",
                )
            with self.assertRaises(CommandError):
                self._run(
                    "apply", manifest_path, manifest_sha, root / "out2.json",
                    actor="ghost",
                )
            with self.assertRaises(CommandError):
                self._run("apply", manifest_path, manifest_sha, root / "out3.json")

    def test_anchor_failure_fails_closed(self):
        # changed/cancelled 行锚定不到既有 target：fail closed（dry-run 即失败）
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._changed_row(
                    "ireland-missing-race",
                    2026,
                    before={"local_date": "", "racecourse": "Curragh", "grade_text": "G1"},
                    after={"local_date": "", "racecourse": "Leopardstown", "grade_text": "G1"},
                ),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    def test_empty_actionable_selection_fails_closed(self):
        series = self._series()
        self._target(series, 2026, local_date=self.future)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._unchanged_row(series.key, 2026),
                self._uncovered_row("ireland-uncovered-race", 2026),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    def test_new_row_without_series_key_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = self._new_row("", 2026, local_date=self.future.isoformat(),
                                name="Keyless Race")
            row["series_match_hint"] = [{"series_key": "ireland-irish-derby", "score": 0.9,
                                         "matched_on": "name"}]
            diff_path, diff_sha = self._write_diff(root, [row])
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_verify_detects_tampering_after_apply(self):
        series = self._series()
        target = self._target(series, 2026, local_date=self.future)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                self._changed_row(
                    series.key,
                    2026,
                    before={"local_date": self.future.isoformat(), "racecourse": "Curragh",
                            "grade_text": "G1"},
                    after={"local_date": self.far_future.isoformat(), "racecourse": "Curragh",
                           "grade_text": "G1"},
                ),
            ]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            self._run("apply", manifest_path, manifest_sha, root / "apply.json", actor="operator")
            ok_report = self._run("verify", manifest_path, manifest_sha, root / "verify-ok.json")
            self.assertEqual(ok_report["verifier"]["ok"], True)
            # 人为破坏：把 local_date 改回 before
            target.refresh_from_db()
            target.local_date = self.future
            target.save(update_fields={"local_date"})
            bad_report = self._run("verify", manifest_path, manifest_sha, root / "verify-bad.json")
            self.assertEqual(bad_report["verifier"]["ok"], False)
            self.assertGreater(bad_report["verifier"]["error_count"], 0)
            error_rows = [row for row in bad_report["verifier"]["rows"] if row["errors"]]
            self.assertEqual(error_rows[0]["target_id"], target.pk)

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
    def test_output_refuses_overwrite(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [self._new_row("ireland-brand-new-race", 2026, name="Brand New Race")]
            diff_path, diff_sha = self._write_diff(root, rows)
            manifest_path, manifest_sha = self._write_manifest(root, diff_path, diff_sha)
            self._run("dry-run", manifest_path, manifest_sha, root / "out.json")
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, manifest_sha, root / "out.json")

    def test_manifest_schema_validation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [self._new_row("ireland-brand-new-race", 2026, name="Brand New Race")]
            diff_path, diff_sha = self._write_diff(root, rows)
            # schema_version 错误
            manifest_path, manifest_sha = self._write_manifest(
                root, diff_path, diff_sha, extra={"schema_version": "2.0"}
            )
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, manifest_sha, root / "out-1.json")
            # regions 超九地区白名单
            manifest_path, manifest_sha = self._write_manifest(
                root, diff_path, diff_sha, regions=("antarctica",)
            )
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, manifest_sha, root / "out-2.json")
            # diff_artifact sha 非法
            manifest_path, manifest_sha = self._write_manifest(
                root, diff_path, "not-a-sha"
            )
            with self.assertRaises(CommandError):
                self._run("dry-run", manifest_path, manifest_sha, root / "out-3.json")


class RaceCalendarRefreshSettingsTests(SimpleTestCase):
    """settings 挂载：默认关闭不出现，开启后出现。"""

    def test_beat_schedule_default_off_and_enabled_on(self):
        from app import settings as app_settings

        self.assertFalse(app_settings.RACE_CALENDAR_REFRESH_BEAT_ENABLED)
        self.assertNotIn(
            "race-calendar-refresh-diff-candidates", app_settings.CELERY_BEAT_SCHEDULE
        )
        self.assertEqual(app_settings.build_race_calendar_refresh_beat_schedule(), {})
        self.assertEqual(
            app_settings.build_race_calendar_refresh_beat_schedule(refresh_enabled=False), {}
        )
        schedule = app_settings.build_race_calendar_refresh_beat_schedule(refresh_enabled=True)
        entry = schedule["race-calendar-refresh-diff-candidates"]
        self.assertEqual(entry["task"], "stable.tasks.race_calendar_refresh_dry_run_task")
        self.assertEqual(entry["options"]["queue"], "celery")


class RaceCalendarRefreshTaskTests(SimpleTestCase):
    """Celery 薄壳：默认禁用；开启后只生成 diff 候选并通知，不自动 apply。"""

    def test_task_disabled_by_default(self):
        from stable.tasks import race_calendar_refresh_dry_run_task

        self.assertEqual(
            race_calendar_refresh_dry_run_task(),
            {"enabled": False, "status": "disabled"},
        )

    def test_task_generates_diff_candidates_without_apply(self):
        from stable.tasks import race_calendar_refresh_dry_run_task

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            incoming_path = root / "incoming.jsonl"
            incoming_path.write_text(
                json.dumps(
                    {
                        "record_type": "timeline",
                        "country_region": "ireland",
                        "year": 2026,
                        "series_key": "ireland-brand-new-race",
                        "canonical_name_original": "Brand New Race",
                        "original_name": "Brand New Race",
                        "grade_text": "G1",
                        "racecourse": "Curragh",
                        "local_date": "2026-10-17",
                        "expectation_status": "held",
                        "source_scope": "official_calendar",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            existing_path = root / "existing.csv"
            existing_path.write_text(
                "series_key,country_region,year,local_date,racecourse,grade_text,"
                "expectation_status,resolution_status\n"
                "ireland-irish-derby,ireland,2026,2026-06-28,Curragh,G1,held,pending\n",
                encoding="utf-8",
            )
            with override_settings(
                RACE_CALENDAR_REFRESH_BEAT_ENABLED=True,
                RACE_CALENDAR_REFRESH_INCOMING=[
                    f"https://www.hri-ras.ie/pattern={incoming_path}"
                ],
                RACE_CALENDAR_REFRESH_EXISTING_SNAPSHOT=str(existing_path),
                RACE_CALENDAR_REFRESH_COVERS=["ireland:2026"],
                RACE_CALENDAR_REFRESH_OUTPUT_ROOT=str(root / "out"),
                HISTORICAL_RUNNER_TOOL_ROOT=str(TOOLS_ROOT),
            ):
                result = race_calendar_refresh_dry_run_task()
            output_dir = Path(result["output_dir"])
            self.assertTrue((output_dir / "calendar_diff.jsonl").is_file())
            self.assertTrue((output_dir / "summary.json").is_file())

        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["counts"]["buckets"]["new"], 1)
        self.assertEqual(result["counts"]["buckets"]["cancelled"], 1)
        # 只读候选：不触发通知发送器之外的任何写入路径（通知默认禁用）
        self.assertEqual(result["notified"], 0)

    def test_task_skips_when_inputs_unconfigured(self):
        from stable.tasks import race_calendar_refresh_dry_run_task

        with override_settings(
            RACE_CALENDAR_REFRESH_BEAT_ENABLED=True,
            RACE_CALENDAR_REFRESH_INCOMING=[],
            RACE_CALENDAR_REFRESH_EXISTING_SNAPSHOT="",
        ):
            result = race_calendar_refresh_dry_run_task()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "missing_inputs")
