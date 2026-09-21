from stable import test_race_multisource_identity as fixtures
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
from django.test import TestCase, override_settings
from stable import models
from stable.test_race_multisource_identity import policy_payload, NOW
from stable.services.race_data_source_adapters import (
    parse_multisource_policy,
    fetch_bound_observation,
    run_multisource_claim,
)
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_control import claim_due_enrollments
from stable.services.race_pre_race import baseline, parse_jra_card

CARD = "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0106202604061120260920/D6"
RESULT = (
    "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0106202604061120260920/92"
)


@override_settings(
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_SCHEDULER_ENABLED=True,
    RACE_DATA_SYNC_ALLOW_NETWORK=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
    RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True,
    RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
    RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result",),
)
class JraColdStartTests(TestCase):
    def setUp(self):
        fixtures.IdentityTests.setUp(self)
        self.event.original_name = "産経賞オールカマー"
        self.event.save()
        root = Path(__file__).parent / "fixtures/jra_pre_race"
        self.card = (root / "all_comers_official_card.html").read_text()
        self.result = (root / "all_comers_official_result.html").read_text()
        payload = parse_jra_card(self.card, event=self.event, url=CARD)
        self.candidate = models.RaceEventDataCandidate.objects.create(
            event=self.event,
            module="runners",
            source_name="jra_pre_race_v1",
            source_url=CARD,
            candidate_payload=payload,
            raw_payload={
                "jra_pre_race_v1": {
                    "validated": True,
                    "baseline": baseline(self.event),
                    "raw_sha256": "d" * 64,
                    "stage": "numbered",
                }
            },
            fetched_at=NOW - timedelta(days=1),
        )
        self.policy = parse_multisource_policy(policy_payload(), now=NOW)
        self.loader = patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=self.policy,
        )
        self.loader.start()
        self.addCleanup(self.loader.stop)
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        if url == CARD:
            return self.card
        if url == RESULT:
            return self.result
        raise AssertionError(url)

    def enroll(self):
        value = fetch_bound_observation(
            event=self.event, route=self.policy.routes[0], now=NOW, fetcher=self.fetch
        )
        self.assertEqual(value["result_phase"], "official")
        decision = attach_multisource_observation(value, policy=self.policy, now=NOW)
        self.assertEqual(decision.action, "acquired", decision)

    def claim(self):
        return claim_due_enrollments(
            now=NOW,
            batch_size=20,
            ttl_seconds=240,
            enabled_providers=("jra",),
            enabled_regions=("japan_jra",),
            enabled_data_kinds=("result",),
        )[0]

    def test_cold_start_result_only_full_chain(self):
        self.enroll()
        self.assertEqual(models.RaceEventIdentityKey.objects.count(), 1)
        self.assertEqual(self.event.runners.count(), 0)
        result = run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)
        self.assertTrue(result["processed"], result)
        self.event.refresh_from_db()
        self.assertEqual(
            (self.event.status, self.event.results.count(), self.event.runners.count()),
            ("finished", 13, 13),
        )
        self.assertIsNotNone(self.event.result_confirmed_at)
        self.assertEqual(models.RaceEventRevisionPublication.objects.count(), 1)

    def test_stale_old_baseline_cannot_seed(self):
        self.event.original_name = "other"
        self.event.save()
        with self.assertRaisesMessage(ValueError, "source_identity_missing"):
            fetch_bound_observation(
                event=self.event,
                route=self.policy.routes[0],
                now=NOW,
                fetcher=self.fetch,
            )
        self.assertEqual(self.calls, [])

    def test_public_read_survives_write_disabled_and_binding_expiry(self):
        from stable.services.race_events import resolve_race_live_public_read

        self.enroll()
        result = run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)
        self.assertTrue(result["processed"], result)
        self.event.refresh_from_db()
        with override_settings(
            RACE_DATA_MULTISOURCE_APPLY_ENABLED=False,
            RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_SYNC_RESULT_APPLY_ENABLED=False,
        ):
            decision = resolve_race_live_public_read(
                event_id=self.event.pk, now=NOW + timedelta(days=40)
            )
        self.assertTrue(decision.visible, decision)

    def test_late_discovery_does_not_stop_at_start_or_t_plus_five(self):
        from stable.services.race_data_sync_enrollment import (
            discover_multisource_events,
        )

        self.event.race_datetime = NOW - timedelta(hours=1)
        self.event.save()
        result = discover_multisource_events(
            now=NOW, policy=self.policy, fetcher=self.fetch
        )
        self.assertEqual(result["coverage"]["counts"]["enrollment_missing"], 1)
        self.assertEqual(models.RaceDataSyncEnrollment.objects.count(), 1, result)

    def test_partial_result_never_bootstraps_half_roster(self):
        self.enroll()
        self.result = self.result.replace("</html>", "")
        result = run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)
        self.assertFalse(result["processed"])
        self.assertEqual(self.event.runners.count(), 0)
        self.assertEqual(self.event.results.count(), 0)

    def test_complete_html_with_missing_runner_does_not_publish(self):
        from bs4 import BeautifulSoup

        self.enroll()
        soup = BeautifulSoup(self.result, "html.parser")
        soup.select("tbody > tr")[-1].decompose()
        self.result = str(soup)
        result = run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)
        self.assertFalse(result["processed"], result)
        self.assertEqual(self.event.runners.count(), 0)
        self.assertEqual(self.event.results.count(), 0)

    def test_explicit_source_block_hides_published_result(self):
        from stable.services.race_events import resolve_race_live_public_read

        self.enroll()
        self.assertTrue(
            run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)[
                "processed"
            ]
        )
        source = models.RaceResultSourceIdentity.objects.get(event=self.event)
        source.terms_status = "blocked"
        source.automation_allowed = False
        source.save()
        decision = resolve_race_live_public_read(event_id=self.event.pk, now=NOW)
        self.assertFalse(decision.visible, decision)

    def test_bootstrap_cannot_replace_horse_using_same_number(self):
        self.enroll()
        self.result = self.result.replace("メイショウゲキリン", "まったく別の馬")
        result = run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)
        self.assertFalse(result["processed"], result)
        self.assertFalse(self.event.runners.exists())

    def test_cancellation_after_claim_cannot_be_overwritten(self):
        self.enroll()
        claim = self.claim()
        self.event.status = "cancelled"
        self.event.save()
        result = run_multisource_claim(claim=claim, now=NOW, fetcher=self.fetch)
        self.assertFalse(result["processed"], result)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, "cancelled")
        self.assertFalse(self.event.results.exists())

    def test_expired_discovery_lease_cannot_attach(self):
        value = fetch_bound_observation(
            event=self.event, route=self.policy.routes[0], now=NOW, fetcher=self.fetch
        )
        self.event.source_refs = {
            "source_discovery_v2": {
                "token": "old",
                "lease_until": (NOW - timedelta(seconds=1)).isoformat(),
            }
        }
        self.event.save()
        decision = attach_multisource_observation(
            value, policy=self.policy, now=NOW, discovery_token="old"
        )
        self.assertEqual(decision.reason_code, "discovery_lease_stale")
        self.assertFalse(models.RaceDataSyncEnrollment.objects.exists())

    def test_card_and_schedule_use_bound_source_writer(self):
        from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS

        before = NOW - timedelta(hours=1)
        self.clock.stop()
        self.clock = patch("django.utils.timezone.now", return_value=before)
        self.clock.start()
        self.event.race_datetime = NOW - timedelta(minutes=15)
        self.event.save()
        policy = parse_multisource_policy(
            policy_payload(kinds=("race_time", "racecard")), now=before
        )
        self.loader.stop()
        self.loader = patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=policy,
        )
        self.loader.start()
        with override_settings(
            RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED=True,
            RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard"),
            RACE_DATA_SYNC_ENABLED_FIELDS=tuple(_ROSTER_ALLOWED_FIELDS),
        ):
            value = fetch_bound_observation(
                event=self.event,
                route=policy.routes[0],
                now=before,
                fetcher=self.fetch,
                kind="racecard",
            )
            decision = attach_multisource_observation(value, policy=policy, now=before)
            self.assertEqual(decision.action, "acquired", decision)
            claims = claim_due_enrollments(
                now=before,
                batch_size=20,
                ttl_seconds=240,
                enabled_providers=("jra",),
                enabled_regions=("japan_jra",),
                enabled_data_kinds=("race_time", "racecard"),
            )
            self.assertEqual(len(claims), 1)
            result = run_multisource_claim(
                claim=claims[0], now=before, fetcher=self.fetch
            )
            self.assertTrue(result["processed"], result)
        self.assertEqual(self.event.runners.count(), 13)
        self.assertFalse(self.event.results.exists())

    def test_formal_number_slot_is_not_stable_horse_identity(self):
        self.enroll()
        value = fetch_bound_observation(
            event=self.event, route=self.policy.routes[0], now=NOW, fetcher=self.fetch
        )
        for row in value["roster"]:
            models.RaceEventRunner.objects.create(
                event=self.event,
                horse_name=row["horse_name"],
                horse_number=row["number"],
                source_refs={"jra": row["external_runner_id"]},
            )
        self.result = self.result.replace("メイショウゲキリン", "まったく別の馬")
        result = run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)
        self.assertFalse(result["processed"], result)
        self.assertFalse(self.event.results.exists())

    def test_new_source_set_does_not_reuse_stale_observation_authority(self):
        from copy import deepcopy
        from stable.services.race_data_sync_results import DataSyncResultApplyDecision

        payload = policy_payload()
        other = deepcopy(payload["routes"][0])
        other.update(provider="alternate", identity_namespace="alternate-race-v1")
        payload["routes"].append(other)
        self.policy = parse_multisource_policy(payload, now=NOW)
        self.loader.stop()
        self.loader = patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=self.policy,
        )
        self.loader.start()
        with override_settings(RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra", "alternate")):
            self.enroll()
            with patch(
                "stable.services.race_data_sync_results.apply_data_sync_result_observation",
                return_value=DataSyncResultApplyDecision("rejected", "injected"),
            ):
                self.assertFalse(
                    run_multisource_claim(
                        claim=self.claim(), now=NOW, fetcher=self.fetch
                    )["processed"]
                )
            value = fetch_bound_observation(
                event=self.event,
                route=self.policy.routes[0],
                now=NOW,
                fetcher=self.fetch,
            )
            value.update(provider="alternate", identity_namespace="alternate-race-v1")
            self.assertEqual(
                attach_multisource_observation(
                    value, policy=self.policy, now=NOW
                ).action,
                "attached",
            )
            later = NOW + timedelta(hours=1)
            with patch("django.utils.timezone.now", return_value=later):
                claims = claim_due_enrollments(
                    now=later,
                    batch_size=20,
                    ttl_seconds=240,
                    enabled_providers=("jra",),
                    enabled_regions=("japan_jra",),
                    enabled_data_kinds=("result",),
                )
                self.assertEqual(len(claims), 1)
                result = run_multisource_claim(
                    claim=claims[0], now=later, fetcher=self.fetch
                )
            self.assertTrue(result["processed"], result)
        self.assertEqual(models.RaceResultObservation.objects.count(), 2)
        self.assertEqual(models.RaceEventRevisionPublication.objects.count(), 1)

    def test_publication_failure_rolls_back_whole_bootstrap(self):
        self.enroll()
        with patch(
            "stable.models.RaceEventRevisionPublication.objects.create",
            side_effect=RuntimeError("publication_injected"),
        ):
            result = run_multisource_claim(
                claim=self.claim(), now=NOW, fetcher=self.fetch
            )
        self.assertFalse(result["processed"], result)
        for model in (
            models.RaceEventRunner,
            models.RaceEventResult,
            models.RaceEventRevision,
            models.RaceEventParticipant,
            models.RaceEventRevisionPublication,
        ):
            self.assertEqual(model.objects.count(), 0, model)

    def test_late_preview_retained_until_formal_roster_takes_over(self):
        from stable.services.race_pre_race import public_jra_preview

        self.event.race_datetime = NOW - timedelta(hours=1)
        self.event.save()
        with override_settings(
            RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
            RACE_DATA_SYNC_ENABLED_FIELDS=("participants.horse_name",),
        ):
            preview = public_jra_preview(self.event, now=NOW)
            self.assertIsNotNone(preview)
            self.assertEqual(len(preview["rows"]), 13)
            with override_settings(RACE_DATA_MULTISOURCE_APPLY_ENABLED=False):
                self.assertIsNone(public_jra_preview(self.event, now=NOW))
            models.RaceEventRunner.objects.create(
                event=self.event, horse_name="Formal", horse_number="1"
            )
            self.assertIsNone(public_jra_preview(self.event, now=NOW))

    @override_settings(
        RACE_DATA_SYNC_RACECARD_APPLY_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_DATA_KINDS=("racecard",),
        RACE_DATA_SYNC_ENABLED_FIELDS=(
            "participants.horse_name",
            "participants.number",
            "participants.draw",
            "participants.status",
            "participants.jockey_name",
            "participants.trainer_name",
            "participants.carried_weight",
        ),
    )
    def _check_card_slot_change(self, *, reviewed):
        policy = parse_multisource_policy(policy_payload(kinds=("racecard",)), now=NOW)
        self.event.race_datetime = NOW + timedelta(hours=1)
        self.event.save()
        self.candidate.raw_payload["jra_pre_race_v1"]["baseline"] = baseline(self.event)
        self.candidate.save()
        with patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=policy,
        ):
            value = fetch_bound_observation(
                event=self.event,
                route=policy.routes[0],
                now=NOW,
                fetcher=self.fetch,
                kind="racecard",
            )
            attach_multisource_observation(value, policy=policy, now=NOW)

            def claim(at):
                return claim_due_enrollments(
                    now=at,
                    batch_size=20,
                    ttl_seconds=240,
                    enabled_providers=("jra",),
                    enabled_regions=("japan_jra",),
                    enabled_data_kinds=("racecard",),
                )[0]

            first = run_multisource_claim(claim=claim(NOW), now=NOW, fetcher=self.fetch)
            self.assertTrue(first["processed"], first)
            runners = list(self.event.runners.order_by("pk"))
            before = [(r.horse_name, r.trainer_name) for r in runners]
            target = runners[-1]
            self.card = self.card.replace(target.horse_name, "まったく別の馬")
            if runners[0].trainer_name:
                self.card = self.card.replace(runners[0].trainer_name, "別の調教師", 1)
            if reviewed:
                source = models.RaceResultSourceIdentity.objects.get(
                    event=self.event, source_key="jra"
                )
                source.identity_fields["reviewed_runner_crosswalk"] = {
                    "event_id": self.event.pk,
                    "evidence_sha256": "e" * 64,
                    "runners": {target.external_runner_id: target.pk},
                }
                source.save(update_fields=("identity_fields",))
            later = NOW + timedelta(minutes=11)
            with patch("django.utils.timezone.now", return_value=later):
                result = run_multisource_claim(
                    claim=claim(later), now=later, fetcher=self.fetch
                )
            self.assertEqual(result["processed"], reviewed, result)
            self.assertEqual(self.event.runners.count(), 13)
            if reviewed:
                target.refresh_from_db()
                self.assertEqual(target.horse_name, "まったく別の馬")
            else:
                self.assertEqual(
                    list(
                        self.event.runners.order_by("pk").values_list(
                            "horse_name", "trainer_name"
                        )
                    ),
                    before,
                )
                self.assertTrue(
                    models.RaceEventFieldChange.objects.filter(
                        event=self.event,
                        rejection_reason="runner_identity_mapping_required",
                        applied=False,
                    ).exists()
                )

    def test_number_replacement(self):
        self._check_card_slot_change(reviewed=False)

    def test_reviewed_card_crosswalk_allows_name_change(self):
        self._check_card_slot_change(reviewed=True)

    def test_result_not_due_before_start(self):
        self.event.race_datetime = NOW + timedelta(hours=2)
        self.event.save()
        self.candidate.raw_payload["jra_pre_race_v1"]["baseline"] = baseline(self.event)
        self.candidate.save()
        value = fetch_bound_observation(
            event=self.event,
            route=self.policy.routes[0],
            now=NOW,
            fetcher=self.fetch,
            kind="racecard",
        )
        attach_multisource_observation(value, policy=self.policy, now=NOW)
        opening = self.event.race_datetime + timedelta(minutes=3)
        checkpoint = models.RaceEventLiveProviderCheckpoint.objects.get(
            tracking__event=self.event, data_kind="result"
        )
        self.assertEqual(checkpoint.next_poll_at, opening)
        # 历史/故障路径即使错误把checkpoint提前，selector也必须重新约束窗口。
        for at in (NOW, NOW + timedelta(minutes=5), opening - timedelta(seconds=1)):
            checkpoint.next_poll_at = at
            checkpoint.save()
            models.RaceEventLiveTracking.objects.filter(event=self.event).update(
                next_poll_at=at
            )
            with patch("django.utils.timezone.now", return_value=at):
                claims = claim_due_enrollments(
                    now=at,
                    batch_size=20,
                    ttl_seconds=240,
                    enabled_providers=("jra",),
                    enabled_regions=("japan_jra",),
                    enabled_data_kinds=("result",),
                )
            self.assertEqual(claims, ())
            checkpoint.refresh_from_db()
            self.assertEqual(checkpoint.next_poll_at, opening)
            self.assertEqual(checkpoint.consecutive_failures, 0)
        with patch("django.utils.timezone.now", return_value=opening):
            claims = claim_due_enrollments(
                now=opening,
                batch_size=20,
                ttl_seconds=240,
                enabled_providers=("jra",),
                enabled_regions=("japan_jra",),
                enabled_data_kinds=("result",),
            )
        self.assertEqual(len(claims), 1)

    def test_date_only_result_opens_on_local_race_day(self):
        from stable.services.race_data_sync_control import multisource_initial_poll_at
        from datetime import datetime
        from zoneinfo import ZoneInfo

        self.event.race_datetime = None
        self.event.local_date = (NOW + timedelta(days=1)).date()
        opening = datetime.combine(
            self.event.local_date,
            datetime.min.time(),
            tzinfo=ZoneInfo(self.event.timezone_name),
        )
        self.assertEqual(
            multisource_initial_poll_at(event=self.event, kind="result", now=NOW),
            opening,
        )
        self.assertEqual(
            multisource_initial_poll_at(event=self.event, kind="result", now=opening),
            opening,
        )

    def _check_result_correction(
        self, *, explicit, field="finish_time", value_text="2:09.9", unchanged=False
    ):
        self.enroll()
        self.event.race_datetime = NOW - timedelta(minutes=15)
        self.event.save()
        first = run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)
        self.assertTrue(first["processed"], first)
        self.event.refresh_from_db()
        control = models.RaceEventProjectionControl.objects.get(event=self.event)
        current = control.current_result_revision_id
        value = fetch_bound_observation(
            event=self.event, route=self.policy.routes[0], now=NOW, fetcher=self.fetch
        )
        value["result_phase"] = "corrected" if explicit else "official"
        if not unchanged:
            value["roster"][0][field] = value_text
        later = NOW + timedelta(hours=6, minutes=1)
        value["fetched_at"] = later.isoformat()
        with patch("django.utils.timezone.now", return_value=later):
            claim = claim_due_enrollments(
                now=later,
                batch_size=20,
                ttl_seconds=240,
                enabled_providers=("jra",),
                enabled_regions=("japan_jra",),
                enabled_data_kinds=("result",),
            )[0]
            with patch(
                "stable.services.race_data_source_adapters.fetch_bound_observation",
                return_value=value,
            ):
                result = run_multisource_claim(
                    claim=claim, now=later, fetcher=self.fetch
                )
        control.refresh_from_db()
        published_correction = explicit and not unchanged
        self.assertEqual(result["processed"], explicit or unchanged, result)
        self.assertEqual(
            control.current_result_revision_id != current, published_correction
        )
        self.assertEqual(
            models.RaceEventRevisionPublication.objects.count(),
            2 if published_correction else 1,
        )
        if unchanged:
            self.assertEqual(self.event.revisions.count(), 1)
            self.assertEqual(
                models.RaceEventRevisionEvidence.objects.filter(
                    role="supporting"
                ).count(),
                1 if explicit else 0,
            )
        if published_correction:
            from stable.services.race_events import resolve_race_live_public_read

            public = resolve_race_live_public_read(event_id=self.event.pk, now=later)
            self.assertTrue(public.visible, public)
            self.assertTrue(self.event.results.filter(**{field: value_text}).exists())

    def test_explicit_correction(self):
        self._check_result_correction(explicit=True)

    def test_changed_official_result_does_not_invent_correction(self):
        self._check_result_correction(explicit=False)

    def test_jockey_name_explicit_correction(self):
        self._check_result_correction(
            explicit=True, field="jockey_name", value_text="Corrected Jockey"
        )

    def test_jockey_name_unmarked_conflict(self):
        self._check_result_correction(
            explicit=False, field="jockey_name", value_text="Corrected Jockey"
        )

    def test_trainer_name_explicit_correction(self):
        self._check_result_correction(
            explicit=True, field="trainer_name", value_text="Corrected Trainer"
        )

    def test_trainer_name_unmarked_conflict(self):
        self._check_result_correction(
            explicit=False, field="trainer_name", value_text="Corrected Trainer"
        )

    def test_carried_weight_explicit_correction(self):
        self._check_result_correction(
            explicit=True, field="carried_weight", value_text="57.5"
        )

    def test_carried_weight_unmarked_conflict(self):
        self._check_result_correction(
            explicit=False, field="carried_weight", value_text="57.5"
        )

    def test_barrier_explicit_correction(self):
        self._check_result_correction(explicit=True, field="barrier", value_text="14")

    def test_barrier_unmarked_conflict(self):
        self._check_result_correction(explicit=False, field="barrier", value_text="14")

    @override_settings(RACE_DATA_COVERAGE_ALERTS_ENABLED=True)
    def test_unknown_timezone_does_not_block_valid_event_discovery(self):
        from stable.services.race_data_sync_enrollment import (
            discover_multisource_events,
        )

        invalid = models.RaceEvent.objects.get(pk=self.event.pk)
        invalid.pk = None
        invalid.slug = "missing-timezone"
        invalid.timezone_name = ""
        invalid.save()
        result = discover_multisource_events(
            now=NOW, policy=self.policy, fetcher=self.fetch
        )
        self.assertEqual(result["coverage"]["counts"]["missing_timezone"], 1)
        self.assertTrue(
            models.RaceDataSyncEnrollment.objects.filter(event=self.event).exists()
        )
        self.assertFalse(
            models.RaceDataSyncEnrollment.objects.filter(event=invalid).exists()
        )

    @override_settings(RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra", "alternate"))
    def test_same_result_crosslanguage_alternate(self):
        from stable.services.race_data_sync_control import finish_multisource_claim

        payload = policy_payload()
        payload["routes"] += policy_payload("alternate")["routes"]
        self.policy = parse_multisource_policy(payload, now=NOW)
        with patch(
            "stable.services.race_data_source_adapters.load_multisource_policy",
            return_value=self.policy,
        ):
            self.enroll()
            self.event.race_datetime = NOW - timedelta(minutes=15)
            self.event.save()
            self.assertTrue(
                run_multisource_claim(claim=self.claim(), now=NOW, fetcher=self.fetch)[
                    "processed"
                ]
            )
            self.event.refresh_from_db()
            value = fetch_bound_observation(
                event=self.event,
                route=self.policy.routes[0],
                now=NOW,
                fetcher=self.fetch,
            )
            value.update(provider="alternate", identity_namespace="alternate-race-v1")
            for r in value["roster"]:
                r["external_runner_id"] = "alt:" + r["number"]
                r["horse_name"] = "English Horse " + r["number"]
                r["jockey_name"] = "English Rider " + r["number"]
                r["trainer_name"] = "English Trainer " + r["number"]
            result = attach_multisource_observation(value, policy=self.policy, now=NOW)
            self.assertEqual(result.action, "attached")
            source = models.RaceResultSourceIdentity.objects.get(
                event=self.event, source_key="alternate"
            )
            source.identity_fields["reviewed_runner_crosswalk"] = {
                "event_id": self.event.pk,
                "evidence_sha256": "e" * 64,
                "runners": {
                    "alt:" + r.horse_number: r.pk for r in self.event.runners.all()
                },
            }
            source.save()
            later = NOW + timedelta(hours=6, minutes=1)
            value["fetched_at"] = later.isoformat()

            def claim():
                return claim_due_enrollments(
                    now=later,
                    batch_size=20,
                    ttl_seconds=240,
                    enabled_providers=("jra", "alternate"),
                    enabled_regions=("japan_jra",),
                    enabled_data_kinds=("result",),
                )[0]

            with patch("django.utils.timezone.now", return_value=later):
                a = claim()
                self.assertEqual(a.checkpoint_plan[0]["source_key"], "jra")
                finish_multisource_claim(
                    claim=a, now=later, success=False, reason_code="http_403"
                )
                b = claim()
                self.assertEqual(b.checkpoint_plan[0]["source_key"], "alternate")
                with patch(
                    "stable.services.race_data_source_adapters.fetch_bound_observation",
                    return_value=value,
                ):
                    result = run_multisource_claim(
                        claim=b, now=later, fetcher=self.fetch
                    )
            self.assertTrue(result["processed"], result)
            self.assertEqual(models.RaceEventRevisionPublication.objects.count(), 1)

            self.assertEqual(self.event.revisions.count(), 1)

    def test_identical_official_result_reuses_observation_without_republication(self):
        self._check_result_correction(explicit=False, unchanged=True)

    def test_identical_corrected_result_adds_evidence_without_republication(self):
        self._check_result_correction(explicit=True, unchanged=True)
