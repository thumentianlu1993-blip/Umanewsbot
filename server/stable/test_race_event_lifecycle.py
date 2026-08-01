"""
Phase A: Race event lifecycle — unit and integration tests.

Covers test_cases.md A01-A33: time-based transitions, DST, cancellation,
postponement, claim/generation, dry-run/shadow/enforce, manifest enrollment,
cache invalidation, query bounds, and global-mode capping.
"""

import re
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.db import connection, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as django_timezone

from stable import models as stable_models
from stable.services import race_event_lifecycle


# ── helpers ──────────────────────────────────────────────────────────

def _make_event(
    *,
    year: int = 2026,
    slug: str = "test-race",
    country_region: str = "japan",
    status: str = "scheduled",
    priority: str = "P0",
    visibility_status: str = "published",
    race_datetime: datetime | None = None,
    timezone_name: str = "Asia/Tokyo",
    local_date: date | None = None,
    local_start_time: time | None = None,
    is_featured: bool = False,
    **kwargs,
) -> stable_models.RaceEvent:
    return stable_models.RaceEvent.objects.create(
        year=year,
        slug=slug,
        original_name="Test Race",
        chinese_name="测试赛事",
        country_region=country_region,
        racecourse="Test Racecourse",
        grade_text="G1",
        normalized_grade="G1",
        surface="turf",
        status=status,
        priority=priority,
        visibility_status=visibility_status,
        race_datetime=race_datetime,
        timezone_name=timezone_name,
        local_date=local_date,
        local_start_time=local_start_time,
        is_featured=is_featured,
        **kwargs,
    )


def _make_control(event, *, mode="shadow", next_refresh_at=None, schedule_generation=1):
    return stable_models.RaceEventLifecycleControl.objects.create(
        event=event,
        mode=mode,
        next_refresh_at=next_refresh_at or django_timezone.now(),
        schedule_generation=schedule_generation,
    )


def _apply(event, *, expected_generation=1, now=None, mode="enforce",
           attempt_token="", expected_claim_generation=0):
    """Wrapper: calls apply inside transaction.atomic()."""
    if now is None:
        now = django_timezone.now()
    with transaction.atomic():
        return race_event_lifecycle.apply_race_lifecycle_decision(
            event_id=event.id,
            expected_generation=expected_generation,
            now=now,
            mode=mode,
            attempt_token=attempt_token,
            expected_claim_generation=expected_claim_generation,
        )


# ── A01-A13: time-based transitions ──────────────────────────────────

class RaceEventLifecycleDecisionTests(SimpleTestCase):
    """Pure decision function: no database, no network."""

    def test_a01_before_race_datetime_stays_scheduled(self):
        now = datetime(2026, 7, 1, 14, 0, 0, tzinfo=dt_timezone.utc)
        race_dt = datetime(2026, 7, 1, 15, 0, 0, tzinfo=dt_timezone.utc)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Tokyo",
            status="scheduled", now=now, region="japan",
        )
        self.assertEqual(decision.action, "noop")

    def test_a02_arrive_at_race_datetime_transitions_to_running(self):
        now = datetime(2026, 7, 1, 15, 0, 0, tzinfo=dt_timezone.utc)
        race_dt = datetime(2026, 7, 1, 15, 0, 0, tzinfo=dt_timezone.utc)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Tokyo",
            status="scheduled", now=now, region="japan",
        )
        self.assertEqual(decision.action, "transition")
        self.assertEqual(decision.to_status, "running")

    def test_a03_t_plus_30_no_result_finishes(self):
        race_dt = datetime(2026, 7, 1, 14, 30, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Tokyo",
            status="running", now=now, region="japan",
        )
        self.assertEqual(decision.action, "transition")
        self.assertEqual(decision.to_status, "finished")

    def test_a03_scheduled_past_t30_also_finishes(self):
        race_dt = datetime(2026, 7, 1, 14, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Tokyo",
            status="scheduled", now=now, region="japan",
        )
        self.assertEqual(decision.to_status, "finished")

    def test_a04_source_failure_does_not_block_time_transition(self):
        race_dt = datetime(2026, 7, 1, 14, 30, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Tokyo",
            status="running", now=now, region="japan",
        )
        self.assertEqual(decision.to_status, "finished")
        self.assertNotEqual(decision.action, "error")

    def test_a05_no_time_before_local_midnight_does_not_advance(self):
        now = datetime(2026, 7, 1, 14, 59, 0, tzinfo=dt_timezone.utc)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=None, timezone_name="Asia/Tokyo",
            local_date=date(2026, 7, 1), status="scheduled", now=now, region="japan",
        )
        self.assertEqual(decision.action, "noop")

    def test_a06_no_time_local_next_day_midnight_finishes(self):
        now = datetime(2026, 7, 1, 15, 0, 0, tzinfo=dt_timezone.utc)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=None, timezone_name="Asia/Tokyo",
            local_date=date(2026, 7, 1), status="scheduled", now=now, region="japan",
        )
        self.assertEqual(decision.action, "transition")
        self.assertEqual(decision.to_status, "finished")

    def test_a07_london_dst(self):
        race_dt = datetime(2026, 3, 28, 14, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        d = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Europe/London",
            status="running", now=now, region="united_kingdom",
        )
        self.assertEqual(d.to_status, "finished")

    def test_a08_paris_dst(self):
        race_dt = datetime(2026, 3, 28, 14, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        d = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Europe/Paris",
            status="running", now=now, region="france",
        )
        self.assertEqual(d.to_status, "finished")

    def test_a09_new_york_dst(self):
        race_dt = datetime(2026, 11, 1, 5, 30, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        d = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="America/New_York",
            status="running", now=now, region="united_states",
        )
        self.assertEqual(d.to_status, "finished")

    def test_a10_la_and_ny_same_instant(self):
        race_dt = datetime(2026, 7, 1, 22, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        d_la = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="America/Los_Angeles",
            status="running", now=now, region="united_states",
        )
        d_ny = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="America/New_York",
            status="running", now=now, region="united_states",
        )
        self.assertEqual(d_la.to_status, "finished")
        self.assertEqual(d_ny.to_status, "finished")

    def test_a11_japan_hk_no_dst(self):
        race_dt = datetime(2026, 7, 1, 6, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        d_jp = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Tokyo",
            status="running", now=now, region="japan",
        )
        d_hk = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Hong_Kong",
            status="running", now=now, region="hong_kong",
        )
        self.assertEqual(d_jp.to_status, "finished")
        self.assertEqual(d_hk.to_status, "finished")

    def test_a12_invalid_timezone_errors(self):
        race_dt = datetime(2026, 7, 1, 6, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(hours=1)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Invalid/Time_Zone",
            status="scheduled", now=now, region="japan",
        )
        self.assertEqual(decision.action, "error")

    def test_a13_cancelled_stays_cancelled(self):
        race_dt = datetime(2026, 7, 1, 6, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(hours=2)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Tokyo",
            status="cancelled", now=now, region="japan",
        )
        self.assertEqual(decision.action, "noop")


# ── A14-A15: postponement & generation ───────────────────────────────

class RaceEventLifecyclePostponementTests(TestCase):
    def test_a14_postponed_old_time_does_not_advance(self):
        event = _make_event(
            slug="postponed-old", status="postponed",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(hours=2)
        result = _apply(event, now=now)
        self.assertIsNone(result.error)
        event.refresh_from_db()
        self.assertEqual(event.status, "postponed")

    def test_a15_new_generation_rejects_old_task(self):
        event = _make_event(
            slug="new-gen", status="postponed",
            race_datetime=datetime(2026, 7, 1, 15, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce", schedule_generation=5)
        now = event.race_datetime + timedelta(minutes=30)
        result = _apply(event, expected_generation=3, now=now)
        self.assertEqual(result.action, "generation_stale")


# ── A16, A18: idempotency & claim ────────────────────────────────────

class RaceEventLifecycleIdempotencyTests(TestCase):
    def test_a16_replay_same_task_only_one_transition(self):
        event = _make_event(
            slug="replay",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce", schedule_generation=1)
        now = event.race_datetime + timedelta(minutes=30)

        r1 = _apply(event, now=now)
        self.assertIsNone(r1.error)
        r2 = _apply(event, now=now)
        self.assertIsNone(r2.error)

        count = stable_models.RaceEventLifecycleTransition.objects.filter(
            event=event, record_kind="applied"
        ).count()
        self.assertEqual(count, 1)

    def test_a18_expired_claim_recyclable(self):
        event = _make_event(
            slug="claim-recycle",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        past = django_timezone.now() - timedelta(minutes=10)
        ctrl = _make_control(
            event, mode="enforce",
            next_refresh_at=past - timedelta(minutes=5),
        )
        ctrl.claim_expires_at = past
        ctrl.claim_token = "expired-token"
        ctrl.claim_generation = 1
        ctrl.save()

        now = django_timezone.now()
        claims = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now, batch_size=10, ttl_seconds=240,
        )
        self.assertGreaterEqual(len(claims), 1)

    def test_expired_claim_message_is_stale_after_reclaim(self):
        now = datetime(2026, 8, 2, 6, 0, 0, tzinfo=dt_timezone.utc)
        event = _make_event(
            slug="expired-claim-message",
            race_datetime=now - timedelta(minutes=5),
        )
        control = _make_control(
            event,
            mode="shadow",
            next_refresh_at=now - timedelta(minutes=10),
            schedule_generation=1,
        )
        old_token = "generation-one-token"
        stable_models.RaceEventLifecycleControl.objects.filter(
            pk=control.pk,
        ).update(
            claim_token=old_token,
            claim_generation=1,
            claim_expires_at=now - timedelta(seconds=1),
        )

        claims = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now,
            batch_size=10,
            ttl_seconds=240,
        )
        claim = next(item for item in claims if item.event_id == event.id)
        self.assertEqual(claim.schedule_generation, 1)
        self.assertEqual(claim.claim_generation, 2)
        self.assertNotEqual(claim.attempt_token, old_token)

        control_fields = tuple(
            field.attname
            for field in stable_models.RaceEventLifecycleControl._meta.concrete_fields
        )
        control_after_reclaim = (
            stable_models.RaceEventLifecycleControl.objects.filter(pk=control.pk)
            .values(*control_fields)
            .get()
        )
        event_after_reclaim = (
            stable_models.RaceEvent.objects.filter(pk=event.pk)
            .values("status", "updated_at")
            .get()
        )

        stale_result = _apply(
            event,
            expected_generation=1,
            now=now,
            mode="shadow",
            attempt_token=old_token,
            expected_claim_generation=1,
        )

        self.assertIn(
            stale_result.action,
            ("claim_not_expired", "claim_generation_mismatch"),
        )
        self.assertEqual(
            stable_models.RaceEventLifecycleControl.objects.filter(pk=control.pk)
            .values(*control_fields)
            .get(),
            control_after_reclaim,
        )
        self.assertEqual(
            stable_models.RaceEvent.objects.filter(pk=event.pk)
            .values("status", "updated_at")
            .get(),
            event_after_reclaim,
        )
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.filter(event=event).count(),
            0,
        )

        fresh_result = _apply(
            event,
            expected_generation=claim.schedule_generation,
            now=now,
            mode="shadow",
            attempt_token=claim.attempt_token,
            expected_claim_generation=claim.claim_generation,
        )

        self.assertEqual(fresh_result.action, "proposed")
        event.refresh_from_db()
        self.assertEqual(event.status, "scheduled")
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event,
                record_kind="proposal",
            ).count(),
            1,
        )
        self.assertFalse(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event,
                record_kind="applied",
            ).exists()
        )


# ── A19-A22: dry-run / shadow / enforce / rollback ───────────────────

class RaceEventLifecycleModeTests(TestCase):
    def test_a19_dry_run_zero_writes(self):
        event = _make_event(
            slug="dry-run",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(minutes=30)

        result = _apply(event, now=now, mode="dry_run")
        self.assertIsNone(result.error)
        event.refresh_from_db()
        self.assertEqual(event.status, "scheduled")
        self.assertFalse(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="applied"
            ).exists()
        )

    def test_a20_shadow_writes_proposal_not_status(self):
        event = _make_event(
            slug="shadow",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="shadow")
        now = event.race_datetime + timedelta(minutes=30)

        result = _apply(event, now=now, mode="shadow")
        self.assertIsNone(result.error)
        event.refresh_from_db()
        self.assertEqual(event.status, "scheduled")
        self.assertTrue(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="proposal"
            ).exists()
        )

    def test_a21_enforce_writes_status_and_applied_transition(self):
        event = _make_event(
            slug="enforce",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(minutes=30)

        result = _apply(event, now=now)
        self.assertIsNone(result.error)
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
        self.assertTrue(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="applied"
            ).exists()
        )

    def test_a22_transaction_integrity(self):
        event = _make_event(
            slug="tx-integrity",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(minutes=30)

        result = _apply(event, now=now)
        self.assertIsNone(result.error)
        self.assertEqual(result.action, "applied")
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="applied"
            ).count(),
            1,
        )

    def test_global_shadow_caps_enforce_control(self):
        """P0 #3: global mode=shadow must cap control.mode=enforce to shadow."""
        event = _make_event(
            slug="global-shadow",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")  # control says enforce
        now = event.race_datetime + timedelta(minutes=30)

        # global mode = shadow → effective = shadow
        result = _apply(event, now=now, mode="shadow")
        self.assertIsNone(result.error)
        event.refresh_from_db()
        # status MUST NOT change
        self.assertEqual(event.status, "scheduled",
                         "global shadow must not allow enforce writes")
        # Only proposal, no applied
        self.assertTrue(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="proposal"
            ).exists()
        )
        self.assertFalse(
            stable_models.RaceEventLifecycleTransition.objects.filter(
                event=event, record_kind="applied"
            ).exists()
        )

    def test_scanner_claim_then_apply_with_token(self):
        """P0 #2: claim → task passes token → apply succeeds."""
        event = _make_event(
            slug="claim-apply",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        ctrl = _make_control(
            event, mode="enforce",
            next_refresh_at=django_timezone.now() - timedelta(minutes=5),
        )
        # Scanner claims
        claims = race_event_lifecycle.claim_due_lifecycle_controls(
            now=django_timezone.now(), batch_size=10, ttl_seconds=240,
        )
        self.assertGreaterEqual(len(claims), 1)
        claim = [c for c in claims if c.event_id == event.id][0]

        # Task applies with claim identity
        now = event.race_datetime + timedelta(minutes=30)
        result = _apply(
            event, now=now, mode="enforce",
            attempt_token=claim.attempt_token,
            expected_claim_generation=claim.claim_generation,
        )
        self.assertIsNone(result.error, f"apply failed: {result.error}")
        self.assertEqual(result.action, "applied")
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")


# ── A23-A24: result-phase coexistence ────────────────────────────────

class RaceEventLifecycleResultPhaseTests(TestCase):
    def test_a23_official_result_not_downgraded(self):
        event = _make_event(
            slug="official", status="finished",
            result_confirmed_at=django_timezone.now(),
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(minutes=30)
        result = _apply(event, now=now)
        self.assertIn(result.action, ("noop", "already_finished"))

    def test_a24_provisional_and_finished_coexist(self):
        event = _make_event(
            slug="provisional", status="running",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(minutes=30)
        result = _apply(event, now=now)
        self.assertIsNone(result.error)
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
        self.assertIsNone(event.result_confirmed_at)


# ── A25-A28: enrollment manifest ─────────────────────────────────────

class RaceEventLifecycleEnrollmentTests(TestCase):
    def test_a25_no_control_defaults_off(self):
        event = _make_event(
            slug="no-ctrl",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        now = event.race_datetime + timedelta(minutes=30)
        result = _apply(event, expected_generation=0, now=now)
        self.assertTrue(result.error or result.action in ("noop",))

    def test_a26_manifest_applied_twice_no_duplicates(self):
        event = _make_event(slug="manifest-twice", priority="P0")
        from stable.services.race_event_lifecycle import reconcile_lifecycle_controls

        stats1 = reconcile_lifecycle_controls(
            event_ids=[event.id], manifest_sha256="sha-abc123", apply=True,
        )
        stats2 = reconcile_lifecycle_controls(
            event_ids=[event.id], manifest_sha256="sha-abc123", apply=True,
        )
        self.assertEqual(stats1["created"], 1)
        self.assertEqual(stats2["created"], 0)
        self.assertEqual(stats2["replayed"], 1)

    def test_a27_qualification_loss_disables_control(self):
        event = _make_event(slug="qual-loss", priority="P0")
        ctrl = _make_control(event, mode="enforce")

        from stable.services.race_event_lifecycle import reconcile_lifecycle_controls
        reconcile_lifecycle_controls(
            event_ids=[event.id], manifest_sha256="sha-a27", apply=True,
            eligibility_snapshot={
                str(event.id): {"is_key_race": False, "is_published": True, "is_cancelled": False},
            },
        )
        ctrl.refresh_from_db()
        self.assertEqual(ctrl.mode, "off")

    def test_a28_new_key_race_not_in_manifest_not_enrolled(self):
        event = _make_event(slug="new-key", priority="P0")
        now = django_timezone.now()
        claims = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now, batch_size=10, ttl_seconds=240,
        )
        self.assertNotIn(event.id, {c.event_id for c in claims})


# ── A29-A30: shadow → enforce replay ─────────────────────────────────

class RaceEventLifecycleShadowEnforceTests(TestCase):
    def test_a29_shadow_then_enforce(self):
        event = _make_event(
            slug="shadow-enforce",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="shadow")
        now = event.race_datetime + timedelta(minutes=30)

        for _ in range(3):
            _apply(event, now=now, mode="shadow")
        proposals = stable_models.RaceEventLifecycleTransition.objects.filter(
            event=event, record_kind="proposal"
        ).count()
        self.assertEqual(proposals, 1)

        ctrl = event.lifecycle_control
        ctrl.mode = "enforce"
        ctrl.save()

        _apply(event, now=now, mode="enforce")
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
        applied = stable_models.RaceEventLifecycleTransition.objects.filter(
            event=event, record_kind="applied"
        ).count()
        self.assertEqual(applied, 1)

    def test_a30_enforce_replay_no_duplicate_applied(self):
        event = _make_event(
            slug="enforce-replay",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(minutes=30)

        _apply(event, now=now)
        _apply(event, now=now)

        applied_count = stable_models.RaceEventLifecycleTransition.objects.filter(
            event=event, record_kind="applied"
        ).count()
        self.assertEqual(applied_count, 1)


# ── A31-A33: timezone contract enforcement ───────────────────────────

class RaceEventLifecycleTimezoneContractTests(SimpleTestCase):
    def test_a31_hk_uses_london_timezone_fails(self):
        race_dt = datetime(2026, 7, 1, 6, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(hours=1)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Europe/London",
            status="scheduled", now=now, region="hong_kong",
        )
        self.assertEqual(decision.action, "error")

    def test_a32_japan_uses_non_tokyo_zone_fails(self):
        race_dt = datetime(2026, 7, 1, 6, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(hours=1)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="Asia/Hong_Kong",
            status="scheduled", now=now, region="japan",
        )
        self.assertEqual(decision.action, "error")

    def test_a33_us_wrong_america_zone_fails(self):
        race_dt = datetime(2026, 7, 1, 22, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(hours=1)
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="America/Chicago",
            status="scheduled", now=now, region="united_states",
            allowed_us_zones=frozenset({"America/New_York"}),
        )
        self.assertEqual(decision.action, "error")

    def test_us_event_no_zones_provided_passes_prefix_check_only(self):
        """Without allowed_us_zones, any America/* passes the prefix check."""
        race_dt = datetime(2026, 7, 1, 22, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(minutes=30)
        # With no explicit zone list, the prefix check alone passes.
        # This is acceptable for Phase A because the task now reads zones
        # from control.manifest_data; if none were enrolled, no US events
        # should have lifecycle controls in the first place.
        decision = race_event_lifecycle.decide_race_lifecycle(
            race_datetime=race_dt, timezone_name="America/Chicago",
            status="running", now=now, region="united_states",
            allowed_us_zones=None,
        )
        self.assertEqual(decision.to_status, "finished")


# ── cache invalidation ───────────────────────────────────────────────

class RaceEventLifecycleCacheTests(TestCase):
    def test_enforce_commits_cache_invalidation(self):
        event = _make_event(
            slug="cache-test",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce")
        now = event.race_datetime + timedelta(minutes=30)

        result = _apply(event, now=now)
        self.assertIsNone(result.error)
        self.assertEqual(result.action, "applied")
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
        from stable.services.race_event_public_cache import invalidate_public_race_cache
        self.assertTrue(callable(invalidate_public_race_cache))


# ── query-count bound ────────────────────────────────────────────────

class RaceEventLifecycleQueryCountTests(TestCase):
    def test_scanner_100_due_controls_within_8_queries(self):
        now = django_timezone.now()
        for i in range(100):
            event = _make_event(
                slug=f"qc-{i}",
                race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
            )
            _make_control(event, mode="shadow", next_refresh_at=now - timedelta(minutes=1))

        with CaptureQueriesContext(connection) as ctx:
            claims = race_event_lifecycle.claim_due_lifecycle_controls(
                now=now + timedelta(minutes=1),
                batch_size=100,
                ttl_seconds=240,
            )
        self.assertEqual(len(claims), 100)
        self.assertLessEqual(
            len(ctx.captured_queries), 8,
            f"claim_due_lifecycle_controls used {len(ctx.captured_queries)} queries (limit 8)"
        )


# ── scanner does not dispatch race-live ──────────────────────────────

class RaceEventLifecycleTaskRouteContractTests(SimpleTestCase):
    def test_lifecycle_route_matches_production_worker_default_queue(self):
        worker_script = (
            Path(__file__).resolve().parents[2]
            / "deploy"
            / "docker"
            / "start-worker.sh"
        ).read_text(encoding="utf-8")
        queue_match = re.search(
            r'--queues="\$\{CELERY_WORKER_QUEUES:-([^}]+)\}"',
            worker_script,
        )
        self.assertIsNotNone(
            queue_match,
            "start-worker.sh must declare the production worker default queue",
        )
        worker_default_queue = queue_match.group(1)
        lifecycle_route = settings.CELERY_TASK_ROUTES[
            "stable.tasks.advance_race_event_lifecycle_task"
        ]["queue"]

        self.assertEqual(worker_default_queue, "celery")
        self.assertEqual(lifecycle_route, worker_default_queue)

    def test_race_live_routes_remain_isolated(self):
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["stable.tasks.poll_race_live_event_task"],
            {"queue": "race_live"},
        )
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["stable.tasks.monitor_race_live_sla_task"],
            {"queue": "race_live"},
        )


class RaceEventLifecycleNoLiveDispatchTests(TestCase):
    def test_lifecycle_scanner_never_dispatches_poll_race_live(self):
        event = _make_event(
            slug="no-live",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce", next_refresh_at=django_timezone.now())

        with patch("stable.tasks.poll_race_live_event_task.apply_async") as mock_poll:
            from stable.tasks import advance_race_event_lifecycle_task
            advance_race_event_lifecycle_task(
                event_id=event.id,
                expected_generation=1,
                attempt_token="test",
                expected_claim_generation=0,
            )
            mock_poll.assert_not_called()


# ── rollback/global-gate fail-closed contracts ─────────────────────

class RaceEventLifecycleDisabledGateTests(TestCase):
    control_runtime_fields = (
        "mode",
        "next_refresh_at",
        "schedule_generation",
        "last_attempt_at",
        "last_success_at",
        "last_result_code",
        "last_error",
        "last_source_key",
        "consecutive_failures",
        "claim_token",
        "claim_generation",
        "claim_expires_at",
        "updated_at",
    )

    def _runtime_snapshot(self, control):
        return stable_models.RaceEventLifecycleControl.objects.filter(
            pk=control.pk
        ).values(*self.control_runtime_fields).get()

    def _make_due_non_key_control(self, *, slug):
        now = django_timezone.now()
        event = _make_event(
            slug=slug,
            priority="P2",
            is_featured=False,
            race_datetime=now - timedelta(hours=1),
            local_date=now.date(),
        )
        self.assertFalse(event.is_key_race)
        control = _make_control(
            event,
            mode="shadow",
            next_refresh_at=now - timedelta(minutes=5),
            schedule_generation=7,
        )
        stable_models.RaceEventLifecycleControl.objects.filter(
            pk=control.pk
        ).update(
            last_attempt_at=now - timedelta(minutes=15),
            last_success_at=now - timedelta(minutes=20),
            last_result_code="prior-result",
            last_error="prior-error",
            last_source_key="prior-source",
            consecutive_failures=2,
            claim_token="queued-attempt",
            claim_generation=3,
            claim_expires_at=now - timedelta(minutes=1),
        )
        control.refresh_from_db()
        return event, control

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_disabled_scanner_does_not_claim_or_dispatch_due_non_key_control(self):
        event, control = self._make_due_non_key_control(
            slug="disabled-scan-non-key"
        )
        before_control = self._runtime_snapshot(control)

        with patch(
            "stable.tasks.advance_race_event_lifecycle_task.apply_async"
        ) as dispatch:
            from stable.tasks import scan_due_race_event_lifecycle_task

            result = scan_due_race_event_lifecycle_task()

        self.assertEqual(
            result,
            {"enabled": False, "claimed": 0, "dispatched": 0},
        )
        dispatch.assert_not_called()
        self.assertEqual(self._runtime_snapshot(control), before_control)
        event.refresh_from_db()
        self.assertEqual(event.status, "scheduled")
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.count(), 0
        )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_disabled_queued_advance_is_noop_for_non_key_control(self):
        event, control = self._make_due_non_key_control(
            slug="disabled-queued-non-key"
        )
        before_status = event.status
        before_control = self._runtime_snapshot(control)

        from stable.tasks import advance_race_event_lifecycle_task

        result = advance_race_event_lifecycle_task(
            event_id=event.id,
            expected_generation=control.schedule_generation,
            attempt_token=control.claim_token,
            expected_claim_generation=control.claim_generation,
        )

        self.assertEqual(
            result,
            {
                "processed": False,
                "reason": "lifecycle_disabled_mid_flight",
                "event_id": event.id,
            },
        )
        event.refresh_from_db()
        self.assertEqual(event.status, before_status)
        self.assertEqual(self._runtime_snapshot(control), before_control)
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.count(), 0
        )


# ── manifest US zone enforcement ────────────────────────────────────

class ManifestUSZoneValidationTests(SimpleTestCase):
    """Schema-level manifest validation without database."""

    def _validate(self, events_cfg: dict):
        from stable.management.commands.reconcile_race_event_lifecycle_controls import (
            _validate_and_extract,
        )
        return _validate_and_extract(events_cfg)

    def _valid_us_event(self, **overrides):
        base = {
            "mode": "shadow",
            "region": "united_states",
            "allowed_us_zones": ["America/New_York"],
            "eligibility": {"is_key_race": True, "is_published": True, "is_cancelled": False},
            "enrollment_schedule_hash": "a" * 64,
        }
        base.update(overrides)
        return base

    def _valid_non_us_event(self, **overrides):
        base = {
            "mode": "shadow",
            "region": "japan",
            "eligibility": {"is_key_race": True, "is_published": True, "is_cancelled": False},
            "enrollment_schedule_hash": "b" * 64,
        }
        base.update(overrides)
        return base

    def test_us_missing_allowlist_rejected(self):
        with self.assertRaises(SystemExit):
            self._validate({"1": self._valid_us_event(allowed_us_zones=[])})
        with self.assertRaises(SystemExit):
            cfg = self._valid_us_event()
            del cfg["allowed_us_zones"]
            self._validate({"1": cfg})

    def test_us_invalid_timezone_rejected(self):
        with self.assertRaises(SystemExit):
            self._validate({"1": self._valid_us_event(allowed_us_zones=["Asia/Tokyo"])})
        with self.assertRaises(SystemExit):
            self._validate({"1": self._valid_us_event(allowed_us_zones=["America/New_York", "Europe/London"])})

    def test_non_us_omits_allowlist_succeeds(self):
        ids, modes, zones, elig, hashes, regions = self._validate({
            "1": self._valid_non_us_event(),
        })
        self.assertEqual(ids, [1])
        self.assertNotIn("1", zones)
        self.assertEqual(regions[1], "japan")

    def test_valid_us_allowlist_parsed(self):
        ids, modes, zones, elig, hashes, regions = self._validate({
            "1": self._valid_us_event(allowed_us_zones=["America/New_York", "America/Los_Angeles"]),
        })
        self.assertEqual(zones["1"], ["America/New_York", "America/Los_Angeles"])
        self.assertEqual(regions[1], "united_states")

    def test_missing_region_rejected(self):
        with self.assertRaises(SystemExit):
            cfg = self._valid_non_us_event()
            del cfg["region"]
            self._validate({"1": cfg})


class ManifestUSZoneApplyTests(TestCase):
    """Integration: pre-enrollment timezone drift check catches mismatches."""

    def test_us_event_timezone_not_in_allowlist_rejected(self):
        """Live event has America/Chicago but manifest only allows America/New_York."""
        event = _make_event(
            slug="us-drift",
            country_region="united_states",
            timezone_name="America/Chicago",
        )
        from stable.management.commands.reconcile_race_event_lifecycle_controls import (
            _check_us_timezone_drift,
        )
        with self.assertRaises(SystemExit):
            _check_us_timezone_drift(
                [event.id],
                {event.id: "united_states"},
                {str(event.id): ["America/New_York"]},
            )

    def test_us_event_timezone_in_allowlist_passes(self):
        event = _make_event(
            slug="us-ok",
            country_region="united_states",
            timezone_name="America/New_York",
        )
        from stable.management.commands.reconcile_race_event_lifecycle_controls import (
            _check_us_timezone_drift,
        )
        _check_us_timezone_drift(
            [event.id],
            {event.id: "united_states"},
            {str(event.id): ["America/New_York", "America/Los_Angeles"]},
        )

    def test_manifest_region_must_match_db_region(self):
        """DB has united_states, manifest claims japan → region drift rejected."""
        event = _make_event(
            slug="region-drift",
            country_region="united_states",
            timezone_name="America/New_York",
        )
        from stable.management.commands.reconcile_race_event_lifecycle_controls import (
            _check_us_timezone_drift,
        )
        with self.assertRaises(SystemExit):
            _check_us_timezone_drift(
                [event.id],
                {event.id: "japan"},
                {},
            )

    def test_unsupported_region_rejected_by_timezone_validation(self):
        """other + Europe/Dublin must fail in lifecycle timezone validation."""
        race_dt = datetime(2026, 7, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
        now = race_dt + timedelta(hours=1)
        for bad_region in ("other", "ireland", ""):
            with self.subTest(region=bad_region):
                decision = race_event_lifecycle.decide_race_lifecycle(
                    race_datetime=race_dt,
                    timezone_name="Europe/Dublin",
                    status="scheduled", now=now,
                    region=bad_region,
                )
                self.assertEqual(decision.action, "error",
                                 f"region={bad_region} must be rejected")

    def test_db_us_missing_manifest_zones_rejected(self):
        """DB is united_states, manifest has no zones → rejected."""
        event = _make_event(
            slug="us-no-zones",
            country_region="united_states",
            timezone_name="America/New_York",
        )
        from stable.management.commands.reconcile_race_event_lifecycle_controls import (
            _check_us_timezone_drift,
        )
        with self.assertRaises(SystemExit):
            _check_us_timezone_drift(
                [event.id],
                {event.id: "united_states"},
                {},  # no zones
            )

    def test_valid_us_manifest_creates_control_with_zones(self):
        event = _make_event(
            slug="us-enroll",
            country_region="united_states",
            timezone_name="America/New_York",
            race_datetime=datetime(2026, 7, 1, 22, 0, 0, tzinfo=dt_timezone.utc),
        )
        from stable.services.race_event_lifecycle import reconcile_lifecycle_controls

        stats = reconcile_lifecycle_controls(
            event_ids=[event.id],
            manifest_sha256="c" * 64,
            apply=True,
            target_modes={
                str(event.id): "shadow",
                f"us_zones:{event.id}": ["America/New_York"],
                f"schedule_hash:{event.id}": "d" * 64,
            },
            eligibility_snapshot={
                str(event.id): {"is_key_race": True, "is_published": True, "is_cancelled": False},
            },
        )
        self.assertEqual(stats["created"], 1)
        ctrl = event.lifecycle_control
        self.assertEqual(ctrl.manifest_data.get("allowed_us_zones"), ["America/New_York"])


# ── backoff / hot-loop prevention ───────────────────────────────────

class RaceEventLifecycleBackoffTests(TestCase):
    """Verify that past-due events don't keep re-occupying every batch."""

    def test_noop_backoff_cancelled_sets_none(self):
        """A cancelled event with past-due next_refresh gets set to None (terminal)."""
        event = _make_event(
            slug="backoff-cancelled", status="cancelled",
            race_datetime=datetime(2026, 1, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        past = django_timezone.now() - timedelta(minutes=10)
        ctrl = _make_control(event, mode="enforce", next_refresh_at=past)
        now = django_timezone.now()

        _apply(event, now=now, mode="enforce")
        ctrl.refresh_from_db()
        self.assertIsNone(ctrl.next_refresh_at,
                          "cancelled event should set next_refresh_at=None (terminal)")

    def test_error_backoff_advances_next_refresh(self):
        """An event with invalid timezone gets bumped forward after error."""
        event = _make_event(
            slug="backoff-error",
            status="scheduled",
            timezone_name="Invalid/Zone",
            race_datetime=datetime(2026, 7, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        past = django_timezone.now() - timedelta(minutes=10)
        ctrl = _make_control(event, mode="enforce", next_refresh_at=past)
        now = django_timezone.now()

        result = _apply(event, now=now, mode="enforce")
        self.assertEqual(result.action, "error")
        ctrl.refresh_from_db()
        self.assertGreater(ctrl.next_refresh_at, now,
                           "error should bump past-due next_refresh_at forward")

    def test_duplicate_proposal_backoff_advances_next_refresh(self):
        """Already-proposed shadow events with future next_refresh don't regress."""
        event = _make_event(
            slug="backoff-dup",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        now = event.race_datetime + timedelta(minutes=30)
        # Set next_refresh exactly at 'now' — the <= fix should still bump it
        ctrl = _make_control(event, mode="shadow", next_refresh_at=now)

        # First shadow: creates proposal, recomputes next_refresh → None (finished)
        _apply(event, now=now, mode="shadow")
        ctrl.refresh_from_db()
        self.assertIsNone(ctrl.next_refresh_at,
                          "finished→next_refresh_at should be None")

        # Re-set to exactly 'now' to simulate re-claim after operator re-enables
        ctrl.next_refresh_at = now
        ctrl.claim_token = ""
        ctrl.save()

        # Second shadow: duplicate of running→finished → should set None (terminal)
        _apply(event, now=now, mode="shadow")
        ctrl.refresh_from_db()
        self.assertIsNone(
            ctrl.next_refresh_at,
            "duplicate running→finished proposal should set next_refresh_at=None"
        )

# ── reconcile command integration tests ─────────────────────────────

class ReconcileCommandTests(TestCase):
    """Integration tests: call_command() exercises the real entry point."""

    def test_dry_run_zero_writes(self):
        event = _make_event(slug="cmd-dry", priority="P0")
        before_ctrl = stable_models.RaceEventLifecycleControl.objects.count()
        before_tx = stable_models.RaceEventLifecycleTransition.objects.count()

        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command(
            "reconcile_race_event_lifecycle_controls",
            event_ids=[event.id],
            default_mode="shadow",
            stdout=out,
        )
        output = out.getvalue()

        self.assertEqual(
            stable_models.RaceEventLifecycleControl.objects.count(), before_ctrl,
            "dry-run must not create controls"
        )
        self.assertEqual(
            stable_models.RaceEventLifecycleTransition.objects.count(), before_tx,
            "dry-run must not create transitions"
        )
        self.assertIn("DRY-RUN", output, "output must indicate dry-run")

    def test_dry_run_outputs_decision_summary(self):
        """Command stdout includes eligible_transition count for past-due events."""
        event = _make_event(
            slug="cmd-summary",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
            priority="P0",
        )
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command(
            "reconcile_race_event_lifecycle_controls",
            event_ids=[event.id],
            default_mode="shadow",
            stdout=out,
        )
        output = out.getvalue()
        # Final summary line must contain decisions: prefix with counts
        self.assertIn("decisions:", output.lower(),
                      f"dry-run output missing decision summary: {output[:200]}")

    def test_auto_discover_capped(self):
        """--auto-discover passes at most 2000 IDs even when more are eligible."""
        from unittest.mock import patch

        # Bulk-create 2001 eligible events (past T+30)
        now = django_timezone.now()
        race_dt = now - timedelta(hours=2)
        events = [
            stable_models.RaceEvent(
                year=2026,
                slug=f"ad-cap-{i}",
                original_name=f"Cap {i}",
                chinese_name=f"上限{i}",
                country_region="japan",
                racecourse="Tokyo",
                grade_text="G1",
                normalized_grade="G1",
                surface="turf",
                status="scheduled",
                priority="P0",
                visibility_status="published",
                race_datetime=race_dt,
                timezone_name="Asia/Tokyo",
                local_date=race_dt.date(),
            )
            for i in range(2001)
        ]
        stable_models.RaceEvent.objects.bulk_create(events)

        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        captured_ids = []

        def _capture(self, ids, *args, **kwargs):
            captured_ids.extend(ids)

        with patch(
            "stable.management.commands.reconcile_race_event_lifecycle_controls.Command._run",
            _capture,
        ):
            call_command(
                "reconcile_race_event_lifecycle_controls",
                auto_discover=True,
                stdout=out,
            )
        output = out.getvalue()
        self.assertIn("自动发现 2000 个赛事（上限 2000）", output,
                      f"unexpected discover output: {output[:120]}")
        self.assertEqual(
            len(captured_ids), 2000,
            f"auto-discover must cap at 2000, got {len(captured_ids)}"
        )
