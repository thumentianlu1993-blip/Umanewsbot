from __future__ import annotations

import json
import hashlib
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

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
from stable.services.historical_race_batches import (
    select_first_acceptance_targets,
    target_identity,
)
from stable.services.historical_race_date_discovery import (
    DISCOVERY_ADAPTER_ALLOWED_HOSTS,
    _locked_date_discovery_targets,
    apply_date_source_discovery_artifact,
    build_provider_discovery_candidates,
    build_date_source_discovery_artifact,
    parse_distance_evidence,
    validate_date_source_discovery_artifact,
    validate_direct_source_urls,
)
from stable.services.historical_race_inventory import InventoryValidationError, canonical_json, file_identity


@override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
class HistoricalRaceDateDiscoveryTests(TestCase):
    regions = (
        RacingRegion.JAPAN,
        RacingRegion.HONG_KONG,
        RacingRegion.UNITED_KINGDOM,
        RacingRegion.FRANCE,
        RacingRegion.UNITED_STATES,
    )

    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="admin")

    def _series(self, region: str, suffix: str) -> RaceSeries:
        return RaceSeries.objects.create(
            key=f"{region}-{suffix}",
            country_region=region,
            canonical_name_original=f"{region} {suffix}",
            chinese_name=f"{region} {suffix}",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )

    def _target(
        self,
        series: RaceSeries,
        year: int,
        *,
        expectation: str = HistoricalRaceExpectationStatus.HELD,
    ) -> HistoricalRaceEventTarget:
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=year,
            expectation_status=expectation,
            resolution_status=HistoricalRaceResolutionStatus.PENDING,
            original_name=series.canonical_name_original,
            chinese_name=series.chinese_name,
            racecourse="Test Course",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            distance_text=(
                "1m 4f"
                if series.country_region == RacingRegion.UNITED_KINGDOM
                else "6f"
                if series.country_region == RacingRegion.UNITED_STATES
                else "2400m"
            ),
            source_refs={"catalog": "official", "preserve_me": True},
            artifact_sha256="a" * 64,
        )

    def _candidate(
        self,
        target: HistoricalRaceEventTarget,
        *,
        local_date: str | None = None,
        url_key: str = "result_url",
        url: str = "https://www.racingpost.com/results/fixture",
        adapter_key: str = "uk_racingpost",
        actual_year: int | None = None,
        cross_year_reason: str = "",
    ) -> dict:
        authority_by_adapter = {
            "hkjc": "official",
            "france_galop": "official",
            "uk_racingpost": "third_party_high_access",
        }
        row = {
            "target_id": target.pk,
            "expected_target_sha256": target_identity(target)["target_sha256"],
            "inventory_manifest_sha256": "a" * 64,
            "adapter_key": adapter_key,
            "local_date": local_date or f"{target.year}-06-01",
            "urls": {
                url_key: {
                    "url": url,
                    "source_provider": adapter_key,
                    "source_authority": authority_by_adapter.get(adapter_key, "third_party_high_access"),
                    "redirect_chain": [],
                }
            },
            "distance_text": target.distance_text,
        }
        if actual_year is not None:
            row["actual_year"] = actual_year
        if cross_year_reason:
            row["cross_year_reason"] = cross_year_reason
        return row

    def _approve(self, artifact_dir: Path, target_ids: list[int]) -> Path:
        approval_path = artifact_dir / "approval.json"
        approval_path.write_text(
            json.dumps(
                {
                    "status": "approved",
                    "manifest_identity": file_identity(
                        artifact_dir / "manifest.json", relative_to=artifact_dir
                    ).as_dict(),
                    "approved_by": self.actor.username,
                    "approved_at": "2026-07-13T00:00:00Z",
                    "approved_target_ids": target_ids,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return approval_path

    def _selection_snapshot(self, targets: list[HistoricalRaceEventTarget], root: Path) -> Path:
        path = root / "selection-snapshot.json"
        payload = {
            "schema_version": "1.0",
            "inventory_manifest_sha256": "a" * 64,
            "target_count": len(targets),
            "targets": [target_identity(target) for target in targets],
        }
        payload["snapshot_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _build_artifact(
        self,
        rows: list[dict],
        root: Path,
        *,
        selected_targets: list[HistoricalRaceEventTarget] | None = None,
    ) -> dict:
        if selected_targets is None:
            target_ids = sorted({int(row["target_id"]) for row in rows})
            selected_targets = list(
                HistoricalRaceEventTarget.objects.select_related("race_series", "event")
                .filter(pk__in=target_ids)
                .order_by("pk")
            )
        source_cache_manifest = root / "input-source-cache-manifest.json"
        request_ledger = root / "input-request-ledger.jsonl"
        cache_files = {}
        request_rows = []
        identities_by_url = {}
        for row in rows:
            for evidence in (row.get("urls") or {}).values():
                url = evidence["url"]
                cache_identity = identities_by_url.get(url)
                if cache_identity is None:
                    index = len(identities_by_url) + 1
                    cache_identity = {
                        "path": f"fixture/source-{index}.html",
                        "sha256": f"{index:064x}"[-64:],
                        "size": 4,
                        "source_url": url,
                    }
                    identities_by_url[url] = cache_identity
                cache_files[cache_identity["path"]] = cache_identity
                request_rows.append(
                    {
                        "source_url": url,
                        "status": "succeeded",
                        "source_cache_identity": cache_identity,
                    }
                )
        source_cache_manifest.write_text(
            json.dumps({"schema_version": "1.0", "files": cache_files}) + "\n",
            encoding="utf-8",
        )
        request_ledger.write_text(
            "".join(json.dumps(item) + "\n" for item in request_rows),
            encoding="utf-8",
        )
        return build_date_source_discovery_artifact(
            candidate_rows=rows,
            selection_snapshot_path=self._selection_snapshot(selected_targets, root),
            output_dir=root,
            inventory_manifest_sha256="a" * 64,
            source_cache_manifest_path=source_cache_manifest,
            request_ledger_path=request_ledger,
        )

    def test_failed_source_request_keeps_candidate_in_gap_ledger(self):
        series = self._series(RacingRegion.UNITED_KINGDOM, "fetch-failed")
        target = self._target(series, 2000)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = self._candidate(target)
            source_cache_manifest = root / "source-cache-manifest.json"
            request_ledger = root / "request-ledger.jsonl"
            source_cache_manifest.write_text('{"schema_version":"1.0","files":{}}\n', encoding="utf-8")
            request_ledger.write_text(
                json.dumps(
                    {
                        "source_url": row["urls"]["result_url"]["url"],
                        "status": "failed",
                        "error": "HTTP Error 406",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = build_date_source_discovery_artifact(
                candidate_rows=[row],
                selection_snapshot_path=self._selection_snapshot([target], root),
                output_dir=root / "artifact",
                inventory_manifest_sha256="a" * 64,
                source_cache_manifest_path=source_cache_manifest,
                request_ledger_path=request_ledger,
            )

            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["gap_count"], 1)
            review = (root / "artifact" / "date_source_review.csv").read_text(encoding="utf-8-sig")
            self.assertIn("source_fetch_not_succeeded:result_url", review)

    def test_postgres_lock_query_does_not_join_nullable_event_relation(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "lock-query"), 2000)

        queryset = _locked_date_discovery_targets([target.pk])

        self.assertIn("race_series", queryset.query.select_related)
        self.assertNotIn("event", queryset.query.select_related)

    def _build_and_approve(self, rows: list[dict], root: Path) -> tuple[Path, Path]:
        self._build_artifact(rows, root)
        return root, self._approve(root, [row["target_id"] for row in rows])

    def test_pre_discovery_selection_uses_pending_targets_in_1998_stage(self):
        series_by_region: dict[str, list[str]] = {}
        for region in self.regions:
            series_by_region[region] = []
            for index in range(3):
                series = self._series(region, f"series-{index}")
                series_by_region[region].append(series.key)
                for year in (2000, 2012, 2025):
                    self._target(series, year)

        selected = select_first_acceptance_targets(
            series_keys_by_region=series_by_region,
            anchors=(2000, 2012, 2025),
            require_ready=False,
        )

        self.assertEqual(len(selected), 45)
        self.assertTrue(all(target.event_id is None for target in selected))
        self.assertTrue(all(target.resolution_status == HistoricalRaceResolutionStatus.PENDING for target in selected))
        for region in self.regions:
            regional = [target for target in selected if target.country_region == region]
            self.assertEqual({target.year for target in regional}, {2000, 2012, 2025})

    def test_post_discovery_selection_requires_same_target_ids(self):
        series_by_region: dict[str, list[str]] = {}
        selected_ids: list[int] = []
        for region in self.regions:
            series_by_region[region] = []
            for index in range(3):
                series = self._series(region, f"post-{index}")
                series_by_region[region].append(series.key)
                for year in (2000, 2012, 2025):
                    target = self._target(series, year)
                    target.resolution_status = HistoricalRaceResolutionStatus.READY
                    target.save(update_fields={"resolution_status"})
                    event = RaceEvent.objects.create(
                        race_series=series,
                        year=year,
                        slug=f"{series.key}-{year}",
                        original_name=target.original_name,
                        chinese_name=target.chinese_name,
                        country_region=region,
                        racecourse=target.racecourse,
                        status=RaceEventStatus.FINISHED,
                        visibility_status=RaceEventVisibility.DRAFT,
                        source_refs={"historical_target_id": target.pk},
                    )
                    target.event = event
                    target.save(update_fields={"event"})
                    selected_ids.append(target.pk)

        selected = select_first_acceptance_targets(
            series_keys_by_region=series_by_region,
            anchors=(2000, 2012, 2025),
            require_ready=True,
            required_target_ids=selected_ids,
        )
        self.assertEqual({target.pk for target in selected}, set(selected_ids))

        with self.assertRaisesMessage(InventoryValidationError, "same target ids"):
            select_first_acceptance_targets(
                series_keys_by_region=series_by_region,
                anchors=(2000, 2012, 2025),
                require_ready=True,
                required_target_ids=selected_ids[:-1],
            )

    def test_acceptance_batch_command_exports_pending_snapshot(self):
        series_by_region: dict[str, list[str]] = {}
        for region in self.regions:
            series_by_region[region] = []
            for index in range(3):
                series = self._series(region, f"command-series-{index}")
                series_by_region[region].append(series.key)
                for year in (2000, 2012, 2025):
                    self._target(series, year)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection_path = root / "series.json"
            output_path = root / "acceptance.json"
            selection_path.write_text(json.dumps(series_by_region), encoding="utf-8")
            call_command(
                "build_historical_race_acceptance_batch",
                series_selection=str(selection_path),
                anchors="2000,2012,2025",
                inventory_manifest_sha256="a" * 64,
                output=str(output_path),
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["target_count"], 45)
        self.assertTrue(all(row["resolution_status"] == "pending" for row in payload["targets"]))

    def test_artifact_binds_manifest_targets_and_source_cache(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "artifact"), 2000)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._build_artifact([self._candidate(target)], root)

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(manifest["inventory_manifest_sha256"], "a" * 64)
            self.assertEqual(manifest["source_cache_manifest_identity"]["path"], "source_cache_manifest.json")
            self.assertEqual(manifest["request_ledger_identity"]["path"], "request_ledger.jsonl")
            self.assertEqual(manifest["selection_snapshot_identity"]["path"], "selection_snapshot.json")
            self.assertTrue((root / "date_source_candidates.jsonl").is_file())
            self.assertTrue((root / "date_source_review.csv").is_file())
            self.assertTrue((root / "gap_ledger.csv").is_file())

            approval = self._approve(root, [target.pk])
            request_ledger_bytes = (root / "request_ledger.jsonl").read_bytes()
            (root / "request_ledger.jsonl").write_text('{"request": "tampered"}\n', encoding="utf-8")
            with self.assertRaisesMessage(InventoryValidationError, "changed after manifest"):
                validate_date_source_discovery_artifact(root, approval)
            (root / "request_ledger.jsonl").write_bytes(request_ledger_bytes)

            manifest["candidate_count"] = 2
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            approval = self._approve(root, [target.pk])
            with self.assertRaisesMessage(InventoryValidationError, "candidate count"):
                validate_date_source_discovery_artifact(root, approval)

    def test_apply_preserves_sources_marks_ready_materializes_and_audits(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "apply"), 2000)
        before_sha = target_identity(target)["target_sha256"]
        with TemporaryDirectory() as tmp:
            root, approval = self._build_and_approve([self._candidate(target)], Path(tmp))
            result = apply_date_source_discovery_artifact(artifact_dir=root, approval_path=approval)

        target.refresh_from_db()
        self.assertEqual(target.local_date, date(2000, 6, 1))
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        self.assertTrue(target.source_refs["preserve_me"])
        self.assertEqual(target.source_refs["result_url"], "https://www.racingpost.com/results/fixture")
        self.assertEqual(target.source_refs["detail_discovery"]["actual_year"], 2000)
        self.assertEqual(target.event.visibility_status, RaceEventVisibility.DRAFT)
        self.assertEqual(result["target_sha256_changes"][0]["before"], before_sha)
        self.assertEqual(result["target_sha256_changes"][0]["after"], target_identity(target)["target_sha256"])
        self.assertTrue(OperationLog.objects.filter(action_type="historical_race_date_source_applied").exists())

    def test_cross_year_running_requires_reason_and_keeps_edition_year(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "bristol"), 2001)
        invalid = self._candidate(target, local_date="2002-01-11", actual_year=2002)
        with TemporaryDirectory() as tmp:
            result = self._build_artifact([invalid], Path(tmp))
            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["gap_count"], 1)
            self.assertIn("cross_year_reason_missing", (Path(tmp) / "gap_ledger.csv").read_text())

        missing_actual_year = self._candidate(
            target,
            local_date="2002-01-11",
            cross_year_reason="2001 running was rescheduled into January 2002",
        )
        with TemporaryDirectory() as tmp:
            result = self._build_artifact([missing_actual_year], Path(tmp))
            self.assertEqual(result["gap_count"], 1)
            self.assertIn("actual_year_missing", (Path(tmp) / "gap_ledger.csv").read_text())

        far_cross_year = self._candidate(
            target,
            local_date="2005-01-11",
            actual_year=2005,
            cross_year_reason="incorrect distant year",
        )
        with TemporaryDirectory() as tmp:
            result = self._build_artifact([far_cross_year], Path(tmp))
            self.assertEqual(result["gap_count"], 1)
            self.assertIn("cross_year_out_of_range", (Path(tmp) / "gap_ledger.csv").read_text())

        valid = self._candidate(
            target,
            local_date="2002-01-11",
            actual_year=2002,
            cross_year_reason="2001 running was rescheduled into January 2002",
        )
        with TemporaryDirectory() as tmp:
            root, approval = self._build_and_approve([valid], Path(tmp))
            apply_date_source_discovery_artifact(artifact_dir=root, approval_path=approval)

        target.refresh_from_db()
        self.assertEqual(target.year, 2001)
        self.assertEqual(target.local_date, date(2002, 1, 11))
        self.assertEqual(target.event.year, 2001)
        self.assertEqual(target.source_refs["detail_discovery"]["actual_year"], 2002)

    def test_cancelled_target_accepts_cancellation_evidence_without_fake_details(self):
        target = self._target(
            self._series(RacingRegion.HONG_KONG, "cancelled"),
            2012,
            expectation=HistoricalRaceExpectationStatus.CANCELLED,
        )
        row = self._candidate(
            target,
            url_key="cancellation_url",
            url="https://racing.hkjc.com/racing/information/English/Racing/Cancelled.aspx",
            adapter_key="hkjc",
        )
        with TemporaryDirectory() as tmp:
            root, approval = self._build_and_approve([row], Path(tmp))
            apply_date_source_discovery_artifact(artifact_dir=root, approval_path=approval)

        target.refresh_from_db()
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)
        self.assertEqual(target.event.status, RaceEventStatus.CANCELLED)
        self.assertFalse(target.event.runners.exists())
        self.assertFalse(target.event.results.exists())

    def test_apply_rejects_hash_drift_without_partial_writes(self):
        first = self._target(self._series(RacingRegion.UNITED_KINGDOM, "first"), 2000)
        second = self._target(self._series(RacingRegion.UNITED_KINGDOM, "second"), 2001)
        with TemporaryDirectory() as tmp:
            root, approval = self._build_and_approve(
                [self._candidate(first), self._candidate(second)], Path(tmp)
            )
            second.original_name = "Changed after approval"
            second.save(update_fields={"original_name"})
            with self.assertRaisesMessage(InventoryValidationError, "changed after approval"):
                apply_date_source_discovery_artifact(artifact_dir=root, approval_path=approval)

        first.refresh_from_db()
        self.assertIsNone(first.local_date)
        self.assertEqual(first.resolution_status, HistoricalRaceResolutionStatus.PENDING)
        self.assertFalse(RaceEvent.objects.exists())

    def test_apply_rolls_back_all_targets_when_materialization_fails(self):
        first = self._target(self._series(RacingRegion.UNITED_KINGDOM, "rollback-a"), 2000)
        second = self._target(self._series(RacingRegion.UNITED_KINGDOM, "rollback-b"), 2001)
        with TemporaryDirectory() as tmp:
            root, approval = self._build_and_approve(
                [self._candidate(first), self._candidate(second)], Path(tmp)
            )
            with patch(
                "stable.services.historical_race_date_discovery.materialize_historical_event",
                side_effect=[object(), RuntimeError("simulated materialize failure")],
            ):
                with self.assertRaisesMessage(RuntimeError, "simulated materialize failure"):
                    apply_date_source_discovery_artifact(artifact_dir=root, approval_path=approval)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNone(first.local_date)
        self.assertIsNone(second.local_date)
        self.assertEqual(OperationLog.objects.count(), 0)

    def test_unapproved_operator_cannot_apply(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "operator"), 2000)
        with TemporaryDirectory() as tmp:
            root, approval = self._build_and_approve([self._candidate(target)], Path(tmp))
            payload = json.loads(approval.read_text(encoding="utf-8"))
            payload["approved_by"] = "missing-user"
            approval.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesMessage(InventoryValidationError, "approval operator"):
                apply_date_source_discovery_artifact(artifact_dir=root, approval_path=approval)

    def test_missing_date_duplicate_candidates_and_held_without_result_stay_in_gap_ledger(self):
        missing_date = self._target(self._series(RacingRegion.FRANCE, "missing-date"), 2000)
        no_result = self._target(self._series(RacingRegion.FRANCE, "no-result"), 2001)
        duplicate = self._target(self._series(RacingRegion.FRANCE, "duplicate"), 2002)
        missing_row = self._candidate(
            missing_date,
            local_date="2000-06-01",
            url="https://www.france-galop.com/fr/course/fixture",
            adapter_key="france_galop",
        )
        missing_row["local_date"] = ""
        no_result_row = self._candidate(
            no_result,
            url_key="declared_runners_url",
            url="https://www.france-galop.com/fr/course/fixture",
            adapter_key="france_galop",
        )
        first_duplicate = self._candidate(
            duplicate,
            local_date="2002-06-01",
            url="https://www.france-galop.com/fr/course/a",
            adapter_key="france_galop",
        )
        second_duplicate = self._candidate(
            duplicate,
            local_date="2002-06-08",
            url="https://www.france-galop.com/fr/course/b",
            adapter_key="france_galop",
        )

        with TemporaryDirectory() as tmp:
            result = self._build_artifact(
                [missing_row, no_result_row, first_duplicate, second_duplicate],
                Path(tmp),
            )
            gaps = (Path(tmp) / "gap_ledger.csv").read_text(encoding="utf-8")

        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["gap_count"], 3)
        self.assertIn("missing_date", gaps)
        self.assertIn("held_direct_result_missing", gaps)
        self.assertIn("multiple_candidates", gaps)

    def test_direct_url_without_source_authority_stays_in_gap(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "missing-authority"), 2000)
        row = self._candidate(target)
        row["urls"]["result_url"]["source_authority"] = ""
        with TemporaryDirectory() as tmp:
            result = self._build_artifact([row], Path(tmp))
            gaps = (Path(tmp) / "gap_ledger.csv").read_text(encoding="utf-8")
        self.assertEqual(result["gap_count"], 1)
        self.assertIn("source authority", gaps)

    def test_wrong_region_and_supplementary_only_result_sources_stay_in_gap(self):
        france = self._target(self._series(RacingRegion.FRANCE, "wrong-region"), 2000)
        usa = self._target(self._series(RacingRegion.UNITED_STATES, "supplementary"), 2000)
        wrong_region = self._candidate(france)
        supplementary = self._candidate(
            usa,
            adapter_key="bloodhorse",
            url="https://www.bloodhorse.com/horse-racing/race/fixture",
        )
        supplementary["urls"]["result_url"]["source_authority"] = "third_party"
        with TemporaryDirectory() as tmp:
            result = self._build_artifact([wrong_region, supplementary], Path(tmp))
            gaps = (Path(tmp) / "gap_ledger.csv").read_text(encoding="utf-8")
        self.assertEqual(result["gap_count"], 2)
        self.assertIn("adapter_region_mismatch", gaps)
        self.assertIn("held_primary_result_provider_missing", gaps)

    def test_selection_snapshot_keeps_missing_candidates_in_gaps_and_rejects_substitution(self):
        selected = self._target(self._series(RacingRegion.FRANCE, "selected"), 2000)
        missing = self._target(self._series(RacingRegion.FRANCE, "missing"), 2001)
        outside = self._target(self._series(RacingRegion.FRANCE, "outside"), 2002)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected_candidate = self._candidate(
                selected,
                adapter_key="france_galop",
                url="https://www.france-galop.com/fr/course/selected",
            )
            result = self._build_artifact(
                [selected_candidate],
                root,
                selected_targets=[selected, missing],
            )
            gaps = (root / "gap_ledger.csv").read_text(encoding="utf-8")
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["gap_count"], 1)
            self.assertIn("missing_candidate", gaps)

        with TemporaryDirectory() as tmp:
            with self.assertRaisesMessage(InventoryValidationError, "outside selection snapshot"):
                self._build_artifact(
                    [
                        selected_candidate,
                        self._candidate(
                            outside,
                            adapter_key="france_galop",
                            url="https://www.france-galop.com/fr/course/outside",
                        ),
                    ],
                    Path(tmp),
                    selected_targets=[selected, missing],
                )

    def test_management_command_build_validate_and_commit(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "command"), 2000)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.jsonl"
            source_cache_manifest = root / "source-cache-manifest.json"
            request_ledger = root / "request-ledger.jsonl"
            selection_snapshot = self._selection_snapshot([target], root)
            artifact_dir = root / "artifact"
            candidate = self._candidate(target)
            input_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            source_url = candidate["urls"]["result_url"]["url"]
            cache_identity = {
                "path": "fixture/source.html",
                "sha256": "b" * 64,
                "size": 4,
                "source_url": source_url,
            }
            source_cache_manifest.write_text(
                json.dumps({"schema_version": "1.0", "files": {cache_identity["path"]: cache_identity}}) + "\n",
                encoding="utf-8",
            )
            request_ledger.write_text(
                json.dumps(
                    {
                        "source_url": source_url,
                        "status": "succeeded",
                        "source_cache_identity": cache_identity,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            call_command(
                "build_historical_race_date_discovery",
                candidate_jsonl=str(input_path),
                output_dir=str(artifact_dir),
                inventory_manifest_sha256="a" * 64,
                source_cache_manifest=str(source_cache_manifest),
                request_ledger=str(request_ledger),
                selection_snapshot=str(selection_snapshot),
            )
            approval = self._approve(artifact_dir, [target.pk])
            manifest, _approval = validate_date_source_discovery_artifact(artifact_dir, approval)
            self.assertEqual(manifest["candidate_count"], 1)
            call_command(
                "build_historical_race_date_discovery",
                commit=True,
                artifact_dir=str(artifact_dir),
                approval=str(approval),
            )

        target.refresh_from_db()
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.READY)

        with self.assertRaises(CommandError):
            call_command("build_historical_race_date_discovery", commit=True)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken = root / "broken.jsonl"
            cache_manifest = root / "cache.json"
            request_ledger = root / "requests.jsonl"
            selection = self._selection_snapshot([target], root)
            broken.write_text("not-json\n", encoding="utf-8")
            cache_manifest.write_text("{}\n", encoding="utf-8")
            request_ledger.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command(
                    "build_historical_race_date_discovery",
                    candidate_jsonl=str(broken),
                    selection_snapshot=str(selection),
                    output_dir=str(root / "artifact"),
                    inventory_manifest_sha256="a" * 64,
                    source_cache_manifest=str(cache_manifest),
                    request_ledger=str(request_ledger),
                )

    def test_direct_urls_reject_non_https_private_hosts_and_redirect_escape(self):
        valid = {
            "result_url": {
                "url": "https://www.racingpost.com/results/fixture",
                "redirect_chain": ["https://www.racingpost.com/results/final"],
                "source_authority": "third_party_high_access",
            }
        }
        validate_direct_source_urls("uk_racingpost", valid)
        sporting_life = validate_direct_source_urls(
            "uk_sportinglife",
            {
                "result_url": {
                    "url": "https://www.sportinglife.com/racing/results/fixture",
                    "redirect_chain": [],
                    "source_authority": "third_party_high_access",
                }
            },
        )
        self.assertEqual(sporting_life["result_url"]["source_provider"], "uk_sportinglife")
        hrn = validate_direct_source_urls(
            "us_hrn",
            {
                "result_url": {
                    "url": "https://entries.horseracingnation.com/entries-results/churchill-downs/2025-09-27",
                    "redirect_chain": [],
                    "source_authority": "third_party_high_access",
                }
            },
        )
        self.assertEqual(hrn["result_url"]["source_provider"], "us_hrn")

        for url in (
            "http://www.racingpost.com/results/fixture",
            "file:///tmp/result.html",
            "https://127.0.0.1/result",
            "https://metadata.google.internal/result",
            "https://evil.example/result",
        ):
            with self.subTest(url=url):
                with self.assertRaises(InventoryValidationError):
                    validate_direct_source_urls(
                        "uk_racingpost",
                        {"result_url": {"url": url, "redirect_chain": [], "source_authority": "third_party_high_access"}},
                    )

        with self.assertRaisesMessage(InventoryValidationError, "redirect"):
            validate_direct_source_urls(
                "uk_racingpost",
                {
                    "result_url": {
                        "url": "https://www.racingpost.com/results/fixture",
                        "redirect_chain": ["https://evil.example/final"],
                        "source_authority": "third_party_high_access",
                    }
                },
            )

    def test_all_regional_adapter_hosts_have_positive_and_negative_cases(self):
        cases = {
            "jra": ("https://www.jra.go.jp/JRADB/accessS.html", "official"),
            "nar": ("https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceNo=9", "official"),
            "netkeiba": ("https://db.netkeiba.com/race/200001010101/", "third_party_high_access"),
            "jbis": ("https://www.jbis.or.jp/race/result/", "third_party_high_access"),
            "hkjc": ("https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx", "official"),
            "uk_racingpost": ("https://www.racingpost.com/results/fixture", "third_party_high_access"),
            "uk_skysports": ("https://www.skysports.com/racing/racecards/fixture", "third_party_high_access"),
            "uk_sportinglife": ("https://www.sportinglife.com/racing/results/fixture", "third_party_high_access"),
            "uk_irishracing": ("https://www.irishracing.com/raceresults/Thu-22nd-Jun-2000/Ascot/1545", "third_party_high_access"),
            "uk_bha": ("https://www.britishhorseracing.com/racing/results/fixture", "official"),
            "france_galop": ("https://www.france-galop.com/fr/course/fixture", "official"),
            "pmu": ("https://www.pmu.fr/turf/fixture", "third_party_high_access"),
            "zeturf": ("https://www.zeturf.fr/fr/course-du-jour/fixture", "third_party_high_access"),
            "zone_turf": ("https://www.zone-turf.fr/rapports/fixture", "third_party_database"),
            "france_irishracing": ("https://www.irishracing.com/raceresults/Sun-1st-Oct-2000/Longchamp/1520", "third_party_high_access"),
            "equibase": ("https://www.equibase.com/premium/chartEmb.cfm", "third_party"),
            "brisnet": ("https://www.brisnet.com/content/results/fixture", "third_party"),
            "drf": ("https://www.drf.com/race-results/fixture", "third_party_high_access"),
            "bloodhorse": ("https://www.bloodhorse.com/horse-racing/race/fixture", "third_party"),
            "nsa": ("https://nationalsteeplechase.com/results/fixture", "official"),
            "us_hrn": ("https://entries.horseracingnation.com/entries-results/fixture", "third_party_high_access"),
        }
        self.assertEqual(set(cases), set(DISCOVERY_ADAPTER_ALLOWED_HOSTS))
        for adapter_key, (url, authority) in cases.items():
            with self.subTest(adapter_key=adapter_key):
                validate_direct_source_urls(
                    adapter_key,
                    {"result_url": {"url": url, "redirect_chain": [], "source_authority": authority}},
                )
                with self.assertRaises(InventoryValidationError):
                    validate_direct_source_urls(
                        adapter_key,
                        {"result_url": {"url": "https://evil.example/result", "redirect_chain": [], "source_authority": authority}},
                    )

    def test_apply_keeps_declared_actual_non_runner_and_result_sources_separate(self):
        target = self._target(self._series(RacingRegion.UNITED_KINGDOM, "source-separation"), 2000)
        row = self._candidate(target)
        row["urls"] = {
            "declared_runners_url": {
                "url": "https://www.skysports.com/racing/racecards/fixture",
                "source_provider": "uk_skysports",
                "source_authority": "reference",
                "redirect_chain": [],
            },
            "actual_runners_url": {
                "url": "https://www.racingpost.com/results/fixture",
                "source_provider": "uk_racingpost",
                "source_authority": "third_party_high_access",
                "redirect_chain": [],
            },
            "non_runner_url": {
                "url": "https://www.skysports.com/racing/racecards/fixture",
                "source_provider": "uk_skysports",
                "source_authority": "reference",
                "redirect_chain": [],
            },
            "result_url": {
                "url": "https://www.racingpost.com/results/fixture",
                "source_provider": "uk_racingpost",
                "source_authority": "third_party_high_access",
                "redirect_chain": [],
            },
        }
        with TemporaryDirectory() as tmp:
            root, approval = self._build_and_approve([row], Path(tmp))
            apply_date_source_discovery_artifact(artifact_dir=root, approval_path=approval)

        target.refresh_from_db()
        for key in ("declared_runners_url", "actual_runners_url", "non_runner_url", "result_url"):
            self.assertEqual(target.source_refs[key], row["urls"][key]["url"])
            self.assertEqual(
                target.source_refs["detail_discovery"]["urls"][key]["source_provider"],
                row["urls"][key]["source_provider"],
            )

    def test_distance_parser_preserves_regional_units_and_rejects_bare_numbers(self):
        uk = parse_distance_evidence("3m 210y", RacingRegion.UNITED_KINGDOM)
        self.assertEqual(uk["distance_text"], "3m 210y")
        self.assertEqual(uk["measurement_system"], "imperial_racing")
        self.assertEqual(uk["components"], [{"value": 3, "unit": "mile"}, {"value": 210, "unit": "yard"}])

        france = parse_distance_evidence("2400m", RacingRegion.FRANCE)
        self.assertEqual(france["components"], [{"value": 2400, "unit": "metre"}])
        self.assertEqual(france["measurement_system"], "metric")

        mixed = parse_distance_evidence("2m 4f 56y", RacingRegion.UNITED_KINGDOM)
        self.assertEqual([part["unit"] for part in mixed["components"]], ["mile", "furlong", "yard"])

        compact = parse_distance_evidence("2m1f", RacingRegion.UNITED_KINGDOM)
        self.assertEqual(
            compact["components"],
            [{"value": 2, "unit": "mile"}, {"value": 1, "unit": "furlong"}],
        )
        self.assertEqual(compact["distance_text"], "2m1f")

        compact_fraction = parse_distance_evidence("3m21/2f", RacingRegion.UNITED_KINGDOM)
        self.assertEqual(
            compact_fraction["components"],
            [{"value": 3, "unit": "mile"}, {"value": 2.5, "unit": "furlong"}],
        )
        self.assertEqual(compact_fraction["distance_text"], "3m21/2f")

        with self.assertRaisesMessage(InventoryValidationError, "explicit unit"):
            parse_distance_evidence("2400", RacingRegion.FRANCE)

    def test_provider_records_map_five_regions_to_fixed_selection_targets(self):
        provider_cases = (
            (
                RacingRegion.JAPAN,
                "jra",
                "https://www.jra.go.jp/JRADB/accessS.html",
                "official",
            ),
            (
                RacingRegion.HONG_KONG,
                "hkjc",
                "https://racing.hkjc.com/en-us/local/information/localresults?RaceNo=8",
                "official",
            ),
            (
                RacingRegion.UNITED_KINGDOM,
                "uk_racingpost",
                "https://www.racingpost.com/results/11/cheltenham/2000-04-19/fixture",
                "third_party_high_access",
            ),
            (
                RacingRegion.FRANCE,
                "france_galop",
                "https://www.france-galop.com/fr/content/resultat-fixture",
                "official",
            ),
            (
                RacingRegion.UNITED_STATES,
                "equibase",
                "https://tvg.equibase.com/static/chart/pdf/CD102900USA.pdf",
                "third_party",
            ),
        )
        targets = [self._target(self._series(region, "provider"), 2000) for region, *_rest in provider_cases]
        with TemporaryDirectory() as tmp:
            snapshot = self._selection_snapshot(targets, Path(tmp))
            records = []
            for target, (_region, adapter_key, url, authority) in zip(targets, provider_cases, strict=True):
                records.append(
                    {
                        "adapter_key": adapter_key,
                        "series_key": target.race_series.key,
                        "edition_year": target.year,
                        "local_date": "2000-06-01",
                        "distance_text": target.distance_text,
                        "urls": {
                            "result_url": {
                                "url": url,
                                "source_provider": adapter_key,
                                "source_authority": authority,
                                "redirect_chain": [],
                            }
                        },
                    }
                )
            result = build_provider_discovery_candidates(
                provider_rows=records,
                selection_snapshot_path=snapshot,
                inventory_manifest_sha256="a" * 64,
            )

        self.assertEqual(len(result["candidate_rows"]), 5)
        self.assertEqual(result["issues"], [])
        self.assertEqual(
            {row["target_id"] for row in result["candidate_rows"]},
            {target.pk for target in targets},
        )
        self.assertTrue(all(row["expected_target_sha256"] for row in result["candidate_rows"]))

    def test_provider_records_preserve_conflicts_cross_year_and_cancellation_evidence(self):
        bristol = self._target(self._series(RacingRegion.UNITED_KINGDOM, "provider-bristol"), 2001)
        cancelled = self._target(
            self._series(RacingRegion.HONG_KONG, "provider-cancelled"),
            2012,
            expectation=HistoricalRaceExpectationStatus.CANCELLED,
        )
        with TemporaryDirectory() as tmp:
            snapshot = self._selection_snapshot([bristol, cancelled], Path(tmp))
            base_bristol = {
                "adapter_key": "uk_racingpost",
                "series_key": bristol.race_series.key,
                "edition_year": 2001,
                "local_date": "2002-01-11",
                "actual_year": 2002,
                "cross_year_reason": "2001 running was staged in January 2002",
                "distance_text": "3m",
                "urls": {
                    "result_url": {
                        "url": "https://www.racingpost.com/results/26/huntingdon/2002-01-11/fixture",
                        "source_provider": "uk_racingpost",
                        "source_authority": "third_party_high_access",
                        "redirect_chain": [],
                    }
                },
            }
            records = [
                base_bristol,
                {**base_bristol, "local_date": "2002-01-12"},
                {
                    "adapter_key": "hkjc",
                    "series_key": cancelled.race_series.key,
                    "edition_year": 2012,
                    "local_date": "2012-09-16",
                    "distance_text": "1600m",
                    "urls": {
                        "cancellation_url": {
                            "url": "https://racing.hkjc.com/racing/information/English/Racing/Cancelled.aspx",
                            "source_provider": "hkjc",
                            "source_authority": "official",
                            "redirect_chain": [],
                        }
                    },
                },
            ]
            result = build_provider_discovery_candidates(
                provider_rows=records,
                selection_snapshot_path=snapshot,
                inventory_manifest_sha256="a" * 64,
            )

        self.assertEqual(len(result["candidate_rows"]), 3)
        self.assertEqual(result["candidate_rows"][0]["actual_year"], 2002)
        self.assertIn("cross_year_reason", result["candidate_rows"][0])
        self.assertIn("cancellation_url", result["candidate_rows"][2]["urls"])

    def test_provider_records_report_unknown_target_and_region_mismatch(self):
        target = self._target(self._series(RacingRegion.FRANCE, "provider-errors"), 2000)
        with TemporaryDirectory() as tmp:
            snapshot = self._selection_snapshot([target], Path(tmp))
            result = build_provider_discovery_candidates(
                provider_rows=[
                    {
                        "adapter_key": "hkjc",
                        "series_key": target.race_series.key,
                        "edition_year": 2000,
                        "local_date": "2000-06-01",
                        "distance_text": "2400m",
                        "urls": {},
                    },
                    {
                        "adapter_key": "france_galop",
                        "series_key": "unknown-series",
                        "edition_year": 2000,
                        "local_date": "2000-06-01",
                        "distance_text": "2400m",
                        "urls": {},
                    },
                ],
                selection_snapshot_path=snapshot,
                inventory_manifest_sha256="a" * 64,
            )

        self.assertEqual(result["candidate_rows"], [])
        self.assertEqual(
            [issue["code"] for issue in result["issues"]],
            ["adapter_region_mismatch", "target_not_in_selection"],
        )
