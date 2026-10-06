"""A042 已审入口合同候选；保留独立首RED断言，仅ROOT隔离PG窗口执行。"""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import io
import os
from contextlib import contextmanager
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TransactionTestCase

from stable import models
from stable.services.horse_basic_profile_from_cache import BASIC_FIELDS
from stable.test_horse_basic_profile_review_consumer import FrozenPrepareConsumerContractTests as OriginalConsumerFixture

FIXTURE = Path(__file__).parent / "fixtures/h03_reviewed_input"
NOW = datetime(2026, 10, 3, 1, tzinfo=timezone.utc)
EXPECTED = {
    "packet.json": "111d004d7c886300ceb26c2445fd023e0e6ad4ceaab875c74ee73b1c858dbe26",
    "cache.json": "2ba3faa4706c64f4da1e8c0967713d51cc5cc776264cfccbc317e4638acec7bb",
    "manifest.json": "ca3feeab3d7fd85d84d9c9c3a117b84c8d376b804e64ee412020ba532aa4e1c2",
    "combined_candidates.jsonl": "cd5c98d797c54137828ce13c5416c911da2f92515457fa0fdff5afa804339dcb",
    "prefrozen-reviewed-input.json": "ce5099bf3a90a68ce1989974c60e259460ba9634489d9dde737c9837bf7f72c7",
}

class FixtureDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

class ReviewedBasicProfileCommandTests(TransactionTestCase):
    # 仅复用无super的已审fixture辅助方法，不继承三个旧test方法。
    state = OriginalConsumerFixture.state
    request = OriginalConsumerFixture.request
    preflight = OriginalConsumerFixture.preflight
    assert_real_apply = OriginalConsumerFixture.assert_real_apply

    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql", "requires ROOT isolated PostgreSQL")
        self.assertTrue(str(connection.settings_dict["NAME"]).startswith("test_"))
        self.assertIn(connection.settings_dict["HOST"], ("127.0.0.1", "localhost", "/tmp"))
        clock_now = patch("django.utils.timezone.now", return_value=NOW)
        clock_now.start()
        self.addCleanup(clock_now.stop)
        self.raw = {}
        for name, digest in EXPECTED.items():
            self.raw[name] = (FIXTURE / name).read_bytes()
            self.assertEqual(hashlib.sha256(self.raw[name]).hexdigest(), digest)
        self.assertEqual(json.loads((FIXTURE / "frozen_sha256.json").read_bytes()), EXPECTED)
        self.packet = json.loads(self.raw["packet.json"])
        self.manifest = json.loads(self.raw["manifest.json"])
        self.display = json.loads(self.raw["combined_candidates.jsonl"])
        self.assertIs(self.display["reviewed"], False)
        self.assertIs(self.manifest["reviewed"], False)
        self.assertEqual(self.manifest["status"], "local_pending_review")
        self.actor = get_user_model().objects.create_user(username="a041-synthetic-staff", pk=1, is_staff=True, is_superuser=False)
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
            year=2025, edition_year=2025, slug="a041-synthetic-sentinel",
            original_name="Synthetic untouched event", country_region="hong_kong")
        models.HorseRaceRecord.objects.create(
            horse_profile=self.profile, event=event, race_name="Synthetic untouched record",
            race_date=date(2025, 12, 7), race_date_precision="exact")
        source = models.RaceResultSourceIdentity.objects.create(
            event=event, source_key="a041-synthetic", external_race_id="sentinel",
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
            raise AssertionError("A041 forbidden external/source/publication/queue action")
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
        clock = patch("stable.services.p0_horse_completion_source_clients.datetime", FixtureDateTime)
        clock.start()
        self.addCleanup(clock.stop)

    def original_preflight_with_rollback(self, stage):
        before = self.state()
        request = self.preflight()
        with transaction.atomic():
            result = self.assert_real_apply(request)
            transaction.set_rollback(True)
        self.assertEqual(self.state(), before, "original H03 outer rollback must restore all rows")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.updated_at, self.baseline)
        self.assertEqual(self.forbidden, [])
        print("A041_PREFLIGHT_EVIDENCE " + json.dumps({
            "stage": stage, "trusted_now": NOW.isoformat(), "original_status": result["status"],
            "before": result["before"], "after": result["after"],
            "input_sha256": result["input_sha256"], "outer_rollback": True,
            "candidate_count_after_rollback": models.HorseProfileDataCandidate.objects.count(),
            "log_count_after_rollback": models.OperationLog.objects.count(),
            "source_reviewed": self.display["reviewed"],
        }, sort_keys=True, allow_nan=False))

    def invoke_normal_command(self, argv):
        command = load_command_class("stable", "horse_basic_profile_from_review")
        # Import/parser/signature failures are errors, never accepted business RED.
        command.create_parser("manage.py", "horse_basic_profile_from_review").parse_args(argv)
        stream = io.StringIO()
        call_command("horse_basic_profile_from_review", *argv, stdout=stream)
        return json.loads(stream.getvalue())

    @contextmanager
    def private_bundle(self, *, decision=None):
        with tempfile.TemporaryDirectory(prefix="a042-review-") as directory:
            root = Path(directory)
            root.chmod(0o700)
            for name in ("inputs", "reviews", "outputs"):
                (root / name).mkdir(mode=0o700)
            for name, raw in self.raw.items():
                target = (root / "reviews" if name == "prefrozen-reviewed-input.json" else root / "inputs") / name
                target.write_bytes(raw)
                target.chmod(0o600)
            if decision is not None:
                self.freeze_decision(root, decision)
            yield root

    def freeze_decision(self, root, decision):
        raw = (json.dumps(decision, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()
        path = root / "reviews/prefrozen-reviewed-input.json"
        path.write_bytes(raw)
        path.chmod(0o600)
        return hashlib.sha256(raw).hexdigest()

    def command_args(self, root, mode="commit", *, review_sha=None, decision="approved", output="recorded"):
        code = json.loads(self.raw["prefrozen-reviewed-input.json"])["code_sha"]
        args = ["--" + mode, "--input-root", str(root / "inputs"), "--actor-id", str(self.actor.pk), "--code-sha", code]
        if mode == "record-review":
            args.extend(["--packet", "packet.json", "--manifest", "manifest.json", "--candidates", "combined_candidates.jsonl",
                         "--decision", decision, "--decision-source-reference", "a042-synthetic-contract-only",
                         "--output-root", str(root / "outputs"), "--output-dir", output])
            for flag, name in (("input", "packet.json"), ("source", "cache.json"),
                               ("manifest", "manifest.json"), ("candidates", "combined_candidates.jsonl")):
                args.extend(["--expected-" + flag + "-sha256", EXPECTED[name]])
        else:
            digest = review_sha or hashlib.sha256((root / "reviews/prefrozen-reviewed-input.json").read_bytes()).hexdigest()
            args.extend(["--review-root", str(root / "reviews"), "--review-input", "prefrozen-reviewed-input.json",
                         "--expected-reviewed-input-sha256", digest])
        return args

    def assert_protected(self, before):
        after = self.state()
        allowed = set(BASIC_FIELDS) | {"updated_at", "completeness_status"}
        for field, value in before[models.HorseProfile._meta.label][0].items():
            if field not in allowed:
                self.assertEqual(after[models.HorseProfile._meta.label][0][field], value, field)
        for model in self.tables:
            if model not in (models.HorseProfile, models.HorseProfileDataCandidate, models.OperationLog):
                self.assertEqual(after[model._meta.label], before[model._meta.label], model._meta.label)
        self.assertEqual(self.forbidden, [])

    def test_explicit_review_commit_and_replay_keep_prepare_pending_and_profile_private(self):
        decision = json.loads(self.raw["prefrozen-reviewed-input.json"])
        self.assertEqual(set(decision), {"schema_version", "code_sha", "inputs", "target", "scope",
                                         "module_reviews", "reviewer_id", "before", "after"})
        self.assertEqual(decision["schema_version"], "h03-basic-profile-reviewed-input.v1")
        self.assertEqual(decision["code_sha"], "941da3ebc8634cc26678cae3ac8f1f2d15a9282a")
        self.assertEqual(decision["reviewer_id"], self.actor.pk)
        self.assertTrue(self.actor.is_active and self.actor.is_staff)
        self.assertFalse(self.actor.is_superuser)
        self.assertEqual(decision["scope"], {"module": "profile", "fields": list(BASIC_FIELDS)})
        self.assertEqual(decision["before"], {n: None if n == "birth_date" else "" for n in BASIC_FIELDS})
        self.assertEqual(decision["after"], self.display["basic_profile"])
        review = decision["module_reviews"]["profile"]
        self.assertEqual(review["status"], "approved")
        self.assertEqual(review["reviewed_by"], self.actor.username)
        self.assertEqual(review["decision_source_reference"], "a041-synthetic-contract-only")
        self.assertLessEqual(datetime.fromisoformat(review["approved_at"]), NOW)
        self.assertLessEqual(datetime.fromisoformat(self.packet["as_of"]), NOW)
        source_time = datetime.fromisoformat(json.loads(self.raw["cache.json"])["source"]["fetched_at"].replace("Z", "+00:00"))
        self.assertGreaterEqual((NOW - source_time).total_seconds(), 0)
        self.assertLessEqual((NOW - source_time).total_seconds(), self.packet["max_age_seconds"])
        for role, name in (("packet", "packet.json"), ("cache", "cache.json"),
                           ("manifest", "manifest.json"), ("candidates", "combined_candidates.jsonl")):
            self.assertEqual(decision["inputs"][role], {"path": name, "sha256": EXPECTED[name]})
        self.assertEqual(decision["target"], {
            "profile_id": self.profile.pk, "entity_key": "profile:1",
            "entity_version": self.manifest["entity_version"],
            "profile_baseline": self.packet["profile_baseline"],
            "h02_sha256": self.manifest["h02_sha256"],
            "candidate_idempotency_key": self.manifest["candidate_idempotency_key"],
        })
        with tempfile.TemporaryDirectory(prefix="a041-reviewed-input-") as directory:
            root = Path(directory)
            root.chmod(0o700)
            inputs, outputs, reviews = (root / n for n in ("inputs", "outputs", "reviews"))
            for path in (inputs, outputs, reviews):
                path.mkdir(mode=0o700)
            for name, raw in self.raw.items():
                destination = (reviews if name == "prefrozen-reviewed-input.json" else inputs) / name
                destination.write_bytes(raw)
                destination.chmod(0o600)
            common = ["--input-root", str(inputs), "--actor-id", str(self.actor.pk),
                      "--code-sha", decision["code_sha"]]
            consume = ["--review-root", str(reviews), "--review-input", "prefrozen-reviewed-input.json",
                       "--expected-reviewed-input-sha256", EXPECTED["prefrozen-reviewed-input.json"]]
            baseline = self.state()
            dry = self.invoke_normal_command(["--dry-run", *common, *consume])
            self.assertEqual(dry["mode"], "dry-run")
            self.assertIs(dry["committed"], False)
            self.assertEqual(self.state(), baseline)
            record_argv = ["--record-review", *common,
                           "--packet", "packet.json", "--manifest", "manifest.json",
                           "--candidates", "combined_candidates.jsonl",
                           "--decision", "approved", "--decision-source-reference", review["decision_source_reference"],
                           "--output-root", str(outputs), "--output-dir", "recorded"]
            for flag, name in (("input", "packet.json"), ("source", "cache.json"),
                               ("manifest", "manifest.json"), ("candidates", "combined_candidates.jsonl")):
                record_argv.extend(["--expected-" + flag + "-sha256", EXPECTED[name]])
            # Independent subcases: missing record output cannot prevent prefrozen commit invocation.
            self.original_preflight_with_rollback("record")
            recorded = self.invoke_normal_command(record_argv)
            self.assertEqual(self.state(), baseline)
            output = outputs / "recorded" / "reviewed-input.json"
            print("A041_BUSINESS_EVIDENCE " + json.dumps({"stage": "record", "actual_status": recorded["status"],
                  "decision_exists": output.is_file(), "database_unchanged": self.state() == baseline}))
            with self.subTest(stage="record"):
                self.assertEqual(recorded["status"], "recorded", "legal explicit review must record independent decision")
                self.assertTrue(output.is_file())
            self.original_preflight_with_rollback("prefrozen_commit")
            with transaction.atomic():
                committed = self.invoke_normal_command(["--commit", *common, *consume])
                self.profile.refresh_from_db()
                actual = {n: getattr(self.profile, n) for n in BASIC_FIELDS}
                print("A041_BUSINESS_EVIDENCE " + json.dumps({"stage": "prefrozen_commit",
                      "actual_status": committed["status"], "actual_basic_profile": actual,
                      "candidate_count": models.HorseProfileDataCandidate.objects.count(),
                      "log_count": models.OperationLog.objects.count()}, default=str, sort_keys=True))
                with self.subTest(stage="prefrozen_commit"):
                    self.assertEqual(self.profile.country, "AUS", "valid independent reviewed input must write actual country")
                    expected = deepcopy(decision["after"])
                    expected["birth_date"] = date.fromisoformat(expected["birth_date"])
                    self.assertEqual(actual, expected)
                    self.assertEqual(models.HorseProfileDataCandidate.objects.count(), 1)
                    self.assertEqual(models.OperationLog.objects.count(), 1)
                    stored = models.HorseProfileDataCandidate.objects.get()
                    binding = stored.raw_payload["review_input_binding"]
                    self.assertEqual(binding["reviewed_input_sha256"], EXPECTED["prefrozen-reviewed-input.json"])
                    self.assertEqual(binding["reviewer_id"], self.actor.pk)
                    self.assertEqual(binding["code_sha"], decision["code_sha"])
                    self.assertIs(committed["committed"], True)
                transaction.set_rollback(True)
            self.assertEqual(self.state(), baseline)
            self.profile.refresh_from_db()
            # Genuine record output frozen by the independent test caller, then commit/replay.
            recorded_bytes = output.read_bytes()
            external_digest = hashlib.sha256(recorded_bytes).hexdigest()
            full_consume = ["--review-root", str(outputs / "recorded"), "--review-input", "reviewed-input.json",
                            "--expected-reviewed-input-sha256", external_digest]
            applied = self.invoke_normal_command(["--commit", *common, *full_consume])
            self.assertEqual(applied["status"], "applied")
            self.assertTrue(applied["committed"])
            self.assert_protected(baseline)
            after = self.state()
            replay = self.invoke_normal_command(["--commit", *common, *full_consume])
            self.assertEqual(replay["status"], "already_applied")
            self.assertEqual(replay["candidate_id"], applied["candidate_id"])
            self.assertEqual(self.state(), after)
            stored = models.HorseProfileDataCandidate.objects.get()
            self.assertEqual(stored.raw_payload["review_input_binding"]["reviewed_input_sha256"], external_digest)
            binding = stored.raw_payload["review_input_binding"]
            generated = json.loads(recorded_bytes)
            self.assertEqual(binding, {"reviewed_input_sha256": external_digest, "code_sha": generated["code_sha"],
                                      "reviewer_id": self.actor.pk, "module_reviews": generated["module_reviews"],
                                      "inputs": generated["inputs"], "scope": generated["scope"]})
            self.assertEqual(stored.applied_by_id, self.actor.pk)
            self.assertEqual(stored.confidence, 0)
            for name, raw in self.raw.items():
                destination = (reviews if name == "prefrozen-reviewed-input.json" else inputs) / name
                self.assertEqual(destination.read_bytes(), raw)
            self.assertIs(self.display["reviewed"], False)
            self.assertEqual(self.forbidden, [])

    def test_real_dry_run_rollback_and_ignore_preserve_business_and_audit_rows(self):
        self.original_preflight_with_rollback("dry_run_positive_control")
        with self.private_bundle() as root:
            before = self.state()
            from stable.management.commands import horse_basic_profile_from_review as cli
            actual_save = cli._save_binding
            observed = []
            def observe_real_dry_binding(candidate, binding):
                actual_save(candidate, binding)
                self.profile.refresh_from_db()
                persisted = models.HorseProfileDataCandidate.objects.get(pk=candidate.pk)
                self.assertEqual(persisted.raw_payload["review_input_binding"], binding)
                self.assertEqual(self.profile.country, "AUS")
                self.assertEqual(models.OperationLog.objects.get().admin_id, self.actor.pk)
                observed.append(candidate.pk)
            with patch.object(cli, "_save_binding", side_effect=observe_real_dry_binding):
                result = self.invoke_normal_command(self.command_args(root, "dry-run"))
            self.assertEqual(len(observed), 1, "dry-run must reach real writer and binding readback")
            self.assertTrue(result["dry_run"])
            self.assertFalse(result["committed"])
            self.assertEqual(result["simulated_status"], "applied")
            self.assertEqual(result["after"], self.display["basic_profile"])
            self.assertIsNone(result["candidate_id"])
            self.assertEqual(result["simulated_counts"], {"candidates": 1, "operation_logs": 1})
            self.assertEqual(self.state(), before)
            self.profile.refresh_from_db()
            self.assertEqual(self.profile.updated_at, self.baseline)
            ignored = self.invoke_normal_command(self.command_args(root, "record-review", decision="ignore"))
            path = root / "outputs/recorded/reviewed-input.json"
            self.assertEqual(ignored["status"], "recorded")
            decision = json.loads(path.read_bytes())
            self.assertEqual(decision["module_reviews"]["profile"]["status"], "ignore")
            digest = self.freeze_decision(root, decision)
            from stable.services import horse_basic_profile_from_cache as h03
            with patch.object(h03, "apply_basic_profile_from_cache", side_effect=AssertionError("ignore must not invoke H03")):
                for mode in ("dry-run", "commit"):
                    self.assertEqual(self.invoke_normal_command(self.command_args(root, mode, review_sha=digest))["status"], "ignored")
                    self.assertEqual(self.state(), before)
            with self.assertRaisesRegex(CommandError, "output_exists"):
                self.invoke_normal_command(self.command_args(root, "record-review", decision="ignore"))
            self.assertEqual(json.loads(path.read_bytes()), decision)
            # Output failure cleanup keeps only our owned inode, never foreign entries.
            from stable.management.commands import horse_basic_profile_from_review as cli
            actual_fsync = cli.os.fsync
            def foreign_then_fail(fd):
                directory = root / "outputs/failed"
                if directory.is_dir():
                    (directory / "foreign.txt").write_text("synthetic-foreign")
                    raise OSError("synthetic output failure")
                return actual_fsync(fd)
            with patch.object(cli.os, "fsync", side_effect=foreign_then_fail):
                with self.assertRaisesRegex(CommandError, "review_output_failed"):
                    self.invoke_normal_command(self.command_args(root, "record-review", output="failed"))
            self.assertEqual(list((root / "outputs/failed").iterdir()), [root / "outputs/failed/foreign.txt"])
            self.assertEqual(self.state(), before)
            # Existing original writer preserves both field and module manual locks.
            for flags in ({"owner_name": True}, {"profile": True}):
                with self.subTest(locks=flags), self.private_bundle() as approved_root, transaction.atomic():
                    approved_decision = json.loads((approved_root / "reviews/prefrozen-reviewed-input.json").read_bytes())
                    self.assertEqual(approved_decision["module_reviews"]["profile"]["status"], "approved")
                    models.HorseProfile.objects.filter(pk=1).update(manual_lock_flags=flags)
                    protected = self.state()
                    applied = self.invoke_normal_command(self.command_args(approved_root))
                    self.assertEqual(applied["status"], "applied")
                    self.profile.refresh_from_db()
                    self.assertEqual(self.profile.owner_name, "")
                    self.assertIn("owner_name", applied["skipped_locked"])
                    if flags.get("profile"):
                        self.assertEqual(self.profile.country, "")
                    self.assert_protected(protected)
                    transaction.set_rollback(True)
            self.assertEqual(self.state(), before)

    def real_locked_pair(self, first_action, second_action, *, on_wait=None):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections, connections
        entered, release = threading.Event(), threading.Event()
        pids = {}
        def worker(key, action, hold):
            close_old_connections()
            try:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids[key] = cursor.fetchone()[0]
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '12s'")
                with transaction.atomic():
                    result = action()
                    if hold:
                        entered.set()
                        if not release.wait(10):
                            raise AssertionError("A042 transaction release timeout")
                    return result
            finally:
                connections["default"].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker, "first", first_action, True)
            second = None
            try:
                self.assertTrue(entered.wait(5), "first transaction must hold real lock")
                second = pool.submit(worker, "second", second_action, False)
                deadline, seen = time.monotonic() + 5, False
                while time.monotonic() < deadline and not second.done():
                    if "second" in pids:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = %s", [pids["second"]])
                            current = cursor.fetchone()
                        if current and current[0] == "Lock" and pids["first"] in current[1]:
                            print("A042_PG_LOCK_EVIDENCE " + json.dumps(dict(first_pid=pids["first"], second_pid=pids["second"], wait_event_type=current[0], blocking_pids=current[1])))
                            seen = True
                            break
                    time.sleep(0.02)
                self.assertTrue(seen, "must observe actual PG Lock and blocking PID")
                if on_wait:
                    on_wait()
            finally:
                release.set()
            return first.result(timeout=10), second.result(timeout=10)

    def restore_unconsumed(self, baseline):
        models.HorseProfileDataCandidate.objects.all().delete()
        models.OperationLog.objects.all().delete()
        profile = deepcopy(baseline[models.HorseProfile._meta.label][0])
        profile.pop("id")
        models.HorseProfile.objects.filter(pk=1).update(**profile)
        user = deepcopy(baseline[get_user_model()._meta.label][0])
        user.pop("id")
        get_user_model().objects.filter(pk=self.actor.pk).update(**user)
        self.profile.refresh_from_db()
        self.actor.refresh_from_db()
        self.assertEqual(self.state(), baseline)

    def test_review_binding_permissions_freshness_and_failures_are_atomic(self):
        from stable.management.commands import horse_basic_profile_from_review as cli
        from stable.services import horse_basic_profile_from_cache as h03
        baseline = self.state()
        original = json.loads(self.raw["prefrozen-reviewed-input.json"])
        mutations = {
            "target": lambda d: d["target"].update(profile_id=2),
            "version": lambda d: d["target"].update(entity_version="changed"),
            "baseline": lambda d: d["target"].update(profile_baseline="2026-10-01T00:00:00+00:00"),
            "before": lambda d: d["before"].update(country="NZ"),
            "after": lambda d: d["after"].update(country="NZ"),
            "module": lambda d: d["scope"].update(module="career"),
            "reviewer": lambda d: d.update(reviewer_id=2),
            "username": lambda d: d["module_reviews"]["profile"].update(reviewed_by="same-name-impostor"),
            "code": lambda d: d.update(code_sha="0" * 40),
            "approval_future": lambda d: d["module_reviews"]["profile"].update(approved_at=(NOW + timedelta(seconds=1)).isoformat()),
            "extra": lambda d: d.update(extra=True),
            "reference_empty": lambda d: d["module_reviews"]["profile"].update(decision_source_reference=""),
            "target_bool": lambda d: d["target"].update(profile_id=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(reject=name), self.private_bundle() as root:
                self.original_preflight_with_rollback(name)
                value = deepcopy(original)
                mutate(value)
                digest = self.freeze_decision(root, value)
                with self.assertRaises(CommandError):
                    self.invoke_normal_command(self.command_args(root, review_sha=digest))
                self.assertEqual(self.state(), baseline)
        for name in ("packet.json", "cache.json", "manifest.json", "combined_candidates.jsonl"):
            with self.subTest(tamper=name), self.private_bundle() as root:
                self.original_preflight_with_rollback("tamper_" + name)
                (root / "inputs" / name).write_bytes(self.raw[name] + b" ")
                with self.assertRaises(CommandError):
                    self.invoke_normal_command(self.command_args(root))
                self.assertEqual(self.state(), baseline)
        for name, field, value in (("manifest.json", "read_only", 1), ("manifest.json", "reviewed", 0),
                                   ("combined_candidates.jsonl", "reviewed", 0)):
            with self.subTest(type_sensitive=(name, field)), self.private_bundle() as root:
                decision = deepcopy(original)
                parsed = json.loads(self.raw[name])
                parsed[field] = value
                raw = (json.dumps(parsed, allow_nan=False) + "\n").encode()
                (root / "inputs" / name).write_bytes(raw)
                role = "manifest" if name == "manifest.json" else "candidates"
                decision["inputs"][role]["sha256"] = hashlib.sha256(raw).hexdigest()
                digest = self.freeze_decision(root, decision)
                with self.assertRaisesRegex(CommandError, "manifest_mismatch|candidates_mismatch"):
                    self.invoke_normal_command(self.command_args(root, review_sha=digest))
                self.assertEqual(self.state(), baseline)
        for digest in ("0" * 64, "BAD", ""):
            with self.subTest(review_hash=digest), self.private_bundle() as root:
                self.original_preflight_with_rollback("external_review_sha")
                argv = self.command_args(root)
                argv[-1] = digest
                with self.assertRaises(CommandError):
                    self.invoke_normal_command(argv)
                self.assertEqual(self.state(), baseline)
        for field in ("is_active", "is_staff"):
            with self.subTest(permission=field), self.private_bundle() as root, transaction.atomic():
                self.original_preflight_with_rollback("permission_" + field)
                get_user_model().objects.filter(pk=self.actor.pk).update(**{field: False})
                changed = self.state()
                with self.assertRaisesRegex(CommandError, "actor_not_staff"):
                    self.invoke_normal_command(self.command_args(root))
                self.assertEqual(self.state(), changed)
                transaction.set_rollback(True)
        for now in (NOW + timedelta(seconds=1), datetime(2026, 7, 17, tzinfo=timezone.utc)):
            with self.subTest(now=now), self.private_bundle() as root, patch.object(cli, "_now", return_value=now):
                with self.assertRaises(CommandError):
                    self.invoke_normal_command(self.command_args(root))
                self.assertEqual(self.state(), baseline)
        # Binding save failure occurs after the real writer/log and is rolled back as one transaction.
        actual_save = cli._save_binding
        def save_then_fail(*args):
            actual_save(*args)
            self.assertEqual(models.HorseProfileDataCandidate.objects.count(), 1)
            self.assertEqual(models.OperationLog.objects.count(), 1)
            raise RuntimeError("synthetic binding failure")
        with self.private_bundle() as root, patch.object(cli, "_save_binding", side_effect=save_then_fail):
            with self.assertRaisesRegex(RuntimeError, "synthetic binding failure"):
                self.invoke_normal_command(self.command_args(root))
        self.assertEqual(self.state(), baseline)
        with self.private_bundle() as root, patch.object(models.OperationLog.objects, "create", side_effect=RuntimeError("synthetic log failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic log failure"):
                self.invoke_normal_command(self.command_args(root))
        self.assertEqual(self.state(), baseline)
        trusted = [NOW]
        def save_then_expire(*args):
            actual_save(*args)
            trusted[0] = NOW + timedelta(seconds=1)
        with self.private_bundle() as root, patch.object(cli, "_now", side_effect=lambda: trusted[0]), patch.object(cli, "_save_binding", side_effect=save_then_expire):
            with self.assertRaisesRegex(CommandError, "source_expired"):
                self.invoke_normal_command(self.command_args(root))
        self.assertEqual(self.state(), baseline, "expiry after real apply/binding must roll back all rows")
        # Real pairs: wrapper/wrapper and mixed direct/wrapper in both orders.
        for first_kind, second_kind in (("wrapper", "wrapper"), ("direct", "wrapper"), ("wrapper", "direct")):
            with self.subTest(pair=(first_kind, second_kind)), self.private_bundle() as root:
                request = self.preflight()
                def invoke(kind):
                    if kind == "direct":
                        return h03.apply_basic_profile_from_cache(**request)
                    try:
                        return self.invoke_normal_command(self.command_args(root))
                    except CommandError as exc:
                        return {"status": "rejected", "reason": str(exc)}
                first, second = self.real_locked_pair(lambda: invoke(first_kind), lambda: invoke(second_kind))
                self.assertEqual(first["status"], "applied")
                if first_kind == "direct":
                    self.assertEqual(second, {"status": "rejected", "reason": "review_binding_missing"})
                    self.assertNotIn("review_input_binding", models.HorseProfileDataCandidate.objects.get().raw_payload)
                else:
                    self.assertEqual(second["status"], "already_applied")
                self.assertEqual(models.HorseProfileDataCandidate.objects.count(), 1)
                self.assertEqual(models.OperationLog.objects.count(), 1)
                self.assert_protected(baseline)
                self.restore_unconsumed(baseline)
        # Revocation committed before actor lock acquisition rejects immediately.
        with self.private_bundle() as root:
            get_user_model().objects.filter(pk=self.actor.pk).update(is_staff=False)
            revoked = self.state()
            with self.assertRaisesRegex(CommandError, "actor_not_staff"):
                self.invoke_normal_command(self.command_args(root))
            self.assertEqual(self.state(), revoked)
            self.restore_unconsumed(baseline)
            # A later revocation actually waits behind held no_key actor lock.
            first, _ = self.real_locked_pair(
                lambda: self.invoke_normal_command(self.command_args(root)),
                lambda: get_user_model().objects.filter(pk=self.actor.pk).update(is_staff=False))
            self.assertEqual(first["status"], "applied")
            committed_state = self.state()
            with self.assertRaisesRegex(CommandError, "actor_not_staff"):
                self.invoke_normal_command(self.command_args(root))
            self.assertEqual(self.state(), committed_state)
            self.assertEqual(models.HorseProfileDataCandidate.objects.count(), 1)
            self.restore_unconsumed(baseline)
        # Genuine actor and profile lock waits cross trusted source deadline; writer stays rolled back.
        for resource in ("actor", "profile"):
            current_time = [NOW]
            def lock_target():
                if resource == "actor":
                    get_user_model().objects.select_for_update(no_key=True).get(pk=self.actor.pk)
                else:
                    models.HorseProfile.objects.select_for_update().get(pk=1)
                return "held"
            with self.subTest(deadline_lock=resource), self.private_bundle() as root, patch.object(cli, "_now", side_effect=lambda: current_time[0]):
                def invoke_expired():
                    try:
                        self.invoke_normal_command(self.command_args(root))
                    except CommandError as exc:
                        return str(exc)
                    self.fail("lock wait crossed source deadline must reject")
                _, reason = self.real_locked_pair(lock_target, invoke_expired, on_wait=lambda: current_time.__setitem__(0, NOW + timedelta(seconds=1)))
                self.assertEqual(reason, "source_expired")
                self.assertEqual(self.state(), baseline)
        # Actual PG timeout is a database failure, not a business success or retry.
        from django.db import OperationalError
        import time
        with self.private_bundle() as root:
            def hold_actor():
                get_user_model().objects.select_for_update(no_key=True).get(pk=self.actor.pk)
                return "held"
            def timeout_actor():
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '200ms'")
                try:
                    self.invoke_normal_command(self.command_args(root))
                except OperationalError as exc:
                    self.assertEqual(getattr(exc.__cause__, "sqlstate", getattr(exc.__cause__, "pgcode", None)), "55P03")
                    return "actual_pg_lock_timeout"
                self.fail("must propagate actual database timeout")
            _, reason = self.real_locked_pair(hold_actor, timeout_actor, on_wait=lambda: time.sleep(0.35))
            self.assertEqual(reason, "actual_pg_lock_timeout")
            self.assertEqual(self.state(), baseline)
        # Real stdout BrokenPipe happens after durable commit, not before or inside atomic.
        class BrokenStream(io.StringIO):
            def write(self, value):
                raise BrokenPipeError("synthetic broken pipe")
        with self.private_bundle() as root:
            with self.assertRaises(BrokenPipeError):
                call_command("horse_basic_profile_from_review", *self.command_args(root), stdout=BrokenStream())
            self.profile.refresh_from_db()
            self.assertEqual(self.profile.country, "AUS")
            committed_state = self.state()
            self.assertEqual(models.HorseProfileDataCandidate.objects.count(), 1)
            self.assertEqual(models.OperationLog.objects.count(), 1)
            replay = self.invoke_normal_command(self.command_args(root))
            self.assertEqual(replay["status"], "already_applied")
            self.assertEqual(self.state(), committed_state)
            for gate in ("expired", "private", "hidden", "identity", "binding"):
                with self.subTest(post_commit_gate=gate), transaction.atomic():
                    if gate == "private":
                        models.HorseProfile.objects.filter(pk=1).update(review_status=models.HorseProfileStatus.PUBLISHED)
                    elif gate == "hidden":
                        models.HorseProfile.objects.filter(pk=1).update(hidden_at=NOW)
                    elif gate == "identity":
                        models.HorseProfile.objects.filter(pk=1).update(source_refs={"horse_identity_verified_keys": ["hkjc:other"]})
                    elif gate == "binding":
                        candidate = models.HorseProfileDataCandidate.objects.get()
                        candidate.raw_payload["review_input_binding"]["reviewer_id"] = 2
                        candidate.save(update_fields=["raw_payload"])
                    state = self.state()
                    with patch.object(cli, "_now", return_value=NOW + timedelta(seconds=1) if gate == "expired" else NOW):
                        with self.assertRaises(CommandError):
                            self.invoke_normal_command(self.command_args(root))
                    self.assertEqual(self.state(), state, "rejection must retain prior committed audit")
                    transaction.set_rollback(True)

    def test_private_same_fd_strict_json_inputs_reject_aliases_and_tamper(self):
        from stable.services import horse_basic_profile_prepare_input as files
        self.original_preflight_with_rollback("private_files_positive_control")
        baseline = self.state()
        invalid_json = [b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', b'{"x":Infinity}',
                        b'{"x":1e9999}', b'{} {}', b'\xff', b'[' * 34 + b'0' + b']' * 34]
        for raw in invalid_json:
            with self.subTest(raw=raw[:40]), self.private_bundle() as root:
                valid = self.invoke_normal_command(self.command_args(root, "dry-run"))
                self.assertEqual(valid["simulated_status"], "applied")
                self.assertEqual(self.state(), baseline)
                path = root / "reviews/prefrozen-reviewed-input.json"
                path.write_bytes(raw)
                with self.assertRaises(CommandError):
                    self.invoke_normal_command(self.command_args(root))
                self.assertEqual(self.state(), baseline)
        for kind in ("symlink", "parent_symlink", "hardlink", "fifo", "directory", "mode", "root_mode", "owner", "oversize", "alias"):
            with self.subTest(file=kind), self.private_bundle() as root:
                valid = self.invoke_normal_command(self.command_args(root, "dry-run"))
                self.assertEqual(valid["simulated_status"], "applied")
                self.assertEqual(self.state(), baseline)
                path = root / "inputs/cache.json"
                argv = self.command_args(root)
                if kind == "symlink":
                    path.rename(root / "inputs/real-cache.json")
                    path.symlink_to("real-cache.json")
                elif kind == "parent_symlink":
                    (root / "inputs").rename(root / "actual-inputs")
                    (root / "inputs").symlink_to("actual-inputs", target_is_directory=True)
                elif kind == "hardlink":
                    os.link(path, root / "inputs/hardlink.json")
                elif kind == "fifo":
                    path.unlink(); os.mkfifo(path, mode=0o600)
                elif kind == "directory":
                    path.unlink(); path.mkdir(mode=0o700)
                elif kind == "mode":
                    path.chmod(0o644)
                elif kind == "root_mode":
                    (root / "inputs").chmod(0o755)
                elif kind == "owner":
                    # Nonroot isolated worker cannot chown. Pure helper rejects a real /proc file
                    # owned by another UID without reading any host personal files.
                    self.assertNotEqual(Path("/proc/version").stat().st_uid, os.getuid())
                    with files._root("/proc", "input_path") as fd:
                        with self.assertRaisesRegex(CommandError, "input_owner"):
                            files._read(fd, "version", "input_size", private=True, metadata=True)
                    continue
                elif kind == "oversize":
                    path.write_bytes(b' ' * (128 * 1024 + 1))
                elif kind == "alias":
                    decision = json.loads(self.raw["prefrozen-reviewed-input.json"])
                    decision["inputs"]["cache"] = deepcopy(decision["inputs"]["packet"])
                    self.freeze_decision(root, decision)
                with self.assertRaises(CommandError):
                    self.invoke_normal_command(argv)
                self.assertEqual(self.state(), baseline)
        with self.private_bundle() as root:
            argv = self.command_args(root, "record-review")
            argv[argv.index("--output-root") + 1] = str(root / "inputs")
            with self.assertRaisesRegex(CommandError, "output_path"):
                self.invoke_normal_command(argv)
            self.assertFalse((root / "inputs/recorded").exists())
            for name in ("packet.json", "cache.json", "manifest.json", "combined_candidates.jsonl"):
                self.assertEqual((root / "inputs" / name).read_bytes(), self.raw[name])
        with self.private_bundle() as root:
            with files._root(str(root / "inputs"), "input_path", private=True) as fd:
                capture = files._CapturedInputs()
                capture.read(fd, "packet.json", EXPECTED["packet.json"])
                with self.assertRaisesRegex(CommandError, "input_alias"):
                    capture.read(fd, "packet.json", EXPECTED["packet.json"])
        with self.private_bundle() as root:
            raw = b"x" * files.MAX_BYTES
            digest = hashlib.sha256(raw).hexdigest()
            for index in range(6):
                p = root / "inputs" / (str(index) + ".json")
                p.write_bytes(raw)
                p.chmod(0o600)
            with files._root(str(root / "inputs"), "input_path", private=True) as fd:
                capture = files._CapturedInputs()
                for index in range(5):
                    capture.read(fd, str(index) + ".json", digest)
                with self.assertRaisesRegex(CommandError, "input_total_size"):
                    capture.read(fd, "5.json", digest)
        self.assertEqual(files._strict_json(b'{"ratio":0.5}', allow_float=True), {"ratio": 0.5})
        with self.assertRaises(CommandError):
            files._strict_json(b'{"ratio":0.5}')
        # Same captured FD metadata/bytes; replacing the pathname cannot substitute payload.
        with self.private_bundle() as root:
            path = root / "inputs/cache.json"
            original_read = files.os.read
            replaced = []
            def replace_after_open(fd, size):
                if not replaced:
                    path.rename(root / "inputs/original-cache.json")
                    path.write_bytes(b'{"replacement":true}')
                    path.chmod(0o600)
                    replaced.append(True)
                return original_read(fd, size)
            with files._root(str(root / "inputs"), "input_path", private=True) as fd:
                with patch.object(files.os, "read", side_effect=replace_after_open):
                    raw, metadata = files._read(fd, "cache.json", "input_size", private=True, metadata=True)
                self.assertEqual(raw, self.raw["cache.json"])
                original_inode = (root / "inputs/original-cache.json").stat()
                self.assertEqual((metadata.st_dev, metadata.st_ino), (original_inode.st_dev, original_inode.st_ino))
                self.assertNotEqual(metadata.st_ino, path.stat().st_ino)
                self.assertIsInstance(files._read(fd, "original-cache.json", "input_size"), bytes)
        self.assertEqual(self.state(), baseline)
