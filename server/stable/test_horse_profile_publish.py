"""Tests for the BASIC-tier publish gate and stock publish channel."""

from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path

from django.test import TestCase

from stable.models import (
    HorseProfile,
    HorseProfileStatus,
    OperationLog,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)
from stable.services.horse_profile_publish import (
    P0HorsePublishError,
    approve_publish_manifest,
    auto_publish_profiles,
    build_publish_dry_run_artifact,
    commit_approved_publish_manifest,
    evaluate_basic_publish_gate,
    write_publish_manifest,
)


class PublishTestBase(TestCase):
    def _term(self, name: str, region: str = RacingRegion.JAPAN, **overrides):
        defaults = {
            "term_type": TermType.HORSE,
            "source_language": SourceLanguage.JAPANESE,
            "source_ja": name,
            "target_zh": "",
            "racing_region": region,
            "is_active": True,
        }
        defaults.update(overrides)
        return TermEntry.objects.create(**defaults)

    def _profile(self, name: str, region: str = RacingRegion.JAPAN, **overrides):
        term = overrides.pop("primary_term", None) or self._term(name, region)
        defaults = {
            "primary_term": term,
            "original_name": name,
            "racing_region": region,
        }
        defaults.update(overrides)
        return HorseProfile.objects.create(**defaults)

    def _verified_profile(self, name="テストマ", **overrides):
        refs = {"horse_identity_verified_keys": ["netkeiba:2010100001"]}
        refs.update(overrides.pop("source_refs", {}))
        return self._profile(name, source_refs=refs, **overrides)

    def _reviewer(self, *, superuser=True):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(
            username=f"reviewer-{HorseProfile.objects.count()}",
            is_superuser=superuser,
            is_staff=True,
        )


class BasicPublishGateTests(PublishTestBase):
    def test_verified_key_passes(self):
        profile = self._verified_profile()
        self.assertTrue(evaluate_basic_publish_gate(profile).eligible)

    def test_flat_sync_key_does_not_pass(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_keys": ["netkeiba:2010100001"]},
        )
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("gate.identity", gate.blocking_reasons)

    def test_unrecognized_namespace_does_not_pass(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_verified_keys": ["jbis:0001234567"]},
        )
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("gate.identity", gate.blocking_reasons)

    def test_verified_key_without_identifier_does_not_pass(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_verified_keys": ["netkeiba", "netkeiba:"]},
        )
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("gate.identity", gate.blocking_reasons)

    def test_three_fields_pass_without_keys(self):
        profile = self._profile(
            "テストマ",
            sire_text="父马A",
            dam_text="母马A",
            birth_date=datetime.date(2020, 4, 1),
        )
        self.assertTrue(evaluate_basic_publish_gate(profile).eligible)

    def test_two_of_three_fields_blocked(self):
        profile = self._profile("テストマ", sire_text="父马A", dam_text="母马A")
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("gate.identity", gate.blocking_reasons)

    def test_empty_name_blocked(self):
        profile = self._profile("", original_name="", english_name="", japanese_name="")
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("gate.name", gate.blocking_reasons)

    def test_other_region_blocked(self):
        profile = self._verified_profile(region=RacingRegion.OTHER)
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("gate.region", gate.blocking_reasons)

    def test_hidden_blocked(self):
        profile = self._verified_profile(review_status=HorseProfileStatus.HIDDEN)
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("state.hidden", gate.blocking_reasons)

    def test_ready_with_hidden_at_blocked(self):
        profile = self._verified_profile(
            review_status=HorseProfileStatus.READY,
            hidden_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        )
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("state.hidden", gate.blocking_reasons)

    def test_lock_flag_blocked(self):
        profile = self._verified_profile(manual_lock_flags={"auto_publish_blocked": True})
        gate = evaluate_basic_publish_gate(profile)
        self.assertFalse(gate.eligible)
        self.assertIn("state.locked", gate.blocking_reasons)

    def test_draft_and_ready_eligible(self):
        draft = self._verified_profile("马A", primary_term=self._term("马A"))
        ready = self._verified_profile(
            "马B",
            primary_term=self._term("马B"),
            review_status=HorseProfileStatus.READY,
        )
        self.assertTrue(evaluate_basic_publish_gate(draft).eligible)
        self.assertTrue(evaluate_basic_publish_gate(ready).eligible)


class AutoPublishProfilesTests(PublishTestBase):
    def test_publishes_eligible_with_audit(self):
        profile = self._verified_profile()
        reviewer = self._reviewer()
        report = auto_publish_profiles(
            [profile], user=reviewer, note="test note"
        )
        self.assertEqual(report["published"], 1)
        profile.refresh_from_db()
        self.assertEqual(profile.review_status, HorseProfileStatus.PUBLISHED)
        self.assertEqual(profile.published_by, reviewer)
        self.assertIsNotNone(profile.published_at)
        self.assertTrue(
            OperationLog.objects.filter(
                action_type="horse_profile_status_changed",
                target_id=str(profile.pk),
            ).exists()
        )

    def test_skips_published_and_counts_blocked(self):
        published = self._verified_profile(
            "马A",
            primary_term=self._term("马A"),
            review_status=HorseProfileStatus.PUBLISHED,
        )
        blocked = self._profile("马B", primary_term=self._term("马B"))
        report = auto_publish_profiles([published, blocked], user=self._reviewer(), note="n")
        self.assertEqual(report["skipped_already_published"], 1)
        self.assertEqual(report["blocked"], 1)
        self.assertEqual(report["blocked_reasons"], {"gate.identity": 1})

    def test_locking_read_and_gate_run_inside_per_profile_atomic(self):
        from contextlib import contextmanager
        from unittest import mock

        from stable.services import horse_profile_publish as publish_module

        profile = self._verified_profile()
        reviewer = self._reviewer()
        depth = {"value": 0}
        events = []

        @contextmanager
        def controlled_atomic(*args, **kwargs):
            events.append("atomic_enter")
            depth["value"] += 1
            try:
                yield
            finally:
                depth["value"] -= 1
                events.append("atomic_exit")

        locked = mock.Mock()

        def locked_get(*, pk):
            self.assertGreater(depth["value"], 0)
            events.append("locked_get")
            self.assertEqual(pk, profile.pk)
            profile.refresh_from_db()
            return profile

        locked.get.side_effect = locked_get
        with mock.patch.object(
            publish_module.transaction,
            "atomic",
            side_effect=controlled_atomic,
        ), mock.patch.object(
            publish_module.HorseProfile.objects,
            "select_for_update",
            return_value=locked,
        ), mock.patch.object(
            publish_module,
            "evaluate_basic_publish_gate",
            wraps=publish_module.evaluate_basic_publish_gate,
        ) as gate:
            report = auto_publish_profiles(
                [profile.pk],
                user=reviewer,
                note="postgres transaction boundary",
            )
        self.assertEqual(report["published"], 1)
        self.assertLess(events.index("atomic_enter"), events.index("locked_get"))
        self.assertLess(events.index("locked_get"), events.index("atomic_exit"))
        gate.assert_called_once_with(profile)

    def test_rejects_locking_queryset_before_external_evaluation(self):
        from stable.services.horse_profile_publish import P0HorsePublishError

        profile = self._verified_profile()
        locking_queryset = HorseProfile.objects.select_for_update().filter(
            pk=profile.pk
        )
        with self.assertRaisesRegex(P0HorsePublishError, "non-locking"):
            auto_publish_profiles(
                locking_queryset,
                user=self._reviewer(),
                note="must not evaluate outside atomic",
            )
        self.assertIsNone(locking_queryset._result_cache)

    def test_atomic_exit_failure_is_counted_only_as_error(self):
        from contextlib import contextmanager
        from unittest import mock

        from stable.services import horse_profile_publish as publish_module

        profile = self._verified_profile()

        @contextmanager
        def deferred_commit_failure(*args, **kwargs):
            yield
            raise RuntimeError("deferred commit failed")

        with mock.patch.object(
            publish_module.transaction,
            "atomic",
            side_effect=deferred_commit_failure,
        ):
            report = auto_publish_profiles(
                [profile.pk],
                user=self._reviewer(),
                note="deferred commit failure",
            )
        self.assertEqual(report["published"], 0)
        self.assertEqual(report["published_profile_ids"], [])
        self.assertEqual(
            report["errors"],
            [{"profile_id": profile.pk, "error": "deferred commit failed"}],
        )


class StockPublishChannelTests(PublishTestBase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name)
        self.profile = self._verified_profile()

    def _dry_run(self, regions=(RacingRegion.JAPAN,)):
        artifact = build_publish_dry_run_artifact(regions=list(regions))
        return artifact, write_publish_manifest(artifact, output_dir=self.out_dir)

    def test_dry_run_writes_no_db_changes(self):
        artifact, _ = self._dry_run()
        self.assertEqual(len(artifact["candidates"]), 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.review_status, HorseProfileStatus.DRAFT)

    def test_blocked_histogram_excludes_ineligible(self):
        self._profile("无身份马", primary_term=self._term("无身份马"))
        artifact, _ = self._dry_run()
        self.assertEqual(artifact["stats"]["candidates"], 1)
        self.assertEqual(artifact["stats"]["blocked_reasons"], {"gate.identity": 1})

    def test_commit_requires_approved_manifest(self):
        _, manifest_path = self._dry_run()
        with self.assertRaises(P0HorsePublishError):
            commit_approved_publish_manifest(
                manifest_path,
                approved_sha256="0" * 64,
                reviewer=self._reviewer(),
            )

    def test_commit_rejects_tampered_manifest(self):
        _, manifest_path = self._dry_run()
        approved = approve_publish_manifest(manifest_path, reviewer="mentianlu")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifact_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(P0HorsePublishError):
            commit_approved_publish_manifest(
                manifest_path,
                approved_sha256=approved["approved_sha256"],
                reviewer=self._reviewer(),
            )

    def test_commit_publishes_and_is_idempotent(self):
        _, manifest_path = self._dry_run()
        approved = approve_publish_manifest(manifest_path, reviewer="mentianlu")
        reviewer = self._reviewer()
        report = commit_approved_publish_manifest(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
            reviewer=reviewer,
        )
        self.assertEqual(report["regions"][RacingRegion.JAPAN]["published"], 1)
        after = report["metrics_after"]["regions"][RacingRegion.JAPAN]
        self.assertEqual(after["published"], 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.review_status, HorseProfileStatus.PUBLISHED)
        second = commit_approved_publish_manifest(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
            reviewer=reviewer,
        )
        self.assertEqual(second["regions"][RacingRegion.JAPAN]["published"], 0)
        self.assertEqual(
            second["regions"][RacingRegion.JAPAN]["skipped_already_published"], 1
        )

    def test_gate_reevaluated_at_commit_time(self):
        _, manifest_path = self._dry_run()
        approved = approve_publish_manifest(manifest_path, reviewer="mentianlu")
        # drift: profile loses verified keys after approval
        self.profile.source_refs = {}
        self.profile.save(update_fields=["source_refs"])
        report = commit_approved_publish_manifest(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
            reviewer=self._reviewer(),
        )
        self.assertEqual(report["regions"][RacingRegion.JAPAN]["published"], 0)
        self.assertEqual(report["regions"][RacingRegion.JAPAN]["blocked"], 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.review_status, HorseProfileStatus.DRAFT)


class PublishProvenanceTests(PublishTestBase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name)

    def test_sync_remember_keys_does_not_write_verified(self):
        from stable.services.p0_horse_profiles import _remember_profile_identity_keys

        profile = self._profile("テストマ")
        index = {}
        _remember_profile_identity_keys(
            profile, {"netkeiba:2010100001"}, index
        )
        profile.refresh_from_db()
        self.assertEqual(
            profile.source_refs.get("horse_identity_keys"),
            ["netkeiba:2010100001"],
        )
        self.assertNotIn("horse_identity_verified_keys", profile.source_refs)
        self.assertFalse(evaluate_basic_publish_gate(profile).eligible)

    def test_enrichment_commit_writes_verified_keys(self):
        from stable.models import (
            ExternalDataSource,
            ExternalHorse,
            ExternalHorseAlias,
            HorseP0Source,
            HorseP0SourceStatus,
            HorseP0SourceType,
        )
        from stable.services.p0_horse_identity_enrichment import (
            approve_enrichment_manifest,
            build_dry_run_artifact,
            commit_approved_artifact,
            write_dry_run_artifact,
        )

        profile = self._profile("テストマ")
        HorseP0Source.objects.create(
            profile=profile,
            source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
            status=HorseP0SourceStatus.ACTIVE,
            racing_region=RacingRegion.JAPAN,
            horse_name=profile.original_name,
            participant_key=f"test:{profile.pk}",
            source_url="https://example.test/race/1",
        )
        horse = ExternalHorse.objects.create(
            source=ExternalDataSource.NETKEIBA,
            horse_id="2010100001",
            horse_name="テストマ",
            normalized_horse_name="テストマ",
        )
        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.NETKEIBA,
            horse=horse,
            external_horse_id="2010100001",
            name_ja="テストマ",
            normalized_name="テストマ",
        )
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        commit_approved_artifact(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
        )
        profile.refresh_from_db()
        self.assertEqual(
            profile.source_refs["horse_identity_keys"], ["netkeiba:2010100001"]
        )
        self.assertEqual(
            profile.source_refs["horse_identity_verified_keys"],
            ["netkeiba:2010100001"],
        )
        self.assertTrue(evaluate_basic_publish_gate(profile).eligible)

    def test_enrichment_dry_run_without_candidates_leaves_provenance_untouched(self):
        from stable.models import (
            ExternalDataSource,
            ExternalHorse,
            ExternalHorseAlias,
            HorseP0Source,
            HorseP0SourceStatus,
            HorseP0SourceType,
        )
        from stable.services.p0_horse_identity_enrichment import (
            approve_enrichment_manifest,
            build_dry_run_artifact,
            commit_approved_artifact,
            write_dry_run_artifact,
        )

        # key exists from before provenance support; verified list missing
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_keys": ["netkeiba:2010100001"]},
        )
        HorseP0Source.objects.create(
            profile=profile,
            source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
            status=HorseP0SourceStatus.ACTIVE,
            racing_region=RacingRegion.JAPAN,
            horse_name=profile.original_name,
            participant_key=f"test:{profile.pk}",
            source_url="https://example.test/race/1",
        )
        horse = ExternalHorse.objects.create(
            source=ExternalDataSource.NETKEIBA,
            horse_id="2010100001",
            horse_name="テストマ",
            normalized_horse_name="テストマ",
        )
        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.NETKEIBA,
            horse=horse,
            external_horse_id="2010100001",
            name_ja="テストマ",
            normalized_name="テストマ",
        )
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        # already present: no candidate this round; simulate re-commit of the
        # previously approved artifact instead.
        self.assertEqual(artifact["candidates"], [])
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        commit_approved_artifact(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
        )
        profile.refresh_from_db()
        # no candidate this round -> provenance not touched by this commit
        self.assertNotIn("horse_identity_verified_keys", profile.source_refs)
