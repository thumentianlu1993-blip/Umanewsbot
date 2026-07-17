from __future__ import annotations

import hashlib
import importlib
import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase

from stable.models import (
    HistoricalRaceEventTarget,
    OperationLog,
    RaceEvent,
    RaceEventResult,
    RaceEventRunner,
    RaceEventStatus,
    RaceEventSurface,
    RaceEventVisibility,
    RaceSeries,
    RaceSeriesName,
    RaceSeriesRelation,
    RaceSeriesRelationType,
    RaceSeriesReviewStatus,
    RacingRegion,
)


class RaceSeriesIdentityReviewTests(TestCase):
    maxDiff = None

    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="identity-reviewer",
            password="unused",
        )

    @staticmethod
    def _service():
        return importlib.import_module("stable.services.race_series_identity_review")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _series(self, key: str, *, region: str = RacingRegion.UNITED_STATES) -> RaceSeries:
        return RaceSeries.objects.create(
            key=key,
            country_region=region,
            canonical_name_original=key.replace("-", " ").title(),
            review_status=RaceSeriesReviewStatus.APPROVED,
            manual_lock_flags={"existing_series_lock": True},
            source_refs={"catalogue": key},
        )

    def _event(
        self,
        *,
        series: RaceSeries,
        year: int,
        slug: str,
        surface: str = RaceEventSurface.DIRT,
        local_date: date | None = None,
    ) -> RaceEvent:
        return RaceEvent.objects.create(
            race_series=series,
            year=year,
            slug=slug,
            original_name=slug.replace("-", " ").title(),
            chinese_name=slug,
            country_region=series.country_region,
            racecourse="Santa Anita Park",
            grade_text="G3",
            normalized_grade="G3",
            surface=surface,
            distance_text="6f",
            local_date=local_date or date(year, 9, 26),
            status=RaceEventStatus.SCHEDULED,
            visibility_status=RaceEventVisibility.PUBLISHED,
            source_refs={"calendar": "existing"},
            manual_lock_flags={"results": True},
        )

    def _target(
        self,
        *,
        series: RaceSeries,
        year: int,
        target_id: int | None = None,
    ) -> HistoricalRaceEventTarget:
        values = {
            "race_series": series,
            "year": year,
            "country_region": series.country_region,
            "original_name": series.canonical_name_original,
            "surface": RaceEventSurface.TURF,
            "local_date": date(year, 9, 26),
        }
        if target_id is not None:
            values["id"] = target_id
        return HistoricalRaceEventTarget.objects.create(**values)

    def _decision(
        self,
        *,
        sequence: int,
        decision: str,
        target: HistoricalRaceEventTarget,
        event: RaceEvent,
        evidence: str | None = None,
        sheet: str = "test-sheet",
        decision_id: str | None = None,
    ) -> dict:
        return {
            "decision_id": decision_id or f"{sheet}:{sequence}",
            "sheet": sheet,
            "sequence": sequence,
            "decision": decision,
            "target_id": target.pk,
            "target_series_id": target.race_series_id,
            "event_id": event.pk,
            "event_series_id": event.race_series_id,
            "year": target.year,
            "country_region": target.country_region,
            "confidence": "high",
            "evidence": {
                "summary": evidence or f"review evidence {sequence}",
                "source_urls": [f"https://example.test/review/{sequence}"],
            },
        }

    def _write_inputs(
        self,
        root: Path,
        decisions: list[dict],
        *,
        repairs: list[dict] | None = None,
    ) -> tuple[Path, Path]:
        decisions_path = root / "decisions.json"
        decisions_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "unit-test",
                    "source_sha256": "a" * 64,
                    "decisions": decisions,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        repairs_path = root / "field-repairs.json"
        repairs_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "repairs": repairs or [],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return decisions_path, repairs_path

    def _prepare(
        self,
        root: Path,
        decisions: list[dict],
        *,
        repairs: list[dict] | None = None,
    ) -> tuple[Path, dict]:
        decisions_path, repairs_path = self._write_inputs(root, decisions, repairs=repairs)
        output = root / "artifact"
        result = self._service().prepare_race_series_identity_review(
            decisions_path=decisions_path,
            field_repairs_path=repairs_path,
            output_dir=output,
        )
        return output, result

    def _approve(
        self,
        output: Path,
        manifest_sha256: str,
        *,
        approved_by: str = "identity-reviewer",
    ) -> tuple[Path, str]:
        approval = output / "approval.json"
        approval.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "approved",
                    "approved_by": approved_by,
                    "approved_at": "2026-07-17T08:30:00+00:00",
                    "manifest_sha256": manifest_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return approval, self._sha256(approval)

    def _positive_fixture(self, *, surface: str = RaceEventSurface.DIRT):
        destination = self._series("destination-series")
        source = self._series("source-series")
        target = self._target(series=destination, year=2026)
        event = self._event(
            series=source,
            year=2026,
            slug="candidate-event-2026",
            surface=surface,
        )
        RaceEventRunner.objects.create(
            event=event,
            sort_order=1,
            horse_number="1",
            horse_name="Runner One",
        )
        RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_number="1",
            horse_name="Runner One",
            is_confirmed=False,
        )
        return destination, source, target, event

    def test_identity_lock_queries_lock_only_base_rows_while_prefetching_series(self):
        _, _, target, event = self._positive_fixture()
        service = self._service()

        for model, row, expected_join in (
            (HistoricalRaceEventTarget, target, "INNER JOIN"),
            (RaceEvent, event, "LEFT OUTER JOIN"),
        ):
            with self.subTest(model=model.__name__):
                queryset = service._identity_rows_for_update(model, {row.pk})
                sql = str(queryset.query)
                self.assertIn(expected_join, sql)
                self.assertTrue(queryset.query.select_for_update)
                self.assertEqual(queryset.query.select_for_update_of, ("self",))

    @skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
    def test_lock_action_rows_executes_with_nullable_series_join_on_postgresql(self):
        destination, source, target, event = self._positive_fixture()

        series, targets, events = self._service()._lock_action_rows(
            {
                "positive_actions": [
                    {
                        "source_series_id": source.pk,
                        "destination_series_id": destination.pk,
                        "target_id": target.pk,
                        "event_id": event.pk,
                    }
                ],
                "negative_actions": [],
            }
        )

        self.assertEqual(set(series), {source.pk, destination.pk})
        self.assertEqual(set(targets), {target.pk})
        self.assertEqual(set(events), {event.pk})

    def test_default_command_is_read_only_and_artifact_is_non_overwriting(self):
        _, _, target, event = self._positive_fixture()
        decision = self._decision(
            sequence=1,
            decision="merge_and_link",
            target=target,
            event=event,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decisions_path, repairs_path = self._write_inputs(root, [decision])
            output = root / "artifact"
            call_command(
                "reconcile_race_series_identity_review",
                "--decisions",
                str(decisions_path),
                "--field-repairs",
                str(repairs_path),
                "--output-dir",
                str(output),
            )
            target.refresh_from_db()
            event.refresh_from_db()
            self.assertIsNone(target.event_id)
            self.assertEqual(event.race_series_id, decision["event_series_id"])
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "actions.json",
                    "approval.json",
                    "decisions.normalized.jsonl",
                    "input.decisions.json",
                    "input.field_repairs.json",
                    "manifest.json",
                    "review.json",
                    "summary.json",
                },
            )
            with self.assertRaises(CommandError):
                call_command(
                    "reconcile_race_series_identity_review",
                    "--decisions",
                    str(decisions_path),
                    "--field-repairs",
                    str(repairs_path),
                    "--output-dir",
                    str(output),
                )

    def test_commit_requires_double_sha_matching_actor_and_stable_identity(self):
        _, _, target, event = self._positive_fixture()
        decision = self._decision(
            sequence=1,
            decision="merge_and_link",
            target=target,
            event=event,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), [decision])
            service = self._service()
            with self.assertRaisesRegex(service.RaceSeriesIdentityReviewError, "approval"):
                service.apply_race_series_identity_review(
                    artifact_dir=output,
                    expected_manifest_sha256=prepared["manifest_sha256"],
                    approval_path=output / "approval.json",
                    expected_approval_sha256=prepared["approval_sha256"],
                    actor=self.actor,
                )
            approval, approval_sha = self._approve(
                output,
                prepared["manifest_sha256"],
                approved_by="someone-else",
            )
            with self.assertRaisesRegex(service.RaceSeriesIdentityReviewError, "actor"):
                service.apply_race_series_identity_review(
                    artifact_dir=output,
                    expected_manifest_sha256=prepared["manifest_sha256"],
                    approval_path=approval,
                    expected_approval_sha256=approval_sha,
                    actor=self.actor,
                )
            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            event.original_name = "Identity Drift"
            event.save(update_fields={"original_name"})
            with self.assertRaisesRegex(service.RaceSeriesIdentityReviewError, "drift"):
                service.apply_race_series_identity_review(
                    artifact_dir=output,
                    expected_manifest_sha256=prepared["manifest_sha256"],
                    approval_path=approval,
                    expected_approval_sha256=approval_sha,
                    actor=self.actor,
                )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)

    def test_positive_merge_links_target_creates_relation_and_preserves_details(self):
        destination, source, target, event = self._positive_fixture()
        decision = self._decision(
            sequence=1,
            decision="merge_and_link",
            target=target,
            event=event,
            evidence="surface=turf appears in prose but is not a field repair",
        )
        before = {
            "visibility": event.visibility_status,
            "status": event.status,
            "surface": event.surface,
            "runners": event.runners.count(),
            "results": event.results.count(),
            "source_refs": event.source_refs,
            "manual_lock_flags": event.manual_lock_flags,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), [decision])
            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            result = self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
            target.refresh_from_db()
            event.refresh_from_db()
            relation = RaceSeriesRelation.objects.get(
                from_series=source,
                to_series=destination,
                relation_type=RaceSeriesRelationType.MERGED_INTO,
            )
            self.assertEqual(target.event_id, event.pk)
            self.assertEqual(event.race_series_id, destination.pk)
            self.assertEqual(event.series_key, destination.key)
            self.assertEqual(relation.review_status, RaceSeriesReviewStatus.APPROVED)
            self.assertEqual(relation.approved_by_id, self.actor.pk)
            self.assertEqual(event.visibility_status, before["visibility"])
            self.assertEqual(event.status, before["status"])
            self.assertEqual(event.surface, before["surface"])
            self.assertEqual(event.runners.count(), before["runners"])
            self.assertEqual(event.results.count(), before["results"])
            self.assertEqual(event.source_refs, before["source_refs"])
            self.assertEqual(event.manual_lock_flags, before["manual_lock_flags"])
            self.assertTrue(result["verification"]["ok"])
            self.assertTrue(
                OperationLog.objects.filter(
                    action_type="race_series_identity_review_applied",
                    admin=self.actor,
                ).exists()
            )

    def test_apply_rejects_source_dependency_or_destination_year_conflict_atomically(self):
        mutations = ("extra_event", "extra_target", "name", "relation", "destination_conflict")
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.captureOnCommitCallbacks(execute=True):
                destination, source, target, event = self._positive_fixture()
                decision = self._decision(
                    sequence=1,
                    decision="merge_and_link",
                    target=target,
                    event=event,
                )
                with tempfile.TemporaryDirectory() as temporary:
                    output, prepared = self._prepare(Path(temporary), [decision])
                    approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
                    extra = None
                    if mutation == "extra_event":
                        extra = self._event(
                            series=source,
                            year=2025,
                            slug="extra-source-event-2025",
                        )
                    elif mutation == "extra_target":
                        extra = self._target(series=source, year=2025)
                    elif mutation == "name":
                        extra = RaceSeriesName.objects.create(
                            series=source,
                            text="Source Alias",
                        )
                    elif mutation == "relation":
                        other = self._series("other-series")
                        extra = RaceSeriesRelation.objects.create(
                            from_series=source,
                            to_series=other,
                            relation_type=RaceSeriesRelationType.REPLACED_BY,
                        )
                    else:
                        extra = self._event(
                            series=destination,
                            year=2026,
                            slug="destination-conflict-2026",
                        )
                    with self.assertRaisesRegex(
                        self._service().RaceSeriesIdentityReviewError,
                        "drift|dependency|conflict",
                    ):
                        self._service().apply_race_series_identity_review(
                            artifact_dir=output,
                            expected_manifest_sha256=prepared["manifest_sha256"],
                            approval_path=approval,
                            expected_approval_sha256=approval_sha,
                            actor=self.actor,
                        )
                    target.refresh_from_db()
                    event.refresh_from_db()
                    self.assertIsNone(target.event_id)
                    self.assertEqual(event.race_series_id, source.pk)
                    self.assertFalse(
                        RaceSeriesRelation.objects.filter(
                            from_series=source,
                            to_series=destination,
                            relation_type=RaceSeriesRelationType.MERGED_INTO,
                        ).exists()
                    )
                    extra.delete()
                HistoricalRaceEventTarget.objects.all().delete()
                RaceEvent.objects.all().delete()
                RaceSeriesRelation.objects.all().delete()
                RaceSeriesName.objects.all().delete()
                RaceSeries.objects.all().delete()

    def test_negative_decisions_write_symmetric_idempotent_locks_and_helper_blocks_pair(self):
        left = self._series("bayakoa-oaklawn")
        right = self._series("bayakoa-california")
        left_target_2025 = self._target(series=left, year=2025)
        left_target_2026 = self._target(series=left, year=2026)
        right_event_2025 = self._event(
            series=right,
            year=2025,
            slug="bayakoa-california-2025",
        )
        right_event_2026 = self._event(
            series=right,
            year=2026,
            slug="bayakoa-california-2026",
        )
        decisions = [
            self._decision(
                sequence=1,
                decision="keep_independent",
                target=left_target_2025,
                event=right_event_2025,
            ),
            self._decision(
                sequence=2,
                decision="keep_independent",
                target=left_target_2026,
                event=right_event_2026,
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), decisions)
            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
        left.refresh_from_db()
        right.refresh_from_db()
        left_entry = left.manual_lock_flags["identity_do_not_merge"][str(right.pk)]
        right_entry = right.manual_lock_flags["identity_do_not_merge"][str(left.pk)]
        self.assertEqual(left_entry["decision"], "keep_independent")
        self.assertEqual(right_entry["decision"], "keep_independent")
        self.assertEqual(len(left_entry["evidence"]), 2)
        self.assertEqual(len(right_entry["evidence"]), 2)
        self.assertTrue(self._service().is_identity_pair_do_not_merge(left, right))
        self.assertTrue(self._service().is_identity_pair_do_not_merge(right, left))
        self.assertEqual(left.manual_lock_flags["existing_series_lock"], True)
        self.assertEqual(right.manual_lock_flags["existing_series_lock"], True)

    def test_production_shape_allows_cross_sheet_sequences_shared_series_and_multi_pair_locks(
        self,
    ):
        destination = self._series("shared-destination")
        source = self._series("positive-source")
        false_match = self._series("false-match-series")
        independent = self._series("independent-series")
        positive_target = self._target(series=destination, year=2026)
        positive_event = self._event(
            series=source,
            year=2026,
            slug="positive-source-2026",
        )
        false_match_target = self._target(series=destination, year=2025)
        false_match_event = self._event(
            series=false_match,
            year=2025,
            slug="false-match-2025",
        )
        independent_target = self._target(series=destination, year=2024)
        independent_event = self._event(
            series=independent,
            year=2024,
            slug="independent-2024",
        )
        decisions = [
            self._decision(
                sequence=1,
                sheet="identity-conflicts",
                decision_id="identity-conflicts:1",
                decision="merge_and_link",
                target=positive_target,
                event=positive_event,
            ),
            self._decision(
                sequence=1,
                sheet="alias-candidates",
                decision_id="alias-candidates:1",
                decision="ignore_false_match",
                target=false_match_target,
                event=false_match_event,
            ),
            self._decision(
                sequence=2,
                sheet="alias-candidates",
                decision_id="alias-candidates:2",
                decision="keep_independent",
                target=independent_target,
                event=independent_event,
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), decisions)
            approval, approval_sha = self._approve(
                output, prepared["manifest_sha256"]
            )
            applied = self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
            self.assertTrue(applied["verification"]["ok"])
        destination.refresh_from_db()
        false_match.refresh_from_db()
        independent.refresh_from_db()
        locks = destination.manual_lock_flags["identity_do_not_merge"]
        self.assertEqual(
            locks[str(false_match.pk)]["decision"], "ignore_false_match"
        )
        self.assertEqual(
            locks[str(false_match.pk)]["evidence"][0]["decision"],
            "ignore_false_match",
        )
        self.assertEqual(
            locks[str(independent.pk)]["decision"], "keep_independent"
        )
        self.assertEqual(
            locks[str(independent.pk)]["evidence"][0]["decision"],
            "keep_independent",
        )
        self.assertTrue(
            self._service().is_identity_pair_do_not_merge(
                destination, false_match
            )
        )
        self.assertTrue(
            self._service().is_identity_pair_do_not_merge(
                destination, independent
            )
        )
        self.assertEqual(
            false_match.manual_lock_flags["identity_do_not_merge"][
                str(destination.pk)
            ]["decision"],
            "ignore_false_match",
        )
        self.assertEqual(
            independent.manual_lock_flags["identity_do_not_merge"][
                str(destination.pk)
            ]["decision"],
            "keep_independent",
        )

    def test_prepare_rejects_only_conflicting_decisions_for_the_same_exact_pair(self):
        _, _, target, event = self._positive_fixture()
        decisions = [
            self._decision(
                sequence=1,
                sheet="identity-conflicts",
                decision_id="identity-conflicts:1",
                decision="merge_and_link",
                target=target,
                event=event,
            ),
            self._decision(
                sequence=1,
                sheet="alias-candidates",
                decision_id="alias-candidates:1",
                decision="ignore_false_match",
                target=target,
                event=event,
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                self._service().RaceSeriesIdentityReviewError,
                "exact pair.*conflict",
            ):
                self._prepare(Path(temporary), decisions)

    def test_shared_positive_and_negative_event_applies_verifies_and_rolls_back(self):
        destination = self._series("shared-event-destination")
        source = self._series("shared-event-source")
        independent = self._series("shared-event-independent")
        positive_target = self._target(series=destination, year=2026)
        negative_target = self._target(series=independent, year=2026)
        event = self._event(
            series=source,
            year=2026,
            slug="shared-event-source-2026",
        )
        decisions = [
            self._decision(
                sequence=1,
                sheet="identity-conflicts",
                decision_id="identity-conflicts:1",
                decision="merge_and_link",
                target=positive_target,
                event=event,
            ),
            self._decision(
                sequence=1,
                sheet="alias-candidates",
                decision_id="alias-candidates:1",
                decision="keep_independent",
                target=negative_target,
                event=event,
            ),
        ]

        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), decisions)
            approval, approval_sha = self._approve(
                output, prepared["manifest_sha256"]
            )
            applied = self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
            verified = self._service().verify_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                expected_state="applied",
            )
            self.assertTrue(verified["ok"])

            event.refresh_from_db()
            positive_target.refresh_from_db()
            source.refresh_from_db()
            independent.refresh_from_db()
            destination.refresh_from_db()
            self.assertEqual(positive_target.event_id, event.pk)
            self.assertEqual(event.race_series_id, destination.pk)
            self.assertEqual(event.series_key, destination.key)
            self.assertTrue(
                self._service().is_identity_pair_do_not_merge(
                    source, independent
                )
            )
            self.assertFalse(
                self._service().is_identity_pair_do_not_merge(
                    destination, independent
                )
            )

            rolled_back = self._service().rollback_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                rollback_path=applied["rollback_path"],
                expected_rollback_sha256=applied["rollback_sha256"],
                actor=self.actor,
            )
            self.assertTrue(rolled_back["verification"]["ok"])

        event.refresh_from_db()
        positive_target.refresh_from_db()
        source.refresh_from_db()
        independent.refresh_from_db()
        self.assertIsNone(positive_target.event_id)
        self.assertEqual(event.race_series_id, source.pk)
        self.assertEqual(event.series_key, source.key)
        self.assertFalse(
            self._service().is_identity_pair_do_not_merge(source, independent)
        )

    def test_shared_positive_and_negative_event_still_rejects_post_prepare_drift(self):
        destination = self._series("shared-drift-destination")
        source = self._series("shared-drift-source")
        independent = self._series("shared-drift-independent")
        positive_target = self._target(series=destination, year=2026)
        negative_target = self._target(series=independent, year=2026)
        event = self._event(
            series=source,
            year=2026,
            slug="shared-drift-source-2026",
        )
        decisions = [
            self._decision(
                sequence=1,
                sheet="identity-conflicts",
                decision_id="identity-conflicts:1",
                decision="merge_and_link",
                target=positive_target,
                event=event,
            ),
            self._decision(
                sequence=1,
                sheet="alias-candidates",
                decision_id="alias-candidates:1",
                decision="keep_independent",
                target=negative_target,
                event=event,
            ),
        ]

        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), decisions)
            approval, approval_sha = self._approve(
                output, prepared["manifest_sha256"]
            )
            event.original_name = "Unexpected shared event drift"
            event.save(update_fields={"original_name"})
            with self.assertRaisesRegex(
                self._service().RaceSeriesIdentityReviewError,
                "drift",
            ):
                self._service().apply_race_series_identity_review(
                    artifact_dir=output,
                    expected_manifest_sha256=prepared["manifest_sha256"],
                    approval_path=approval,
                    expected_approval_sha256=approval_sha,
                    actor=self.actor,
                )

        event.refresh_from_db()
        positive_target.refresh_from_db()
        source.refresh_from_db()
        independent.refresh_from_db()
        self.assertIsNone(positive_target.event_id)
        self.assertEqual(event.race_series_id, source.pk)
        self.assertFalse(
            self._service().is_identity_pair_do_not_merge(source, independent)
        )

    def test_cross_region_ignore_false_match_preserves_existing_event_owner(self):
        candidate_series = self._series(
            "cross-region-candidate",
            region=RacingRegion.UNITED_STATES,
        )
        event_series = self._series(
            "cross-region-event",
            region=RacingRegion.UNITED_KINGDOM,
        )
        candidate_target = self._target(series=candidate_series, year=2026)
        owner_target = self._target(series=event_series, year=2026)
        event = self._event(
            series=event_series,
            year=2026,
            slug="cross-region-event-2026",
        )
        owner_target.event = event
        owner_target.save(update_fields={"event"})
        decision = self._decision(
            sequence=1,
            decision="ignore_false_match",
            target=candidate_target,
            event=event,
        )

        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), [decision])
            approval, approval_sha = self._approve(
                output, prepared["manifest_sha256"]
            )
            applied = self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
            verified = self._service().verify_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                expected_state="applied",
            )
            self.assertTrue(verified["ok"])

            candidate_target.refresh_from_db()
            owner_target.refresh_from_db()
            event.refresh_from_db()
            candidate_series.refresh_from_db()
            event_series.refresh_from_db()
            self.assertIsNone(candidate_target.event_id)
            self.assertEqual(owner_target.event_id, event.pk)
            self.assertEqual(event.race_series_id, event_series.pk)
            self.assertEqual(
                event.country_region,
                RacingRegion.UNITED_KINGDOM,
            )
            self.assertTrue(
                self._service().is_identity_pair_do_not_merge(
                    candidate_series, event_series
                )
            )
            self.assertTrue(
                self._service().is_identity_pair_do_not_merge(
                    event_series, candidate_series
                )
            )

            rolled_back = self._service().rollback_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                rollback_path=applied["rollback_path"],
                expected_rollback_sha256=applied["rollback_sha256"],
                actor=self.actor,
            )
            self.assertTrue(rolled_back["verification"]["ok"])

        candidate_target.refresh_from_db()
        owner_target.refresh_from_db()
        event.refresh_from_db()
        candidate_series.refresh_from_db()
        event_series.refresh_from_db()
        self.assertIsNone(candidate_target.event_id)
        self.assertEqual(owner_target.event_id, event.pk)
        self.assertEqual(event.race_series_id, event_series.pk)
        self.assertFalse(
            self._service().is_identity_pair_do_not_merge(
                candidate_series, event_series
            )
        )

    def test_cross_region_owned_event_is_rejected_for_keep_or_merge(self):
        for index, decision_value in enumerate(
            ("keep_independent", "merge_and_link"),
            start=1,
        ):
            with self.subTest(decision=decision_value):
                candidate_series = self._series(
                    f"cross-region-rejected-candidate-{index}",
                    region=RacingRegion.UNITED_STATES,
                )
                event_series = self._series(
                    f"cross-region-rejected-event-{index}",
                    region=RacingRegion.UNITED_KINGDOM,
                )
                candidate_target = self._target(
                    series=candidate_series,
                    year=2026,
                )
                owner_target = self._target(series=event_series, year=2026)
                event = self._event(
                    series=event_series,
                    year=2026,
                    slug=f"cross-region-rejected-event-{index}-2026",
                )
                owner_target.event = event
                owner_target.save(update_fields={"event"})
                decision = self._decision(
                    sequence=index,
                    decision=decision_value,
                    target=candidate_target,
                    event=event,
                )

                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaisesRegex(
                        self._service().RaceSeriesIdentityReviewError,
                        "decision identity drift",
                    ):
                        self._prepare(Path(temporary), [decision])

    def test_negative_decision_rows_fail_closed_on_identity_or_detail_drift(self):
        mutations = (
            "target_series",
            "event_series",
            "target_year",
            "event_region",
            "event_detail",
        )
        for index, mutation in enumerate(mutations, start=1):
            with self.subTest(mutation=mutation):
                left = self._series(f"negative-left-{index}")
                right = self._series(f"negative-right-{index}")
                target = self._target(series=left, year=2026)
                event = self._event(
                    series=right,
                    year=2026,
                    slug=f"negative-right-{index}-2026",
                )
                decision = self._decision(
                    sequence=1,
                    decision="keep_independent",
                    target=target,
                    event=event,
                )
                try:
                    with tempfile.TemporaryDirectory() as temporary:
                        output, prepared = self._prepare(
                            Path(temporary), [decision]
                        )
                        approval, approval_sha = self._approve(
                            output, prepared["manifest_sha256"]
                        )
                        if mutation == "target_series":
                            other = self._series(f"other-target-series-{index}")
                            target.race_series = other
                            target.save(update_fields={"race_series"})
                        elif mutation == "event_series":
                            other = self._series(f"other-event-series-{index}")
                            event.race_series = other
                            event.save(update_fields={"race_series"})
                        elif mutation == "target_year":
                            target.year = 2025
                            target.save(update_fields={"year"})
                        elif mutation == "event_region":
                            event.country_region = RacingRegion.HONG_KONG
                            event.save(update_fields={"country_region"})
                        else:
                            RaceEventRunner.objects.create(
                                event=event,
                                sort_order=1,
                                horse_number="1",
                                horse_name="Late Detail",
                            )
                        with self.assertRaisesRegex(
                            self._service().RaceSeriesIdentityReviewError,
                            "drift",
                        ):
                            self._service().apply_race_series_identity_review(
                                artifact_dir=output,
                                expected_manifest_sha256=prepared[
                                    "manifest_sha256"
                                ],
                                approval_path=approval,
                                expected_approval_sha256=approval_sha,
                                actor=self.actor,
                            )
                finally:
                    HistoricalRaceEventTarget.objects.all().delete()
                    RaceEvent.objects.all().delete()
                    RaceSeriesRelation.objects.all().delete()
                    RaceSeriesName.objects.all().delete()
                    RaceSeries.objects.all().delete()

    def test_explicit_john_c_harris_surface_repair_preserves_existing_sources_and_locks(self):
        _, _, target, event = self._positive_fixture(surface=RaceEventSurface.DIRT)
        decision = self._decision(
            sequence=183,
            decision="merge_and_link",
            target=target,
            event=event,
            evidence="John C. Harris is the reviewed continuation.",
        )
        repair = {
            "repair_id": "john-c-harris-surface",
            "event_id": event.pk,
            "field": "surface",
            "expected_before": RaceEventSurface.DIRT,
            "value": RaceEventSurface.TURF,
            "evidence": {
                "summary": "Santa Anita says the race is run on the hillside turf course.",
                "source_urls": ["https://www.santaanita.com/example"],
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), [decision], repairs=[repair])
            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
        event.refresh_from_db()
        self.assertEqual(event.surface, RaceEventSurface.TURF)
        self.assertEqual(event.source_refs["calendar"], "existing")
        self.assertIn("identity_review_field_repairs", event.source_refs)
        self.assertEqual(event.manual_lock_flags["results"], True)
        self.assertTrue(event.manual_lock_flags["surface"])

    def test_apply_verifier_and_rollback_restore_positive_negative_and_repair(self):
        destination, source, target, event = self._positive_fixture(surface=RaceEventSurface.DIRT)
        negative_left = self._series("davona-dale-fair-grounds")
        negative_right = self._series("davona-dale-gulfstream")
        negative_target = self._target(series=negative_left, year=2026)
        negative_event = self._event(
            series=negative_right,
            year=2026,
            slug="davona-dale-gulfstream-2026",
        )
        decisions = [
            self._decision(
                sequence=1,
                decision="merge_and_link",
                target=target,
                event=event,
            ),
            self._decision(
                sequence=2,
                decision="keep_independent",
                target=negative_target,
                event=negative_event,
            ),
        ]
        repair = {
            "repair_id": "john-c-harris-surface",
            "event_id": event.pk,
            "field": "surface",
            "expected_before": RaceEventSurface.DIRT,
            "value": RaceEventSurface.TURF,
            "evidence": {
                "summary": "Official turf evidence.",
                "source_urls": ["https://example.test/official"],
            },
        }
        before_event_sources = event.source_refs
        before_event_locks = event.manual_lock_flags
        before_left_locks = negative_left.manual_lock_flags
        before_right_locks = negative_right.manual_lock_flags
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), decisions, repairs=[repair])
            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            applied = self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
            verified = self._service().verify_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                expected_state="applied",
            )
            self.assertTrue(verified["ok"])
            rolled_back = self._service().rollback_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                rollback_path=applied["rollback_path"],
                expected_rollback_sha256=applied["rollback_sha256"],
                actor=self.actor,
            )
            self.assertTrue(rolled_back["verification"]["ok"])
        target.refresh_from_db()
        event.refresh_from_db()
        negative_left.refresh_from_db()
        negative_right.refresh_from_db()
        self.assertIsNone(target.event_id)
        self.assertEqual(event.race_series_id, source.pk)
        self.assertEqual(event.series_key, source.key)
        self.assertEqual(event.surface, RaceEventSurface.DIRT)
        self.assertEqual(event.source_refs, before_event_sources)
        self.assertEqual(event.manual_lock_flags, before_event_locks)
        self.assertEqual(negative_left.manual_lock_flags, before_left_locks)
        self.assertEqual(negative_right.manual_lock_flags, before_right_locks)
        self.assertFalse(
            RaceSeriesRelation.objects.filter(
                from_series=source,
                to_series=destination,
                relation_type=RaceSeriesRelationType.MERGED_INTO,
            ).exists()
        )
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="race_series_identity_review_rolled_back",
                admin=self.actor,
            ).exists()
        )

    def test_manifest_approval_and_symlink_or_path_replacement_fail_closed(self):
        _, _, target, event = self._positive_fixture()
        decision = self._decision(
            sequence=1,
            decision="merge_and_link",
            target=target,
            event=event,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, prepared = self._prepare(root, [decision])
            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            service = self._service()

            approval.write_bytes(approval.read_bytes() + b" ")
            with self.assertRaisesRegex(service.RaceSeriesIdentityReviewError, "approval SHA"):
                service.apply_race_series_identity_review(
                    artifact_dir=output,
                    expected_manifest_sha256=prepared["manifest_sha256"],
                    approval_path=approval,
                    expected_approval_sha256=approval_sha,
                    actor=self.actor,
                )

            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            actions = output / "actions.json"
            actions_copy = root / "actions-copy.json"
            actions_copy.write_bytes(actions.read_bytes())
            actions.unlink()
            actions.symlink_to(actions_copy)
            with self.assertRaisesRegex(service.RaceSeriesIdentityReviewError, "safely open"):
                service.apply_race_series_identity_review(
                    artifact_dir=output,
                    expected_manifest_sha256=prepared["manifest_sha256"],
                    approval_path=approval,
                    expected_approval_sha256=approval_sha,
                    actor=self.actor,
                )
            target.refresh_from_db()
            self.assertIsNone(target.event_id)

    def test_prepare_publish_collision_does_not_replace_competing_directory(self):
        _, _, target, event = self._positive_fixture()
        decision = self._decision(
            sequence=1,
            decision="merge_and_link",
            target=target,
            event=event,
        )
        service = self._service()
        original_publish = service._publish_directory_no_replace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            decisions_path, repairs_path = self._write_inputs(root, [decision])
            output = root / "artifact"

            def collide(temporary_dir, destination):
                destination.mkdir()
                return original_publish(temporary_dir, destination)

            with mock.patch.object(
                service,
                "_publish_directory_no_replace",
                side_effect=collide,
            ):
                with self.assertRaisesRegex(
                    service.RaceSeriesIdentityReviewError,
                    "already exists",
                ):
                    service.prepare_race_series_identity_review(
                        decisions_path=decisions_path,
                        field_repairs_path=repairs_path,
                        output_dir=output,
                    )
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])

    def test_rollback_detects_post_apply_detail_drift_before_restoring_anything(self):
        _, source, target, event = self._positive_fixture()
        decision = self._decision(
            sequence=1,
            decision="merge_and_link",
            target=target,
            event=event,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), [decision])
            approval, approval_sha = self._approve(output, prepared["manifest_sha256"])
            applied = self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
            RaceEventRunner.objects.create(
                event=event,
                sort_order=2,
                horse_number="2",
                horse_name="Late Runner",
            )
            with self.assertRaisesRegex(
                self._service().RaceSeriesIdentityReviewError,
                "detail drift",
            ):
                self._service().rollback_race_series_identity_review(
                    artifact_dir=output,
                    expected_manifest_sha256=prepared["manifest_sha256"],
                    approval_path=approval,
                    expected_approval_sha256=approval_sha,
                    rollback_path=applied["rollback_path"],
                    expected_rollback_sha256=applied["rollback_sha256"],
                    actor=self.actor,
                )
        target.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(target.event_id, event.pk)
        self.assertNotEqual(event.race_series_id, source.pk)

    def test_rollback_ignores_unrelated_event_changes_after_apply(self):
        _, source, target, event = self._positive_fixture()
        decision = self._decision(
            sequence=1,
            decision="merge_and_link",
            target=target,
            event=event,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output, prepared = self._prepare(Path(temporary), [decision])
            approval, approval_sha = self._approve(
                output, prepared["manifest_sha256"]
            )
            applied = self._service().apply_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                actor=self.actor,
            )
            unrelated_series = self._series("unrelated-series")
            unrelated_event = self._event(
                series=unrelated_series,
                year=2025,
                slug="unrelated-event-2025",
            )
            rolled_back = self._service().rollback_race_series_identity_review(
                artifact_dir=output,
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                rollback_path=applied["rollback_path"],
                expected_rollback_sha256=applied["rollback_sha256"],
                actor=self.actor,
            )
            self.assertTrue(rolled_back["verification"]["ok"])
            self.assertTrue(
                RaceEvent.objects.filter(pk=unrelated_event.pk).exists()
            )
        target.refresh_from_db()
        event.refresh_from_db()
        self.assertIsNone(target.event_id)
        self.assertEqual(event.race_series_id, source.pk)
