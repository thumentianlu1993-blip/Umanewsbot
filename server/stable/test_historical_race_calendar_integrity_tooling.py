from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from stable.models import (
    HistoricalRaceCalendarRepairReceipt,
    HistoricalRaceEventTarget,
    RaceEvent,
    RaceEventDataQuality,
    RaceEventPublicPath,
    RaceEventPublicPathKind,
    RaceEventStatus,
    RaceEventVisibility,
    RaceSeries,
    RacingRegion,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True)
class HistoricalRaceCalendarIntegrityToolingTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # Use the canonical path spelling so macOS /var -> /private/var does not
        # itself become the symlink alias under test.
        self.artifact_root = Path(self.temporary.name).resolve()
        self.actor = get_user_model().objects.create_user(username="repair-actor")
        self.reviewer = get_user_model().objects.create_user(username="repair-reviewer")

    def make_mismatch(
        self,
        *,
        key: str,
        old_year: int = 2025,
        natural_year: int = 2024,
        region: str = RacingRegion.HONG_KONG,
        approved_cross_year: bool = True,
        evidence_classification: str = "legitimate_cross_year_edition",
        authority_url: str = "https://racing.hkjc.com/example",
    ) -> RaceEvent:
        series = RaceSeries.objects.create(
            key=key,
            country_region=region,
            canonical_name_original=key,
            chinese_name=key,
        )
        source_refs = {}
        if approved_cross_year:
            source_refs["cross_year_evidence"] = {
                "actual_year": natural_year,
                "reason": "authority_confirmed_postponement",
                "classification": evidence_classification,
                "authority_url": authority_url,
                "approved": True,
            }
        event = RaceEvent.objects.create(
            year=natural_year,
            edition_year=natural_year,
            slug=f"{key}-{old_year}",
            original_name=key,
            chinese_name=key,
            country_region=region,
            racecourse="Test",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            local_date=date(natural_year, 6, 1),
            status=RaceEventStatus.FINISHED,
            visibility_status=RaceEventVisibility.PUBLISHED,
            data_quality_status=RaceEventDataQuality.COMPLETE,
            race_series=series,
            source_refs=source_refs,
        )
        # Seed a pre-Release-A corrupt row without weakening the production
        # writer contract that now rejects this shape.
        RaceEvent._base_manager.filter(pk=event.pk).update(
            year=old_year,
            edition_year=old_year,
        )
        RaceEventPublicPath._base_manager.filter(
            event=event, path_kind=RaceEventPublicPathKind.CANONICAL
        ).update(year=old_year)
        event.refresh_from_db()
        HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=old_year,
            country_region=region,
            event=event,
        )
        return event

    def test_classifier_reuses_strict_cross_year_authority_url_contract(self):
        from stable.services.historical_race_calendar_integrity import _classify_event

        valid_event = self.make_mismatch(
            key="authority-url-valid",
            evidence_classification="ordinary_season_year_shift",
            authority_url="https://racing.hkjc.com/example?notice=official",
        )
        valid = _classify_event(valid_event)
        self.assertEqual(valid["disposition"], "action")
        self.assertEqual(valid["classification"], "ordinary_season_year_shift")

        invalid_urls = (
            "https://racing.hkjc.com/example#unreviewed-fragment",
            "http://racing.hkjc.com/example",
            "https://reviewer:secret@racing.hkjc.com/example",
            "https://racing.hkjc.com/example notice",
            "not-a-url",
        )
        for index, authority_url in enumerate(invalid_urls):
            with self.subTest(authority_url=authority_url):
                event = self.make_mismatch(
                    key=f"authority-url-invalid-{index}",
                    evidence_classification="ordinary_season_year_shift",
                    authority_url=authority_url,
                )
                classified = _classify_event(event)
                self.assertEqual(classified["disposition"], "manual")
                self.assertEqual(classified["classification"], "needs_manual_review")
                self.assertIn(
                    "hkjc_authoritative_classification_missing",
                    classified["block_reasons"],
                )

    def prepare(self, output_name: str = "prepared") -> dict:
        from stable.services.historical_race_calendar_integrity import (
            prepare_historical_race_calendar_integrity,
        )

        return prepare_historical_race_calendar_integrity(
            output_dir=self.artifact_root / output_name,
            artifact_root=self.artifact_root,
            all_regions=True,
        )

    def approve(self, prepared: dict, *, action_ids: list[str] | None = None) -> tuple[Path, str]:
        manifest_path = Path(prepared["manifest_path"])
        manifest = json.loads(manifest_path.read_text())
        approved_ids = (
            action_ids
            if action_ids is not None
            else [
                row["action_id"]
                for row in manifest["actions"]
                if row["disposition"] == "action"
            ]
        )
        payload = {
            "schema_version": "historical-race-calendar-integrity-approval.v1",
            "status": "approved",
            "manifest_sha256": prepared["manifest_sha256"],
            "action_scope_sha256": manifest["action_scope_sha256"],
            "approved_action_ids": approved_ids,
            "approved_by": self.reviewer.get_username(),
            "approved_at": timezone.now().isoformat(),
            "actor": self.actor.get_username(),
        }
        path = self.artifact_root / "approval.json"
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        return path, _sha256(path)

    def maintenance(self, prepared: dict) -> tuple[Path, str]:
        manifest = json.loads(Path(prepared["manifest_path"]).read_text())
        from stable.services.historical_race_calendar_admission import (
            enter_historical_calendar_maintenance,
        )

        enter_historical_calendar_maintenance(
            manifest_sha256=prepared["manifest_sha256"],
            action_scope_sha256=manifest["action_scope_sha256"],
            actor=self.actor,
        )
        payload = {
            "schema_version": "historical-race-calendar-maintenance-evidence.v1",
            "status": "frozen",
            "manifest_sha256": prepared["manifest_sha256"],
            "action_scope_sha256": manifest["action_scope_sha256"],
            "observed_at": timezone.now().isoformat(),
            "checks": {
                "historical_import": "stopped",
                "reconciliation": "stopped",
                "race_live_projection": "stopped",
                "p0_participant": "stopped",
            },
        }
        path = self.artifact_root / "maintenance.json"
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        return path, _sha256(path)

    def apply_arguments(self, prepared: dict) -> dict:
        approval, approval_sha = self.approve(prepared)
        maintenance, maintenance_sha = self.maintenance(prepared)
        return {
            "manifest_path": prepared["manifest_path"],
            "expected_manifest_sha256": prepared["manifest_sha256"],
            "approval_path": approval,
            "expected_approval_sha256": approval_sha,
            "maintenance_evidence_path": maintenance,
            "expected_maintenance_evidence_sha256": maintenance_sha,
            "actor": self.actor,
            "artifact_root": self.artifact_root,
            "confirm_reviewed_artifact": True,
        }

    def test_apply_feature_gate_defaults_to_fail_closed_before_any_write(self):
        event = self.make_mismatch(
            key="apply-disabled",
            evidence_classification="ordinary_season_year_shift",
        )
        prepared = self.prepare()
        arguments = self.apply_arguments(prepared)
        rollback_path = (
            self.artifact_root
            / "rollback"
            / f"{prepared['manifest_sha256']}.json"
        )
        before = {
            "event": (event.year, event.edition_year, event.slug),
            "receipts": HistoricalRaceCalendarRepairReceipt.objects.count(),
        }
        from stable.services import historical_race_calendar_integrity as integrity

        for configured_settings in (
            SimpleNamespace(),
            SimpleNamespace(HISTORICAL_RACE_BACKFILL_ENABLED=False),
        ):
            with self.subTest(configured_settings=vars(configured_settings)):
                with mock.patch.object(integrity, "settings", configured_settings):
                    with self.assertRaisesMessage(
                        integrity.HistoricalRaceCalendarIntegrityError,
                        "historical race backfill is disabled",
                    ):
                        integrity.apply_historical_race_calendar_integrity(**arguments)

        event.refresh_from_db()
        self.assertEqual(
            (event.year, event.edition_year, event.slug),
            before["event"],
        )
        self.assertEqual(
            HistoricalRaceCalendarRepairReceipt.objects.count(),
            before["receipts"],
        )
        self.assertFalse(rollback_path.exists())

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=False)
    def test_existing_receipt_reentry_cannot_bypass_disabled_feature_gate(self):
        self.make_mismatch(
            key="reentry-disabled",
            evidence_classification="ordinary_season_year_shift",
        )
        prepared = self.prepare()
        arguments = self.apply_arguments(prepared)
        from stable.services import historical_race_calendar_integrity as integrity

        with override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True):
            first = integrity.apply_historical_race_calendar_integrity(**arguments)
        receipt = HistoricalRaceCalendarRepairReceipt.objects.get(pk=first["receipt_id"])
        before = (
            receipt.status,
            receipt.verified_at,
            receipt.verifier_result_sha256,
        )

        with self.assertRaisesMessage(
            integrity.HistoricalRaceCalendarIntegrityError,
            "historical race backfill is disabled",
        ):
            integrity.apply_historical_race_calendar_integrity(**arguments)

        receipt.refresh_from_db()
        self.assertEqual(
            (receipt.status, receipt.verified_at, receipt.verifier_result_sha256),
            before,
        )

    @override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=False)
    def test_rollback_requires_enabled_historical_write_gate(self):
        event = self.make_mismatch(
            key="rollback-disabled",
            evidence_classification="ordinary_season_year_shift",
        )
        prepared = self.prepare()
        arguments = self.apply_arguments(prepared)
        from stable.services import historical_race_calendar_integrity as integrity

        with override_settings(HISTORICAL_RACE_BACKFILL_ENABLED=True):
            applied = integrity.apply_historical_race_calendar_integrity(**arguments)
        receipt = HistoricalRaceCalendarRepairReceipt.objects.get(
            pk=applied["receipt_id"]
        )
        before = (event.pk, receipt.status, receipt.rolled_back_at)

        with self.assertRaisesMessage(
            integrity.HistoricalRaceCalendarIntegrityError,
            "historical race backfill is disabled",
        ):
            integrity.rollback_historical_race_calendar_integrity(
                **arguments,
                rollback_path=applied["rollback_path"],
                expected_rollback_sha256=applied["rollback_sha256"],
            )

        event.refresh_from_db()
        receipt.refresh_from_db()
        self.assertEqual(event.year, 2024)
        self.assertEqual((event.pk, receipt.status, receipt.rolled_back_at), before)

    def test_apply_invalidates_public_year_cache_only_after_commit(self):
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
        )
        from stable.services.race_event_public_cache import (
            invalidate_public_race_cache,
            public_race_calendar_years,
        )

        cache.clear()
        self.addCleanup(cache.clear)
        self.make_mismatch(
            key="apply-cache",
            evidence_classification="ordinary_season_year_shift",
        )
        self.assertEqual(public_race_calendar_years(), [2025])
        arguments = self.apply_arguments(self.prepare())

        with mock.patch(
            "stable.services.historical_race_calendar_integrity.invalidate_public_race_cache",
            wraps=invalidate_public_race_cache,
        ) as invalidate:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                applied = apply_historical_race_calendar_integrity(**arguments)

            self.assertEqual(applied["status"], "verified")
            self.assertEqual(public_race_calendar_years(), [2025])
            invalidate.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            invalidate.assert_called_once_with()
            self.assertEqual(public_race_calendar_years(), [2024])

            invalidate.reset_mock()
            with self.captureOnCommitCallbacks(execute=False) as reentry_callbacks:
                reentered = apply_historical_race_calendar_integrity(**arguments)
            self.assertEqual(reentered["status"], "already_applied")
            self.assertEqual(reentry_callbacks, [])
            invalidate.assert_not_called()

    def test_rollback_invalidates_public_year_cache_only_after_commit(self):
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
            rollback_historical_race_calendar_integrity,
        )
        from stable.services.race_event_public_cache import (
            invalidate_public_race_cache,
            public_race_calendar_years,
        )

        cache.clear()
        self.addCleanup(cache.clear)
        self.make_mismatch(
            key="rollback-cache",
            evidence_classification="ordinary_season_year_shift",
        )
        self.assertEqual(public_race_calendar_years(), [2025])
        arguments = self.apply_arguments(self.prepare())
        with self.captureOnCommitCallbacks(execute=True):
            applied = apply_historical_race_calendar_integrity(**arguments)
        self.assertEqual(public_race_calendar_years(), [2024])

        with mock.patch(
            "stable.services.historical_race_calendar_integrity.invalidate_public_race_cache",
            wraps=invalidate_public_race_cache,
        ) as invalidate:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                rolled_back = rollback_historical_race_calendar_integrity(
                    **arguments,
                    rollback_path=applied["rollback_path"],
                    expected_rollback_sha256=applied["rollback_sha256"],
                )

            self.assertEqual(rolled_back["status"], "rolled_back")
            self.assertEqual(public_race_calendar_years(), [2024])
            invalidate.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            invalidate.assert_called_once_with()
            self.assertEqual(public_race_calendar_years(), [2025])

    def test_failed_apply_discards_cache_invalidation_callback(self):
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
        )
        from stable.services.race_event_public_cache import public_race_calendar_years

        cache.clear()
        self.addCleanup(cache.clear)
        event = self.make_mismatch(
            key="failed-apply-cache",
            evidence_classification="ordinary_season_year_shift",
        )
        self.assertEqual(public_race_calendar_years(), [2025])
        arguments = self.apply_arguments(self.prepare())

        with mock.patch(
            "stable.services.historical_race_calendar_integrity.invalidate_public_race_cache"
        ) as invalidate, mock.patch.object(
            HistoricalRaceCalendarRepairReceipt.objects,
            "create",
            side_effect=RuntimeError("simulated receipt failure"),
        ):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                with self.assertRaisesMessage(RuntimeError, "simulated receipt failure"):
                    apply_historical_race_calendar_integrity(**arguments)

        self.assertEqual(callbacks, [])
        invalidate.assert_not_called()
        event.refresh_from_db()
        self.assertEqual(event.year, 2025)
        self.assertEqual(public_race_calendar_years(), [2025])

    def test_prepare_is_zero_write_and_emits_bound_artifacts(self):
        self.make_mismatch(key="zero-write")
        before = {
            "events": RaceEvent.objects.count(),
            "targets": HistoricalRaceEventTarget.objects.count(),
            "paths": RaceEventPublicPath.objects.count(),
            "receipts": HistoricalRaceCalendarRepairReceipt.objects.count(),
        }

        prepared = self.prepare()

        after = {
            "events": RaceEvent.objects.count(),
            "targets": HistoricalRaceEventTarget.objects.count(),
            "paths": RaceEventPublicPath.objects.count(),
            "receipts": HistoricalRaceCalendarRepairReceipt.objects.count(),
        }
        self.assertEqual(after, before)
        self.assertEqual(
            {path.name for path in (self.artifact_root / "prepared").iterdir()},
            {
                "approval.template.json",
                "census.json",
                "manifest.json",
                "report.md",
                "review.csv",
                "summary.json",
            },
        )
        self.assertEqual(prepared["mismatch_count"], 1)

    def test_prepare_rejects_existing_output_and_symlink_escape(self):
        from stable.services.historical_race_calendar_integrity import (
            prepare_historical_race_calendar_integrity,
        )

        existing = self.artifact_root / "existing"
        existing.mkdir()
        with self.assertRaisesMessage(ValueError, "already exists"):
            prepare_historical_race_calendar_integrity(
                output_dir=existing,
                artifact_root=self.artifact_root,
                all_regions=True,
            )

        outside = Path(self.temporary.name).parent / "outside-calendar-repair"
        escape = self.artifact_root / "escape"
        escape.symlink_to(outside)
        with self.assertRaisesMessage(ValueError, "artifact path"):
            prepare_historical_race_calendar_integrity(
                output_dir=escape,
                artifact_root=self.artifact_root,
                all_regions=True,
            )

    def test_apply_rejects_approval_hash_or_scope_mismatch_before_write(self):
        event = self.make_mismatch(key="approval-drift")
        prepared = self.prepare()
        approval, approval_sha = self.approve(prepared, action_ids=[])
        maintenance, maintenance_sha = self.maintenance(prepared)

        with self.assertRaisesMessage(ValueError, "action IDs"):
            from stable.services.historical_race_calendar_integrity import (
                apply_historical_race_calendar_integrity,
            )

            apply_historical_race_calendar_integrity(
                manifest_path=prepared["manifest_path"],
                expected_manifest_sha256=prepared["manifest_sha256"],
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                maintenance_evidence_path=maintenance,
                expected_maintenance_evidence_sha256=maintenance_sha,
                actor=self.actor,
                artifact_root=self.artifact_root,
                confirm_reviewed_artifact=True,
            )
        event.refresh_from_db()
        self.assertEqual(event.year, 2025)
        self.assertEqual(HistoricalRaceCalendarRepairReceipt.objects.count(), 0)

    def test_duplicate_is_explicitly_blocked_in_release_a(self):
        duplicate = self.make_mismatch(key="duplicate-block")
        RaceEvent.objects.create(
            year=2024,
            edition_year=2024,
            slug="duplicate-block-2024-existing",
            original_name="existing",
            chinese_name="existing",
            country_region=RacingRegion.HONG_KONG,
            racecourse="Test",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            local_date=date(2024, 5, 1),
            race_series=duplicate.race_series,
        )

        prepared = self.prepare()
        manifest = json.loads(Path(prepared["manifest_path"]).read_text())

        self.assertEqual(manifest["actions"][0]["disposition"], "block")
        self.assertEqual(
            manifest["actions"][0]["classification"],
            "canonicalize_duplicate",
        )
        self.assertIn("release_b_required", manifest["actions"][0]["block_reasons"])

    def test_apply_receipt_is_exactly_once_and_reentry_only_verifies(self):
        event = self.make_mismatch(key="idempotent")
        prepared = self.prepare()
        approval, approval_sha = self.approve(prepared)
        maintenance, maintenance_sha = self.maintenance(prepared)
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
        )

        arguments = {
            "manifest_path": prepared["manifest_path"],
            "expected_manifest_sha256": prepared["manifest_sha256"],
            "approval_path": approval,
            "expected_approval_sha256": approval_sha,
            "maintenance_evidence_path": maintenance,
            "expected_maintenance_evidence_sha256": maintenance_sha,
            "actor": self.actor,
            "artifact_root": self.artifact_root,
            "confirm_reviewed_artifact": True,
        }
        first = apply_historical_race_calendar_integrity(**arguments)
        second = apply_historical_race_calendar_integrity(**arguments)

        event.refresh_from_db()
        self.assertEqual(event.year, 2024)
        self.assertEqual(event.edition_year, 2025)
        self.assertEqual(first["status"], "verified")
        self.assertEqual(second["status"], "already_applied")
        self.assertEqual(HistoricalRaceCalendarRepairReceipt.objects.count(), 1)

    def test_orphan_ledger_after_receipt_crash_is_safely_recovered(self):
        self.make_mismatch(key="orphan-ledger")
        prepared = self.prepare()
        approval, approval_sha = self.approve(prepared)
        maintenance, maintenance_sha = self.maintenance(prepared)
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
        )

        arguments = {
            "manifest_path": prepared["manifest_path"],
            "expected_manifest_sha256": prepared["manifest_sha256"],
            "approval_path": approval,
            "expected_approval_sha256": approval_sha,
            "maintenance_evidence_path": maintenance,
            "expected_maintenance_evidence_sha256": maintenance_sha,
            "actor": self.actor,
            "artifact_root": self.artifact_root,
            "confirm_reviewed_artifact": True,
        }
        with mock.patch.object(
            HistoricalRaceCalendarRepairReceipt.objects,
            "create",
            side_effect=KeyboardInterrupt("simulated kill after ledger"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                apply_historical_race_calendar_integrity(**arguments)
        self.assertEqual(HistoricalRaceCalendarRepairReceipt.objects.count(), 0)

        ledger = (
            self.artifact_root
            / "rollback"
            / f"{prepared['manifest_sha256']}.json"
        )
        original_bytes = ledger.read_bytes()
        original = original_bytes.decode()
        outside_temp = tempfile.TemporaryDirectory()
        self.addCleanup(outside_temp.cleanup)
        outside = Path(outside_temp.name) / "outside-ledger.json"
        outside.write_bytes(original_bytes)
        ledger.unlink()
        ledger.symlink_to(outside)
        from stable.services.historical_race_calendar_integrity import (
            HistoricalRaceCalendarIntegrityError,
        )

        with self.assertRaises(HistoricalRaceCalendarIntegrityError):
            apply_historical_race_calendar_integrity(**arguments)
        ledger.unlink()
        inside_other = self.artifact_root / "other-ledger.json"
        inside_other.write_bytes(original_bytes)
        ledger.symlink_to(inside_other)
        with self.assertRaises(HistoricalRaceCalendarIntegrityError):
            apply_historical_race_calendar_integrity(**arguments)
        ledger.unlink()
        ledger.write_bytes(original_bytes)
        tampered = json.loads(original)
        tampered["rows"][0]["event_after"]["slug"] = "tampered-content"
        ledger.write_text(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")) + "\n"
        )
        with self.assertRaises(HistoricalRaceCalendarIntegrityError):
            apply_historical_race_calendar_integrity(**arguments)
        ledger.write_text(original)
        recovered = apply_historical_race_calendar_integrity(**arguments)
        self.assertEqual(recovered["status"], "verified")

    def test_controlled_inputs_reject_in_root_symlink_aliases(self):
        self.make_mismatch(key="in-root-alias")
        prepared = self.prepare()
        approval, approval_sha = self.approve(prepared)
        maintenance, maintenance_sha = self.maintenance(prepared)
        from stable.services.historical_race_calendar_integrity import (
            HistoricalRaceCalendarIntegrityError,
            _load_manifest,
            _validate_approval,
            _validate_maintenance,
        )

        manifest_path = Path(prepared["manifest_path"])
        manifest_alias = self.artifact_root / "manifest-alias.json"
        manifest_alias.symlink_to(manifest_path)
        with self.assertRaises(HistoricalRaceCalendarIntegrityError):
            _load_manifest(
                manifest_path=manifest_alias,
                expected_manifest_sha256=prepared["manifest_sha256"],
                artifact_root=self.artifact_root,
            )

        loaded = _load_manifest(
            manifest_path=manifest_path,
            expected_manifest_sha256=prepared["manifest_sha256"],
            artifact_root=self.artifact_root,
        )
        approval_alias = self.artifact_root / "approval-alias.json"
        approval_alias.symlink_to(approval)
        with self.assertRaises(HistoricalRaceCalendarIntegrityError):
            _validate_approval(
                approval_path=approval_alias,
                expected_approval_sha256=approval_sha,
                loaded=loaded,
                actor=self.actor,
            )

        maintenance_alias = self.artifact_root / "maintenance-alias.json"
        maintenance_alias.symlink_to(maintenance)
        with self.assertRaises(HistoricalRaceCalendarIntegrityError):
            _validate_maintenance(
                path=maintenance_alias,
                expected_sha256=maintenance_sha,
                loaded=loaded,
            )

        self.assertEqual(
            _validate_approval(
                approval_path=approval,
                expected_approval_sha256=approval_sha,
                loaded=loaded,
                actor=self.actor,
            ).sha256,
            approval_sha,
        )
        self.assertEqual(
            _validate_maintenance(
                path=maintenance,
                expected_sha256=maintenance_sha,
                loaded=loaded,
            ).sha256,
            maintenance_sha,
        )

    def test_ordinary_hong_kong_shift_rotates_public_and_edition_year(self):
        event = self.make_mismatch(
            key="ordinary-shift",
            evidence_classification="ordinary_season_year_shift",
        )
        prepared = self.prepare()
        approval, approval_sha = self.approve(prepared)
        maintenance, maintenance_sha = self.maintenance(prepared)
        manifest = json.loads(Path(prepared["manifest_path"]).read_text())
        self.assertEqual(manifest["actions"][0]["operation"], "rotate_year")
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
        )

        result = apply_historical_race_calendar_integrity(
            manifest_path=prepared["manifest_path"],
            expected_manifest_sha256=prepared["manifest_sha256"],
            approval_path=approval,
            expected_approval_sha256=approval_sha,
            maintenance_evidence_path=maintenance,
            expected_maintenance_evidence_sha256=maintenance_sha,
            actor=self.actor,
            artifact_root=self.artifact_root,
            confirm_reviewed_artifact=True,
        )

        event.refresh_from_db()
        target = HistoricalRaceEventTarget.objects.get(event=event)
        self.assertEqual(result["status"], "verified")
        self.assertEqual((event.year, event.edition_year, target.year), (2024, 2024, 2024))

    def test_verifier_mismatch_marks_receipt_failed_without_guessing(self):
        self.make_mismatch(key="verify-drift")
        prepared = self.prepare()
        approval, approval_sha = self.approve(prepared)
        maintenance, maintenance_sha = self.maintenance(prepared)
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
            verify_historical_race_calendar_integrity,
        )

        applied = apply_historical_race_calendar_integrity(
            manifest_path=prepared["manifest_path"],
            expected_manifest_sha256=prepared["manifest_sha256"],
            approval_path=approval,
            expected_approval_sha256=approval_sha,
            maintenance_evidence_path=maintenance,
            expected_maintenance_evidence_sha256=maintenance_sha,
            actor=self.actor,
            artifact_root=self.artifact_root,
            confirm_reviewed_artifact=True,
        )
        event = RaceEvent.objects.get(slug="verify-drift-2024")
        # Simulate out-of-band database drift; production writers are correctly
        # rejected while the live gate is active.
        RaceEvent._base_manager.filter(pk=event.pk).update(year=2023)

        result = verify_historical_race_calendar_integrity(
            manifest_path=prepared["manifest_path"],
            expected_manifest_sha256=prepared["manifest_sha256"],
            artifact_root=self.artifact_root,
            update_receipt=True,
        )

        self.assertEqual(applied["status"], "verified")
        self.assertFalse(result["ok"])
        receipt = HistoricalRaceCalendarRepairReceipt.objects.get()
        self.assertEqual(receipt.status, "verification_failed")

    def test_rollback_requires_exact_ledger_and_restores_before_state(self):
        event = self.make_mismatch(
            key="rollback-exact",
            evidence_classification="ordinary_season_year_shift",
        )
        prepared = self.prepare()
        approval, approval_sha = self.approve(prepared)
        maintenance, maintenance_sha = self.maintenance(prepared)
        from stable.services.historical_race_calendar_integrity import (
            apply_historical_race_calendar_integrity,
            rollback_historical_race_calendar_integrity,
        )

        common = {
            "manifest_path": prepared["manifest_path"],
            "expected_manifest_sha256": prepared["manifest_sha256"],
            "approval_path": approval,
            "expected_approval_sha256": approval_sha,
            "maintenance_evidence_path": maintenance,
            "expected_maintenance_evidence_sha256": maintenance_sha,
            "actor": self.actor,
            "artifact_root": self.artifact_root,
            "confirm_reviewed_artifact": True,
        }
        applied = apply_historical_race_calendar_integrity(**common)
        rolled_back = rollback_historical_race_calendar_integrity(
            **common,
            rollback_path=applied["rollback_path"],
            expected_rollback_sha256=applied["rollback_sha256"],
        )

        event.refresh_from_db()
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(event.year, 2025)
        self.assertEqual(event.edition_year, 2025)
        self.assertEqual(event.slug, "rollback-exact-2025")
        self.assertEqual(
            HistoricalRaceEventTarget.objects.get(event=event).year,
            2025,
        )
        self.assertEqual(
            RaceEventPublicPath.objects.filter(event=event).count(),
            1,
        )
        self.assertEqual(
            HistoricalRaceCalendarRepairReceipt.objects.get().status,
            "rolled_back",
        )

    def test_command_requires_independent_approval_before_artifact_access(self):
        with self.assertRaisesMessage(CommandError, "approval"):
            call_command(
                "repair_historical_race_calendar_integrity",
                "--apply",
                "--artifact",
                str(self.artifact_root / "missing" / "manifest.json"),
                "--expected-manifest-sha256",
                "a" * 64,
                "--actor",
                self.actor.get_username(),
                "--confirm-reviewed-artifact",
            )
