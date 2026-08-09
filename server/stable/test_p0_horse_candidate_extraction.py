from __future__ import annotations

import json
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from stable.models import (
    HorseP0Source,
    HorseProfile,
    RaceEvent,
    RaceEventResult,
    RaceEventRunner,
    RaceEventSurface,
    RaceGrade,
    RaceRunnerStatus,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)
from stable.services.p0_horse_profiles import (
    _participant_identity_keys,
    _source_namespace,
    _source_url_from_payload,
    build_p0_participant_candidate_artifact,
)


class P0HorseCandidateSourceEvidenceTests(SimpleTestCase):
    def test_five_region_import_source_shapes_keep_urls_and_stable_namespaces(self):
        cases = (
            (
                "jra",
                {
                    "primary": "https://www.jra.go.jp/datafile/seiseki/replay/2017/018.html",
                    "source_kind": "jra_official_result_page",
                },
                set(),
            ),
            (
                "hkjc",
                {
                    "primary": "https://racing.hkjc.com/zh-hk/local/information/localresults?RaceNo=8",
                    "source_kind": "hkjc_local_results",
                },
                set(),
            ),
            (
                "sporting_life",
                {
                    "primary": "https://www.sportinglife.com/racing/results/2026/example",
                    "source_kind": "sporting_life_result_detail",
                    "horse_id": 1056974,
                },
                {"sporting_life:1056974"},
            ),
            (
                "zeturf",
                {
                    "primary": "https://www.zeturf.fr/fr/course-du-jour/2026/example",
                    "source_kind": "zeturf_race_detail",
                    "horse_id": "729569",
                },
                {"zeturf:729569"},
            ),
            (
                "equibase",
                {
                    "primary": "https://www.equibase.com/yearbook/Result.cfm?id=1",
                    "source_kind": "equibase_yearbook",
                },
                set(),
            ),
        )

        for namespace, source_refs, identity_keys in cases:
            with self.subTest(namespace=namespace):
                self.assertTrue(_source_url_from_payload(source_refs).startswith("https://"))
                self.assertEqual(_source_namespace(source_refs), namespace)
                self.assertEqual(_participant_identity_keys(source_refs), identity_keys)

    def test_production_adapter_source_kinds_map_to_stable_providers(self):
        cases = {
            "hkjc_official_result_page": "hkjc",
            "horse_racing_nation_track_day": "horse_racing_nation",
            "keiba_go_jp_race_mark_table": "keiba_go_jp",
            "keiba_go_jp_deba_table": "keiba_go_jp",
            "netkeiba_result": "netkeiba",
            "zone_turf_race_detail": "zone_turf",
            "zone_turf_horse_history": "zone_turf",
            "zone_turf_historical_result": "zone_turf",
            "equibase_pdf_chart": "equibase",
            "irishracing_historical_result": "irishracing",
            "nsa_official_result_pdf": "nsa",
        }

        for source_kind, expected_namespace in cases.items():
            with self.subTest(source_kind=source_kind):
                source_refs = {
                    "source_kind": source_kind,
                    "horse_id": "123",
                    "primary": "https://example.com/result",
                }
                self.assertEqual(
                    _source_namespace(source_refs),
                    expected_namespace,
                )
                self.assertEqual(
                    _participant_identity_keys(source_refs),
                    {f"{expected_namespace}:123"},
                )

    def test_historical_runner_primary_url_and_source_kind_are_recognized(self):
        source_refs = {
            "primary": "https://www.sportinglife.com/racing/results/2026/example",
            "source_kind": "sporting_life_result_detail",
            "horse_id": 1056974,
        }

        self.assertEqual(
            _source_url_from_payload(source_refs),
            source_refs["primary"],
        )
        self.assertEqual(_source_namespace(source_refs), "sporting_life")
        self.assertEqual(
            _participant_identity_keys(source_refs),
            {"sporting_life:1056974"},
        )

    def test_nested_event_source_url_is_available_as_fallback(self):
        source_refs = {
            "detail_source": {
                "provider": "equibase",
                "source_url": "https://www.equibase.com/yearbook/Result.cfm?id=1",
            }
        }

        self.assertEqual(
            _source_url_from_payload(source_refs),
            "https://www.equibase.com/yearbook/Result.cfm?id=1",
        )
        self.assertEqual(_source_namespace(source_refs), "equibase")

    def test_specific_source_kind_wins_over_generic_source_label(self):
        source_refs = {
            "source": "official",
            "source_kind": "zeturf_race_detail",
            "primary": "https://www.zeturf.fr/fr/course-du-jour/2026/example",
            "horse_id": "729569",
        }

        self.assertEqual(_source_namespace(source_refs), "zeturf")
        self.assertEqual(
            _participant_identity_keys(source_refs),
            {"zeturf:729569"},
        )

    def test_known_provider_subdomain_uses_stable_namespace(self):
        source_refs = {
            "primary": "https://racing.hkjc.com/zh-hk/local/information/localresults"
        }

        self.assertEqual(_source_namespace(source_refs), "hkjc")

    def test_generic_official_label_falls_back_to_provider_domain(self):
        jra_refs = {
            "source": "official",
            "primary": "https://www.jra.go.jp/datafile/seiseki/replay/2026/001.html",
            "horse_id": "123",
        }
        equibase_refs = {
            "source": "official",
            "primary": "https://www.equibase.com/yearbook/Result.cfm?id=1",
            "horse_id": "123",
        }

        self.assertEqual(_source_namespace(jra_refs), "jra")
        self.assertEqual(_source_namespace(equibase_refs), "equibase")
        self.assertEqual(_participant_identity_keys(jra_refs), {"jra:123"})
        self.assertEqual(_participant_identity_keys(equibase_refs), {"equibase:123"})

    def test_generic_id_payload_uses_provider_from_separate_url_payload(self):
        source_refs = {
            "primary": "https://www.jra.go.jp/datafile/seiseki/replay/2026/001.html",
        }
        raw_payload = {
            "source": "official",
            "horse_id": "123",
        }

        self.assertEqual(_source_namespace(source_refs, raw_payload), "jra")
        self.assertEqual(
            _participant_identity_keys(source_refs, raw_payload),
            {"jra:123"},
        )


class P0HorseCandidateExtractionTests(TestCase):
    def _event(
        self,
        *,
        region: str,
        year: int,
        slug: str,
        grade: str = RaceGrade.G1,
    ) -> RaceEvent:
        return RaceEvent.objects.create(
            year=year,
            slug=slug,
            original_name=slug.replace("-", " ").title(),
            chinese_name="",
            country_region=region,
            racecourse="Test Course",
            grade_text=grade,
            normalized_grade=grade,
            surface=RaceEventSurface.TURF,
            local_date=date(year, 6, 1),
            source_refs={
                "detail_source": {
                    "source_url": f"https://example.com/races/{slug}",
                }
            },
        )

    def _participant(
        self,
        event: RaceEvent,
        *,
        horse_name: str,
        horse_number: str,
        source_kind: str,
        horse_id: str = "",
        source_url: str = "",
        running_status: str = "",
        runner_running_status: str = RaceRunnerStatus.DECLARED,
        identity_payload: dict | None = None,
    ) -> tuple[RaceEventRunner, RaceEventResult]:
        source_refs = {
            "primary": source_url or f"https://example.com/races/{event.slug}",
            "source_kind": source_kind,
            **(identity_payload or {}),
        }
        if horse_id:
            source_refs["horse_id"] = horse_id
        runner = RaceEventRunner.objects.create(
            event=event,
            sort_order=1,
            horse_number=horse_number,
            horse_name=horse_name,
            running_status=runner_running_status,
            source_refs=source_refs,
        )
        result = RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_number=horse_number,
            horse_name=horse_name,
            running_status=running_status,
            source_refs={**source_refs, "official_finish_position": 1},
        )
        return runner, result

    def test_external_identity_deduplicates_but_name_only_never_deduplicates(self):
        uk_events = [
            self._event(
                region=RacingRegion.UNITED_KINGDOM,
                year=year,
                slug=f"uk-race-{year}",
            )
            for year in (2025, 2026)
        ]
        for event in uk_events:
            self._participant(
                event,
                horse_name="Lossiemouth",
                horse_number="1",
                source_kind="sporting_life_result_detail",
                horse_id="1056974",
            )
        us_events = [
            self._event(
                region=RacingRegion.UNITED_STATES,
                year=year,
                slug=f"us-race-{year}",
            )
            for year in (2025, 2026)
        ]
        for event in us_events:
            self._participant(
                event,
                horse_name="Twin Star",
                horse_number="2",
                source_kind="equibase_yearbook",
            )

        before = {
            "terms": TermEntry.objects.count(),
            "profiles": HorseProfile.objects.count(),
            "sources": HorseP0Source.objects.count(),
        }
        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.UNITED_KINGDOM, RacingRegion.UNITED_STATES],
            sample_per_region=10,
        )

        self.assertTrue(artifact["read_only"])
        self.assertEqual(
            artifact["summary"]["regions"][RacingRegion.UNITED_KINGDOM]["candidate_count"],
            1,
        )
        self.assertEqual(
            artifact["summary"]["regions"][RacingRegion.UNITED_STATES]["candidate_count"],
            2,
        )
        uk_candidate = next(
            row
            for row in artifact["candidates"]
            if RacingRegion.UNITED_KINGDOM in row["event_regions"]
        )
        self.assertEqual(uk_candidate["identity_status"], "strong_external_identity")
        self.assertEqual(uk_candidate["evidence_count"], 2)
        self.assertEqual(uk_candidate["identity_keys"], ["sporting_life:1056974"])
        us_candidates = [
            row
            for row in artifact["candidates"]
            if RacingRegion.UNITED_STATES in row["event_regions"]
        ]
        self.assertEqual(
            {row["identity_status"] for row in us_candidates},
            {"needs_identity_enrichment"},
        )
        self.assertEqual(uk_candidate["mapping_disposition"], "create_new")
        self.assertEqual(
            {row["mapping_disposition"] for row in us_candidates},
            {"blocked"},
        )
        self.assertEqual(
            artifact["summary"]["regions"][RacingRegion.UNITED_STATES]["sample_count"],
            1,
        )
        self.assertEqual(artifact["summary"]["unique_sample_candidate_count"], 2)
        self.assertEqual(
            before,
            {
                "terms": TermEntry.objects.count(),
                "profiles": HorseProfile.objects.count(),
                "sources": HorseP0Source.objects.count(),
            },
        )

    def test_non_p0_grade_is_excluded(self):
        event = self._event(
            region=RacingRegion.FRANCE,
            year=2026,
            slug="listed-race",
            grade=RaceGrade.LISTED,
        )
        self._participant(
            event,
            horse_name="Listed Horse",
            horse_number="3",
            source_kind="zeturf_race_detail",
            horse_id="333",
        )

        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.FRANCE],
            sample_per_region=10,
        )

        self.assertEqual(artifact["summary"]["eligible_event_count"], 0)
        self.assertEqual(artifact["candidates"], [])
        self.assertEqual(artifact["sample_rows"], [])

    def test_shared_external_key_connects_expanded_identity_evidence(self):
        first_event = self._event(
            region=RacingRegion.UNITED_KINGDOM,
            year=2025,
            slug="single-source-identity-race",
        )
        self._participant(
            first_event,
            horse_name="Connected Horse",
            horse_number="1",
            source_kind="sporting_life_result_detail",
            horse_id="1001",
        )
        second_event = self._event(
            region=RacingRegion.UNITED_KINGDOM,
            year=2026,
            slug="expanded-identity-race",
        )
        _, second_result = self._participant(
            second_event,
            horse_name="Connected Horse",
            horse_number="2",
            source_kind="sporting_life_result_detail",
            horse_id="1001",
        )
        second_result.source_refs = {
            "primary": "https://www.racingpost.com/results/example",
            "source_kind": "racing_post",
            "horse_id": "2002",
        }
        second_result.save(update_fields=["source_refs"])

        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.UNITED_KINGDOM],
            sample_per_region=10,
        )

        self.assertEqual(len(artifact["candidates"]), 1)
        candidate = artifact["candidates"][0]
        self.assertEqual(candidate["evidence_count"], 2)
        self.assertEqual(
            candidate["identity_keys"],
            ["racing_post:2002", "sporting_life:1001"],
        )

    def test_artifact_uses_url_provider_when_generic_id_is_in_raw_payload(self):
        event = self._event(
            region=RacingRegion.JAPAN,
            year=2026,
            slug="split-provider-identity-race",
        )
        runner, result = self._participant(
            event,
            horse_name="Split Provider Horse",
            horse_number="1",
            source_kind="",
            source_url="https://www.jra.go.jp/datafile/seiseki/replay/2026/001.html",
        )
        raw_payload = {"source": "official", "horse_id": "123"}
        runner.raw_payload = raw_payload
        runner.save(update_fields=["raw_payload"])
        result.raw_payload = raw_payload
        result.save(update_fields=["raw_payload"])

        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.JAPAN],
            sample_per_region=10,
        )

        self.assertEqual(len(artifact["candidates"]), 1)
        self.assertEqual(artifact["candidates"][0]["identity_keys"], ["jra:123"])
        self.assertEqual(
            artifact["candidates"][0]["identity_status"],
            "strong_external_identity",
        )

    def test_later_pedigree_is_aggregated_and_conflicting_pedigree_is_flagged(self):
        first_event = self._event(
            region=RacingRegion.FRANCE,
            year=2024,
            slug="pedigree-empty-race",
        )
        self._participant(
            first_event,
            horse_name="Pedigree Update Horse",
            horse_number="1",
            source_kind="zeturf_race_detail",
            horse_id="3003",
        )
        second_event = self._event(
            region=RacingRegion.FRANCE,
            year=2025,
            slug="pedigree-filled-race",
        )
        self._participant(
            second_event,
            horse_name="Pedigree Update Horse",
            horse_number="2",
            source_kind="zeturf_race_detail",
            horse_id="3003",
            identity_payload={
                "sire_name": "Known Sire",
                "dam_name": "Known Dam",
                "birth_year": 2021,
            },
        )

        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.FRANCE],
            sample_per_region=10,
        )
        candidate = artifact["candidates"][0]
        self.assertEqual(candidate["sire_name"], "Known Sire")
        self.assertEqual(candidate["dam_name"], "Known Dam")
        self.assertEqual(candidate["birth_year"], 2021)
        self.assertEqual(candidate["review_status"], "ready_for_profile_resolution")
        self.assertEqual(candidate["mapping_disposition"], "create_new")

        third_event = self._event(
            region=RacingRegion.FRANCE,
            year=2026,
            slug="pedigree-conflict-race",
        )
        self._participant(
            third_event,
            horse_name="Pedigree Update Horse",
            horse_number="3",
            source_kind="zeturf_race_detail",
            horse_id="3003",
            identity_payload={
                "sire_name": "Different Sire",
                "dam_name": "Known Dam",
                "birth_year": 2021,
            },
        )

        conflicted_artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.FRANCE],
            sample_per_region=10,
        )
        self.assertEqual(len(conflicted_artifact["candidates"]), 1)
        self.assertEqual(
            conflicted_artifact["candidates"][0]["review_status"],
            "identity_conflict",
        )

    def test_distinct_strong_identities_with_same_name_both_enter_sample(self):
        for index, horse_id in enumerate(("4001", "4002"), start=1):
            event = self._event(
                region=RacingRegion.UNITED_KINGDOM,
                year=2024 + index,
                slug=f"same-name-strong-{index}",
            )
            self._participant(
                event,
                horse_name="Shared Name",
                horse_number=str(index),
                source_kind="sporting_life_result_detail",
                horse_id=horse_id,
            )

        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.UNITED_KINGDOM],
            sample_per_region=10,
        )
        same_name_sample = [
            row for row in artifact["sample_rows"] if row["horse_name"] == "Shared Name"
        ]

        self.assertEqual(len(artifact["candidates"]), 2)
        self.assertEqual(len(same_name_sample), 2)
        self.assertEqual(
            len({row["candidate_key"] for row in same_name_sample}),
            2,
        )

    def test_candidate_service_and_command_reject_regions_outside_p0_scope(self):
        with self.assertRaisesMessage(ValueError, "invalid: other"):
            build_p0_participant_candidate_artifact(
                regions=[RacingRegion.OTHER],
                sample_per_region=10,
            )
        with self.assertRaises(CommandError):
            call_command(
                "p0_horse_profiles",
                "--extract-candidates",
                "--region",
                RacingRegion.OTHER,
                stdout=StringIO(),
            )

    def test_unique_existing_provider_identity_is_bind_existing(self):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Bound Horse",
            racing_region=RacingRegion.UNITED_KINGDOM,
        )
        profile = HorseProfile.objects.create(
            primary_term=term,
            original_name="Bound Horse",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_refs={"horse_identity_keys": ["sporting_life:4242"]},
        )
        event = self._event(
            region=RacingRegion.UNITED_KINGDOM,
            year=2025,
            slug="existing-provider-identity",
        )
        self._participant(
            event,
            horse_name="Bound Horse",
            horse_number="1",
            source_kind="sporting_life_result_detail",
            horse_id="4242",
        )

        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.UNITED_KINGDOM],
            sample_per_region=10,
            year=2025,
            actual_starts_only=True,
        )

        self.assertEqual(artifact["candidates"][0]["matched_profile_ids"], [profile.id])
        self.assertEqual(artifact["candidates"][0]["mapping_disposition"], "bind_existing")

    def test_external_and_pedigree_evidence_for_different_profiles_is_a_conflict(self):
        external_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="External Horse",
            racing_region=RacingRegion.UNITED_KINGDOM,
        )
        external_profile = HorseProfile.objects.create(
            primary_term=external_term,
            original_name="External Horse",
            racing_region=RacingRegion.UNITED_KINGDOM,
            source_refs={"horse_identity_keys": ["sporting_life:1001"]},
        )
        pedigree_term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Pedigree Horse",
            racing_region=RacingRegion.UNITED_KINGDOM,
        )
        pedigree_profile = HorseProfile.objects.create(
            primary_term=pedigree_term,
            original_name="Pedigree Horse",
            racing_region=RacingRegion.UNITED_KINGDOM,
            birth_date="2022-03-01",
            sire_text="Test Sire",
            dam_text="Test Dam",
        )
        event = self._event(
            region=RacingRegion.UNITED_KINGDOM,
            year=2026,
            slug="conflicting-identity-race",
        )
        self._participant(
            event,
            horse_name="Pedigree Horse",
            horse_number="1",
            source_kind="sporting_life_result_detail",
            horse_id="1001",
            identity_payload={
                "sire_name": "Test Sire",
                "dam_name": "Test Dam",
                "birth_year": 2022,
            },
        )

        with patch(
            "stable.services.p0_horse_profiles._matched_pedigree_identity_profile_ids",
            side_effect=AssertionError("candidate extraction must use its in-memory pedigree index"),
        ):
            artifact = build_p0_participant_candidate_artifact(
                regions=[RacingRegion.UNITED_KINGDOM],
                sample_per_region=10,
            )

        self.assertEqual(len(artifact["candidates"]), 1)
        candidate = artifact["candidates"][0]
        self.assertEqual(
            candidate["identity_status"],
            "external_pedigree_identity_conflict",
        )
        self.assertEqual(candidate["review_status"], "identity_conflict")
        self.assertEqual(candidate["mapping_disposition"], "ambiguous")
        self.assertEqual(
            candidate["matched_profile_ids"],
            sorted([external_profile.id, pedigree_profile.id]),
        )

    def test_nonstarter_and_unknown_results_are_not_counted_as_actual_starts(self):
        withdrawn_event = self._event(
            region=RacingRegion.UNITED_STATES,
            year=2026,
            slug="withdrawn-result-race",
        )
        self._participant(
            withdrawn_event,
            horse_name="Withdrawn Horse",
            horse_number="1",
            source_kind="equibase_yearbook",
            running_status=RaceRunnerStatus.WITHDRAWN,
        )
        unknown_event = self._event(
            region=RacingRegion.UNITED_STATES,
            year=2026,
            slug="unknown-result-race",
        )
        self._participant(
            unknown_event,
            horse_name="Unknown Horse",
            horse_number="2",
            source_kind="equibase_yearbook",
            running_status=RaceRunnerStatus.UNKNOWN,
        )
        runner_withdrawn_event = self._event(
            region=RacingRegion.UNITED_STATES,
            year=2026,
            slug="runner-withdrawn-result-race",
        )
        self._participant(
            runner_withdrawn_event,
            horse_name="Runner Withdrawn Horse",
            horse_number="3",
            source_kind="equibase_yearbook",
            runner_running_status=RaceRunnerStatus.WITHDRAWN,
        )

        artifact = build_p0_participant_candidate_artifact(
            regions=[RacingRegion.UNITED_STATES],
            sample_per_region=10,
        )
        candidates = {row["horse_name"]: row for row in artifact["candidates"]}

        self.assertEqual(candidates["Withdrawn Horse"]["actual_start_evidence_count"], 0)
        self.assertEqual(candidates["Withdrawn Horse"]["nonstarter_evidence_count"], 1)
        self.assertEqual(candidates["Unknown Horse"]["actual_start_evidence_count"], 0)
        self.assertEqual(candidates["Unknown Horse"]["unconfirmed_evidence_count"], 1)
        self.assertEqual(
            candidates["Runner Withdrawn Horse"]["actual_start_evidence_count"],
            0,
        )
        self.assertEqual(
            candidates["Runner Withdrawn Horse"]["nonstarter_evidence_count"],
            1,
        )

    def test_year_and_actual_start_scope_cover_extended_regions(self):
        included_event = self._event(
            region=RacingRegion.AUSTRALIA,
            year=2025,
            slug="australia-actual-start",
        )
        self._participant(
            included_event,
            horse_name="Official Starter",
            horse_number="1",
            source_kind="au_racing_australia",
            horse_id="AU-123",
            source_url="https://www.racingaustralia.horse/FreeFields/Results.aspx?Key=2025",
        )
        excluded_nonstarter = self._event(
            region=RacingRegion.GERMANY,
            year=2025,
            slug="germany-withdrawn",
        )
        self._participant(
            excluded_nonstarter,
            horse_name="Withdrawn Runner",
            horse_number="2",
            source_kind="de_deutscher_galopp",
            running_status=RaceRunnerStatus.WITHDRAWN,
            source_url="https://www.deutscher-galopp.de/gr/renntage/rennen.php?datum=2025-06-01",
        )
        excluded_year = self._event(
            region=RacingRegion.MIDDLE_EAST,
            year=2024,
            slug="uae-prior-year",
        )
        self._participant(
            excluded_year,
            horse_name="Prior Year Runner",
            horse_number="3",
            source_kind="uae_era",
            source_url="https://emiratesracing.com/racecard/2024-01-01/1/results",
        )

        artifact = build_p0_participant_candidate_artifact(
            regions=[
                RacingRegion.AUSTRALIA,
                RacingRegion.GERMANY,
                RacingRegion.MIDDLE_EAST,
            ],
            sample_per_region=10,
            year=2025,
            actual_starts_only=True,
        )

        self.assertEqual(artifact["year"], 2025)
        self.assertTrue(artifact["actual_starts_only"])
        self.assertEqual([row["horse_name"] for row in artifact["candidates"]], ["Official Starter"])
        self.assertEqual(artifact["candidates"][0]["identity_keys"], ["racing_australia:au-123"])
        self.assertEqual(artifact["summary"]["eligible_event_count"], 2)
        self.assertEqual(artifact["summary"]["participant_observation_count"], 1)
        self.assertEqual(artifact["summary"]["mapping_dispositions"], {"create_new": 1})

    def test_command_rejects_year_scope_outside_candidate_extraction(self):
        with self.assertRaisesMessage(
            CommandError,
            "--year/--actual-starts-only 只能配合 --extract-candidates",
        ):
            call_command(
                "p0_horse_profiles",
                "--queue",
                "--year",
                "2025",
                stdout=StringIO(),
            )

    def test_extended_regions_cannot_enter_operational_sync_or_queue(self):
        for mode in ("--sync-sources", "--queue"):
            with self.subTest(mode=mode), self.assertRaisesMessage(
                CommandError,
                "新增地区当前只允许 --extract-candidates",
            ):
                call_command(
                    "p0_horse_profiles",
                    mode,
                    "--region",
                    RacingRegion.AUSTRALIA,
                    stdout=StringIO(),
                )

    def test_command_writes_reviewable_artifacts_without_database_writes(self):
        event = self._event(
            region=RacingRegion.FRANCE,
            year=2026,
            slug="prix-test",
            grade=RaceGrade.G2,
        )
        self._participant(
            event,
            horse_name="ASMARANI",
            horse_number="4",
            source_kind="zeturf_race_detail",
            horse_id="729569",
        )
        before = (
            TermEntry.objects.count(),
            HorseProfile.objects.count(),
            HorseP0Source.objects.count(),
        )

        with TemporaryDirectory() as output_dir:
            stdout = StringIO()
            call_command(
                "p0_horse_profiles",
                "--extract-candidates",
                "--region",
                RacingRegion.FRANCE,
                "--limit-per-region",
                "10",
                "--output-dir",
                output_dir,
                "--json",
                stdout=stdout,
            )
            command_result = json.loads(stdout.getvalue())
            output = Path(output_dir)
            self.assertTrue((output / "p0_participant_candidates.json").exists())
            self.assertTrue((output / "p0_participant_sample_review.csv").exists())
            self.assertTrue((output / "p0_participant_observations.jsonl").exists())
            self.assertTrue((output / "summary.json").exists())
            self.assertTrue((output / "manifest.json").exists())
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest["files"]),
                {
                    "candidates",
                    "summary",
                    "sample_review_csv",
                    "observations_jsonl",
                },
            )
            self.assertTrue(all(item["sha256"] for item in manifest["files"].values()))
            self.assertEqual(command_result["summary"]["sample_count"], 1)
            with self.assertRaisesMessage(CommandError, "output directory is not empty"):
                call_command(
                    "p0_horse_profiles",
                    "--extract-candidates",
                    "--region",
                    RacingRegion.FRANCE,
                    "--output-dir",
                    output_dir,
                    stdout=StringIO(),
                )

        self.assertEqual(
            before,
            (
                TermEntry.objects.count(),
                HorseProfile.objects.count(),
                HorseP0Source.objects.count(),
            ),
        )

    def test_output_dir_is_rejected_outside_candidate_extraction_mode(self):
        with self.assertRaisesMessage(
            CommandError,
            "--output-dir 只能配合 --extract-candidates",
        ):
            call_command(
                "p0_horse_profiles",
                "--queue",
                "--output-dir",
                "runtime/ignored",
                stdout=StringIO(),
            )

    def test_limit_per_region_is_rejected_for_source_sync(self):
        with self.assertRaisesMessage(
            CommandError,
            "--limit-per-region 只适用于 --queue 或 --extract-candidates",
        ):
            call_command(
                "p0_horse_profiles",
                "--sync-sources",
                "--limit-per-region",
                "10",
                stdout=StringIO(),
            )
