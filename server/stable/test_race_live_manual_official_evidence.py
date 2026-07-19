from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
from io import StringIO
from threading import Barrier, Lock
from unittest import skipUnless
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import (
    DatabaseError,
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import TransactionTestCase, override_settings
from stable import models
from stable.services import race_events
from stable.services.race_live_manual_official_evidence import (
    RaceLiveManualOfficialEvidenceError,
    apply_race_live_manual_official_evidence,
    load_race_live_manual_official_evidence,
    prepare_race_live_manual_official_evidence,
)
from stable.services.race_live_publication_transition import (
    RaceLivePublicationTransitionError,
    apply_race_live_publication_transition,
)
from stable.test_race_live_publication_transition import (
    RaceLivePublicationTransitionTests,
)


class RaceLiveManualOfficialEvidenceTests(
    RaceLivePublicationTransitionTests
):
    def _promote(self):
        bundle = self._bundle()
        apply_race_live_publication_transition(
            self._loaded(bundle["promotion"]),
            now=self.NOW,
        )
        incident = models.RaceLiveOfficialVerificationIncident.objects.get(
            event=self.event
        )
        return bundle, incident

    def _submission(self, incident, *, outcome="available", conflict=False):
        participants = [
            {
                "participant_id": participant.pk,
                "position": index,
            }
            for index, participant in enumerate(self.participants, start=1)
        ]
        if conflict:
            participants[0]["position"], participants[1]["position"] = (
                participants[1]["position"],
                participants[0]["position"],
            )
        return {
            "approved_commit": self.APPROVED_COMMIT,
            "event_id": self.event.pk,
            "revision_id": self.result_revision.pk,
            "incident_id": incident.pk,
            "source_url": "https://www.britishhorseracing.com/racing/results/",
            "observed_at": (self.NOW.replace(microsecond=0)).isoformat(),
            "evidence_sha256": "9" * 64,
            "outcome": outcome,
            "marker_type": "weighed_in" if outcome == "available" else "",
            "participants": participants if outcome == "available" else [],
        }

    def _receipt(self, submission, run_id="manual-evidence"):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        os.chmod(root, 0o700)
        prepared = prepare_race_live_manual_official_evidence(
            submission=submission,
            output_root=root,
            run_id=run_id,
        )
        path = Path(prepared["receipt_path"])
        receipt = load_race_live_manual_official_evidence(
            receipt_path=path,
            expected_receipt_sha256=prepared["receipt_sha256"],
            expected_approved_commit=self.APPROVED_COMMIT,
        )
        return temporary, path, receipt, prepared["receipt_sha256"]

    def _manifest_file(self, payload, *, run_id):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        os.chmod(root, 0o700)
        path = root / f"{run_id}.manifest.json"
        data = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        path.write_bytes(data)
        os.chmod(path, 0o600)
        return temporary, path, hashlib.sha256(data).hexdigest()

    def _call_manual_dry_run(
        self,
        *,
        receipt_path,
        receipt_sha256,
        disable_path=None,
        disable_sha256=None,
        stdout=None,
    ):
        arguments = [
            "apply_race_live_manual_official_evidence",
            "--receipt",
            str(receipt_path),
            "--expected-receipt-sha256",
            receipt_sha256,
            "--expected-approved-commit",
            self.APPROVED_COMMIT,
        ]
        if disable_path is not None:
            arguments.extend(
                [
                    "--disable-manifest",
                    str(disable_path),
                    "--expected-disable-manifest-sha256",
                    disable_sha256,
                ]
            )
        with patch(
            "stable.services.race_live_manual_official_evidence.timezone.now",
            return_value=self.NOW.replace(minute=31),
        ):
            call_command(*arguments, stdout=stdout or StringIO())

    def _create_other_event_open_incident(self):
        self.allowlist.refresh_from_db()
        other_event = models.RaceEvent.objects.create(
            id=925,
            year=2026,
            slug="event-925-manual-evidence",
            original_name="Event 925 Manual Evidence Stakes",
            chinese_name="赛事 925 人工复核测试",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            racecourse="Newbury",
            grade_text="G3",
            surface=models.RaceEventSurface.TURF,
            status=models.RaceEventStatus.FINISHED,
            visibility_status=models.RaceEventVisibility.PUBLISHED,
            race_datetime=self.NOW - timedelta(hours=3),
        )
        source = models.RaceResultSourceIdentity.objects.create(
            event=other_event,
            source_key="the_racing_api",
            external_race_id="rac_event_925",
            canonical_url="https://api.theracingapi.com/v1/results/rac_event_925",
            host="api.theracingapi.com",
            review_status=models.RaceLiveReviewStatus.APPROVED,
            result_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            reviewed_at=self.NOW - timedelta(days=1),
            terms_status=models.RaceSourceTermsStatus.APPROVED,
            automation_allowed=True,
            valid_until=self.NOW + timedelta(days=20),
            registry_digest=self.REGISTRY_DIGEST,
        )
        participant = models.RaceEventParticipant.objects.create(
            event=other_event,
            stable_key="event-925-runner-1",
            canonical_name="Other Winner",
            country_region=models.RacingRegion.UNITED_KINGDOM,
            review_status=models.RaceLiveReviewStatus.APPROVED,
        )
        models.RaceEventParticipantSourceIdentity.objects.create(
            participant=participant,
            source_identity=source,
            external_runner_id="runner-1",
        )
        racecard = models.RaceEventRevision.objects.create(
            event=other_event,
            kind=models.RaceEventRevisionKind.RACECARD,
            revision_no=1,
            phase=models.RaceResultPhase.RACECARD,
            content_sha256="4" * 64,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
        )
        models.RaceEventRevisionItem.objects.create(
            revision=racecard,
            participant=participant,
            source_order=1,
            internal_order=1,
            status=models.RaceEventRevisionItemStatus.DECLARED,
            horse_number="1",
        )
        payload = {
            "external_race_id": source.external_race_id,
            "participants": [
                {
                    "external_runner_id": "runner-1",
                    "official_finish_position": 1,
                    "status": models.RaceEventRevisionItemStatus.FINISHED,
                }
            ],
        }
        normalized_sha = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        observation = models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=self.NOW - timedelta(minutes=15),
            parser_version="the_racing_api_free_v1",
            raw_sha256="5" * 64,
            normalized_sha256=normalized_sha,
            result_phase=models.RaceResultPhase.PROVISIONAL,
            normalized_payload=payload,
            permission_classification="licensed_api_automation",
        )
        result = models.RaceEventRevision.objects.create(
            event=other_event,
            kind=models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=models.RaceResultPhase.PROVISIONAL,
            content_sha256=normalized_sha,
            source_authority=models.RaceResultSourceAuthority.SUPPLEMENTAL,
            decision_reason="provisional_result_accepted",
            primary_observation=observation,
            published_at=self.NOW,
        )
        models.RaceEventRevisionItem.objects.create(
            revision=result,
            participant=participant,
            source_order=1,
            internal_order=1,
            official_finish_position=1,
            status=models.RaceEventRevisionItemStatus.FINISHED,
            horse_number="1",
        )
        control = models.RaceEventProjectionControl.objects.create(
            event=other_event,
            write_owner=models.RaceEventProjectionWriteOwner.LIVE,
            owner_generation=1,
            owner_manifest_sha256="6" * 64,
            current_racecard_revision=racecard,
            last_known_good_racecard_revision=racecard,
            current_result_revision=result,
            last_known_good_result_revision=result,
            next_racecard_revision_no=2,
            next_result_revision_no=2,
        )
        models.RaceEventLiveTracking.objects.create(
            event=other_event,
            state=models.RaceEventLiveState.PROVISIONAL_RESULT,
            tracking_enabled=False,
            claim_generation=1,
            source_route_version="the_racing_api-free-v1",
        )
        models.RaceLivePublicationPolicy.objects.create(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(other_event.pk),
            mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            version=2,
            registry_digest=self.REGISTRY_DIGEST,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            valid_until=self.NOW + timedelta(days=20),
        )
        allowlist = models.RaceLiveEventPublicationAllowlist.objects.create(
            event=other_event,
            source_key=source.source_key,
            max_mode=models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            coverage_proof_digest=self.COVERAGE_DIGEST,
            official_verification_route="bha_manual_verification",
            official_verification_route_version="bha-manual-v1",
            official_verification_contract_digest=(
                self.allowlist.official_verification_contract_digest
            ),
            official_terms_evidence_digest=(
                self.allowlist.official_terms_evidence_digest
            ),
            official_verification_valid_until=self.NOW + timedelta(days=20),
            enabled=True,
            version=2,
        )
        incident = models.RaceLiveOfficialVerificationIncident.objects.create(
            event=other_event,
            provisional_revision=result,
            status=models.RaceLiveOfficialVerificationIncidentStatus.OPEN,
            deadline_at=other_event.race_datetime + timedelta(hours=2),
            official_route=allowlist.official_verification_route,
            official_route_version=allowlist.official_verification_route_version,
            official_route_contract_digest=(
                allowlist.official_verification_contract_digest
            ),
            official_terms_evidence_digest=(
                allowlist.official_terms_evidence_digest
            ),
            manual_verification_due_at=self.NOW + timedelta(minutes=15),
        )
        self.assertEqual(
            control.current_result_revision_id,
            result.pk,
        )
        return other_event, result, incident

    def test_apply_accepts_another_event_with_a_complete_matching_open_incident(self):
        self._promote()
        other_event, other_revision, other_incident = (
            self._create_other_event_open_incident()
        )
        receipt = deepcopy(
            self._receipt(
                self._submission(
                    models.RaceLiveOfficialVerificationIncident.objects.get(
                        event=self.event
                    ),
                    outcome="unavailable",
                ),
                run_id="manual-other-event-rejected",
            )[2]
        )
        receipt["event_id"] = other_event.pk
        receipt["revision_id"] = other_revision.pk
        receipt["incident_id"] = other_incident.pk
        digest = hashlib.sha256(
            json.dumps(
                receipt,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        ).hexdigest()

        result = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=31),
        )

        self.assertEqual(result["event_ids"], [other_event.pk])
        self.assertEqual(result["outcome"], "unavailable")

    def test_match_creates_minimal_official_evidence_resolves_incident_and_keeps_page_provisional(self):
        _, incident = self._promote()
        temporary, path, receipt, digest = self._receipt(
            self._submission(incident)
        )
        self.addCleanup(temporary.cleanup)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

        result = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=31),
        )

        self.assertEqual(result["comparison"], "match")
        incident.refresh_from_db()
        self.assertEqual(
            incident.status,
            models.RaceLiveOfficialVerificationIncidentStatus.RESOLVED,
        )
        self.assertEqual(incident.resolved_at, self.NOW.replace(minute=31))
        source = models.RaceResultSourceIdentity.objects.get(
            event=self.event,
            source_key="bha_manual",
        )
        self.assertEqual(
            source.result_authority,
            models.RaceResultSourceAuthority.OFFICIAL,
        )
        self.assertFalse(source.automation_allowed)
        observation = models.RaceResultObservation.objects.get(
            source_identity=source
        )
        self.assertEqual(observation.result_phase, models.RaceResultPhase.OFFICIAL)
        self.assertEqual(observation.raw_artifact_path, "")
        self.assertEqual(observation.raw_size_bytes, None)
        evidence = models.RaceLiveOfficialMarkerEvidence.objects.get(
            observation=observation
        )
        self.assertEqual(evidence.marker_type, "weighed_in")
        self.result_revision.refresh_from_db()
        self.assertEqual(
            self.result_revision.phase,
            models.RaceResultPhase.PROVISIONAL,
        )
        replay = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=32),
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            models.RaceResultObservation.objects.filter(
                source_identity=source
            ).count(),
            1,
        )
        incident.refresh_from_db()
        self.assertEqual(incident.resolved_at, self.NOW.replace(minute=31))

    def test_staged_official_revision_publishes_after_exact_authorization(self):
        _, incident = self._promote()
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident),
            run_id="manual-staged-then-authorized",
        )
        self.addCleanup(temporary.cleanup)
        first_result = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=31),
        )
        self.assertEqual(first_result["comparison"], "match")
        staged = models.RaceEventRevision.objects.get(
            event=self.event,
            phase=models.RaceResultPhase.OFFICIAL,
        )
        self.assertIsNone(staged.published_at)
        self.control.refresh_from_db()
        self.assertEqual(
            self.control.current_result_revision_id,
            self.result_revision.pk,
        )

        for policy in models.RaceLivePublicationPolicy.objects.filter(
            scope_type__in=(
                models.RaceLivePublicationScopeType.GLOBAL,
                models.RaceLivePublicationScopeType.REGION,
                models.RaceLivePublicationScopeType.EVENT,
            )
        ):
            policy.mode = models.RaceLivePublicationMode.OFFICIAL_PUBLIC
            policy.version += 1
            policy.save(update_fields=("mode", "version", "updated_at"))
        self.allowlist.refresh_from_db()
        call_command(
            "authorize_race_live_official_publication",
            "--event-id",
            str(self.event.pk),
            "--max-phase",
            models.RaceResultPhase.OFFICIAL,
            "--valid-until",
            (self.NOW + timedelta(days=10)).isoformat(),
            "--expected-version",
            "0",
            "--apply",
            "--confirm",
            f"AUTHORIZE_OFFICIAL_EVENT_{self.event.pk}",
            stdout=StringIO(),
        )
        staged.refresh_from_db()
        self.control.refresh_from_db()
        self.tracking.refresh_from_db()
        self.assertEqual(
            self.control.current_result_revision_id,
            staged.pk,
        )
        self.assertEqual(
            self.tracking.state,
            models.RaceEventLiveState.OFFICIAL_RESULT,
        )
        publication = models.RaceEventRevisionPublication.objects.get(
            revision=staged
        )
        self.assertEqual(publication.authorization_kind, "official_route")
        self.assertEqual(publication.official_authorization_version, 1)
        self.assertEqual(
            publication.allowlist_version,
            self.allowlist.version,
        )
        self.assertEqual(
            publication.policy_versions,
            [
                list(row)
                for row in race_events.resolve_race_live_official_coarse_policy(
                    event_id=self.event.pk,
                    now=self.NOW.replace(minute=32),
                ).policy_versions
            ],
        )
        self.assertTrue(
            race_events.resolve_race_live_public_read(
                event_id=self.event.pk,
                now=self.NOW.replace(minute=32),
            ).visible
        )
        self.assertTrue(
            models.RaceEventResult.objects.filter(
                event=self.event,
                is_confirmed=True,
            ).exists()
        )

    def test_replay_fails_closed_when_recorded_post_state_has_drifted(self):
        _, incident = self._promote()
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident),
            run_id="manual-replay-drift",
        )
        self.addCleanup(temporary.cleanup)
        apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=31),
        )
        incident.refresh_from_db()
        incident.status = (
            models.RaceLiveOfficialVerificationIncidentStatus.OPEN
        )
        incident.resolved_at = None
        incident.save(
            update_fields=("status", "resolved_at", "updated_at")
        )

        with self.assertRaises(RaceLiveManualOfficialEvidenceError):
            apply_race_live_manual_official_evidence(
                receipt=receipt,
                receipt_sha256=digest,
                now=self.NOW.replace(minute=32),
            )

    def test_apply_rejects_future_or_pre_off_observation_time_without_writes(self):
        _, incident = self._promote()
        for label, observed_at in (
            (
                "future",
                self.NOW.replace(minute=31)
                + timedelta(hours=1),
            ),
            (
                "pre-off",
                self.event.race_datetime - timedelta(seconds=1),
            ),
        ):
            with self.subTest(label=label):
                submission = self._submission(incident)
                submission["observed_at"] = observed_at.isoformat()
                temporary, _, receipt, digest = self._receipt(
                    submission,
                    run_id=f"manual-{label}-time",
                )
                self.addCleanup(temporary.cleanup)
                with self.assertRaises(
                    RaceLiveManualOfficialEvidenceError
                ):
                    apply_race_live_manual_official_evidence(
                        receipt=receipt,
                        receipt_sha256=digest,
                        now=self.NOW.replace(minute=31),
                    )

        self.assertFalse(
            models.RaceResultSourceIdentity.objects.filter(
                event=self.event,
                source_key="bha_manual",
            ).exists()
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
    )
    def test_unavailable_sends_one_real_alert_without_fabricating_evidence(self):
        _, incident = self._promote()
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="manual-unavailable",
        )
        self.addCleanup(temporary.cleanup)

        result = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=31),
        )

        self.assertEqual(result["comparison"], "unavailable")
        self.assertEqual(result["alert_status"], "sent")
        incident.refresh_from_db()
        self.assertEqual(
            incident.status,
            models.RaceLiveOfficialVerificationIncidentStatus.OPEN,
        )
        self.assertEqual(incident.last_probe_at, self.NOW.replace(minute=31))
        self.assertEqual(incident.alert_sent_at, self.NOW.replace(minute=31))
        self.assertIsNotNone(incident.next_probe_at)
        self.assertFalse(
            models.RaceResultSourceIdentity.objects.filter(
                event=self.event,
                source_key="bha_manual",
            ).exists()
        )
        self.assertFalse(models.RaceLiveOfficialMarkerEvidence.objects.exists())
        notification = models.NotificationLog.objects.get()
        self.assertEqual(
            notification.type,
            models.NotificationType.OPS_ANOMALY,
        )
        self.assertEqual(
            notification.status,
            models.NotificationStatus.SENT,
        )
        self.assertIsNotNone(notification.sent_at)
        self.assertEqual(
            notification.target,
            "race-live-ops@example.com",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            ["race-live-ops@example.com"],
        )
        replay = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=32),
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["alert_status"], "sent")
        incident.refresh_from_db()
        self.assertEqual(incident.last_probe_at, self.NOW.replace(minute=31))
        self.assertEqual(models.NotificationLog.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
    )
    def test_unavailable_failed_alert_stays_retryable_until_same_receipt_sends(self):
        _, incident = self._promote()
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="manual-unavailable-alert-retry",
        )
        self.addCleanup(temporary.cleanup)

        with patch(
            "stable.services.race_live_manual_official_evidence.send_mail",
            side_effect=RuntimeError("smtp unavailable"),
        ):
            failed = apply_race_live_manual_official_evidence(
                receipt=receipt,
                receipt_sha256=digest,
                now=self.NOW.replace(minute=31),
            )

        self.assertEqual(failed["alert_status"], "failed")
        incident.refresh_from_db()
        self.assertIsNone(incident.alert_sent_at)
        failed_log = models.NotificationLog.objects.get()
        self.assertEqual(
            failed_log.status,
            models.NotificationStatus.FAILED,
        )
        self.assertIsNone(failed_log.sent_at)
        self.assertIn("smtp unavailable", failed_log.error_message)
        self.assertEqual(len(mail.outbox), 0)

        retried = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=32),
        )
        self.assertTrue(retried["replayed"])
        self.assertEqual(retried["alert_status"], "sent")
        incident.refresh_from_db()
        self.assertEqual(
            incident.alert_sent_at,
            self.NOW.replace(minute=32),
        )
        self.assertEqual(
            list(
                models.NotificationLog.objects.order_by("created_at").values_list(
                    "status",
                    flat=True,
                )
            ),
            [
                models.NotificationStatus.FAILED,
                models.NotificationStatus.SENT,
            ],
        )
        self.assertEqual(len(mail.outbox), 1)

        deduplicated = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            now=self.NOW.replace(minute=33),
        )
        self.assertTrue(deduplicated["replayed"])
        self.assertEqual(deduplicated["alert_status"], "sent")
        self.assertEqual(models.NotificationLog.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
    )
    def test_unavailable_alert_dedupes_by_incident_across_distinct_receipts(self):
        _, incident = self._promote()
        temporary_a, _, receipt_a, digest_a = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="manual-unavailable-receipt-a",
        )
        self.addCleanup(temporary_a.cleanup)
        first = apply_race_live_manual_official_evidence(
            receipt=receipt_a,
            receipt_sha256=digest_a,
            now=self.NOW.replace(minute=31),
        )
        self.assertEqual(first["alert_status"], "sent")

        submission_b = self._submission(incident, outcome="unavailable")
        submission_b["observed_at"] = self.NOW.replace(
            minute=32,
            microsecond=0,
        ).isoformat()
        submission_b["evidence_sha256"] = "8" * 64
        temporary_b, _, receipt_b, digest_b = self._receipt(
            submission_b,
            run_id="manual-unavailable-receipt-b",
        )
        self.addCleanup(temporary_b.cleanup)
        second = apply_race_live_manual_official_evidence(
            receipt=receipt_b,
            receipt_sha256=digest_b,
            now=self.NOW.replace(minute=32),
        )

        self.assertFalse(second["replayed"])
        self.assertEqual(second["alert_status"], "sent")
        incident.refresh_from_db()
        self.assertEqual(
            incident.last_probe_at,
            self.NOW.replace(minute=32),
        )
        self.assertEqual(
            incident.next_probe_at,
            self.NOW.replace(minute=32) + timedelta(hours=24),
        )
        self.assertEqual(
            incident.alert_sent_at,
            self.NOW.replace(minute=31),
        )
        self.assertEqual(models.NotificationLog.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_live_manual_official_evidence",
            ).count(),
            2,
        )
        operation_details = list(
            models.OperationLog.objects.filter(
                action_type="race_live_manual_official_evidence",
            ).values_list("detail", flat=True)
        )
        self.assertTrue(any(digest_a in detail for detail in operation_details))
        self.assertTrue(any(digest_b in detail for detail in operation_details))

        replay = apply_race_live_manual_official_evidence(
            receipt=receipt_b,
            receipt_sha256=digest_b,
            now=self.NOW.replace(minute=33),
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["alert_status"], "sent")
        self.assertEqual(models.NotificationLog.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_live_manual_official_evidence",
            ).count(),
            2,
        )

    @override_settings(
        RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
    )
    def test_unavailable_durable_intent_probe_and_operation_exist_before_smtp(self):
        _, incident = self._promote()
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="manual-unavailable-durable-before-smtp",
        )
        self.addCleanup(temporary.cleanup)

        def assert_durable_before_send(*args, **kwargs):
            notification = models.NotificationLog.objects.get()
            self.assertEqual(
                notification.status,
                models.NotificationStatus.QUEUED,
            )
            incident.refresh_from_db()
            self.assertEqual(
                incident.last_probe_at,
                self.NOW.replace(minute=31),
            )
            self.assertTrue(
                models.OperationLog.objects.filter(
                    action_type="race_live_manual_official_evidence",
                    detail__contains=digest,
                ).exists()
            )
            return 1

        with patch(
            "stable.services.race_live_manual_official_evidence.send_mail",
            side_effect=assert_durable_before_send,
        ):
            result = apply_race_live_manual_official_evidence(
                receipt=receipt,
                receipt_sha256=digest,
                now=self.NOW.replace(minute=31),
            )

        self.assertEqual(result["alert_status"], "sent")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
    )
    def test_unavailable_late_main_failure_never_sends_or_persists_intent(self):
        _, incident = self._promote()
        incident_before = models.RaceLiveOfficialVerificationIncident.objects.values(
            "last_probe_at",
            "next_probe_at",
            "alert_sent_at",
        ).get(pk=incident.pk)
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="manual-unavailable-late-failure",
        )
        self.addCleanup(temporary.cleanup)
        with patch(
            "stable.services.race_live_manual_official_evidence.models.OperationLog.objects.create",
            side_effect=IntegrityError("late operation failure"),
        ):
            with self.assertRaises(IntegrityError):
                apply_race_live_manual_official_evidence(
                    receipt=receipt,
                    receipt_sha256=digest,
                    now=self.NOW.replace(minute=31),
                )

        self.assertEqual(
            models.RaceLiveOfficialVerificationIncident.objects.values(
                "last_probe_at",
                "next_probe_at",
                "alert_sent_at",
            ).get(pk=incident.pk),
            incident_before,
        )
        self.assertFalse(models.NotificationLog.objects.exists())
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_manual_official_evidence",
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
    )
    def test_unavailable_main_commit_failure_never_sends_or_persists_intent(self):
        _, incident = self._promote()
        incident_before = models.RaceLiveOfficialVerificationIncident.objects.values(
            "last_probe_at",
            "next_probe_at",
            "alert_sent_at",
        ).get(pk=incident.pk)
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="manual-unavailable-commit-failure",
        )
        self.addCleanup(temporary.cleanup)
        original_savepoint_commit = connection.savepoint_commit
        call_count = 0

        def fail_first_savepoint_commit(savepoint_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise DatabaseError("injected main commit failure")
            return original_savepoint_commit(savepoint_id)

        with patch.object(
            connection,
            "savepoint_commit",
            side_effect=fail_first_savepoint_commit,
        ):
            with self.assertRaises(DatabaseError):
                apply_race_live_manual_official_evidence(
                    receipt=receipt,
                    receipt_sha256=digest,
                    now=self.NOW.replace(minute=31),
                )

        self.assertEqual(
            models.RaceLiveOfficialVerificationIncident.objects.values(
                "last_probe_at",
                "next_probe_at",
                "alert_sent_at",
            ).get(pk=incident.pk),
            incident_before,
        )
        self.assertFalse(models.NotificationLog.objects.exists())
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_manual_official_evidence",
            ).exists()
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_conflict_creates_evidence_and_atomically_applies_prepared_disable(self):
        bundle, incident = self._promote()
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, conflict=True),
            run_id="manual-conflict",
        )
        self.addCleanup(temporary.cleanup)

        result = apply_race_live_manual_official_evidence(
            receipt=receipt,
            receipt_sha256=digest,
            disable_manifest=self._loaded(bundle["disable"]),
            now=self.NOW.replace(minute=31),
        )

        self.assertEqual(result["comparison"], "conflict")
        incident.refresh_from_db()
        self.assertEqual(
            incident.status,
            models.RaceLiveOfficialVerificationIncidentStatus.ESCALATED,
        )
        event_policy = models.RaceLivePublicationPolicy.objects.get(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(self.event.pk),
        )
        self.assertEqual(event_policy.mode, models.RaceLivePublicationMode.SHADOW)
        self.assertEqual(event_policy.version, 3)
        self.assertTrue(models.RaceLiveOfficialMarkerEvidence.objects.exists())

    def test_conflict_disable_failure_rolls_back_evidence_incident_and_policy(self):
        bundle, incident = self._promote()
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, conflict=True),
            run_id="manual-conflict-rollback",
        )
        self.addCleanup(temporary.cleanup)
        with patch(
            "stable.services.race_live_manual_official_evidence.apply_race_live_publication_transition",
            side_effect=RaceLivePublicationTransitionError("injected disable failure"),
        ):
            with self.assertRaises(RaceLivePublicationTransitionError):
                apply_race_live_manual_official_evidence(
                    receipt=receipt,
                    receipt_sha256=digest,
                    disable_manifest=self._loaded(bundle["disable"]),
                    now=self.NOW.replace(minute=31),
                )
        incident.refresh_from_db()
        self.assertEqual(
            incident.status,
            models.RaceLiveOfficialVerificationIncidentStatus.OPEN,
        )
        event_policy = models.RaceLivePublicationPolicy.objects.get(
            scope_type=models.RaceLivePublicationScopeType.EVENT,
            scope_key=str(self.event.pk),
        )
        self.assertEqual(
            event_policy.mode,
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        )
        self.assertFalse(
            models.RaceResultSourceIdentity.objects.filter(
                event=self.event,
                source_key="bha_manual",
            ).exists()
        )
        self.assertFalse(models.RaceLiveOfficialMarkerEvidence.objects.exists())

    def test_prepare_rejects_raw_or_operator_supplied_comparison(self):
        _, incident = self._promote()
        submission = self._submission(incident)
        submission["raw_html"] = "<html>copyrighted</html>"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            with self.assertRaises(RaceLiveManualOfficialEvidenceError):
                prepare_race_live_manual_official_evidence(
                    submission=submission,
                    output_root=root,
                    run_id="raw-rejected",
                )
        submission.pop("raw_html")
        submission["comparison"] = "match"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            with self.assertRaises(RaceLiveManualOfficialEvidenceError):
                prepare_race_live_manual_official_evidence(
                    submission=submission,
                    output_root=root,
                    run_id="comparison-rejected",
                )
        submission.pop("comparison")
        submission["source_url"] = (
            "https://www.britishhorseracing.com/press-releases/"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            os.chmod(root, 0o700)
            with self.assertRaises(RaceLiveManualOfficialEvidenceError):
                prepare_race_live_manual_official_evidence(
                    submission=submission,
                    output_root=root,
                    run_id="wrong-bha-route-rejected",
                )

    def test_apply_command_defaults_to_offline_dry_run_and_requires_confirmation(self):
        _, incident = self._promote()
        temporary, path, _, digest = self._receipt(
            self._submission(incident),
            run_id="manual-command",
        )
        self.addCleanup(temporary.cleanup)
        stdout = StringIO()
        self._call_manual_dry_run(
            receipt_path=path,
            receipt_sha256=digest,
            stdout=stdout,
        )
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["comparison"], "match")
        self.assertEqual(result["alert_status"], "not_applicable")
        self.assertEqual(result["network_request_count"], 0)
        self.assertFalse(
            models.RaceResultSourceIdentity.objects.filter(
                event=self.event,
                source_key="bha_manual",
            ).exists()
        )
        with self.assertRaises(CommandError):
            call_command(
                "apply_race_live_manual_official_evidence",
                "--receipt",
                str(path),
                "--expected-receipt-sha256",
                digest,
                "--expected-approved-commit",
                self.APPROVED_COMMIT,
                "--apply",
            )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
    )
    def test_command_dry_run_plans_unavailable_without_writes_or_email(self):
        _, incident = self._promote()
        temporary, path, _, digest = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="manual-command-unavailable",
        )
        self.addCleanup(temporary.cleanup)
        stdout = StringIO()
        incident_before = models.RaceLiveOfficialVerificationIncident.objects.values(
            "last_probe_at",
            "next_probe_at",
            "alert_sent_at",
        ).get(pk=incident.pk)

        self._call_manual_dry_run(
            receipt_path=path,
            receipt_sha256=digest,
            stdout=stdout,
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(result["comparison"], "unavailable")
        self.assertEqual(result["alert_status"], "would_send")
        self.assertEqual(result["notification_side_effect_count"], 0)
        self.assertEqual(
            models.RaceLiveOfficialVerificationIncident.objects.values(
                "last_probe_at",
                "next_probe_at",
                "alert_sent_at",
            ).get(pk=incident.pk),
            incident_before,
        )
        self.assertFalse(models.NotificationLog.objects.exists())
        self.assertFalse(models.OperationLog.objects.filter(
            action_type="race_live_manual_official_evidence",
        ).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_command_dry_run_rejects_stale_revision_closed_or_missing_incident_and_conflict(self):
        _, incident = self._promote()
        for label, mutate, conflict in (
            (
                "stale-revision",
                lambda: models.RaceEventProjectionControl.objects.filter(
                    event=self.event,
                ).update(current_result_revision=None),
                False,
            ),
            (
                "closed-incident",
                lambda: models.RaceLiveOfficialVerificationIncident.objects.filter(
                    pk=incident.pk,
                ).update(
                    status=(
                        models.RaceLiveOfficialVerificationIncidentStatus.RESOLVED
                    ),
                    resolved_at=self.NOW,
                ),
                False,
            ),
            (
                "missing-incident",
                lambda: models.RaceLiveOfficialVerificationIncident.objects.filter(
                    pk=incident.pk,
                ).delete(),
                False,
            ),
            (
                "participant-conflict",
                lambda: None,
                True,
            ),
        ):
            with self.subTest(label=label), transaction.atomic():
                temporary, path, _, digest = self._receipt(
                    self._submission(
                        incident,
                        conflict=conflict,
                    ),
                    run_id=f"manual-command-{label}",
                )
                self.addCleanup(temporary.cleanup)
                mutate()
                with self.assertRaises(CommandError):
                    self._call_manual_dry_run(
                        receipt_path=path,
                        receipt_sha256=digest,
                    )
                self.assertFalse(models.NotificationLog.objects.exists())
                self.assertFalse(models.OperationLog.objects.filter(
                    action_type="race_live_manual_official_evidence",
                ).exists())
                transaction.set_rollback(True)

    def test_command_dry_run_rejects_disable_policy_or_allowlist_cas_drift(self):
        bundle, incident = self._promote()
        temporary, path, _, digest = self._receipt(
            self._submission(incident, conflict=True),
            run_id="manual-command-conflict-cas",
        )
        self.addCleanup(temporary.cleanup)
        manifest_temporary, manifest_path, manifest_sha256 = (
            self._manifest_file(
                bundle["disable"],
                run_id="manual-command-conflict-disable",
            )
        )
        self.addCleanup(manifest_temporary.cleanup)
        stdout = StringIO()
        self._call_manual_dry_run(
            receipt_path=path,
            receipt_sha256=digest,
            disable_path=manifest_path,
            disable_sha256=manifest_sha256,
            stdout=stdout,
        )
        valid_plan = json.loads(stdout.getvalue())
        self.assertEqual(valid_plan["comparison"], "conflict")
        self.assertEqual(valid_plan["notification_side_effect_count"], 0)
        self.assertFalse(models.RaceLiveOfficialMarkerEvidence.objects.exists())
        self.assertEqual(
            models.RaceLivePublicationPolicy.objects.get(
                scope_type=models.RaceLivePublicationScopeType.EVENT,
                scope_key=str(self.event.pk),
            ).mode,
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
        )
        mutations = (
            (
                "policy",
                lambda: models.RaceLivePublicationPolicy.objects.filter(
                    scope_type=models.RaceLivePublicationScopeType.EVENT,
                    scope_key=str(self.event.pk),
                ).update(version=99),
            ),
            (
                "allowlist",
                lambda: models.RaceLiveEventPublicationAllowlist.objects.filter(
                    event=self.event,
                ).update(version=99),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), transaction.atomic():
                mutate()
                with self.assertRaises(CommandError):
                    self._call_manual_dry_run(
                        receipt_path=path,
                        receipt_sha256=digest,
                        disable_path=manifest_path,
                        disable_sha256=manifest_sha256,
                    )
                self.assertFalse(models.NotificationLog.objects.exists())
                self.assertFalse(models.OperationLog.objects.filter(
                    action_type="race_live_manual_official_evidence",
                ).exists())
                transaction.set_rollback(True)


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL")
@override_settings(
    RACE_LIVE_ALERT_NOTIFY_EMAILS=["race-live-ops@example.com"],
)
class RaceLiveManualOfficialEvidencePostgresTests(TransactionTestCase):
    reset_sequences = True
    NOW = RaceLivePublicationTransitionTests.NOW
    APPROVED_COMMIT = RaceLivePublicationTransitionTests.APPROVED_COMMIT
    REGISTRY_DIGEST = RaceLivePublicationTransitionTests.REGISTRY_DIGEST
    COVERAGE_DIGEST = RaceLivePublicationTransitionTests.COVERAGE_DIGEST

    setUp = RaceLivePublicationTransitionTests.setUp
    _bundle = RaceLivePublicationTransitionTests._bundle
    _loaded = RaceLivePublicationTransitionTests._loaded
    _promote = RaceLiveManualOfficialEvidenceTests._promote
    _submission = RaceLiveManualOfficialEvidenceTests._submission
    _receipt = RaceLiveManualOfficialEvidenceTests._receipt

    def test_concurrent_distinct_unavailable_receipts_share_one_durable_intent(self):
        _, incident = self._promote()
        temporary_a, _, receipt_a, digest_a = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="postgres-unavailable-a",
        )
        self.addCleanup(temporary_a.cleanup)
        submission_b = self._submission(incident, outcome="unavailable")
        submission_b["observed_at"] = self.NOW.replace(
            minute=32,
            microsecond=0,
        ).isoformat()
        submission_b["evidence_sha256"] = "8" * 64
        temporary_b, _, receipt_b, digest_b = self._receipt(
            submission_b,
            run_id="postgres-unavailable-b",
        )
        self.addCleanup(temporary_b.cleanup)
        barrier = Barrier(2)
        send_lock = Lock()
        send_count = 0

        def assert_committed_intent_before_send(*args, **kwargs):
            nonlocal send_count

            def inspect_from_independent_connection():
                close_old_connections()
                try:
                    return (
                        models.NotificationLog.objects.filter(
                            status=models.NotificationStatus.QUEUED,
                        ).count(),
                        models.OperationLog.objects.filter(
                            action_type=(
                                "race_live_manual_official_evidence"
                            ),
                        ).count(),
                    )
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as inspector:
                queued_count, operation_count = inspector.submit(
                    inspect_from_independent_connection
                ).result(timeout=5)
            self.assertEqual(queued_count, 1)
            self.assertGreaterEqual(operation_count, 1)
            with send_lock:
                send_count += 1
            return 1

        def apply(receipt, digest, minute):
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET lock_timeout = '4s'")
                    cursor.execute("SET statement_timeout = '8s'")
                barrier.wait(timeout=5)
                return apply_race_live_manual_official_evidence(
                    receipt=receipt,
                    receipt_sha256=digest,
                    now=self.NOW.replace(minute=minute),
                )
            finally:
                connections.close_all()

        with patch(
            "stable.services.race_live_manual_official_evidence.send_mail",
            side_effect=assert_committed_intent_before_send,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [
                    future.result(timeout=12)
                    for future in (
                        pool.submit(apply, receipt_a, digest_a, 31),
                        pool.submit(apply, receipt_b, digest_b, 32),
                    )
                ]

        self.assertEqual(send_count, 1)
        self.assertEqual(
            [result["alert_status"] for result in results],
            [models.NotificationStatus.SENT] * 2,
        )
        self.assertEqual(models.NotificationLog.objects.count(), 1)
        self.assertEqual(
            models.NotificationLog.objects.get().status,
            models.NotificationStatus.SENT,
        )
        self.assertEqual(
            models.OperationLog.objects.filter(
                action_type="race_live_manual_official_evidence",
            ).count(),
            2,
        )
        incident.refresh_from_db()
        self.assertIsNotNone(incident.alert_sent_at)

    def test_postgres_late_main_failure_rolls_back_intent_before_delivery(self):
        _, incident = self._promote()
        incident_before = models.RaceLiveOfficialVerificationIncident.objects.values(
            "last_probe_at",
            "next_probe_at",
            "alert_sent_at",
        ).get(pk=incident.pk)
        temporary, _, receipt, digest = self._receipt(
            self._submission(incident, outcome="unavailable"),
            run_id="postgres-unavailable-rollback",
        )
        self.addCleanup(temporary.cleanup)
        with patch(
            "stable.services.race_live_manual_official_evidence.models.OperationLog.objects.create",
            side_effect=IntegrityError("postgres late operation failure"),
        ), patch(
            "stable.services.race_live_manual_official_evidence.send_mail"
        ) as send_mock:
            with self.assertRaises(IntegrityError):
                apply_race_live_manual_official_evidence(
                    receipt=receipt,
                    receipt_sha256=digest,
                    now=self.NOW.replace(minute=31),
                )

        send_mock.assert_not_called()
        self.assertEqual(
            models.RaceLiveOfficialVerificationIncident.objects.values(
                "last_probe_at",
                "next_probe_at",
                "alert_sent_at",
            ).get(pk=incident.pk),
            incident_before,
        )
        self.assertFalse(models.NotificationLog.objects.exists())
        self.assertFalse(
            models.OperationLog.objects.filter(
                action_type="race_live_manual_official_evidence",
            ).exists()
        )
