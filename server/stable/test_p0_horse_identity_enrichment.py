"""Tests for offline P0 horse external identity enrichment."""

from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from stable.models import (
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceResult,
    HorseIdentityConflict,
    HorseP0Source,
    HorseP0SourceStatus,
    HorseP0SourceType,
    HorseProfile,
    RaceEvent,
    RaceEventRunner,
    RaceEventSurface,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)
from stable.services.p0_horse_identity_enrichment import (
    P0HorseIdentityEnrichmentError,
    aggregate_identity_conflicts,
    approve_enrichment_manifest,
    build_dry_run_artifact,
    build_region_identity_metrics,
    build_resolution_suggestions,
    commit_approved_artifact,
    commit_resolution_suggestions,
    write_aggregation_artifact,
    write_dry_run_artifact,
    write_resolution_artifact,
)
from stable.services.p0_horse_profiles import _participant_identity_keys


class IdentityEnrichmentTestBase(TestCase):
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

    def _p0_source(self, profile, region: str = RacingRegion.JAPAN, **overrides):
        defaults = {
            "profile": profile,
            "source_type": HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
            "status": HorseP0SourceStatus.ACTIVE,
            "racing_region": region,
            "horse_name": profile.original_name,
            "participant_key": f"test:{profile.pk}",
            "source_url": "https://example.test/race/1",
        }
        defaults.update(overrides)
        return HorseP0Source.objects.create(**defaults)

    def _external_horse(self, horse_id: str, name: str, **overrides):
        defaults = {
            "source": ExternalDataSource.NETKEIBA,
            "racing_region": RacingRegion.JAPAN,
            "horse_id": horse_id,
            "horse_name": name,
            "normalized_horse_name": name,
            "father_name": "父马A",
            "mother_name": "母马A",
        }
        defaults.update(overrides)
        horse = ExternalHorse.objects.create(**defaults)
        ExternalHorseAlias.objects.create(
            source=ExternalDataSource.NETKEIBA,
            racing_region=RacingRegion.JAPAN,
            horse=horse,
            external_horse_id=horse_id,
            name_ja=name,
            normalized_name=name,
        )
        return horse


class JapanAliasCandidateTests(IdentityEnrichmentTestBase):
    def test_unique_alias_match_produces_candidate_with_four_fields(self):
        import datetime

        profile = self._profile("テストマ")
        self._p0_source(profile)
        self._external_horse(
            "2010100001",
            "テストマ",
            birth_date=datetime.date(2020, 4, 1),
        )
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        accepted = artifact["candidates"]
        self.assertEqual(len(accepted), 1)
        candidate = accepted[0]
        self.assertEqual(candidate["profile_id"], profile.pk)
        self.assertEqual(candidate["identity_key"], "netkeiba:2010100001")
        self.assertEqual(candidate["namespace"], "netkeiba")
        self.assertEqual(candidate["external_id"], "2010100001")
        self.assertTrue(candidate["source_url"].startswith("https://"))
        four = candidate["four_fields"]
        self.assertEqual(four["sire_text"], "父马A")
        self.assertEqual(four["dam_text"], "母马A")
        self.assertEqual(four["birth_date"], "2020-04-01")

    def test_alias_matching_two_external_ids_goes_to_conflict(self):
        profile = self._profile("同名マ")
        self._p0_source(profile)
        self._external_horse("2010100001", "同名マ")
        self._external_horse("2015100002", "同名マ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(len(artifact["conflicts"]), 1)
        conflict = artifact["conflicts"][0]
        self.assertEqual(conflict["reason"], "ambiguous_external_identity")
        self.assertEqual(
            sorted(conflict["candidate_external_ids"]),
            ["2010100001", "2015100002"],
        )

    def test_same_external_id_matching_two_profiles_goes_to_conflict(self):
        first = self._profile("同名マ")
        self._p0_source(first)
        second = self._profile("同名マ", primary_term=self._term("同名マ"))
        self._p0_source(second)
        self._external_horse("2010100001", "同名マ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(len(artifact["conflicts"]), 2)
        self.assertEqual(
            sorted(c["profile_id"] for c in artifact["conflicts"]),
            [first.pk, second.pk],
        )

    def test_existing_contradictory_key_goes_to_conflict(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_keys": ["netkeiba:9999999999"]},
        )
        self._p0_source(profile)
        self._external_horse("2010100001", "テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(artifact["conflicts"][0]["reason"], "contradictory_identity")

    def test_existing_same_key_is_idempotent_skip(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_keys": ["netkeiba:2010100001"]},
        )
        self._p0_source(profile)
        self._external_horse("2010100001", "テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(artifact["conflicts"], [])
        self.assertEqual(artifact["stats"]["already_present"], 1)

    def test_unmapped_existing_key_is_neutral_not_contradiction(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_keys": ["jbis:0001234567"]},
        )
        self._p0_source(profile)
        self._external_horse("2010100001", "テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(artifact["candidates"]), 1)


class DryRunCommitGateTests(IdentityEnrichmentTestBase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name)
        self.profile = self._profile("テストマ")
        self._p0_source(self.profile)
        self._external_horse("2010100001", "テストマ")

    def test_dry_run_writes_no_db_changes(self):
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        write_dry_run_artifact(artifact, output_dir=self.out_dir)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.source_refs, {})
        self.assertEqual(self.profile.sire_text, "")

    def test_commit_requires_approved_sha(self):
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        with self.assertRaises(P0HorseIdentityEnrichmentError):
            commit_approved_artifact(manifest_path, approved_sha256="0" * 64)

    def test_commit_writes_keys_urls_and_four_fields(self):
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(
            manifest_path,
            reviewer="mentianlu",
        )
        report = commit_approved_artifact(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
        )
        self.assertEqual(report["regions"]["japan"]["applied"], 1)
        self.profile.refresh_from_db()
        keys = self.profile.source_refs["horse_identity_keys"]
        self.assertIn("netkeiba:2010100001", keys)
        self.assertTrue(all(key == key.lower() for key in keys))
        urls = self.profile.source_refs["horse_source_urls"]
        self.assertTrue(urls and urls[0].startswith("https://"))
        self.assertEqual(self.profile.sire_text, "父马A")
        self.assertEqual(self.profile.dam_text, "母马A")
        source = HorseP0Source.objects.get(profile=self.profile, status="active")
        self.assertIn(
            "netkeiba:2010100001",
            source.evidence_payload["horse_identity_keys"],
        )
        self.assertEqual(
            source.evidence_payload["identity_evidence"][0]["original_namespace"],
            "netkeiba",
        )

    def test_commit_is_idempotent(self):
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        commit_approved_artifact(manifest_path, approved_sha256=approved["approved_sha256"])
        report = commit_approved_artifact(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
        )
        self.assertEqual(report["regions"]["japan"]["applied"], 0)
        self.profile.refresh_from_db()
        self.assertEqual(
            self.profile.source_refs["horse_identity_keys"],
            ["netkeiba:2010100001"],
        )

    def test_existing_columns_not_overwritten_and_conflict_recorded(self):
        self.profile.sire_text = "人工锁定父"
        self.profile.save(update_fields=["sire_text"])
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        # The alias path fails closed on the pedigree contradiction: no
        # candidate is produced, so nothing can be committed.
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(artifact["conflicts"][0]["reason"], "four_field_mismatch")
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        commit_approved_artifact(manifest_path, approved_sha256=approved["approved_sha256"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.sire_text, "人工锁定父")
        self.assertEqual(self.profile.dam_text, "")
        self.assertFalse(self.profile.source_refs.get("horse_identity_keys"))
        self.assertTrue(
            HorseIdentityConflict.objects.filter(
                candidate_profiles=self.profile,
            ).exists()
        )

    def test_commit_blocks_candidate_when_fields_drift_before_write(self):
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(artifact["candidates"]), 1)
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        # drift: a contradictory sire value appears after the dry-run
        self.profile.sire_text = "人工锁定父"
        self.profile.save(update_fields=["sire_text"])
        report = commit_approved_artifact(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
        )
        self.assertEqual(report["regions"]["japan"]["applied"], 0)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.sire_text, "人工锁定父")
        self.assertEqual(self.profile.dam_text, "")
        self.assertFalse(self.profile.source_refs.get("horse_identity_keys"))
        self.assertTrue(
            HorseIdentityConflict.objects.filter(
                candidate_profiles=self.profile,
            ).exists()
        )


class OfflineConflictFingerprintTests(IdentityEnrichmentTestBase):
    def test_conflict_fingerprint_deterministic_and_resolved_skipped(self):
        profile = self._profile("同名マ")
        self._p0_source(profile)
        self._external_horse("2010100001", "同名マ")
        self._external_horse("2015100002", "同名マ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        manifest_path = write_dry_run_artifact(
            artifact, output_dir=Path(self._mkdtemp())
        )
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        commit_approved_artifact(manifest_path, approved_sha256=approved["approved_sha256"])
        from stable.models import HorseIdentityConflict

        conflict = HorseIdentityConflict.objects.get(status="pending")
        fingerprint = conflict.fingerprint
        self.assertEqual(len(fingerprint), 64)
        int(fingerprint, 16)
        conflict.status = "resolved"
        conflict.save(update_fields=["status"])
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        manifest_path = write_dry_run_artifact(
            artifact, output_dir=Path(self._mkdtemp())
        )
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        commit_approved_artifact(manifest_path, approved_sha256=approved["approved_sha256"])
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, "resolved")
        self.assertEqual(conflict.fingerprint, fingerprint)

    def _mkdtemp(self) -> str:
        import tempfile

        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return handle.name


class SyncEvidenceMergeTests(IdentityEnrichmentTestBase):
    def test_upsert_p0_source_preserves_identity_evidence(self):
        from stable.services.p0_horse_profiles import _upsert_p0_source

        profile = self._profile("テストマ")
        source, _ = _upsert_p0_source(
            profile=profile,
            source_type=HorseP0SourceType.TERM_ACTIVE_WITH_ZH,
            term=profile.primary_term,
            evidence_payload={
                "term_id": profile.primary_term.pk,
                "horse_identity_keys": ["netkeiba:2010100001"],
                "identity_evidence": [
                    {"original_namespace": "netkeiba", "original_id": "2010100001"}
                ],
            },
        )
        updated, created = _upsert_p0_source(
            profile=profile,
            source_type=HorseP0SourceType.TERM_ACTIVE_WITH_ZH,
            term=profile.primary_term,
            evidence_payload={"term_id": profile.primary_term.pk},
        )
        self.assertFalse(created)
        self.assertEqual(
            updated.evidence_payload["horse_identity_keys"],
            ["netkeiba:2010100001"],
        )
        self.assertEqual(
            updated.evidence_payload["identity_evidence"][0]["original_id"],
            "2010100001",
        )


class ConflictAggregationTests(IdentityEnrichmentTestBase):
    def test_aggregation_groups_by_name_candidates_reason(self):
        first = self._profile("同名マ")
        second = self._profile("同名マ", primary_term=self._term("同名マ"))
        for profile in (first, second):
            conflict = HorseIdentityConflict.objects.create(
                fingerprint=f"evt:{profile.pk}",
                status="pending",
                horse_name="同名マ",
                evidence_payload={"identity_status": "ambiguous_same_name_profiles"},
            )
            conflict.candidate_profiles.add(first, second)
        before = HorseIdentityConflict.objects.count()
        report = aggregate_identity_conflicts()
        self.assertEqual(HorseIdentityConflict.objects.count(), before)
        self.assertEqual(report["total_pending"], 2)
        group = report["groups"][0]
        self.assertEqual(group["conflict_count"], 2)
        self.assertEqual(group["suggested_action"], "needs_admin_review")

    def test_aggregation_artifact_writes_manifest_with_sha(self):
        import tempfile

        HorseIdentityConflict.objects.create(
            fingerprint="evt:1",
            status="pending",
            horse_name="同名マ",
            evidence_payload={"identity_status": "ambiguous_same_name_profiles"},
        )
        report = aggregate_identity_conflicts()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = write_aggregation_artifact(report, output_dir=tmp)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact_path = Path(manifest["artifact_path"])
            self.assertTrue(artifact_path.is_file())
            import hashlib

            self.assertEqual(
                hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                manifest["artifact_sha256"],
            )


class ParticipantIdentityKeyExtractionTests(SimpleTestCase):
    def test_netkeiba_horse_url_yields_netkeiba_key(self):
        keys = _participant_identity_keys(
            {"horse_url": "https://db.netkeiba.com/horse/2010100001/"}
        )
        self.assertIn("netkeiba:2010100001", keys)

    def test_netkeiba_result_url_yields_netkeiba_key(self):
        keys = _participant_identity_keys(
            {"horse_url": "https://db.netkeiba.com/horse/result/2010100001/"}
        )
        self.assertIn("netkeiba:2010100001", keys)

    def test_hkjc_horseid_url_yields_hkjc_key(self):
        keys = _participant_identity_keys(
            {
                "horse_url": (
                    "https://racing.hkjc.com/racing/information/english/"
                    "horse/horse.aspx?HorseId=HK_20150001"
                )
            }
        )
        self.assertIn("hkjc:hk_20150001", keys)

    def test_nar_lineage_code_url_yields_nar_key(self):
        keys = _participant_identity_keys(
            {
                "horse_url": (
                    "https://www.keiba.go.jp/KeibaWeb/DataRoom/"
                    "HorseMarkInfo?k_lineageLoginCode=123456"
                )
            }
        )
        self.assertIn("nar:123456", keys)

    def test_sporting_life_profile_url_yields_key(self):
        keys = _participant_identity_keys(
            {"horse_url": "https://www.sportinglife.com/racing/profiles/horse/1154799"}
        )
        self.assertIn("sporting_life:1154799", keys)

    def test_zeturf_url_never_yields_key(self):
        keys = _participant_identity_keys(
            {"horse_url": "https://www.zeturf.fr/fr/cheval/12345-foo"}
        )
        self.assertEqual(keys, set())

    def test_hrn_slug_never_yields_key(self):
        keys = _participant_identity_keys(
            {
                "source_name": "horse_racing_nation",
                "horse_slug": "just-a-name-slug",
                "horse_url": "https://www.horseracingnation.com/horse/Foo_Bar",
            }
        )
        self.assertEqual(keys, set())

    def test_numeric_slug_maps_for_recognized_namespace(self):
        keys = _participant_identity_keys(
            {"source_name": "netkeiba", "horse_slug": "2010100001"}
        )
        self.assertIn("netkeiba:2010100001", keys)

    def test_numeric_slug_ignored_for_unmapped_namespace(self):
        keys = _participant_identity_keys(
            {"source_name": "horse_racing_nation", "horse_slug": "12345"}
        )
        self.assertEqual(keys, set())


class ManifestGateTests(IdentityEnrichmentTestBase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name)
        self.profile = self._profile("テストマ")
        self._p0_source(self.profile)
        self._external_horse("2010100001", "テストマ")

    def _approved_manifest(self):
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        manifest_path = write_dry_run_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        return manifest_path, approved["approved_sha256"]

    def test_post_approval_manifest_tampering_is_rejected(self):
        manifest_path, approved_sha = self._approved_manifest()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # swap in a different artifact path while keeping status/approved_sha
        other_dir = self.out_dir / "other"
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        artifact["candidates"][0]["external_id"] = "9999999999"
        artifact["candidates"][0]["identity_key"] = "netkeiba:9999999999"
        write_dry_run_artifact(artifact, output_dir=other_dir)
        manifest["artifact_path"] = str(other_dir / "enrichment_artifact.json")
        manifest["artifact_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(P0HorseIdentityEnrichmentError):
            commit_approved_artifact(manifest_path, approved_sha256=approved_sha)

    def test_resolution_manifest_rejected_by_enrichment_commit(self):
        artifact = build_resolution_suggestions()
        manifest_path = write_resolution_artifact(artifact, output_dir=self.out_dir)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        with self.assertRaises(P0HorseIdentityEnrichmentError):
            commit_approved_artifact(
                manifest_path,
                approved_sha256=approved["approved_sha256"],
            )

    def test_enrichment_manifest_rejected_by_resolution_commit(self):
        from django.contrib.auth import get_user_model

        manifest_path, approved_sha = self._approved_manifest()
        reviewer = get_user_model().objects.create_user(username="reviewer")
        with self.assertRaises(P0HorseIdentityEnrichmentError):
            commit_resolution_suggestions(
                manifest_path,
                approved_sha256=approved_sha,
                resolved_by=reviewer,
            )


class JapanRaceEntryEvidenceTests(IdentityEnrichmentTestBase):
    def setUp(self):
        self.event = RaceEvent.objects.create(
            year=2024,
            slug="test-kikuka-sho-2024",
            original_name="菊花賞",
            chinese_name="菊花赏",
            country_region=RacingRegion.JAPAN,
            racecourse="京都",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            local_date=datetime.date(2024, 10, 20),
        )

    def _external_race(self, race_id="202405050811", **overrides):
        defaults = {
            "source": ExternalDataSource.NETKEIBA,
            "race_id": race_id,
            "race_name": "菊花賞",
            "race_date": self.event.local_date,
            "course": "京都",
            "venue": "京都",
        }
        defaults.update(overrides)
        return ExternalRace.objects.create(**defaults)

    def _entry(self, race, horse_id, name, entry_key="1"):
        return ExternalRaceEntry.objects.create(
            source=ExternalDataSource.NETKEIBA,
            race=race,
            external_race_id=race.race_id,
            entry_key=entry_key,
            horse_id=horse_id,
            horse_name=name,
            normalized_horse_name=name,
        )

    def _runner(self, name, number="3"):
        return RaceEventRunner.objects.create(
            event=self.event,
            horse_name=name,
            horse_number=number,
        )

    def test_unique_aligned_entry_produces_candidate(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ")
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(artifact["candidates"]), 1)
        candidate = artifact["candidates"][0]
        self.assertEqual(candidate["identity_key"], "netkeiba:2010100001")
        self.assertEqual(candidate["evidence_kind"], "external_race_entry")
        self.assertEqual(
            candidate["evidence_refs"]["aligned_event_ids"], [self.event.pk]
        )
        stats = artifact["stats"]["evidence"]["external_race_entry"]
        self.assertEqual(stats["rows_aligned"], 1)

    def test_entry_result_rows_merge_to_single_candidate(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ")
        ExternalRaceResult.objects.create(
            source=ExternalDataSource.NETKEIBA,
            race=race,
            external_race_id=race.race_id,
            result_key="1",
            horse_id="2010100001",
            horse_name="テストマ",
            normalized_horse_name="テストマ",
        )
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(artifact["candidates"]), 1)
        self.assertEqual(artifact["conflicts"], [])

    def test_two_horse_ids_for_one_profile_goes_to_conflict(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ", entry_key="1")
        self._entry(race, "2015100002", "テストマ", entry_key="2")
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(len(artifact["conflicts"]), 1)
        self.assertEqual(
            artifact["conflicts"][0]["reason"], "ambiguous_external_identity"
        )

    def test_ambiguous_event_alignment_discards_into_conflict(self):
        RaceEvent.objects.create(
            year=2024,
            slug="test-kikuka-sho-alt-2024",
            original_name="菊花賞",
            chinese_name="菊花赏",
            country_region=RacingRegion.JAPAN,
            racecourse="京都",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            local_date=self.event.local_date,
        )
        profile = self._profile("テストマ")
        self._p0_source(profile)
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ")
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(
            artifact["conflicts"][0]["reason"], "ambiguous_race_alignment"
        )

    def test_runner_absent_from_aligned_event_discards_row(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ")
        self._runner("別の馬")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(artifact["conflicts"], [])
        stats = artifact["stats"]["evidence"]["external_race_entry"]
        self.assertEqual(stats["rows_unaligned"], 1)

    def test_unique_venue_fallback_aligns_when_name_differs(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        race = self._external_race(race_name="菊花賞（G1）")
        self._entry(race, "2010100001", "テストマ")
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(artifact["candidates"]), 1)

    def test_pedigree_contradiction_blocks_candidate(self):
        profile = self._profile("テストマ", sire_text="人工锁定父")
        self._p0_source(profile)
        # ExternalHorse without an alias: only the race-entry path can see it.
        ExternalHorse.objects.create(
            source=ExternalDataSource.NETKEIBA,
            horse_id="2010100001",
            horse_name="テストマ",
            normalized_horse_name="テストマ",
            father_name="父马A",
            mother_name="母马A",
        )
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ")
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(artifact["conflicts"][0]["reason"], "four_field_mismatch")

    def test_alias_path_winner_skips_entry_path(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        self._external_horse("2010100001", "テストマ")
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ")
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(artifact["candidates"]), 1)
        self.assertEqual(
            artifact["candidates"][0]["evidence_kind"], "external_horse_alias"
        )

    def test_key_held_by_other_profile_goes_to_conflict(self):
        holder = self._profile(
            "別の馬",
            source_refs={"horse_identity_keys": ["netkeiba:2010100001"]},
        )
        self._p0_source(holder)
        profile = self._profile("テストマ", primary_term=self._term("テストマ"))
        self._p0_source(profile)
        race = self._external_race()
        self._entry(race, "2010100001", "テストマ")
        self._runner("テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(artifact["candidates"], [])
        conflict = artifact["conflicts"][0]
        self.assertEqual(conflict["reason"], "ambiguous_external_identity")
        self.assertEqual(conflict["related_profile_ids"], [holder.pk])


class UkRaceSourceRefTests(IdentityEnrichmentTestBase):
    def _uk_profile_with_runner(self, name, *, horse_id="1154799", keys=None):
        profile = self._profile(
            name,
            region=RacingRegion.UNITED_KINGDOM,
            source_refs={"horse_identity_keys": keys} if keys else {},
        )
        event = RaceEvent.objects.create(
            year=2024,
            slug=f"uk-test-{profile.pk}-2024",
            original_name="Test Stakes",
            chinese_name="测试锦标",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            local_date=datetime.date(2024, 6, 20),
        )
        runner = RaceEventRunner.objects.create(
            event=event,
            horse_name=name,
            horse_number="1",
            source_refs={"source_name": "sporting_life", "horse_id": horse_id},
        )
        self._p0_source(
            profile,
            region=RacingRegion.UNITED_KINGDOM,
            evidence_payload={"race_runner_id": runner.pk},
        )
        return profile

    def test_unique_sporting_life_id_produces_candidate(self):
        self._uk_profile_with_runner("Test Horse")
        artifact = build_dry_run_artifact(regions=[RacingRegion.UNITED_KINGDOM])
        candidates = [
            item
            for item in artifact["candidates"]
            if item["namespace"] == "sporting_life"
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["identity_key"], "sporting_life:1154799")

    def test_key_held_by_other_profile_goes_to_conflict(self):
        holder = self._uk_profile_with_runner("Holder Horse")
        holder.source_refs = {"horse_identity_keys": ["sporting_life:1154799"]}
        holder.save(update_fields=["source_refs"])
        self._uk_profile_with_runner("Test Horse")
        artifact = build_dry_run_artifact(regions=[RacingRegion.UNITED_KINGDOM])
        candidates = [
            item
            for item in artifact["candidates"]
            if item["namespace"] == "sporting_life"
        ]
        self.assertEqual(candidates, [])
        conflicts = [
            item
            for item in artifact["conflicts"]
            if item["reason"] == "ambiguous_external_identity"
        ]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["related_profile_ids"], [holder.pk])

    def test_other_provider_namespace_is_not_mislabeled(self):
        profile = self._profile("Test Horse", region=RacingRegion.UNITED_KINGDOM)
        event = RaceEvent.objects.create(
            year=2024,
            slug="uk-test-mislabel-2024",
            original_name="Test Stakes",
            chinese_name="测试锦标",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=RaceEventSurface.TURF,
            local_date=datetime.date(2024, 6, 20),
        )
        runner = RaceEventRunner.objects.create(
            event=event,
            horse_name="Test Horse",
            horse_number="1",
            source_refs={"source_name": "racing_post", "horse_id": "99999"},
        )
        self._p0_source(
            profile,
            region=RacingRegion.UNITED_KINGDOM,
            evidence_payload={"race_runner_id": runner.pk},
        )
        artifact = build_dry_run_artifact(regions=[RacingRegion.UNITED_KINGDOM])
        candidates = [
            item
            for item in artifact["candidates"]
            if item["namespace"] == "sporting_life"
        ]
        self.assertEqual(candidates, [])


class CacheLinkEvidenceTests(IdentityEnrichmentTestBase):
    def _cache_row(self, namespace, external_id, name):
        return {
            "namespace": namespace,
            "external_id": external_id,
            "name": name,
            "normalized_name": name,
            "source_file": "/cache/page1.html",
        }

    def test_hkjc_unique_match_produces_candidate(self):
        profile = self._profile("金鎗六十", region=RacingRegion.HONG_KONG)
        self._p0_source(profile, region=RacingRegion.HONG_KONG)
        rows = [self._cache_row("hkjc", "HK_20150001", "金鎗六十")]
        artifact = build_dry_run_artifact(
            regions=[RacingRegion.HONG_KONG],
            cache_evidence=rows,
        )
        self.assertEqual(len(artifact["candidates"]), 1)
        candidate = artifact["candidates"][0]
        self.assertEqual(candidate["identity_key"], "hkjc:hk_20150001")
        self.assertEqual(candidate["evidence_kind"], "html_cache_reparse")
        self.assertEqual(
            candidate["evidence_refs"]["original_id"], "HK_20150001"
        )

    def test_hkjc_commit_writes_casefolded_keys(self):
        import tempfile

        profile = self._profile("金鎗六十", region=RacingRegion.HONG_KONG)
        self._p0_source(profile, region=RacingRegion.HONG_KONG)
        rows = [self._cache_row("hkjc", "HK_20150001", "金鎗六十")]
        artifact = build_dry_run_artifact(
            regions=[RacingRegion.HONG_KONG],
            cache_evidence=rows,
        )
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = write_dry_run_artifact(artifact, output_dir=tmp)
            approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
            commit_approved_artifact(
                manifest_path,
                approved_sha256=approved["approved_sha256"],
            )
        profile.refresh_from_db()
        self.assertEqual(
            profile.source_refs["horse_identity_keys"], ["hkjc:hk_20150001"]
        )
        source = HorseP0Source.objects.get(profile=profile, status="active")
        self.assertEqual(
            source.evidence_payload["horse_identity_keys"], ["hkjc:hk_20150001"]
        )
        self.assertEqual(
            source.evidence_payload["identity_evidence"][0]["original_id"],
            "HK_20150001",
        )

    def test_hkjc_ambiguous_ids_go_to_conflict(self):
        profile = self._profile("金鎗六十", region=RacingRegion.HONG_KONG)
        self._p0_source(profile, region=RacingRegion.HONG_KONG)
        rows = [
            self._cache_row("hkjc", "HK_20150001", "金鎗六十"),
            self._cache_row("hkjc", "HK_20190002", "金鎗六十"),
        ]
        artifact = build_dry_run_artifact(
            regions=[RacingRegion.HONG_KONG],
            cache_evidence=rows,
        )
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(
            artifact["conflicts"][0]["reason"], "ambiguous_external_identity"
        )

    def test_nar_disabled_without_probe_coverage(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        rows = [self._cache_row("nar", "123456", "テストマ")]
        artifact = build_dry_run_artifact(
            regions=[RacingRegion.JAPAN],
            cache_evidence=rows,
        )
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(
            artifact["stats"]["evidence"]["nar_status"],
            "disabled_insufficient_cache_coverage",
        )

    def test_nar_enabled_with_probe_coverage(self):
        profile = self._profile("テストマ")
        self._p0_source(profile)
        rows = [self._cache_row("nar", "123456", "テストマ")]
        probe = {"files_scanned": 10, "files_with_matches": 8, "named_ids": 5}
        artifact = build_dry_run_artifact(
            regions=[RacingRegion.JAPAN],
            cache_evidence=rows,
            nar_probe=probe,
        )
        candidates = [
            item for item in artifact["candidates"] if item["namespace"] == "nar"
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["identity_key"], "nar:123456")
        self.assertEqual(artifact["stats"]["evidence"]["nar_status"], "enabled")


class HtmlCacheReparseTests(SimpleTestCase):
    def test_hkjc_link_parsing(self):
        from stable.services.horse_identity_html_parse import parse_hkjc_horse_links

        html = (
            '<a href="/racing/information/English/Horse/Horse.aspx?HorseId=HK_20150001">'
            "金鎗六十</a>"
            '<a href="horse.aspx?horseid=HK_20190002">Golden Sixty</a>'
        )
        pairs = parse_hkjc_horse_links(html)
        self.assertEqual(
            pairs,
            [
                {"external_id": "HK_20150001", "name": "金鎗六十"},
                {"external_id": "HK_20190002", "name": "Golden Sixty"},
            ],
        )

    def test_nar_link_parsing(self):
        from stable.services.horse_identity_html_parse import parse_nar_horse_links

        html = (
            '<a href="HorseMarkInfo?k_lineageLoginCode=123456">テストマ</a>'
            '<a href="HorseMarkInfo?k_lineageLoginCode=234567"><span>別の馬</span></a>'
        )
        pairs = parse_nar_horse_links(html)
        self.assertEqual(
            pairs,
            [
                {"external_id": "123456", "name": "テストマ"},
                {"external_id": "234567", "name": "別の馬"},
            ],
        )

    def test_reparse_tool_walks_cache_and_reports_missing_root(self):
        import tempfile

        tool_path = (
            Path(__file__).resolve().parents[2]
            / "runtime"
            / "tools"
            / "reparse_horse_identity_html_cache.py"
        )
        spec = importlib.util.spec_from_file_location("reparse_tool", tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            (cache / "page1.html").write_text(
                '<a href="horse.aspx?HorseId=HK_20150001">金鎗六十</a>',
                encoding="utf-8",
            )
            evidence, summary = module.reparse_cache(
                namespace="hkjc",
                cache_roots=[cache, Path(tmp) / "missing"],
            )
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]["external_id"], "HK_20150001")
            self.assertEqual(evidence[0]["namespace"], "hkjc")
            self.assertEqual(summary["files_scanned"], 1)
            self.assertEqual(summary["files_with_matches"], 1)
            self.assertEqual(summary["missing_roots"], [str(Path(tmp) / "missing")])
            empty_evidence, empty_summary = module.reparse_cache(
                namespace="nar",
                cache_roots=[Path(tmp) / "missing"],
            )
            self.assertEqual(empty_evidence, [])
            self.assertEqual(empty_summary["status"], "cache_missing_or_empty")


class RegionIdentityMetricsTests(IdentityEnrichmentTestBase):
    def test_metrics_counts_and_ratios(self):
        with_keys = self._profile(
            "テストマ",
            source_refs={
                "horse_identity_keys": ["netkeiba:2010100001"],
                "horse_source_urls": ["https://db.netkeiba.com/horse/2010100001/"],
            },
        )
        self._p0_source(with_keys)
        bare = self._profile("別の馬", primary_term=self._term("別の馬"))
        self._p0_source(bare)
        metrics = build_region_identity_metrics([RacingRegion.JAPAN])
        japan = metrics["regions"][RacingRegion.JAPAN]
        self.assertEqual(japan["profiles_total"], 2)
        self.assertEqual(japan["with_identity_keys"], 1)
        self.assertEqual(japan["with_source_urls"], 1)
        self.assertEqual(japan["needs_identity_enrichment"], 1)
        self.assertAlmostEqual(japan["identity_key_coverage"], 0.5)

    def test_dry_run_has_metrics_before_and_commit_has_metrics_after(self):
        import tempfile

        profile = self._profile("テストマ")
        self._p0_source(profile)
        self._external_horse("2010100001", "テストマ")
        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        before = artifact["metrics_before"]["regions"][RacingRegion.JAPAN]
        self.assertEqual(before["with_identity_keys"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = write_dry_run_artifact(artifact, output_dir=tmp)
            approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
            report = commit_approved_artifact(
                manifest_path,
                approved_sha256=approved["approved_sha256"],
            )
        after = report["metrics_after"]["regions"][RacingRegion.JAPAN]
        self.assertEqual(after["with_identity_keys"], 1)
        self.assertEqual(after["needs_identity_enrichment"], 0)


class OfflineEndToEndTests(IdentityEnrichmentTestBase):
    """Task 6.3: candidate -> conflict -> approve -> commit -> sync -> metrics."""

    def test_full_offline_cycle(self):
        import tempfile

        from stable.services.p0_horse_profiles import _upsert_p0_source

        accepted = self._profile("テストマ")
        self._p0_source(accepted)
        self._external_horse("2010100001", "テストマ")
        ambiguous = self._profile("同名マ", primary_term=self._term("同名マ"))
        self._p0_source(ambiguous)
        self._external_horse("2015100002", "同名マ")
        self._external_horse("2016100003", "同名マ")

        artifact = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(len(artifact["candidates"]), 1)
        self.assertEqual(len(artifact["conflicts"]), 1)
        self.assertEqual(
            artifact["metrics_before"]["regions"][RacingRegion.JAPAN][
                "with_identity_keys"
            ],
            0,
        )
        accepted.refresh_from_db()
        self.assertEqual(accepted.source_refs, {})

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = write_dry_run_artifact(artifact, output_dir=tmp)
            approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
            report = commit_approved_artifact(
                manifest_path,
                approved_sha256=approved["approved_sha256"],
            )

        self.assertEqual(report["regions"][RacingRegion.JAPAN]["applied"], 1)
        self.assertEqual(report["regions"][RacingRegion.JAPAN]["conflicts"], 1)
        self.assertEqual(
            report["metrics_after"]["regions"][RacingRegion.JAPAN][
                "with_identity_keys"
            ],
            1,
        )
        accepted.refresh_from_db()
        self.assertEqual(
            accepted.source_refs["horse_identity_keys"], ["netkeiba:2010100001"]
        )
        self.assertTrue(
            HorseIdentityConflict.objects.filter(status="pending").exists()
        )

        # Re-running a source sync must preserve the backfilled identity
        # evidence instead of recomputing it away.
        source = HorseP0Source.objects.get(profile=accepted, status="active")
        updated, created = _upsert_p0_source(
            profile=accepted,
            source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
            term=accepted.primary_term,
            race_event=source.race_event,
            horse_name=accepted.original_name,
            participant_key=source.participant_key,
            evidence_payload={"refreshed": True},
        )
        self.assertFalse(created)
        self.assertEqual(
            updated.evidence_payload["horse_identity_keys"],
            ["netkeiba:2010100001"],
        )

        # A second dry-run sees the key as already present and plans nothing.
        second = build_dry_run_artifact(regions=[RacingRegion.JAPAN])
        self.assertEqual(second["candidates"], [])
        self.assertEqual(second["stats"]["already_present"], 1)


class ResolutionSuggestionTests(IdentityEnrichmentTestBase):
    def _conflict(self, profile, *, fingerprint="offline:test", **overrides):
        defaults = {
            "fingerprint": fingerprint,
            "status": "pending",
            "horse_name": profile.original_name,
            "evidence_payload": {"identity_status": "ambiguous_same_name_profiles"},
        }
        defaults.update(overrides)
        conflict = HorseIdentityConflict.objects.create(**defaults)
        conflict.candidate_profiles.add(profile)
        return conflict

    def _approve_and_commit(self, artifact, reviewer, tmp):
        manifest_path = write_resolution_artifact(artifact, output_dir=tmp)
        approved = approve_enrichment_manifest(manifest_path, reviewer="mentianlu")
        return commit_resolution_suggestions(
            manifest_path,
            approved_sha256=approved["approved_sha256"],
            resolved_by=reviewer,
        )

    def _reviewer(self):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.create_user(username="reviewer")

    def test_four_field_alignment_generates_suggestion_and_resolves(self):
        import tempfile

        profile = self._profile(
            "テストマ",
            sire_text="父马A",
            dam_text="母马A",
            birth_date=datetime.date(2020, 4, 1),
        )
        conflict = self._conflict(
            profile,
            sire_name="父马A",
            dam_name="母马A",
            birth_year=2020,
        )
        artifact = build_resolution_suggestions()
        self.assertEqual(len(artifact["suggestions"]), 1)
        suggestion = artifact["suggestions"][0]
        self.assertEqual(suggestion["fingerprint"], conflict.fingerprint)
        self.assertEqual(suggestion["resolved_profile_id"], profile.pk)
        with tempfile.TemporaryDirectory() as tmp:
            report = self._approve_and_commit(artifact, self._reviewer(), tmp)
        self.assertEqual(report["resolved"], 1)
        conflict.refresh_from_db()
        self.assertEqual(conflict.status, "resolved")
        self.assertEqual(conflict.resolved_profile_id, profile.pk)
        self.assertIsNotNone(conflict.resolved_at)

    def test_identity_key_alignment_generates_suggestion(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_keys": ["netkeiba:2010100001"]},
        )
        self._conflict(profile, identity_keys=["netkeiba:2010100001"])
        artifact = build_resolution_suggestions()
        self.assertEqual(len(artifact["suggestions"]), 1)

    def test_no_unique_alignment_no_suggestion(self):
        first = self._profile(
            "同名マ",
            sire_text="父马A",
            dam_text="母马A",
            birth_date=datetime.date(2020, 4, 1),
        )
        second = self._profile(
            "同名マ",
            primary_term=self._term("同名マ"),
            sire_text="父马A",
            dam_text="母马A",
            birth_date=datetime.date(2020, 4, 1),
        )
        conflict = self._conflict(
            first,
            sire_name="父马A",
            dam_name="母马A",
            birth_year=2020,
        )
        conflict.candidate_profiles.add(second)
        artifact = build_resolution_suggestions()
        self.assertEqual(artifact["suggestions"], [])

    def test_pairing_conflict_without_candidate_number_is_skipped(self):
        profile = self._profile(
            "テストマ",
            source_refs={"horse_identity_keys": ["netkeiba:2010100001"]},
        )
        self._conflict(
            profile,
            identity_keys=["netkeiba:2010100001"],
            horse_number="",
            evidence_payload={
                "identity_status": "pairing_conflict",
                "pairing_conflict": {"horse_numbers": ["3", "5"]},
            },
        )
        artifact = build_resolution_suggestions()
        self.assertEqual(artifact["suggestions"], [])
        self.assertEqual(len(artifact["skipped"]), 1)
        self.assertEqual(
            artifact["skipped"][0]["reason"],
            "pairing_conflict_without_candidate_horse_number",
        )

    def test_commit_requires_approved_manifest(self):
        import tempfile

        artifact = build_resolution_suggestions()
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = write_resolution_artifact(artifact, output_dir=tmp)
            with self.assertRaises(P0HorseIdentityEnrichmentError):
                commit_resolution_suggestions(
                    manifest_path,
                    approved_sha256="0" * 64,
                    resolved_by=self._reviewer(),
                )

    def test_resolved_conflict_not_overwritten_on_rerun(self):
        import tempfile

        profile = self._profile(
            "テストマ",
            sire_text="父马A",
            dam_text="母马A",
            birth_date=datetime.date(2020, 4, 1),
        )
        conflict = self._conflict(
            profile,
            sire_name="父马A",
            dam_name="母马A",
            birth_year=2020,
        )
        artifact = build_resolution_suggestions()
        reviewer = self._reviewer()
        with tempfile.TemporaryDirectory() as tmp:
            self._approve_and_commit(artifact, reviewer, tmp)
            conflict.refresh_from_db()
            first_notes = conflict.resolution_notes
            report = self._approve_and_commit(artifact, reviewer, tmp)
        self.assertEqual(report["resolved"], 0)
        self.assertEqual(report["skipped_not_pending"], 1)
        conflict.refresh_from_db()
        self.assertEqual(conflict.resolution_notes, first_notes)
