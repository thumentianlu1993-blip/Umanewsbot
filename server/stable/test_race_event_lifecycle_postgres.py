"""
Phase A: PostgreSQL-specific concurrency tests.

Run only against isolated PostgreSQL.  Requires environment:
    DB_ENGINE=postgres  DB_NAME=test_umanews_lifecycle  …

Each test closes connections after use to prevent session leaks.
"""

import threading
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection, connections
from django.test import TransactionTestCase
from django.utils import timezone as django_timezone

from stable import models as stable_models
from stable.services import race_event_lifecycle


# ── helpers ──────────────────────────────────────────────────────────

def _pg_only(test_method):
    def wrapper(self, *args, **kwargs):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL")
        return test_method(self, *args, **kwargs)
    return wrapper


def _close_thread_conn():
    """Close all connections in this thread, ensuring clean test teardown."""
    connections.close_all()


def _make_event(**kwargs):
    defaults = dict(
        year=2026,
        slug=f"pg-{kwargs.get('slug','x')}",
        original_name="PG Test",
        chinese_name="PG测试",
        country_region="japan",
        racecourse="PG Racecourse",
        grade_text="G1",
        normalized_grade="G1",
        surface="turf",
        status="scheduled",
        priority="P0",
        visibility_status="published",
        race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        timezone_name="Asia/Tokyo",
    )
    defaults.update(kwargs)
    return stable_models.RaceEvent.objects.create(**defaults)


def _make_control(event, **kwargs):
    defaults = dict(
        mode="enforce",
        next_refresh_at=django_timezone.now() - timedelta(minutes=5),
        schedule_generation=1,
    )
    defaults.update(kwargs)
    return stable_models.RaceEventLifecycleControl.objects.create(
        event=event, **defaults
    )


# ── concurrency tests ───────────────────────────────────────────────

class RaceEventLifecyclePostgresConcurrencyTests(TransactionTestCase):
    """Real PostgreSQL: two workers via threads, one effective update.
    Uses TransactionTestCase so threads with separate connections can see
    committed rows."""

    @_pg_only
    def test_two_workers_concurrent_enforce(self):
        """Two threads racing to enforce; only one writes applied transition."""
        now = datetime(2026, 6, 1, 6, 30, 0, tzinfo=dt_timezone.utc)
        event = _make_event(
            slug="dual-enforce",
            race_datetime=datetime(2026, 6, 1, 6, 0, 0, tzinfo=dt_timezone.utc),
        )
        ctrl = _make_control(
            event, mode="enforce",
            next_refresh_at=now - timedelta(minutes=5),
        )

        # Scanner claims the event
        claims = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now, batch_size=10, ttl_seconds=240,
        )
        self.assertGreaterEqual(len(claims), 1)
        claim = [c for c in claims if c.event_id == event.id][0]

        results = []
        errors = []

        def worker():
            _close_thread_conn()
            from django.db import transaction as tx
            try:
                with tx.atomic():
                    r = race_event_lifecycle.apply_race_lifecycle_decision(
                        event_id=event.id,
                        expected_generation=claim.schedule_generation,
                        now=now,
                        mode="enforce",
                        attempt_token=claim.attempt_token,
                        expected_claim_generation=claim.claim_generation,
                    )
                results.append(r)
            except Exception as e:
                errors.append(str(e))
            finally:
                _close_thread_conn()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0, f"thread errors: {errors}")
        applied = [r for r in results if r.action == "applied"]
        self.assertEqual(
            len(applied), 1,
            f"expected 1 applied, got {[(r.action, r.error) for r in results]}"
        )

        # Verify from a fresh connection
        _close_thread_conn()
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
        applied_count = stable_models.RaceEventLifecycleTransition.objects.filter(
            event=event, record_kind="applied"
        ).count()
        self.assertEqual(applied_count, 1)

    @_pg_only
    def test_skip_locked_claimers_get_disjoint_sets(self):
        """Two concurrent claimers receive non-overlapping event sets."""
        now = django_timezone.now()
        for i in range(10):
            e = _make_event(slug=f"sl-{i}")
            _make_control(
                e, mode="shadow",
                next_refresh_at=now - timedelta(minutes=1),
            )

        claimed_sets: list[set] = []

        def claimer():
            _close_thread_conn()
            try:
                c = race_event_lifecycle.claim_due_lifecycle_controls(
                    now=now + timedelta(minutes=1),
                    batch_size=10,
                    ttl_seconds=240,
                )
                claimed_sets.append({x.event_id for x in c})
            finally:
                _close_thread_conn()

        t1 = threading.Thread(target=claimer)
        t2 = threading.Thread(target=claimer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        all_claimed = set()
        for s in claimed_sets:
            all_claimed |= s
        self.assertEqual(
            len(all_claimed), 10,
            f"skip_locked overlap: sets={[sorted(s) for s in claimed_sets]}"
        )


class RaceEventLifecyclePostgresClaimTests(TransactionTestCase):
    """Claim lifecycle: expiry, active, generation staleness."""

    @_pg_only
    def test_expired_claim_reclaimed(self):
        event = _make_event(slug="expired")
        past = django_timezone.now() - timedelta(minutes=10)
        ctrl = _make_control(
            event, mode="enforce",
            next_refresh_at=past - timedelta(minutes=5),
        )
        ctrl.claim_token = "expired-abc"
        ctrl.claim_expires_at = past
        ctrl.claim_generation = 1
        ctrl.save()

        now = django_timezone.now()
        claims = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now, batch_size=10, ttl_seconds=240,
        )
        self.assertIn(event.id, {c.event_id for c in claims})

    @_pg_only
    def test_active_claim_excluded(self):
        event = _make_event(slug="active")
        future = django_timezone.now() + timedelta(minutes=20)
        ctrl = _make_control(
            event, mode="enforce",
            next_refresh_at=django_timezone.now() - timedelta(minutes=1),
        )
        ctrl.claim_token = "held-by-another"
        ctrl.claim_expires_at = future
        ctrl.claim_generation = 5
        ctrl.save()

        now = django_timezone.now()
        claims = race_event_lifecycle.claim_due_lifecycle_controls(
            now=now, batch_size=10, ttl_seconds=240,
        )
        self.assertNotIn(event.id, {c.event_id for c in claims})

    @_pg_only
    def test_stale_generation_rejected_and_applied_after_reclaim(self):
        """Stale generation is rejected; fresh claim proceeds."""
        from django.db import transaction as tx

        event = _make_event(
            slug="gen-stale",
            race_datetime=datetime(2026, 7, 1, 15, 0, 0, tzinfo=dt_timezone.utc),
        )
        _make_control(event, mode="enforce", schedule_generation=5)
        now = event.race_datetime + timedelta(minutes=30)

        with tx.atomic():
            result = race_event_lifecycle.apply_race_lifecycle_decision(
                event_id=event.id,
                expected_generation=3,  # stale
                now=now,
                mode="enforce",
            )
        self.assertTrue(
            result.action == "generation_stale" or result.error,
            f"expected generation_stale, got action={result.action} error={result.error}",
        )
        _close_thread_conn()
        event.refresh_from_db()
        self.assertEqual(event.status, "scheduled")

        # Fresh generation proceeds
        with tx.atomic():
            result2 = race_event_lifecycle.apply_race_lifecycle_decision(
                event_id=event.id,
                expected_generation=5,
                now=now,
                mode="enforce",
            )
        self.assertEqual(result2.action, "applied")
        _close_thread_conn()
        event.refresh_from_db()
        self.assertEqual(event.status, "finished")
