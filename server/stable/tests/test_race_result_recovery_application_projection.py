"""Application RED contracts for official recovery projection.

Native change task: official recovery projection contract.

No recovery run/receipt/rollback database tables are required here.  The
contracts deliberately reuse the existing source identity, participant,
observation, revision, evidence, projection-control and OperationLog models,
plus an immutable per-event filesystem ledger.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import PROTECT
from django.test import TestCase

from stable import models


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=dt_timezone.utc)
MANIFEST_SHA = "a" * 64
APPROVAL_SHA = "b" * 64
CONTRACT_SHA = "c" * 64
TERMS_SHA = "d" * 64


class RecoveryApplicationFixtureMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username=f"recovery-reviewer-{self.__class__.__name__.lower()}",
            password="unused",
            is_staff=True,
        )

    def _event(
        self,
        slug: str,
        *,
        region=models.RacingRegion.JAPAN,
        year=2026,
        local_date=date(2026, 7, 20),
        status=models.RaceEventStatus.SCHEDULED,
    ):
        return models.RaceEvent.objects.create(
            year=year,
            slug=slug,
            original_name=slug.replace("-", " ").title(),
            chinese_name=f"恢复 {slug}",
            country_region=region,
            racecourse="Tokyo",
            grade_text="G1",
            normalized_grade=models.RaceGrade.G1,
            surface=models.RaceEventSurface.TURF,
            timezone_name="Asia/Tokyo",
            local_date=local_date,
            status=status,
            data_quality_status=models.RaceEventDataQuality.INCOMPLETE,
            priority=models.RaceEventPriority.P0,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )

    def _source(self, event, source_key="jra"):
        return models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key=source_key,
            external_race_id=f"{source_key}-{event.pk}",
            canonical_url="https://www.jra.go.jp/JRADB/accessS.html",
            host="www.jra.go.jp",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            result_authority=models.RaceResultSourceAuthority.OFFICIAL,
            reviewed_by=self.user,
            reviewed_at=NOW,
            terms_status=models.RaceSourceTermsStatus.MANUAL,
            automation_allowed=False,
            valid_until=NOW + timedelta(days=30),
            registry_digest=CONTRACT_SHA,
        )

    def _participant(self, event, source, *, runner_id, number, name):
        participant = models.RaceEventParticipant.objects.create(
            event=event,
            stable_key=f"recovery:{source.source_key}:{runner_id}",
            canonical_name=name,
            country_region=event.country_region,
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=participant,
            source_identity=source,
            external_runner_id=runner_id,
        )
        return participant

    def _receipt_rows(self):
        return [
            {
                "external_runner_id": "runner-1",
                "official_name": "Horse Alpha",
                "horse_number": "1",
                "internal_order": 1,
                "official_finish_position": 1,
                "status": models.RaceEventRevisionItemStatus.DEAD_HEAT,
                "jockey_name": "Jockey A",
                "field_provenance": {
                    "official_finish_position": "official_route",
                    "status": "official_route",
                },
            },
            {
                "external_runner_id": "runner-2",
                "official_name": "Horse Beta",
                "horse_number": "2",
                "internal_order": 2,
                "official_finish_position": 1,
                "status": models.RaceEventRevisionItemStatus.DEAD_HEAT,
                "jockey_name": "Jockey B",
                "field_provenance": {
                    "official_finish_position": "official_route",
                    "status": "official_route",
                },
            },
            {
                "external_runner_id": "runner-3",
                "official_name": "Horse Gamma",
                "horse_number": "3",
                "internal_order": 3,
                "official_finish_position": None,
                "status": models.RaceEventRevisionItemStatus.DID_NOT_FINISH,
                "raw_status": "DNF",
                "jockey_name": "Jockey C",
                "field_provenance": {
                    "status": "official_route",
                },
            },
        ]

    def _receipt(self, event, *, observed_at=NOW, valid_until=None):
        receipt = {
            "schema_version": 1,
            "event_id": event.pk,
            "region": event.country_region,
            "route_key": "jra_manual_results",
            "source_key": "jra",
            "source_url": "https://www.jra.go.jp/JRADB/accessS.html",
            "marker": "official_result",
            "observed_at": observed_at.isoformat(),
            "route_contract_digest": CONTRACT_SHA,
            "terms_digest": TERMS_SHA,
            "valid_until": (
                valid_until or NOW + timedelta(days=7)
            ).isoformat(),
            "rows": self._receipt_rows(),
        }
        receipt["evidence_sha256"] = hashlib.sha256(
            json.dumps(
                receipt["rows"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return receipt

    def _route_registry(self, *, valid_until=None):
        return {
            "schema_version": 1,
            "routes": {
                "jra_manual_results": {
                    "region": models.RacingRegion.JAPAN,
                    "host": "www.jra.go.jp",
                    "path_prefix": "/JRADB/",
                    "marker": "official_result",
                    "contract_digest": CONTRACT_SHA,
                    "terms_digest": TERMS_SHA,
                    "valid_until": (
                        valid_until or NOW + timedelta(days=7)
                    ).isoformat(),
                    "access_mode": "manual_browser_only",
                }
            },
        }


class RecoveryOfficialReceiptContractTests(
    RecoveryApplicationFixtureMixin, TestCase
):
    def _service(self):
        try:
            return importlib.import_module(
                "stable.services.race_result_recovery_receipts"
            )
        except ModuleNotFoundError:
            self.fail(
                "缺少 recovery official receipt validator；"
                "non-live receipt 必须独立支持同着与非完赛"
            )

    def test_receipt_preserves_dead_heat_and_non_finish_with_stable_order(self):
        event = self._event("receipt-dead-heat")
        service = self._service()

        validated = service.validate_recovery_official_receipt(
            receipt=self._receipt(event),
            route_registry=self._route_registry(),
            expected_event_id=event.pk,
            now=NOW,
        )

        self.assertEqual(
            [row["internal_order"] for row in validated["rows"]],
            [1, 2, 3],
        )
        self.assertEqual(
            [row["official_finish_position"] for row in validated["rows"]],
            [1, 1, None],
        )
        self.assertEqual(
            validated["rows"][2]["status"],
            models.RaceEventRevisionItemStatus.DID_NOT_FINISH,
        )
        self.assertEqual(validated["authority"], "official")
        self.assertEqual(len(validated["receipt_sha256"]), 64)

    def test_receipt_fails_closed_when_route_expired_or_digest_drifted(self):
        event = self._event("receipt-expired")
        service = self._service()

        with self.assertRaises(service.RecoveryOfficialReceiptError) as caught:
            service.validate_recovery_official_receipt(
                receipt=self._receipt(
                    event, valid_until=NOW - timedelta(seconds=1)
                ),
                route_registry=self._route_registry(),
                expected_event_id=event.pk,
                now=NOW,
            )
        self.assertEqual(caught.exception.reason_code, "route_expired")

        drifted = self._receipt(event)
        drifted["route_contract_digest"] = "e" * 64
        with self.assertRaises(service.RecoveryOfficialReceiptError) as caught:
            service.validate_recovery_official_receipt(
                receipt=drifted,
                route_registry=self._route_registry(),
                expected_event_id=event.pk,
                now=NOW,
            )
        self.assertEqual(caught.exception.reason_code, "route_digest_drift")

    def test_participant_binding_uses_external_id_not_chinese_or_fuzzy_name(self):
        event = self._event("participant-exact")
        source = self._source(event)
        expected = [
            self._participant(
                event,
                source,
                runner_id=f"runner-{index}",
                number=str(index),
                name=name,
            )
            for index, name in enumerate(
                ("Horse Alpha", "Horse Beta", "Horse Gamma"), start=1
            )
        ]
        service = self._service()

        bindings = service.bind_recovery_participants(
            event=event,
            source_identity=source,
            rows=self._receipt_rows(),
            manifest_sha256=MANIFEST_SHA,
        )
        self.assertEqual(
            [binding["participant_id"] for binding in bindings],
            [participant.pk for participant in expected],
        )
        self.assertEqual(models.RaceEventParticipant.objects.count(), 3)

    def test_participant_binding_rejects_ambiguous_name_number_fallback(self):
        event = self._event("participant-ambiguous")
        source = self._source(event)
        models.RaceEventParticipant.objects.create(
            event=event,
            stable_key="existing-a",
            canonical_name="Shared Name",
            country_region=event.country_region,
        )
        models.RaceEventParticipant.objects.create(
            event=event,
            stable_key="existing-b",
            canonical_name="Shared Name",
            country_region=event.country_region,
        )
        rows = [
            {
                "external_runner_id": "",
                "official_name": "Shared Name",
                "horse_number": "7",
                "internal_order": 1,
                "official_finish_position": 1,
                "status": models.RaceEventRevisionItemStatus.FINISHED,
                "field_provenance": {"official_name": "official_route"},
            }
        ]
        before = models.RaceEventParticipant.objects.count()
        service = self._service()

        with self.assertRaises(service.RecoveryParticipantIdentityError) as caught:
            service.bind_recovery_participants(
                event=event,
                source_identity=source,
                rows=rows,
                manifest_sha256=MANIFEST_SHA,
            )
        self.assertEqual(caught.exception.reason_code, "participant_ambiguous")
        self.assertEqual(models.RaceEventParticipant.objects.count(), before)


class CanonicalProductLinkContractTests(
    RecoveryApplicationFixtureMixin, TestCase
):
    def _service(self):
        try:
            return importlib.import_module(
                "stable.services.race_result_recovery_projection"
            )
        except ModuleNotFoundError:
            self.fail(
                "缺少 canonical identity approval/projection service"
            )

    def _model(self):
        model = getattr(models, "RaceEventProductCanonicalLink", None)
        self.assertIsNotNone(
            model,
            "RaceEventProductCanonicalLink 模型尚未实现",
        )
        return model

    def test_canonical_model_has_protect_fks_audit_digests_and_active_unique(self):
        model = self._model()
        duplicate = model._meta.get_field("duplicate_event")
        canonical = model._meta.get_field("canonical_event")
        self.assertIs(duplicate.remote_field.on_delete, PROTECT)
        self.assertIs(canonical.remote_field.on_delete, PROTECT)
        self.assertEqual(model._meta.get_field("identity_sha256").max_length, 64)
        self.assertEqual(model._meta.get_field("manifest_sha256").max_length, 64)
        active_uniques = [
            item
            for item in model._meta.constraints
            if getattr(item, "fields", ()) == ("duplicate_event",)
            and getattr(item, "condition", None) is not None
        ]
        self.assertEqual(
            len(active_uniques),
            1,
            "每个 duplicate 必须只有一个 active 条件唯一约束",
        )
        self.assertTrue(
            any(
                tuple(index.fields) == ("canonical_event", "is_active")
                for index in model._meta.indexes
            ),
            "canonical/is_active 必须有批量公开读取索引",
        )

    def test_database_rejects_self_link_and_second_active_link(self):
        model = self._model()
        duplicate = self._event("canonical-duplicate")
        canonical_a = self._event("canonical-a")
        canonical_b = self._event("canonical-b")
        common = {
            "identity_sha256": "1" * 64,
            "manifest_sha256": MANIFEST_SHA,
            "approved_by": self.user,
            "approved_at": NOW,
            "is_active": True,
        }
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                model.objects.create(
                    duplicate_event=duplicate,
                    canonical_event=duplicate,
                    **common,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                model.objects.create(
                    duplicate_event=canonical_a,
                    canonical_event=canonical_b,
                    identity_sha256="short",
                    manifest_sha256=MANIFEST_SHA,
                    approved_by=self.user,
                    approved_at=NOW,
                    is_active=True,
                )

        model.objects.create(
            duplicate_event=duplicate,
            canonical_event=canonical_a,
            **common,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                model.objects.create(
                    duplicate_event=duplicate,
                    canonical_event=canonical_b,
                    **common,
                )

    def test_service_rejects_cross_region_year_chain_and_cycle(self):
        service = self._service()
        duplicate = self._event("identity-duplicate")
        canonical = self._event("identity-canonical")
        foreign_region = self._event(
            "identity-foreign",
            region=models.RacingRegion.FRANCE,
        )
        foreign_year = self._event("identity-year", year=2025)

        for target, reason in (
            (foreign_region, "canonical_region_mismatch"),
            (foreign_year, "canonical_year_mismatch"),
        ):
            with self.assertRaises(service.CanonicalIdentityApprovalError) as caught:
                service.approve_canonical_link(
                    duplicate_event_id=duplicate.pk,
                    canonical_event_id=target.pk,
                    identity_sha256="1" * 64,
                    manifest_sha256=MANIFEST_SHA,
                    approved_by_id=self.user.pk,
                    approved_at=NOW,
                )
            self.assertEqual(caught.exception.reason_code, reason)

        first = service.approve_canonical_link(
            duplicate_event_id=duplicate.pk,
            canonical_event_id=canonical.pk,
            identity_sha256="2" * 64,
            manifest_sha256=MANIFEST_SHA,
            approved_by_id=self.user.pk,
            approved_at=NOW,
        )
        self.assertTrue(first.is_active)
        with self.assertRaises(service.CanonicalIdentityApprovalError) as caught:
            service.approve_canonical_link(
                duplicate_event_id=canonical.pk,
                canonical_event_id=duplicate.pk,
                identity_sha256="3" * 64,
                manifest_sha256=MANIFEST_SHA,
                approved_by_id=self.user.pk,
                approved_at=NOW,
            )
        self.assertIn(
            caught.exception.reason_code,
            {"canonical_chain_forbidden", "canonical_cycle_forbidden"},
        )

    def test_inactive_history_is_preserved_when_canonical_is_reselected(self):
        service = self._service()
        model = self._model()
        duplicate = self._event("reselect-duplicate")
        canonical_a = self._event("reselect-a")
        canonical_b = self._event("reselect-b")
        old = service.approve_canonical_link(
            duplicate_event_id=duplicate.pk,
            canonical_event_id=canonical_a.pk,
            identity_sha256="4" * 64,
            manifest_sha256=MANIFEST_SHA,
            approved_by_id=self.user.pk,
            approved_at=NOW,
        )
        service.deactivate_canonical_link(
            link_id=old.pk,
            expected_manifest_sha256=MANIFEST_SHA,
            deactivated_by_id=self.user.pk,
            deactivated_at=NOW,
        )
        new = service.approve_canonical_link(
            duplicate_event_id=duplicate.pk,
            canonical_event_id=canonical_b.pk,
            identity_sha256="5" * 64,
            manifest_sha256=MANIFEST_SHA,
            approved_by_id=self.user.pk,
            approved_at=NOW,
        )

        self.assertNotEqual(old.pk, new.pk)
        self.assertEqual(model.objects.filter(duplicate_event=duplicate).count(), 2)
        self.assertEqual(
            model.objects.filter(
                duplicate_event=duplicate, is_active=True
            ).count(),
            1,
        )


class RecoveryProjectionContractTests(
    RecoveryApplicationFixtureMixin, TestCase
):
    def _services(self):
        try:
            receipts = importlib.import_module(
                "stable.services.race_result_recovery_receipts"
            )
            projection = importlib.import_module(
                "stable.services.race_result_recovery_projection"
            )
        except ModuleNotFoundError:
            self.fail(
                "缺少 recovery receipt/projection service；"
                "RED 要求 official revision 先于 legacy projection"
            )
        return receipts, projection

    def _prepared(self, *, slug, owner):
        event = self._event(slug)
        source = self._source(event)
        for index, name in enumerate(
            ("Horse Alpha", "Horse Beta", "Horse Gamma"), start=1
        ):
            self._participant(
                event,
                source,
                runner_id=f"runner-{index}",
                number=str(index),
                name=name,
            )
        control = models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner=owner,
            owner_generation=0 if owner == models.RaceEventProjectionWriteOwner.UNMANAGED else 3,
            owner_manifest_sha256="" if owner == models.RaceEventProjectionWriteOwner.UNMANAGED else MANIFEST_SHA,
        )
        receipts, projection = self._services()
        validated = receipts.validate_recovery_official_receipt(
            receipt=self._receipt(event),
            route_registry=self._route_registry(),
            expected_event_id=event.pk,
            now=NOW,
        )
        return event, source, control, validated, projection

    def _apply(self, event, control, validated, projection, ledger_root):
        return projection.apply_recovery_event(
            event_id=event.pk,
            validated_receipt=validated,
            manifest_sha256=MANIFEST_SHA,
            approval_sha256=APPROVAL_SHA,
            expected_owner=control.write_owner,
            expected_generation=control.owner_generation,
            expected_before_identity=projection.current_recovery_event_identity(
                event.pk
            ),
            route_registry=self._route_registry(),
            ledger_root=ledger_root,
            applied_by_id=self.user.pk,
            now=NOW,
        )

    def test_unmanaged_owner_is_cas_promoted_and_projects_official_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            event, source, control, validated, projection = self._prepared(
                slug="apply-unmanaged",
                owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
            )
            result = self._apply(
                event, control, validated, projection, Path(temporary)
            )

        control.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(result["status"], "applied")
        self.assertEqual(
            control.write_owner,
            models.RaceEventProjectionWriteOwner.HISTORICAL,
        )
        self.assertEqual(control.owner_generation, 1)
        self.assertEqual(control.owner_manifest_sha256, MANIFEST_SHA)
        self.assertEqual(event.status, models.RaceEventStatus.FINISHED)
        self.assertEqual(event.data_quality_status, models.RaceEventDataQuality.COMPLETE)
        self.assertEqual(event.result_confirmed_at, NOW)
        self.assertEqual(event.results.filter(is_confirmed=True).count(), 3)
        revision = control.current_result_revision
        self.assertIsNotNone(revision)
        self.assertEqual(revision.phase, models.RaceResultPhase.OFFICIAL)
        self.assertEqual(
            revision.source_authority,
            models.RaceResultSourceAuthority.OFFICIAL,
        )
        self.assertEqual(revision.primary_observation.source_identity, source)
        self.assertEqual(revision.evidence_links.count(), 1)
        self.assertEqual(
            list(
                revision.items.order_by("internal_order").values_list(
                    "official_finish_position", flat=True
                )
            ),
            [1, 1, None],
        )
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_result_recovery_apply",
                target_id=str(event.pk),
            ).count(),
            1,
        )

    def test_historical_owner_stays_historical_and_manual_paused_is_zero_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            historical = self._prepared(
                slug="apply-historical",
                owner=models.RaceEventProjectionWriteOwner.HISTORICAL,
            )
            event, _source, control, validated, projection = historical
            self._apply(event, control, validated, projection, Path(temporary))
            control.refresh_from_db()
            self.assertEqual(
                control.write_owner,
                models.RaceEventProjectionWriteOwner.HISTORICAL,
            )
            self.assertEqual(control.owner_generation, 3)

            paused = self._prepared(
                slug="apply-paused",
                owner=models.RaceEventProjectionWriteOwner.MANUAL_PAUSED,
            )
            event, _source, control, validated, projection = paused
            before = {
                "results": models.RaceEventResult.objects.filter(event=event).count(),
                "observations": models.RaceResultObservation.objects.filter(
                    source_identity__event=event
                ).count(),
                "revisions": models.RaceEventRevision.objects.filter(
                    event=event
                ).count(),
            }
            with self.assertRaises(projection.RecoveryApplyBlocked) as caught:
                self._apply(
                    event, control, validated, projection, Path(temporary)
                )
            self.assertEqual(caught.exception.reason_code, "owner_manual_paused")
            self.assertEqual(
                models.RaceEventResult.objects.filter(event=event).count(),
                before["results"],
            )
            self.assertEqual(
                models.RaceResultObservation.objects.filter(
                    source_identity__event=event
                ).count(),
                before["observations"],
            )
            self.assertEqual(
                models.RaceEventRevision.objects.filter(event=event).count(),
                before["revisions"],
            )

    def test_live_owner_without_live_prerequisites_is_blocked_not_stolen(self):
        event, _source, control, validated, projection = self._prepared(
            slug="apply-live-blocked",
            owner=models.RaceEventProjectionWriteOwner.LIVE,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(projection.RecoveryApplyBlocked) as caught:
                self._apply(
                    event, control, validated, projection, Path(temporary)
                )
        self.assertEqual(caught.exception.reason_code, "live_prerequisites_missing")
        control.refresh_from_db()
        self.assertEqual(
            control.write_owner, models.RaceEventProjectionWriteOwner.LIVE
        )
        self.assertEqual(models.RaceEventResult.objects.filter(event=event).count(), 0)
        self.assertEqual(models.RaceEventRevision.objects.filter(event=event).count(), 0)

    def test_apply_rolls_back_whole_event_when_operation_log_write_fails(self):
        event, _source, control, validated, projection = self._prepared(
            slug="apply-transaction-rollback",
            owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                models.OperationLog.objects,
                "create",
                side_effect=RuntimeError("simulated operation log failure"),
            ):
                with self.assertRaises(RuntimeError):
                    self._apply(
                        event, control, validated, projection, Path(temporary)
                    )

        event.refresh_from_db()
        control.refresh_from_db()
        self.assertEqual(event.status, models.RaceEventStatus.SCHEDULED)
        self.assertIsNone(event.result_confirmed_at)
        self.assertEqual(
            control.write_owner,
            models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        self.assertEqual(control.owner_generation, 0)
        self.assertEqual(models.RaceEventResult.objects.filter(event=event).count(), 0)
        self.assertEqual(models.RaceResultObservation.objects.count(), 0)
        self.assertEqual(models.RaceEventRevision.objects.filter(event=event).count(), 0)

    def test_apply_rejects_manifest_bound_before_projection_drift(self):
        event, _source, control, validated, projection = self._prepared(
            slug="apply-before-drift",
            owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        expected = projection.current_recovery_event_identity(event.pk)
        models.RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_name="Unexpected Result",
            is_confirmed=False,
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(projection.RecoveryApplyBlocked) as caught:
                projection.apply_recovery_event(
                    event_id=event.pk,
                    validated_receipt=validated,
                    manifest_sha256=MANIFEST_SHA,
                    approval_sha256=APPROVAL_SHA,
                    expected_owner=control.write_owner,
                    expected_generation=control.owner_generation,
                    expected_before_identity=expected,
                    route_registry=self._route_registry(),
                    ledger_root=Path(temporary),
                    applied_by_id=self.user.pk,
                    now=NOW,
                )
        self.assertEqual(caught.exception.reason_code, "before_identity_drift")
        self.assertEqual(models.RaceEventRevision.objects.filter(event=event).count(), 0)

    def test_apply_rejects_manifest_bound_current_revision_drift(self):
        event, _source, control, validated, projection = self._prepared(
            slug="apply-revision-drift",
            owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        expected = projection.current_recovery_event_identity(event.pk)
        drift = models.RaceEventRevision.objects.create(
            event=event,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.OFFICIAL,
            content_sha256="e" * 64,
            source_authority=models.RaceResultSourceAuthority.OFFICIAL,
            applied_by=self.user,
        )
        control.current_result_revision = drift
        control.save(update_fields=("current_result_revision", "updated_at"))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(projection.RecoveryApplyBlocked) as caught:
                projection.apply_recovery_event(
                    event_id=event.pk,
                    validated_receipt=validated,
                    manifest_sha256=MANIFEST_SHA,
                    approval_sha256=APPROVAL_SHA,
                    expected_owner=control.write_owner,
                    expected_generation=control.owner_generation,
                    expected_before_identity=expected,
                    route_registry=self._route_registry(),
                    ledger_root=Path(temporary),
                    applied_by_id=self.user.pk,
                    now=NOW,
                )
        self.assertEqual(caught.exception.reason_code, "before_identity_drift")

    def test_apply_revalidates_route_registry_at_apply_time(self):
        event, _source, control, validated, projection = self._prepared(
            slug="apply-route-expired",
            owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        registries = []
        expired = self._route_registry(
            valid_until=NOW - timedelta(seconds=1)
        )
        registries.append(("route_expired", expired))
        revoked = self._route_registry()
        revoked["routes"] = {}
        registries.append(("route_not_approved", revoked))
        contract_drift = self._route_registry()
        contract_drift["routes"]["jra_manual_results"][
            "contract_digest"
        ] = "e" * 64
        registries.append(("route_digest_drift", contract_drift))
        terms_drift = self._route_registry()
        terms_drift["routes"]["jra_manual_results"]["terms_digest"] = "f" * 64
        registries.append(("terms_digest_drift", terms_drift))
        for reason, registry in registries:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(projection.RecoveryApplyBlocked) as caught:
                    projection.apply_recovery_event(
                        event_id=event.pk,
                        validated_receipt=validated,
                        manifest_sha256=MANIFEST_SHA,
                        approval_sha256=APPROVAL_SHA,
                        expected_owner=control.write_owner,
                        expected_generation=control.owner_generation,
                        expected_before_identity=projection.current_recovery_event_identity(
                            event.pk
                        ),
                        route_registry=registry,
                        ledger_root=Path(temporary),
                        applied_by_id=self.user.pk,
                        now=NOW,
                    )
            self.assertEqual(caught.exception.reason_code, reason)
        self.assertEqual(models.RaceEventRevision.objects.filter(event=event).count(), 0)

    def test_ledger_finalize_failure_rolls_back_database(self):
        for fault in ("replace", "directory_fsync"):
            with self.subTest(fault=fault):
                event, _source, control, validated, projection = self._prepared(
                    slug=f"apply-ledger-finalize-{fault}",
                    owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
                )
                if fault == "replace":
                    fault_patch = patch.object(
                        projection.os,
                        "replace",
                        side_effect=OSError("simulated atomic replace failure"),
                    )
                else:
                    fault_patch = patch.object(
                        projection.os,
                        "fsync",
                        side_effect=[
                            None,
                            None,
                            OSError("simulated directory fsync failure"),
                        ],
                    )
                with tempfile.TemporaryDirectory() as temporary:
                    with fault_patch:
                        with self.assertRaises(OSError):
                            self._apply(
                                event,
                                control,
                                validated,
                                projection,
                                Path(temporary),
                            )
                    self.assertEqual(
                        list(Path(temporary).glob("event-*.json")), []
                    )
                event.refresh_from_db()
                control.refresh_from_db()
                self.assertEqual(event.status, models.RaceEventStatus.SCHEDULED)
                self.assertEqual(
                    control.write_owner,
                    models.RaceEventProjectionWriteOwner.UNMANAGED,
                )
                self.assertEqual(event.results.count(), 0)
                self.assertEqual(
                    models.RaceEventRevision.objects.filter(event=event).count(),
                    0,
                )
                self.assertEqual(
                    models.OperationLog.objects.filter(
                        action_type="race_result_recovery_apply",
                        target_id=str(event.pk),
                    ).count(),
                    0,
                )

    def test_replay_is_idempotent_including_audit_and_updated_at(self):
        with tempfile.TemporaryDirectory() as temporary:
            event, _source, control, validated, projection = self._prepared(
                slug="apply-idempotent",
                owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
            )
            first = self._apply(
                event, control, validated, projection, Path(temporary)
            )
            event.refresh_from_db()
            control.refresh_from_db()
            before = {
                "event_updated_at": event.updated_at,
                "control_updated_at": control.updated_at,
                "result_updated_at": list(
                    event.results.order_by("finish_position").values_list(
                        "updated_at", flat=True
                    )
                ),
                "observations": models.RaceResultObservation.objects.count(),
                "revisions": models.RaceEventRevision.objects.count(),
                "operations": models.OperationLog.objects.count(),
            }
            replay = projection.apply_recovery_event(
                event_id=event.pk,
                validated_receipt=validated,
                manifest_sha256=MANIFEST_SHA,
                approval_sha256=APPROVAL_SHA,
                expected_owner=models.RaceEventProjectionWriteOwner.HISTORICAL,
                expected_generation=1,
                expected_before_identity=projection.current_recovery_event_identity(
                    event.pk
                ),
                route_registry=self._route_registry(),
                ledger_root=Path(temporary),
                applied_by_id=self.user.pk,
                now=NOW + timedelta(minutes=5),
            )
            event.refresh_from_db()
            control.refresh_from_db()

        self.assertEqual(first["status"], "applied")
        self.assertEqual(replay["status"], "already_applied")
        self.assertEqual(event.updated_at, before["event_updated_at"])
        self.assertEqual(control.updated_at, before["control_updated_at"])
        self.assertEqual(
            list(
                event.results.order_by("finish_position").values_list(
                    "updated_at", flat=True
                )
            ),
            before["result_updated_at"],
        )
        self.assertEqual(
            models.RaceResultObservation.objects.count(),
            before["observations"],
        )
        self.assertEqual(models.RaceEventRevision.objects.count(), before["revisions"])
        self.assertEqual(models.OperationLog.objects.count(), before["operations"])

    def test_orphan_ledger_is_prepared_not_applied_and_cannot_rollback(self):
        _receipts, projection = self._services()
        event = self._event("ledger-orphan")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / f"event-{event.pk}-{MANIFEST_SHA}.json"
            payload = {
                "schema_version": 1,
                "state": "prepared",
                "event_id": event.pk,
                "manifest_sha256": MANIFEST_SHA,
                "approval_sha256": APPROVAL_SHA,
                "before_identity": "1" * 64,
                "after_identity": "2" * 64,
                "database_operation_log_id": None,
            }
            path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            verdict = projection.verify_recovery_ledger(path)
            self.assertEqual(verdict["status"], "prepared_not_applied")
            self.assertFalse(verdict["rollback_allowed"])
            with self.assertRaises(projection.RecoveryLedgerError) as caught:
                projection.rollback_recovery_event(
                    ledger_path=path,
                    expected_manifest_sha256=MANIFEST_SHA,
                    rolled_back_by_id=self.user.pk,
                    now=NOW,
                )
            self.assertEqual(
                caught.exception.reason_code, "prepared_not_applied"
            )

    def test_verifier_rejects_current_projection_drift_after_apply(self):
        for drift_kind in ("results", "event_status", "revision_pointer"):
            with self.subTest(drift_kind=drift_kind), tempfile.TemporaryDirectory() as temporary:
                event, _source, control, validated, projection = self._prepared(
                    slug=f"verify-after-{drift_kind}",
                    owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
                )
                applied = self._apply(
                    event, control, validated, projection, Path(temporary)
                )
                if drift_kind == "results":
                    result = event.results.order_by("finish_position").first()
                    result.horse_name = "Tampered Winner"
                    result.save(update_fields=("horse_name", "updated_at"))
                elif drift_kind == "event_status":
                    event.status = models.RaceEventStatus.SCHEDULED
                    event.save(update_fields=("status", "updated_at"))
                else:
                    control.refresh_from_db()
                    control.current_result_revision = None
                    control.save(
                        update_fields=("current_result_revision", "updated_at")
                    )
                verdict = projection.verify_recovery_ledger(
                    Path(applied["ledger_path"])
                )
            self.assertEqual(verdict["status"], "ledger_database_drift")
            self.assertFalse(verdict["rollback_allowed"])

    def test_apply_accepts_preapproved_exact_name_number_fallback_identity(self):
        event = self._event("participant-fallback-apply")
        source = self._source(event)
        control = models.RaceEventProjectionControl.objects.create(
            event=event,
            write_owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
            owner_generation=0,
        )
        receipts, projection = self._services()
        raw = self._receipt(event)
        raw["rows"][0]["external_runner_id"] = ""
        raw["evidence_sha256"] = hashlib.sha256(
            json.dumps(
                raw["rows"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        validated = receipts.validate_recovery_official_receipt(
            receipt=raw,
            route_registry=self._route_registry(),
            expected_event_id=event.pk,
            now=NOW,
        )
        receipts.bind_recovery_participants(
            event=event,
            source_identity=source,
            rows=validated["rows"],
            manifest_sha256=MANIFEST_SHA,
        )
        with tempfile.TemporaryDirectory() as temporary:
            result = projection.apply_recovery_event(
                event_id=event.pk,
                validated_receipt=validated,
                manifest_sha256=MANIFEST_SHA,
                approval_sha256=APPROVAL_SHA,
                expected_owner=control.write_owner,
                expected_generation=control.owner_generation,
                expected_before_identity=projection.current_recovery_event_identity(
                    event.pk
                ),
                route_registry=self._route_registry(),
                ledger_root=Path(temporary),
                applied_by_id=self.user.pk,
                now=NOW,
            )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(event.results.count(), 3)

    def test_apply_keeps_non_target_event_and_results_byte_semantics_unchanged(self):
        target, _source, control, validated, projection = self._prepared(
            slug="apply-target-only",
            owner=models.RaceEventProjectionWriteOwner.UNMANAGED,
        )
        non_target = self._event(
            "apply-non-target",
            status=models.RaceEventStatus.FINISHED,
        )
        existing = models.RaceEventResult.objects.create(
            event=non_target,
            finish_position=1,
            official_finish_position=1,
            horse_name="Untouched Winner",
            is_confirmed=True,
            source_refs={"proof": "existing"},
        )
        before = {
            "event": (
                non_target.status,
                non_target.result_confirmed_at,
                non_target.updated_at,
            ),
            "result": (
                existing.horse_name,
                existing.is_confirmed,
                existing.source_refs,
                existing.updated_at,
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            self._apply(
                target, control, validated, projection, Path(temporary)
            )
        non_target.refresh_from_db()
        existing.refresh_from_db()

        self.assertEqual(
            (
                non_target.status,
                non_target.result_confirmed_at,
                non_target.updated_at,
            ),
            before["event"],
        )
        self.assertEqual(
            (
                existing.horse_name,
                existing.is_confirmed,
                existing.source_refs,
                existing.updated_at,
            ),
            before["result"],
        )
