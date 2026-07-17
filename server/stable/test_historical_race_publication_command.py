from __future__ import annotations

import hashlib
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_inventory import load_historical_publication_manifest


class HistoricalRacePublicationCommandTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="historical-publisher")
        self.series = RaceSeries.objects.create(
            key="publication-series",
            country_region=RacingRegion.UNITED_KINGDOM,
            canonical_name_original="Publication Stakes",
            chinese_name="发布锦标",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )

    def _target(
        self,
        year: int,
        *,
        complete_details: bool = True,
        artifact_sha256: str | None = None,
    ) -> HistoricalRaceEventTarget:
        event = RaceEvent.objects.create(
            race_series=self.series,
            year=year,
            slug=f"publication-stakes-{year}",
            original_name="Publication Stakes",
            chinese_name="发布锦标",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            distance_text="1m",
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.DRAFT,
            data_quality_status=RaceEventDataQuality.INCOMPLETE,
            source_refs={"official_result": f"https://official.test/{year}"},
        )
        target = HistoricalRaceEventTarget.objects.create(
            race_series=self.series,
            year=year,
            country_region=RacingRegion.UNITED_KINGDOM,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.IMPORTED,
            event=event,
            artifact_sha256=artifact_sha256 or f"{year % 10:x}" * 64,
        )
        if complete_details:
            RaceEventResult.objects.create(
                event=event,
                finish_position=1,
                official_finish_position=1,
                horse_number="1",
                horse_name=f"Winner {year}",
                is_confirmed=True,
            )
            RaceEventRunner.objects.create(
                event=event,
                sort_order=1,
                horse_number="1",
                horse_name=f"Winner {year}",
                source_refs={"derived_from_results": True},
            )
        return target

    def _manifest(self, root: Path, targets: list[HistoricalRaceEventTarget], *, name: str = "manifest.json"):
        path = root / name
        payload = {
            "schema_version": "historical-race-publication/v1",
            "target_ids": [target.pk for target in targets],
            "targets": [
                {
                    "target_id": target.pk,
                    "artifact_sha256": target.artifact_sha256,
                }
                for target in targets
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        path.write_bytes(encoded)
        return path, hashlib.sha256(encoded).hexdigest()

    def _run(self, mode: str, manifest: Path, manifest_sha: str, output: Path, *extra: str):
        call_command(
            "publish_historical_race_targets",
            mode,
            "--manifest",
            str(manifest),
            "--expected-manifest-sha256",
            manifest_sha,
            "--output",
            str(output),
            *extra,
            stdout=StringIO(),
        )
        return json.loads(output.read_text(encoding="utf-8"))

    def test_dry_run_is_read_only_and_reports_exact_per_target_blockers(self):
        eligible = self._target(2001)
        blocked = self._target(2002, complete_details=False)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha = self._manifest(root, [eligible, blocked])
            with patch(
                "stable.services.historical_race_inventory.invalidate_public_race_cache"
            ) as invalidate:
                result = self._run("dry-run", manifest, manifest_sha, root / "dry-run.json")

        self.assertEqual(
            result["summary"],
            {
                "already_published_count": 0,
                "blocked_count": 1,
                "blocker_counts": {
                    "confirmed_results_missing": 1,
                    "runners_missing": 1,
                },
                "eligible_count": 1,
                "target_count": 2,
            },
        )
        self.assertEqual(
            [row["status"] for row in result["targets"]],
            ["eligible", "blocked"],
        )
        self.assertEqual(
            result["targets"][1]["blockers"],
            ["confirmed_results_missing", "runners_missing"],
        )
        self.assertEqual(
            RaceEvent.objects.filter(visibility_status=RaceEventVisibility.PUBLISHED).count(),
            0,
        )
        self.assertFalse(OperationLog.objects.exists())
        invalidate.assert_not_called()

    def test_manifest_sha_and_per_target_artifact_are_fail_closed(self):
        target = self._target(2003)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha = self._manifest(root, [target])
            with self.assertRaisesMessage(CommandError, "manifest SHA-256"):
                self._run("dry-run", manifest, "0" * 64, root / "wrong-sha.json")

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["targets"][0]["artifact_sha256"] = "f" * 64
            manifest.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            changed_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            with self.assertRaisesMessage(CommandError, "artifact_sha256"):
                self._run("dry-run", manifest, changed_sha, root / "wrong-artifact.json")

        self.assertEqual(
            target.event.visibility_status,
            RaceEventVisibility.DRAFT,
        )
        self.assertFalse(OperationLog.objects.exists())

    def test_manifest_sha_and_json_are_derived_from_the_same_single_read(self):
        target = self._target(2021)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha = self._manifest(root, [target])
            manifest_bytes = manifest.read_bytes()
            with patch.object(Path, "read_bytes", return_value=manifest_bytes) as read_bytes, patch.object(
                Path,
                "read_text",
                side_effect=AssertionError("manifest must not be read a second time"),
            ) as read_text:
                loaded = load_historical_publication_manifest(
                    manifest,
                    expected_sha256=manifest_sha,
                )

        self.assertEqual(loaded.target_ids, (target.pk,))
        read_bytes.assert_called_once_with()
        read_text.assert_not_called()

    def test_manifest_rejects_duplicate_or_missing_target_artifact_rows(self):
        target = self._target(2004)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, _ = self._manifest(root, [target])
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["target_ids"].append(target.pk)
            manifest.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            with self.assertRaisesMessage(CommandError, "重复"):
                self._run("dry-run", manifest, manifest_sha, root / "duplicate.json")

            payload["target_ids"] = [target.pk]
            payload["targets"] = []
            manifest.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            with self.assertRaisesMessage(CommandError, "完整对应"):
                self._run("dry-run", manifest, manifest_sha, root / "missing.json")

    def test_apply_requires_write_gate_actor_and_network_disabled(self):
        target = self._target(2005)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha = self._manifest(root, [target])
            with self.assertRaisesMessage(CommandError, "HISTORICAL_RACE_BACKFILL_ENABLED"):
                self._run(
                    "apply",
                    manifest,
                    manifest_sha,
                    root / "disabled.json",
                    "--actor-username",
                    self.actor.username,
                )
            with override_settings(
                HISTORICAL_RACE_BACKFILL_ENABLED=True,
                HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
            ), self.assertRaisesMessage(CommandError, "--actor-username"):
                self._run("apply", manifest, manifest_sha, root / "no-actor.json")
            with override_settings(
                HISTORICAL_RACE_BACKFILL_ENABLED=True,
                HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=True,
            ), self.assertRaisesMessage(CommandError, "ALLOW_NETWORK"):
                self._run(
                    "apply",
                    manifest,
                    manifest_sha,
                    root / "network-enabled.json",
                    "--actor-username",
                    self.actor.username,
                )

        target.event.refresh_from_db()
        self.assertEqual(target.event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertFalse(OperationLog.objects.exists())

    @override_settings(
        HISTORICAL_RACE_BACKFILL_ENABLED=True,
        HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
    )
    def test_apply_is_atomic_audited_cached_and_idempotent(self):
        first = self._target(2006)
        second = self._target(2007)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha = self._manifest(root, [first, second])
            with patch(
                "stable.services.historical_race_inventory.invalidate_public_race_cache"
            ) as invalidate:
                with self.captureOnCommitCallbacks(execute=True):
                    applied = self._run(
                        "apply",
                        manifest,
                        manifest_sha,
                        root / "apply.json",
                        "--actor-username",
                        self.actor.username,
                    )
                self.assertEqual(invalidate.call_count, 1)
                with self.captureOnCommitCallbacks(execute=True):
                    replay = self._run(
                        "apply",
                        manifest,
                        manifest_sha,
                        root / "replay.json",
                        "--actor-username",
                        self.actor.username,
                    )
                self.assertEqual(invalidate.call_count, 1)

        self.assertEqual(applied["summary"]["published_count"], 2)
        self.assertEqual(applied["summary"]["already_published_count"], 0)
        self.assertTrue(applied["verifier"]["ok"])
        self.assertEqual(applied["verifier"]["checked_count"], 2)
        self.assertEqual(replay["summary"]["published_count"], 0)
        self.assertEqual(replay["summary"]["already_published_count"], 2)
        self.assertEqual(
            OperationLog.objects.filter(action_type="historical_race_publication").count(),
            2,
        )
        for target in (first, second):
            target.event.refresh_from_db()
            self.assertEqual(target.event.visibility_status, RaceEventVisibility.PUBLISHED)
            self.assertEqual(target.event.data_quality_status, RaceEventDataQuality.COMPLETE)

    @override_settings(
        HISTORICAL_RACE_BACKFILL_ENABLED=True,
        HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
    )
    def test_apply_rolls_back_every_target_when_one_target_is_blocked(self):
        eligible = self._target(2008)
        blocked = self._target(2009, complete_details=False)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha = self._manifest(root, [eligible, blocked])
            with patch(
                "stable.services.historical_race_inventory.invalidate_public_race_cache"
            ) as invalidate, self.assertRaisesMessage(CommandError, "发布阻断"):
                self._run(
                    "apply",
                    manifest,
                    manifest_sha,
                    root / "blocked.json",
                    "--actor-username",
                    self.actor.username,
                )

        eligible.event.refresh_from_db()
        blocked.event.refresh_from_db()
        self.assertEqual(eligible.event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(blocked.event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertFalse(OperationLog.objects.exists())
        invalidate.assert_not_called()

    @override_settings(
        HISTORICAL_RACE_BACKFILL_ENABLED=True,
        HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=False,
    )
    def test_verify_outputs_per_target_published_and_complete_state(self):
        target = self._target(2010)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha = self._manifest(root, [target])
            with self.captureOnCommitCallbacks(execute=True):
                self._run(
                    "apply",
                    manifest,
                    manifest_sha,
                    root / "apply.json",
                    "--actor-username",
                    self.actor.username,
                )
            verified = self._run("verify", manifest, manifest_sha, root / "verify.json")

        self.assertTrue(verified["verifier"]["ok"])
        self.assertEqual(
            verified["verifier"]["targets"],
            [
                {
                    "complete": True,
                    "errors": [],
                    "event_id": target.event_id,
                    "published": True,
                    "target_id": target.pk,
                }
            ],
        )

    def test_dry_run_query_count_does_not_scale_with_target_count(self):
        targets = [self._target(2011 + offset) for offset in range(20)]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            one_manifest, one_sha = self._manifest(root, targets[:1], name="one.json")
            many_manifest, many_sha = self._manifest(root, targets, name="many.json")
            with CaptureQueriesContext(connection) as one_queries:
                self._run("dry-run", one_manifest, one_sha, root / "one-output.json")
            with CaptureQueriesContext(connection) as many_queries:
                self._run("dry-run", many_manifest, many_sha, root / "many-output.json")

        self.assertLessEqual(len(many_queries), len(one_queries) + 2)
