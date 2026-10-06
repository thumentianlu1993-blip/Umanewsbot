"""A039 冻结 prepare 原件→现有 H03 合同；只允许 ROOT 隔离 PG 窗口。"""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TransactionTestCase

from stable import models
from stable.services.horse_basic_profile_from_cache import BASIC_FIELDS, apply_basic_profile_from_cache
from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.services.horse_source_cache_reuse_adapter import adapt_hkjc_source_cache
from stable.services.p0_horse_completion_adapters import P0HorseCompletionRequest, REGION_ADAPTERS
from stable.test_horse_basic_profile_from_cache import FrozenDateTime


FIXTURE = Path(__file__).parent / "fixtures/h03_review_consumer"
# 独立于包自报摘要；来自 ROOT/R 冻结的 A037 原字节。
EXPECTED = {
    "packet.json": "111d004d7c886300ceb26c2445fd023e0e6ad4ceaab875c74ee73b1c858dbe26",
    "cache.json": "2ba3faa4706c64f4da1e8c0967713d51cc5cc776264cfccbc317e4638acec7bb",
    "manifest.json": "ca3feeab3d7fd85d84d9c9c3a117b84c8d376b804e64ee412020ba532aa4e1c2",
    "combined_candidates.jsonl": "cd5c98d797c54137828ce13c5416c911da2f92515457fa0fdff5afa804339dcb",
}


class FrozenPrepareConsumerContractTests(TransactionTestCase):
    """三个显式方法；不继承旧测试，不 mock 业务结果或审批能力。"""

    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql", "requires ROOT isolated PostgreSQL")
        self.assertTrue(str(connection.settings_dict["NAME"]).startswith("test_"))
        self.assertIn(connection.settings_dict["HOST"], ("127.0.0.1", "localhost", "/tmp"))
        self.raw = {}
        for name, digest in EXPECTED.items():
            self.raw[name] = (FIXTURE / name).read_bytes()
            self.assertEqual(hashlib.sha256(self.raw[name]).hexdigest(), digest)
        self.assertEqual(json.loads((FIXTURE / "frozen_sha256.json").read_bytes()), EXPECTED)
        decision = json.loads((FIXTURE / "synthetic_decision.json").read_bytes())
        self.assertIs(decision["synthetic_only"], True)
        self.assertEqual(decision["trusted_original_sha256"], EXPECTED)
        self.packet = json.loads(self.raw["packet.json"])
        self.manifest = json.loads(self.raw["manifest.json"])
        self.display = json.loads(self.raw["combined_candidates.jsonl"])
        self.assertIs(self.display["reviewed"], False)
        self.assertIs(self.manifest["reviewed"], False)
        self.assertEqual(self.manifest["status"], "local_pending_review")
        self.actor = get_user_model().objects.create_user(username="a039-synthetic-actor")
        self.term = models.TermEntry.objects.create(
            term_type="horse", source_language="en", source_ja="HARBOUR TEST",
            target_zh="", racing_region="hong_kong")
        self.profile = models.HorseProfile.objects.create(
            pk=1, primary_term=self.term, original_name="HARBOUR TEST", racing_region="hong_kong",
            source_refs={"horse_identity_verified_keys": ["hkjc:hk-001"]},
            manual_lock_flags={"pedigree": True})
        self.baseline = datetime.fromisoformat(self.packet["profile_baseline"])
        models.HorseProfile.objects.filter(pk=1).update(updated_at=self.baseline)
        self.profile.refresh_from_db()
        # 非空保护哨兵：不声明其为可用 career 授权，不调用 career writer。
        event = models.RaceEvent.objects.create(
            year=2025, edition_year=2025, slug="a039-synthetic-sentinel",
            original_name="Synthetic untouched event", country_region="hong_kong")
        models.HorseRaceRecord.objects.create(
            horse_profile=self.profile, event=event, race_name="Synthetic untouched record",
            race_date=date(2025, 12, 7), race_date_precision="exact")
        source = models.RaceResultSourceIdentity.objects.create(
            event=event, source_key="a039-synthetic", external_race_id="sentinel",
            region_code="hong_kong", identity_namespace="synthetic-only",
            automation_allowed=False, proof_network_allowed=False)
        enrollment = models.RaceDataSyncEnrollment.objects.create(
            event=event, source_identity=source, standing_policy_digest="a" * 64,
            route_digest="b" * 64, event_snapshot_sha256="c" * 64,
            manifest_sha256="d" * 64, entry_sha256="e" * 64)
        models.RaceDataSyncSourceBinding.objects.create(
            enrollment=enrollment, source_identity=source, state="quarantined", capabilities=[],
            route_digest="b" * 64, contract_digest="f" * 64, proof_digest="1" * 64,
            identity_evidence_sha256="2" * 64, binding_manifest={"synthetic_only": True},
            binding_manifest_sha256="3" * 64,
            valid_until=datetime(2026, 10, 4, tzinfo=timezone.utc))
        self.tables = (models.HorseProfile, models.HorseProfileDataCandidate, models.OperationLog,
                       models.TermEntry, models.HorseRaceRecord, models.RaceEvent,
                       models.RaceResultSourceIdentity, models.RaceDataSyncEnrollment,
                       models.RaceDataSyncSourceBinding, get_user_model())
        self.forbidden = []
        def blocked(*args, **kwargs):
            self.forbidden.append("external_or_public_action")
            raise AssertionError("A039 forbidden external/source/publication/queue action")
        for target in (
            "urllib.request.urlopen", "requests.sessions.Session.request",
            "socket.socket.connect", "socket.socket.connect_ex", "socket.socket.sendto",
            "socket.create_connection", "socket.getaddrinfo",
            "redis.Redis.execute_command", "redis.asyncio.client.Redis.execute_command",
            "celery.app.task.Task.apply_async",
            "stable.services.p0_horse_completion_source_clients._HKJCClient._fetch",
            "stable.services.p0_horse_completion_adapters.run_p0_horse_completion_adapter",
            "stable.services.horse_profile_publish.auto_publish_profiles",
            "stable.services.horse_profiles.transition_review_status",
            "stable.services.horse_profiles.upsert_race_record",
        ):
            guard = patch(target, side_effect=blocked)
            guard.start()
            self.addCleanup(guard.stop)
        clock = patch("stable.services.p0_horse_completion_source_clients.datetime", FrozenDateTime)
        clock.start()
        self.addCleanup(clock.stop)

    def state(self):
        return {m._meta.label: deepcopy(list(m.objects.order_by("pk").values())) for m in self.tables}

    def request(self, *, packet=None):
        packet = self.packet if packet is None else packet
        record = adapt_hkjc_source_cache(
            self.raw["cache.json"], expected_sha256=EXPECTED["cache.json"],
            ref=packet["cache_ref"], source_ref=packet["source_ref"])
        plan = plan_cache_reuse(packet["snapshot"], [record], packet["entity_versions"],
                                as_of=packet["as_of"], max_age_seconds=packet["max_age_seconds"])
        self.assertEqual(len(plan["candidates"]), 1)
        candidate = plan["candidates"][0]
        self.assertEqual(candidate["action"], "reusable")
        return dict(snapshot=deepcopy(packet["snapshot"]), candidate=deepcopy(candidate),
                    raw_bytes=self.raw["cache.json"], expected_sha256=EXPECTED["cache.json"],
                    ref=packet["cache_ref"], source_ref=packet["source_ref"],
                    entity_versions=deepcopy(packet["entity_versions"]), as_of=packet["as_of"],
                    max_age_seconds=packet["max_age_seconds"], expected_updated_at=self.baseline,
                    actor=self.actor), plan, record

    def preflight(self):
        request, plan, record = self.request()
        candidate = request["candidate"]
        self.assertEqual(plan["content_sha256"], self.manifest["h02_sha256"])
        self.assertEqual(candidate["idempotency_key"], self.manifest["candidate_idempotency_key"])
        self.assertEqual(candidate["entity_key"], "profile:1")
        self.assertEqual(candidate["entity_version"], self.manifest["entity_version"])
        self.assertEqual(self.packet["profile_baseline"], self.manifest["profile_baseline"])
        self.assertEqual(self.manifest["input_sha256"], EXPECTED["packet.json"])
        self.assertEqual(self.manifest["source_sha256"], EXPECTED["cache.json"])
        source = json.loads(record["content"])
        payload = REGION_ADAPTERS["hong_kong"].normalize(source, P0HorseCompletionRequest(
            candidate_key=candidate["idempotency_key"], region="hong_kong",
            horse_name=source["identity"]["horse_name"], source_url=source["source"]["url"],
            external_horse_id=source["source"]["external_horse_id"], candidate_source_name="hkjc"))
        payload["reviewed"] = False
        self.assertEqual(payload, self.display, "real normalizer must match frozen display payload")
        self.assertEqual(payload["failure_reason"], [])
        return request

    def assert_real_apply(self, request):
        before = self.state()
        expected_before = {n: (None if n == "birth_date" else "") for n in BASIC_FIELDS}
        self.assertEqual({n: before[models.HorseProfile._meta.label][0][n] for n in BASIC_FIELDS}, expected_before)
        result = apply_basic_profile_from_cache(**request)
        self.assertEqual(result.get("before"), expected_before)
        self.profile.refresh_from_db()
        self.assertEqual(result["status"], "applied")
        self.assertIs(result["published"], False)
        expected = deepcopy(self.display["basic_profile"])
        expected["birth_date"] = date.fromisoformat(expected["birth_date"])
        self.assertEqual({n: getattr(self.profile, n) for n in BASIC_FIELDS}, expected)
        self.assertEqual(result["after"], self.display["basic_profile"])
        self.assertEqual(set(result["updated_fields"]), set(BASIC_FIELDS))
        self.assertEqual(result["skipped_locked"], [])
        after = self.state()
        allowed = set(BASIC_FIELDS) | {"updated_at", "completeness_status"}
        for n, value in before[models.HorseProfile._meta.label][0].items():
            if n not in allowed:
                self.assertEqual(after[models.HorseProfile._meta.label][0][n], value, n)
        for model in self.tables:
            if model not in (models.HorseProfile, models.HorseProfileDataCandidate, models.OperationLog):
                self.assertEqual(after[model._meta.label], before[model._meta.label], model._meta.label)
        self.assertEqual(len(after[models.HorseProfile._meta.label]), 1)
        self.assertEqual(len(after[models.HorseProfileDataCandidate._meta.label]), 1)
        self.assertEqual(len(after[models.OperationLog._meta.label]), 1)
        stored = models.HorseProfileDataCandidate.objects.get(pk=result["candidate_id"])
        self.assertEqual(stored.status, models.HorseProfileCandidateStatus.APPLIED)
        self.assertEqual(stored.applied_by_id, self.actor.pk)
        self.assertIsNotNone(stored.applied_at)
        self.assertEqual(stored.raw_payload["h02_idempotency_key"], request["candidate"]["idempotency_key"])
        self.assertEqual(stored.raw_payload["content_sha256"], EXPECTED["cache.json"])
        self.assertEqual(stored.raw_payload["input_sha256"], result["input_sha256"])
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        expected_input_sha = digest({
            "candidate": request["candidate"], "snapshot_sha": digest(request["snapshot"]),
            "entity_versions": request["entity_versions"], "as_of": request["as_of"],
            "max_age_seconds": request["max_age_seconds"],
            "expected_updated_at": self.baseline.isoformat(), "source_role": "h03_hkjc_basic_cache.v1",
        })
        self.assertEqual(result["input_sha256"], expected_input_sha)
        self.assertEqual(stored.candidate_payload["birth_date"], "2020-09-14")
        self.assertEqual(stored.raw_payload["h03_result"]["after"], self.display["basic_profile"])
        json.dumps(stored.diff_payload, allow_nan=False)
        log = models.OperationLog.objects.get()
        self.assertEqual(log.admin_id, self.actor.pk)
        self.assertEqual(log.action_type, "horse_candidate_applied")
        self.assertEqual(self.forbidden, [])
        return result

    def test_frozen_prepare_packet_rebuild_applies_and_replays_without_publication(self):
        request = self.preflight()
        first = self.assert_real_apply(request)
        before = self.state()
        self.assertNotEqual(self.profile.updated_at, self.baseline)
        second = apply_basic_profile_from_cache(**request)
        self.assertEqual(second["status"], "already_applied")
        self.assertEqual(second["candidate_id"], first["candidate_id"])
        self.assertEqual(request["expected_updated_at"], self.baseline)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.forbidden, [])
        print("A039_CONTRACT_EVIDENCE " + json.dumps({"kind": "persist_and_replay",
              "before": first["before"], "after": first["after"], "input_sha256": first["input_sha256"],
              "h02_key": request["candidate"]["idempotency_key"], "candidate_id": first["candidate_id"],
              "replay_status": second["status"], "extra_writes": 0, "forbidden_events": self.forbidden}), flush=True)

    def test_real_consumer_outer_rollback_restores_profile_candidate_and_operation_log(self):
        request = self.preflight()
        before = self.state()
        with transaction.atomic():
            result = self.assert_real_apply(request)
            simulation = {"dry_run": True, "committed": False, "simulated_status": result["status"],
                          "before": result["before"], "after": result["after"]}
            transaction.set_rollback(True)
        self.assertEqual(self.state(), before, "all business and audit rows including updated_at restored")
        self.assertEqual(self.forbidden, [])
        print("A039_CONTRACT_EVIDENCE " + json.dumps({"kind": "outer_rollback",
              **simulation, "all_rows_restored": True, "sequence_rollback_claimed": False}), flush=True)

    def test_display_payload_and_changed_bound_inputs_are_rejected_without_writes(self):
        original = self.preflight()
        # 合法正向 preflight 真实写入后rollback，不让消费键掩盖负向理由。
        initial = self.state()
        with transaction.atomic():
            self.assert_real_apply(original)
            transaction.set_rollback(True)
        self.assertEqual(self.state(), initial)
        cases = (
            ("display", "input_invalid"), ("display_reviewed", "input_invalid"),
            ("candidate_reviewed", "candidate_mismatch"), ("bytes", "input_invalid"),
            ("expected_sha", "input_invalid"), ("candidate_version", "candidate_mismatch"),
            ("versions", "candidate_mismatch"), ("new_key_old_baseline", "stale_baseline"),
            ("missing_identity", "strong_identity_missing"), ("public", "target_not_private"),
        )
        evidence = []
        for kind, reason in cases:
            with self.subTest(kind=kind), transaction.atomic():
                self.assertEqual(self.state(), initial, "each case starts unconsumed independent state")
                request, _, _ = self.request()
                if kind in ("display", "display_reviewed"):
                    request["candidate"] = deepcopy(self.display)
                    if kind == "display_reviewed":
                        request["candidate"]["reviewed"] = True
                elif kind == "candidate_reviewed":
                    request["candidate"]["reviewed"] = True
                elif kind == "bytes":
                    request["raw_bytes"] += b" "
                elif kind == "expected_sha":
                    request["expected_sha256"] = "0" * 64
                elif kind == "candidate_version":
                    request["candidate"]["entity_version"] = "tampered-version"
                elif kind == "versions":
                    request["entity_versions"]["profile:1"] = "different-version"
                elif kind == "new_key_old_baseline":
                    packet = deepcopy(self.packet)
                    packet["entity_versions"]["profile:1"] = "a039-new-unconsumed-version"
                    request, _, _ = self.request(packet=packet)
                    self.assertNotEqual(request["candidate"]["idempotency_key"], original["candidate"]["idempotency_key"])
                    request["expected_updated_at"] = datetime(2026, 10, 1, tzinfo=timezone.utc)
                elif kind == "missing_identity":
                    models.HorseProfile.objects.filter(pk=1).update(source_refs={"horse_identity_keys": ["hkjc:hk-001"]})
                elif kind == "public":
                    models.HorseProfile.objects.filter(pk=1).update(review_status=models.HorseProfileStatus.PUBLISHED)
                before = self.state()
                self.assertFalse(models.HorseProfileDataCandidate.objects.exists())
                result = apply_basic_profile_from_cache(**request)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["reason"], reason)
                self.assertEqual(self.state(), before, "zero business/audit writes")
                self.assertEqual(self.forbidden, [])
                evidence.append({"case": kind, "reason": reason, "zero_writes": True, "unconsumed": True})
                transaction.set_rollback(True)
        self.assertEqual(self.state(), initial)
        print("A039_CONTRACT_EVIDENCE " + json.dumps({"kind": "negative_contracts", "cases": evidence,
              "file_approval_enforced_by_service": False, "forbidden_events": self.forbidden}), flush=True)
