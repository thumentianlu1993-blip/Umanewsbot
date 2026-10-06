"""A032 独立合成输入；必须由 ROOT 分配的隔离 PostgreSQL 执行。"""
import hashlib
import json
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from stable.models import (
    HorseProfile, HorseProfileCandidateStatus, HorseProfileDataCandidate,
    HorseProfileStatus, HorseRaceRecord, OperationLog, TermEntry,
)
from stable.services.horse_basic_profile_from_cache import apply_basic_profile_from_cache
from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.services.horse_source_cache_reuse_adapter import adapt_hkjc_source_cache
from stable.test_horse_target_inventory import document, event, identity, row


FIXTURE = Path(__file__).parent / "fixtures/h03_basic_profile/hkjc_synthetic.json"
FIELDS = ("country", "sex", "color", "birth_date", "owner_name", "trainer_name", "breeder_name")


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 3, tzinfo=timezone.utc)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class BasicProfileFromCacheFixture:
    """每项首个正向写入断言会揭示 no-op stub，不把导入错误当 RED。"""

    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            raise AssertionError("A032 requires ROOT-allocated isolated PostgreSQL")
        self.actor = get_user_model().objects.create_user(username="a032-synthetic-actor")
        self.term = TermEntry.objects.create(
            term_type="horse", source_language="en", source_ja="HARBOUR TEST",
            target_zh="", racing_region="hong_kong",
        )
        self.profile = HorseProfile.objects.create(
            primary_term=self.term, original_name="HARBOUR TEST", racing_region="hong_kong",
            source_refs={"horse_identity_verified_keys": ["hkjc:hk-001"]},
        )
        self.clock = patch("stable.services.p0_horse_completion_source_clients.datetime", FrozenDateTime)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        for target in (
            "urllib.request.urlopen",
            "stable.services.p0_horse_completion_adapters.run_p0_horse_completion_adapter",
            "stable.services.p0_horse_completion_source_clients._HKJCClient._fetch",
            "stable.services.horse_profile_publish.auto_publish_profiles",
            "stable.services.horse_profiles.transition_review_status",
            "stable.services.horse_profiles.upsert_race_record",
        ):
            guard = patch(target, side_effect=AssertionError("producer/publication/career forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def request(self, *, version="a032-v1", payload=None):
        raw = FIXTURE.read_bytes() if payload is None else (
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        digest = hashlib.sha256(raw).hexdigest()
        snapshot = document()
        snapshot.update(
            events=[event(region="hong_kong")],
            participations=[row(horse_key="hkjc:HK-001", birth_year=2020)],
            identities=[identity("hkjc:HK-001", profile=self.profile.pk)],
        )
        record = adapt_hkjc_source_cache(
            raw, expected_sha256=digest, ref="cache:a032", source_ref="fixture:a032",
        )
        versions = {f"profile:{self.profile.pk}": version}
        planned = plan_cache_reuse(
            snapshot, [record], versions, as_of="2026-10-03T01:00:00Z",
            max_age_seconds=77 * 86400 + 3600,
        )
        self.assertEqual(planned["decisions"][0]["status"], "reusable", "fixture must be reusable before business RED")
        self.profile.refresh_from_db()
        return dict(
            snapshot=snapshot, candidate=deepcopy(planned["candidates"][0]), raw_bytes=raw,
            expected_sha256=digest, ref="cache:a032", source_ref="fixture:a032",
            entity_versions=versions, as_of="2026-10-03T01:00:00Z",
            max_age_seconds=77 * 86400 + 3600,
            expected_updated_at=self.profile.updated_at, actor=self.actor,
        )

    def counts(self):
        return (HorseProfileDataCandidate.objects.count(), OperationLog.objects.count(),
                HorseProfile.objects.count(), HorseRaceRecord.objects.count(), TermEntry.objects.count())

    def assert_applied(self, request=None):
        request = request or self.request()
        result = apply_basic_profile_from_cache(**request)
        self.profile.refresh_from_db()
        # This assertion, rather than import/signature errors, is the designated RED.
        self.assertEqual(self.profile.country, "AUS", "H03 must actually persist seven basic fields")
        self.assertEqual(result["status"], "applied")
        return result

    def assert_blocked_without_writes(self, request):
        self.profile.refresh_from_db()
        before = deepcopy(HorseProfile.objects.values().get(pk=self.profile.pk))
        counts = self.counts()
        result = apply_basic_profile_from_cache(**request)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(HorseProfile.objects.values().get(pk=self.profile.pk), before)
        self.assertEqual(self.counts(), counts)


class BasicProfileFromCacheTests(BasicProfileFromCacheFixture, TransactionTestCase):
    def test_persists_seven_fields_and_json_safe_date_without_publication(self):
        request = self.request()
        result = self.assert_applied(request)
        expected = json.loads(request["raw_bytes"])["basic_profile"]
        expected["birth_date"] = date.fromisoformat(expected["birth_date"])
        self.assertEqual({field: getattr(self.profile, field) for field in FIELDS}, expected)
        candidate = HorseProfileDataCandidate.objects.get(profile=self.profile)
        self.assertEqual(candidate.status, HorseProfileCandidateStatus.APPLIED)
        self.assertEqual(candidate.candidate_payload["birth_date"], "2020-09-14")
        json.dumps(candidate.diff_payload, allow_nan=False)
        self.assertEqual(candidate.confidence, 0)
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1))
        self.assertFalse(result["published"])
        self.assertEqual(self.profile.review_status, HorseProfileStatus.DRAFT)
        self.assertIsNone(self.profile.published_at)
        self.assertEqual(self.profile.display_name, "HARBOUR TEST")
        self.assertEqual(self.profile.display_name_zh, "")
        self.assertEqual(self.profile.sire_text, "")
        self.assertEqual(self.profile.source_refs, {"horse_identity_verified_keys": ["hkjc:hk-001"]})
        self.term.refresh_from_db()
        self.assertEqual(self.term.target_zh, "")

    def test_existing_date_diff_is_json_safe(self):
        self.profile.birth_date = date(2020, 1, 1)
        self.profile.save(update_fields=["birth_date", "updated_at"])
        self.assert_applied()
        c = HorseProfileDataCandidate.objects.get(profile=self.profile)
        serialized = json.dumps(c.diff_payload, allow_nan=False)
        self.assertIn("2020-01-01", serialized)
        self.assertIn("2020-09-14", serialized)

    def test_original_request_replay_after_real_field_change_is_zero_write(self):
        request = self.request()
        self.assert_applied(request)
        self.assertNotEqual(self.profile.updated_at, request["expected_updated_at"])
        before = deepcopy(HorseProfile.objects.values().get(pk=self.profile.pk))
        counts = self.counts()
        result = apply_basic_profile_from_cache(**request)
        self.assertEqual(result["status"], "already_applied")
        self.assertEqual(HorseProfile.objects.values().get(pk=self.profile.pk), before)
        self.assertEqual(self.counts(), counts)

    def test_new_key_old_baseline_is_blocked(self):
        original = self.request()
        self.assert_applied(original)
        new = self.request(version="a032-v2")
        new["expected_updated_at"] = original["expected_updated_at"]
        self.assert_blocked_without_writes(new)

    def test_consumed_key_changed_content_is_blocked(self):
        self.assert_applied()
        payload = json.loads(FIXTURE.read_bytes())
        payload["basic_profile"]["owner_name"] = "Other Synthetic Owner"
        self.assert_blocked_without_writes(self.request(payload=payload))

    def test_field_lock_preserves_manual_owner(self):
        self.profile.owner_name = "Manual Owner"
        self.profile.manual_lock_flags = {"owner_name": True}
        self.profile.save(update_fields=["owner_name", "manual_lock_flags", "updated_at"])
        self.assert_applied()
        self.assertEqual(self.profile.owner_name, "Manual Owner")

    def test_module_lock_consumes_once_without_overwrite_after_unlock(self):
        self.profile.manual_lock_flags = {"profile": True}
        self.profile.save(update_fields=["manual_lock_flags", "updated_at"])
        request = self.request()
        first = apply_basic_profile_from_cache(**request)
        self.assertEqual(first["status"], "applied")
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.country, "")
        self.profile.manual_lock_flags = {}
        self.profile.save(update_fields=["manual_lock_flags", "updated_at"])
        counts = self.counts()
        second = apply_basic_profile_from_cache(**request)
        self.assertEqual(second["status"], "already_applied")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.country, "")
        self.assertEqual(self.counts(), counts)

    def test_flat_identity_key_is_insufficient(self):
        request = self.request()
        self.profile.source_refs = {"horse_identity_keys": ["hkjc:hk-001"]}
        self.profile.save(update_fields=["source_refs", "updated_at"])
        request["expected_updated_at"] = self.profile.updated_at
        self.assert_blocked_without_writes(request)

    def test_public_or_hidden_target_is_blocked(self):
        for status in (HorseProfileStatus.PUBLISHED, HorseProfileStatus.HIDDEN):
            with self.subTest(status=status):
                self.profile.review_status = status
                self.profile.save(update_fields=["review_status", "updated_at"])
                self.assert_blocked_without_writes(self.request())

    def test_tampered_candidate_and_bytes_are_blocked(self):
        for kind in ("candidate", "bytes"):
            with self.subTest(kind=kind):
                request = self.request()
                if kind == "candidate":
                    request["candidate"]["entity_key"] = "profile:999999"
                else:
                    request["raw_bytes"] += b" "
                self.assert_blocked_without_writes(request)

    def test_identity_drift_still_blocks_consumed_replay(self):
        request = self.request()
        self.assert_applied(request)
        self.profile.source_refs = {"horse_identity_verified_keys": ["hkjc:other"]}
        self.profile.save(update_fields=["source_refs", "updated_at"])
        self.assert_blocked_without_writes(request)

    def test_log_failure_rolls_back_profile_and_candidate(self):
        request = self.request()
        before = deepcopy(HorseProfile.objects.values().get(pk=self.profile.pk))
        counts = self.counts()
        with patch("stable.services.horse_profiles.log_operation", side_effect=RuntimeError("synthetic log failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic log failure"):
                apply_basic_profile_from_cache(**request)
        self.assertEqual(HorseProfile.objects.values().get(pk=self.profile.pk), before)
        self.assertEqual(self.counts(), counts)

    def test_existing_writer_is_used(self):
        from stable.services.horse_profiles import apply_data_candidate
        with patch("stable.services.horse_profiles.apply_data_candidate", wraps=apply_data_candidate) as writer:
            self.assert_applied()
        self.assertEqual(writer.call_count, 1)

    def test_duplicate_verified_key_on_other_profile_blocks(self):
        request = self.request()
        other = TermEntry.objects.create(term_type="horse", source_ja="OTHER SYNTHETIC")
        HorseProfile.objects.create(primary_term=other, source_refs={"horse_identity_verified_keys": ["hkjc:hk-001"]})
        self.assert_blocked_without_writes(request)


class BasicProfileCacheConcurrencyTests(BasicProfileFromCacheFixture, TransactionTestCase):
    """只显式选此 method；继承 fixture，PG 确认实际锁等待而非仅同时启动。"""

    def test_second_identical_request_waits_then_returns_already_applied(self):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections, connections
        from stable.services.horse_profiles import apply_data_candidate

        request = self.request()
        first_in_writer = threading.Event()
        release_first = threading.Event()
        second_pid = []
        local = threading.local()

        def paused_writer(*args, **kwargs):
            if getattr(local, "first", False):
                first_in_writer.set()
                if not release_first.wait(10):
                    raise AssertionError("first writer release timeout")
            return apply_data_candidate(*args, **kwargs)

        def invoke(first):
            close_old_connections()
            local.first = first
            try:
                if not first:
                    with connections["default"].cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        second_pid.append(cursor.fetchone()[0])
                return apply_basic_profile_from_cache(**request)
            finally:
                connections["default"].close()

        with patch("stable.services.horse_profiles.apply_data_candidate", side_effect=paused_writer):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(invoke, True)
                try:
                    self.assertTrue(first_in_writer.wait(5), "H03 must reach existing business writer under profile lock")
                    second = pool.submit(invoke, False)
                    deadline = time.monotonic() + 5
                    lock_seen = False
                    while time.monotonic() < deadline and not second.done():
                        if second_pid:
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [second_pid[0]])
                                current = cursor.fetchone()
                                lock_seen = bool(current and current[0] == "Lock")
                                if lock_seen:
                                    break
                        time.sleep(0.02)
                    self.assertTrue(lock_seen, "must observe real PostgreSQL lock wait")
                finally:
                    release_first.set()
                self.assertEqual(first.result(timeout=10)["status"], "applied")
                self.assertEqual(second.result(timeout=10)["status"], "already_applied")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.country, "AUS")
        self.assertEqual(self.counts(), (1, 1, 1, 0, 1))
