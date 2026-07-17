from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from stable.models import (
    HorseCareerHistoryStatus,
    HorseP0Source,
    HorseP0SourceType,
    HorseProfile,
    HorseProfileStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    HorseRaceStartStatus,
    HorseRacingCareerStatus,
    RaceEvent,
    RaceEventResult,
    RaceEventVisibility,
    RacingRegion,
    SourceLanguage,
    TermEntry,
    TermType,
)
from stable.services.horse_race_records import (
    refresh_career_history_completeness,
    upsert_race_record,
)
from stable.services.p0_horse_profiles import evaluate_full_profile_completeness
from stable.services.horse_profile_completion import CompletionOptions, plan_profile_completion


class P0HorseCareerHistoryTests(TestCase):
    def setUp(self):
        self.term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Career Test Horse",
            target_zh="生涯测试马",
            racing_region=RacingRegion.UNITED_KINGDOM,
            is_active=True,
        )
        self.profile = HorseProfile.objects.create(
            primary_term=self.term,
            display_name_zh="生涯测试马",
            original_name="Career Test Horse",
            racing_region=RacingRegion.UNITED_KINGDOM,
            review_status=HorseProfileStatus.PUBLISHED,
        )

    def _payload(self, *, day=1, source_name="official", source_url=None, **overrides):
        payload = {
            "race_name": f"Race {day}",
            "race_name_normalized": f"Race {day}",
            "race_date": date(2024, 1, day).isoformat(),
            "racecourse": "Ascot",
            "race_number": str(day),
            "distance_text": "1600m",
            "result_status": HorseRaceResultStatus.UNPLACED,
            "finish_position": "5",
            "source_name": source_name,
            "source_url": source_url or f"https://example.com/{source_name}/{day}",
        }
        payload.update(overrides)
        return payload

    def test_abnormal_results_use_actual_start_semantics(self):
        statuses = [
            HorseRaceResultStatus.WON,
            HorseRaceResultStatus.DID_NOT_FINISH,
            HorseRaceResultStatus.DISQUALIFIED,
            HorseRaceResultStatus.SCRATCHED,
            HorseRaceResultStatus.WITHDRAWN,
        ]
        for day, status in enumerate(statuses, start=1):
            upsert_race_record(self.profile, self._payload(day=day, result_status=status))

        evaluation = refresh_career_history_completeness(
            self.profile,
            official_or_source_start_count=3,
            verified_at=timezone.now(),
        )

        self.assertEqual(evaluation.status, HorseCareerHistoryStatus.COMPLETE)
        self.assertEqual(evaluation.collected_start_count, 3)
        self.assertEqual(evaluation.unlinked_race_record_count, 5)
        self.assertEqual(
            list(self.profile.race_records.order_by("race_date").values_list("start_status", flat=True)),
            [
                HorseRaceStartStatus.STARTED,
                HorseRaceStartStatus.STARTED,
                HorseRaceStartStatus.STARTED,
                HorseRaceStartStatus.DID_NOT_START,
                HorseRaceStartStatus.DID_NOT_START,
            ],
        )

    def test_unknown_result_stays_unconfirmed_and_blocks_completeness(self):
        record = upsert_race_record(
            self.profile,
            self._payload(result_status=HorseRaceResultStatus.UNKNOWN),
        ).record

        evaluation = refresh_career_history_completeness(
            self.profile,
            official_or_source_start_count=0,
        )

        self.assertEqual(record.start_status, HorseRaceStartStatus.UNCONFIRMED)
        self.assertEqual(evaluation.status, HorseCareerHistoryStatus.NEEDS_REVIEW)
        self.assertIn(f"record:{record.id}:start_status_unconfirmed", evaluation.gap_reasons)

    def test_cross_source_overseas_duplicate_merges_and_keeps_both_sources(self):
        first = upsert_race_record(
            self.profile,
            self._payload(
                source_name="sporting_life",
                source_url="https://sporting.example/race/1",
                external_race_id="sl-1",
                is_overseas=True,
            ),
        )
        second_payload = self._payload(
            source_name="france_galop",
            source_url="https://france.example/race/99",
            external_race_id="fg-99",
            distance_text="1 mile",
            is_overseas=True,
        )
        second = upsert_race_record(self.profile, second_payload)
        corrected_second_payload = {
            **second_payload,
            "race_name": "Corrected foreign race name",
            "race_name_normalized": "Corrected foreign race name",
            "race_number": "",
            "distance_text": "8 furlongs",
            "external_result_id": "fg-result-99",
        }
        upsert_race_record(self.profile, corrected_second_payload)

        self.assertEqual(first.record.id, second.record.id)
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=self.profile).count(), 1)
        second.record.refresh_from_db()
        self.assertEqual(second.record.distance_text, "1600m")
        self.assertEqual(len(second.record.source_refs["sources"]), 2)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.deduplicated_source_record_count, 1)
        self.assertEqual(self.profile.overseas_start_count, 1)

    def test_distance_units_do_not_merge_without_other_strong_identity(self):
        base = self._payload(race_number="", distance_text="1600m")
        other = self._payload(
            race_number="",
            distance_text="1 mile",
            source_name="second_source",
            source_url="https://example.com/second/1",
        )

        upsert_race_record(self.profile, base)
        upsert_race_record(self.profile, other)

        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=self.profile).count(), 2)

    def test_unlinked_record_is_later_linked_without_duplicate(self):
        original = upsert_race_record(self.profile, self._payload()).record
        event = RaceEvent.objects.create(
            year=2024,
            slug="career-test-race",
            original_name="Race 1",
            chinese_name="生涯测试赛",
            country_region=RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="",
            surface="turf",
            local_date=date(2024, 1, 1),
            visibility_status=RaceEventVisibility.PUBLISHED,
        )
        result = RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            horse_name=self.profile.original_name,
        )

        linked = upsert_race_record(
            self.profile,
            self._payload(
                event_id=event.id,
                result_id=result.id,
                source_name="second_source",
                source_url="https://example.com/second/1",
            ),
        ).record

        self.assertEqual(linked.id, original.id)
        self.assertEqual(linked.event_id, event.id)
        self.assertEqual(linked.result_id, result.id)
        self.assertEqual(HorseRaceRecord.objects.filter(horse_profile=self.profile).count(), 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.linked_race_event_count, 1)
        self.assertEqual(self.profile.unlinked_race_record_count, 0)

    def test_full_profile_requires_independent_complete_career_status(self):
        for field_name, value in {
            "country": "GB",
            "sex": "M",
            "color": "Bay",
            "birth_date": date(2020, 1, 1),
            "owner_name": "Owner",
            "trainer_name": "Trainer",
            "breeder_name": "Breeder",
            "sire_text": "Sire",
            "dam_text": "Dam",
            "sire_sire_text": "Sire Sire",
            "sire_dam_text": "Sire Dam",
            "dam_sire_text": "Dam Sire",
            "dam_dam_text": "Dam Dam",
        }.items():
            setattr(self.profile, field_name, value)
        self.profile.racing_career_status = HorseRacingCareerStatus.RETIRED
        self.profile.records_synced_through = date(2024, 1, 1)
        self.profile.save()
        HorseP0Source.objects.create(
            profile=self.profile,
            source_type=HorseP0SourceType.MANUAL,
            source_url="https://example.com/horse",
        )
        upsert_race_record(
            self.profile,
            self._payload(result_status=HorseRaceResultStatus.WON),
        )

        partial = evaluate_full_profile_completeness(self.profile, require_review=False)
        refresh_career_history_completeness(self.profile, official_or_source_start_count=1)
        complete = evaluate_full_profile_completeness(self.profile, require_review=False)

        self.assertFalse(partial.is_complete)
        self.assertIn("race_history.career_status.partial", partial.blocking_reasons)
        self.assertTrue(complete.is_complete)

    def test_dry_run_reports_career_history_counts_without_network(self):
        upsert_race_record(self.profile, self._payload())
        refresh_career_history_completeness(
            self.profile,
            official_or_source_start_count=1,
            verified_at=timezone.now(),
        )

        plan = plan_profile_completion(
            CompletionOptions(regions=[RacingRegion.UNITED_KINGDOM], limit=1)
        )

        career = plan["rows"][0]["career_history"]
        self.assertEqual(career["official_or_source_start_count"], 1)
        self.assertEqual(career["collected_start_count"], 1)
        self.assertEqual(career["gap_count"], 0)
        self.assertEqual(plan["summary"]["career_history"]["collected_start_count_total"], 1)


class P0HorseCareerHistoryPageTests(TestCase):
    def setUp(self):
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.ENGLISH,
            source_ja="Paged Career Horse",
            target_zh="分页履历马",
            racing_region=RacingRegion.UNITED_STATES,
            is_active=True,
        )
        self.profile = HorseProfile.objects.create(
            primary_term=term,
            display_name_zh="分页履历马",
            original_name="Paged Career Horse",
            racing_region=RacingRegion.UNITED_STATES,
            review_status=HorseProfileStatus.PUBLISHED,
        )
        for index in range(25):
            race_date = date(2024, 1, 1) + timedelta(days=index)
            upsert_race_record(
                self.profile,
                {
                    "race_name": f"Ordinary Race {index + 1}",
                    "race_date": race_date.isoformat(),
                    "racecourse": "Belmont",
                    "race_number": str(index + 1),
                    "distance_text": "1 mile",
                    "result_status": HorseRaceResultStatus.UNPLACED,
                    "source_name": "equibase",
                    "source_url": f"https://example.com/equibase/{index + 1}",
                },
            )

    def test_public_page_paginates_all_records_in_both_orders(self):
        url = reverse("public-horse-detail", args=[self.profile.id])

        first_page = self.client.get(url)
        second_page = self.client.get(url, {"records_page": 2})
        ascending = self.client.get(url, {"records_order": "asc"})

        self.assertEqual(first_page.context["race_records_page"].paginator.count, 25)
        self.assertEqual(len(first_page.context["race_records"]), 20)
        self.assertEqual(len(second_page.context["race_records"]), 5)
        self.assertContains(first_page, "records_page=2")
        self.assertEqual(first_page.context["race_records"][0].race_name, "Ordinary Race 25")
        self.assertEqual(ascending.context["race_records"][0].race_name, "Ordinary Race 1")

    def test_unlinked_ordinary_race_displays_snapshot_without_event_link(self):
        response = self.client.get(reverse("public-horse-detail", args=[self.profile.id]))

        self.assertContains(response, "Ordinary Race 25")
        self.assertContains(response, "Belmont")
        self.assertNotContains(response, "/races/2024/")
