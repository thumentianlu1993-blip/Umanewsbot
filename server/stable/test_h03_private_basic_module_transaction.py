"""A151: isolated private ORM transaction capability, never source permission.

New public consumer remains denied. No catalog/old oracle changes. Missing private
interface is NOT_READY, not historical RED; this source has not been executed.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from stable import models
from stable.services import horse_basic_profile_from_cache as consumer
from stable.services.horse_basic_profile_prepare_input import _prepare_basic_module
from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.services.horse_source_cache_reuse_adapter import adapt_hkjc_source_cache
from stable.test_h03_basic_module_input import (
    RealProfileFixture, EXPECTED_BASIC, FIELDS, PERMISSION_RAW, PERMISSION_REF,
    SOURCE_REF, DENIED, canonical, encoded, digest,
)

ROLE = "h03_hkjc_basic_module.v1"
VERSION = "h03-basic-v1:a151-generation-1"
# Declared synthetic review/code binding, not an attestation of running code.
CODE_BINDING = "9ac25245f79d86f2cce732d180e2eefbbd98bf96"
LABELS = dict(transaction_capability_only=True, source_permission_status="not_evaluated",
              public_consumer_authorized=False)


class PrivateBasicModuleTransactionTests(RealProfileFixture, TransactionTestCase):
    def request(self, *, owner_name=None, version=VERSION):
        self.profile.refresh_from_db()
        now = timezone.now()
        value = self.carrier()
        value["source"]["fetched_at"] = (now - timedelta(minutes=1)).isoformat()
        if owner_name is not None:
            value["basic_profile"]["owner_name"] = owner_name
        raw = encoded(value)
        packet = self.packet(raw, self.profile.pk, self.profile.updated_at.isoformat())
        packet.update(as_of=now.isoformat(), max_age_seconds=3600)
        packet["snapshot"].update(as_of=now.date().isoformat(), snapshot_at=now.isoformat())
        packet["entity_versions"] = {f"profile:{self.profile.pk}": version}
        module, plan, candidate = _prepare_basic_module(packet, raw, digest(raw), permission_raw=PERMISSION_RAW)
        self.assertEqual(candidate, plan["candidates"][0])
        self.assertEqual(candidate["action"], "reusable")
        self.assertEqual(module["projection"], value["basic_profile"])
        packet_raw, module_raw = encoded(packet), canonical(module)
        before = {key: getattr(self.profile, key) for key in FIELDS}
        before["birth_date"] = before["birth_date"].isoformat() if before["birth_date"] else None
        inputs = {name:dict(path=path, sha256=digest(content)) for name,path,content in (
            ("packet", "packet.json", packet_raw), ("source", "source.json", raw),
            ("module", "module.json", module_raw), ("permission", "inert-binding.txt", PERMISSION_RAW))}
        review = dict(schema_version="h03-basic-module-reviewed-input.v1", code_sha=CODE_BINDING,
                      producer_version="h03-hkjc-basic-producer.v1", inputs=inputs,
                      target=dict(profile_id=self.profile.pk, entity_key=candidate["entity_key"],
                                  entity_version=version, profile_baseline=packet["profile_baseline"],
                                  h02_plan_sha256=plan["content_sha256"],
                                  candidate_idempotency_key=candidate["idempotency_key"],
                                  module_content_sha256=digest(module_raw), projection_sha256=module["projection_sha256"],
                                  source_sha256=digest(raw), permission_sha256=digest(PERMISSION_RAW)),
                      scope=dict(module="profile", fields=list(FIELDS)),
                      module_reviews={"profile":dict(status="approved", reviewed_by=self.actor.get_username(),
                                                     approved_at=now.isoformat(),
                                                     decision_source_reference="fixture:a151-independent-review")},
                      reviewer_id=self.actor.pk, before=before, after=deepcopy(value["basic_profile"]))
        reviewed_raw = encoded(review)
        return dict(packet_raw=packet_raw, source_raw=raw, module_raw=module_raw,
                    permission_raw=PERMISSION_RAW, reviewed_raw=reviewed_raw,
                    expected_review_sha256=digest(reviewed_raw), actor_id=self.actor.pk,
                    code_sha=CODE_BINDING, dry_run=False)

    def invoke(self, request):
        private, = self.need(consumer, "_apply_basic_module_transaction")
        return private(**request)

    def with_review(self, request, mutate):
        value = json.loads(request["reviewed_raw"])
        mutate(value)
        raw = encoded(value)
        return dict(request, reviewed_raw=raw, expected_review_sha256=digest(raw))

    def assert_labels(self, result):
        for key, value in LABELS.items():
            self.assertEqual(result[key], value)
        self.assertFalse(result["published"])
        self.assertNotIn("publish_gate", result)

    def test_actual_seven_fields_audit_complete_bindings_and_same_request_replay(self):
        request = self.request()
        before = self.state()
        result = self.invoke(request)
        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["committed"])
        self.assert_labels(result)
        self.profile.refresh_from_db()
        expected = dict(EXPECTED_BASIC, birth_date=date(2020, 9, 14))
        self.assertEqual({k:getattr(self.profile,k) for k in FIELDS}, expected)
        stored = models.HorseProfileDataCandidate.objects.get(pk=result["candidate_id"])
        self.assertEqual(stored.source_name, ROLE)
        self.assertEqual(stored.status, models.HorseProfileCandidateStatus.APPLIED)
        self.assertEqual(stored.candidate_payload, EXPECTED_BASIC)
        review = json.loads(request["reviewed_raw"])
        self.assertEqual(stored.raw_payload["module_transaction_binding"],
                         dict(review_sha256=request["expected_review_sha256"], decision=review))
        for key, raw in (("packet_sha256",request["packet_raw"]), ("source_sha256",request["source_raw"]),
                         ("module_sha256",request["module_raw"]), ("permission_sha256",request["permission_raw"])):
            self.assertEqual(stored.raw_payload[key], digest(raw))
        self.assertEqual(stored.raw_payload["projection_sha256"], digest(canonical(EXPECTED_BASIC)))
        after = self.state()
        for key in before["profile"].keys() - set(FIELDS) - {"updated_at","completeness_status"}:
            self.assertEqual(after["profile"][key], before["profile"][key], key)
        self.assertEqual(after["records"], before["records"])
        self.assertEqual(after["term"], before["term"])
        self.assertEqual(len(after["candidates"]),len(before["candidates"])+1)
        self.assertEqual(len(after["logs"]),len(before["logs"])+1)
        replay = self.invoke(request)  # Original bytes/baseline; no new approval or forged candidate.
        self.assertEqual(replay["status"], "already_applied")
        self.assertEqual(replay["candidate_id"],result["candidate_id"])
        self.assert_labels(replay)
        self.assertEqual(self.state(),after)

    def test_new_role_does_not_adopt_real_legacy_writer_receipt_with_same_h02_key(self):
        now = timezone.now()
        value = self.whole(); value["source"]["fetched_at"] = (now-timedelta(minutes=1)).isoformat()
        raw = encoded(value)
        packet = self.packet(raw,self.profile.pk,self.profile.updated_at.isoformat())
        packet.update(as_of=now.isoformat(),max_age_seconds=3600)
        packet["snapshot"].update(as_of=now.date().isoformat(),snapshot_at=now.isoformat())
        packet["entity_versions"] = {f"profile:{self.profile.pk}":VERSION}
        record = adapt_hkjc_source_cache(raw,expected_sha256=digest(raw),ref="cache:a151-whole",source_ref=SOURCE_REF)
        plan = plan_cache_reuse(packet["snapshot"],[record],packet["entity_versions"],as_of=packet["as_of"],max_age_seconds=3600)
        old = consumer.apply_basic_profile_from_cache(snapshot=packet["snapshot"],candidate=plan["candidates"][0],
            raw_bytes=raw,expected_sha256=digest(raw),ref=record["ref"],source_ref=SOURCE_REF,
            entity_versions=packet["entity_versions"],as_of=packet["as_of"],max_age_seconds=3600,
            expected_updated_at=self.profile.updated_at,actor=self.actor)
        self.assertEqual(old["status"],"applied")
        old_stored = models.HorseProfileDataCandidate.objects.get(pk=old["candidate_id"])
        old_before = deepcopy(old_stored.raw_payload)
        request = self.request()
        new = self.invoke(request)
        self.assertEqual(new["status"],"applied")
        self.assertNotEqual(new["candidate_id"],old["candidate_id"])
        new_stored = models.HorseProfileDataCandidate.objects.get(pk=new["candidate_id"])
        self.assertEqual(new_stored.raw_payload["h02_idempotency_key"],old_before["h02_idempotency_key"])
        old_stored.refresh_from_db()
        self.assertEqual(old_stored.raw_payload,old_before)
        self.assertEqual(old_stored.source_name,consumer.SOURCE_ROLE)
        self.assertEqual(new_stored.source_name,ROLE)

    def test_byte_review_code_and_target_mismatches_reject_without_net_writes(self):
        request = self.request()
        self.need(consumer,"_apply_basic_module_transaction")
        variants = [dict(request, **{key:request[key]+b" "}) for key in
                    ("packet_raw","source_raw","module_raw","permission_raw","reviewed_raw")]
        variants += [dict(request,code_sha="a"*40),dict(request,actor_id=self.actor.pk+1000)]
        variants += [self.with_review(request,lambda r:r["after"].update(owner_name="Not reviewed source")),
                     self.with_review(request,lambda r:r["target"].update(module_content_sha256="b"*64))]
        for index,bad in enumerate(variants):
            with self.subTest(index=index):
                before = self.state()
                with self.assertRaises(CommandError): self.invoke(bad)
                self.assertEqual(self.state(),before)

    def test_same_version_different_legitimate_module_content_is_rejected(self):
        first = self.invoke(self.request())
        self.assertEqual(first["status"],"applied")
        changed = self.request(owner_name="Changed independently bound source")
        before = self.state()
        with self.assertRaisesRegex(CommandError,"version_content_conflict"):
            self.invoke(changed)
        self.assertEqual(self.state(),before)

    def test_field_and_module_manual_locks_keep_original_skip_semantics(self):
        self.need(consumer,"_apply_basic_module_transaction")
        for flags,expected_skips in (({"owner_name":True},["owner_name"]),({"profile":True},list(FIELDS))):
            with self.subTest(flags=flags),transaction.atomic():
                models.HorseProfile.objects.filter(pk=self.profile.pk).update(owner_name="LOCKED",manual_lock_flags=flags)
                request = self.request()
                result = self.invoke(request)
                self.assertEqual(result["status"],"applied")
                self.assertEqual(result["skipped_locked"],expected_skips)
                self.assert_labels(result)
                self.profile.refresh_from_db()
                self.assertEqual(self.profile.owner_name,"LOCKED")
                if "profile" in flags: self.assertEqual(self.profile.country,"")
                transaction.set_rollback(True)

    def test_current_staff_private_identity_and_baseline_guards_use_locked_database_state(self):
        self.need(consumer,"_apply_basic_module_transaction")
        for attack,reason in (("staff","actor_not_staff"),("hidden","target_not_private"),
                              ("identity","strong_identity_missing"),("baseline","stale_baseline")):
            with self.subTest(attack=attack),transaction.atomic():
                request = self.request()
                if attack=="staff":get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
                elif attack=="hidden":models.HorseProfile.objects.filter(pk=self.profile.pk).update(hidden_at=timezone.now())
                elif attack=="identity":models.HorseProfile.objects.filter(pk=self.profile.pk).update(source_refs={"horse_identity_verified_keys":[]})
                else:models.HorseProfile.objects.filter(pk=self.profile.pk).update(updated_at=self.profile.updated_at+timedelta(seconds=1))
                before = self.state()
                with self.assertRaisesRegex(CommandError,reason):self.invoke(request)
                self.assertEqual(self.state(),before)
                transaction.set_rollback(True)

    def test_writer_noop_missing_log_and_protected_field_mutation_roll_back(self):
        self.need(consumer,"_apply_basic_module_transaction")
        original = consumer.horse_profiles.apply_data_candidate
        def protected(stored,*,user):
            value=original(stored,user=user)
            models.HorseProfile.objects.filter(pk=self.profile.pk).update(intro="FORBIDDEN")
            return value
        injections = (("apply_data_candidate",dict(return_value=dict(updated_fields=[],skipped_locked=[]))),
                      ("log_operation",dict(return_value=None)),
                      ("apply_data_candidate",dict(side_effect=protected)))
        for index,(name,kwargs) in enumerate(injections):
            with self.subTest(index=index):
                request=self.request();before=self.state()
                with patch.object(consumer.horse_profiles,name,**kwargs):
                    with self.assertRaises(CommandError):self.invoke(request)
                self.assertEqual(self.state(),before)

    def test_post_insert_audit_or_log_exceptions_keep_original_exception_and_roll_back(self):
        self.need(consumer,"_apply_basic_module_transaction")
        original_save=models.HorseProfileDataCandidate.save
        original_log=consumer.horse_profiles.log_operation
        for kind in ("audit","log"):
            request=self.request();before=self.state();failure=RuntimeError("A151 injected "+kind)
            def save_then_fail(stored,*args,**kwargs):
                result=original_save(stored,*args,**kwargs)
                if stored.source_name==ROLE and stored.status==models.HorseProfileCandidateStatus.APPLIED:raise failure
                return result
            def log_then_fail(**kwargs):
                original_log(**kwargs)
                raise failure
            context=patch.object(models.HorseProfileDataCandidate,"save",save_then_fail) if kind=="audit" else patch.object(consumer.horse_profiles,"log_operation",side_effect=log_then_fail)
            with self.subTest(kind=kind),context:
                with self.assertRaises(RuntimeError) as caught:self.invoke(request)
                self.assertIs(caught.exception,failure)
            self.assertEqual(self.state(),before)

    def test_replay_field_or_binding_tamper_and_expiry_cannot_bypass_checks(self):
        request=self.request();result=self.invoke(request)
        for attack in ("field","binding"):
            with self.subTest(attack=attack),transaction.atomic():
                if attack=="field":models.HorseProfile.objects.filter(pk=self.profile.pk).update(owner_name="OUTSIDE CHANGE")
                else:
                    stored=models.HorseProfileDataCandidate.objects.get(pk=result["candidate_id"])
                    raw=deepcopy(stored.raw_payload);raw.pop("module_transaction_binding")
                    models.HorseProfileDataCandidate.objects.filter(pk=stored.pk).update(raw_payload=raw)
                before=self.state()
                with self.assertRaises(CommandError):self.invoke(request)
                self.assertEqual(self.state(),before)
                transaction.set_rollback(True)
        future=timezone.now()+timedelta(hours=2);before=self.state()
        with patch.object(consumer,"_basic_module_now",return_value=future):
            with self.assertRaisesRegex(CommandError,"source_expired"):self.invoke(request)
        self.assertEqual(self.state(),before)

    def test_ignore_dry_run_and_public_denial_never_become_application_authority(self):
        request=self.request();before=self.state()
        dry=self.invoke(dict(request,dry_run=True))
        self.assertEqual(dry["status"],"dry_run");self.assertFalse(dry["committed"])
        self.assertIsNone(dry["candidate_id"]);self.assert_labels(dry);self.assertEqual(self.state(),before)
        ignored=self.with_review(request,lambda r:r["module_reviews"]["profile"].update(status="ignore"))
        result=self.invoke(ignored)
        self.assertEqual(result["status"],"ignored");self.assertFalse(result["committed"])
        self.assert_labels(result);self.assertEqual(self.state(),before)
        with patch.object(consumer,"_apply_basic_module_transaction",side_effect=AssertionError("public delegation")) as guard:
            with CaptureQueriesContext(connection) as queries:denied=consumer.consume_reviewed_basic_module(request)
            self.assertEqual(denied,DENIED);self.assertEqual(len(queries),0);guard.assert_not_called()
        self.assertEqual(self.state(),before)

    def test_real_actor_lock_wait_rechecks_source_expiry_before_any_write(self):
        from queue import Empty, Queue
        import traceback
        import psycopg

        private,=self.need(consumer,"_apply_basic_module_transaction")
        request=self.request();before=self.state();channel=Queue()
        now=[timezone.now()]
        diagnostics=dict(events=[], samples=[], holder=None, observer=None)
        def identity(cursor):
            cursor.execute("SELECT pg_backend_pid(),current_database(),current_user")
            pid,database,user=cursor.fetchone()
            return dict(pid=pid,database=database,user=user)
        def describe(error):
            cause=error.__cause__
            return dict(type=type(error).__module__+"."+type(error).__qualname__,
                        message=str(error),sqlstate=getattr(error,"sqlstate",None) or getattr(cause,"sqlstate",None),
                        traceback="".join(traceback.format_exception(error)))
        def worker():
            stage="connecting"
            try:
                close_old_connections();connection.ensure_connection()
                with connection.cursor() as cursor:backend=identity(cursor)
                channel.put(dict(phase="connected",at=time.monotonic(),**backend))
                stage="private_call"
                channel.put(dict(phase=stage,at=time.monotonic(),**backend))
                result=private(**request)
                channel.put(dict(phase="worker_returned",at=time.monotonic(),result=result))
                return result
            except BaseException as error:
                channel.put(dict(phase="worker_exception",stage=stage,at=time.monotonic(),error=describe(error)))
                raise
            finally:
                connection.close()
                channel.put(dict(phase="worker_connection_closed",at=time.monotonic()))
        with patch.object(consumer,"_basic_module_now",side_effect=lambda:now[0]):
            pool=ThreadPoolExecutor(max_workers=1)
            future=None;observer=None;primary=None;worker_error=None;worker_result=None
            try:
                configured=connection.get_connection_params()
                params={key:configured[key] for key in ("dbname","user","password","host","port") if key in configured}
                observer=psycopg.connect(**params,connect_timeout=5,application_name="a153-lockwait-observer",autocommit=True)
                with observer.cursor() as cursor:
                    cursor.execute("SET statement_timeout=1000")
                    diagnostics["observer"]=identity(cursor)
                diagnostics["holder_scope_entered"]=True
                with transaction.atomic():
                    get_user_model().objects.select_for_update(no_key=True).get(pk=self.actor.pk)
                    with connection.cursor() as cursor:holder=identity(cursor)
                    diagnostics.update(holder=holder,holder_actor_id=self.actor.pk,holder_lock_acquired=True)
                    future=pool.submit(worker)
                    ready=channel.get(timeout=5);diagnostics["events"].append(ready)
                    self.assertEqual(ready["phase"],"connected","worker must identify an established backend")
                    self.assertEqual(ready["database"],holder["database"])
                    self.assertEqual(ready["user"],holder["user"])
                    self.assertEqual(diagnostics["observer"]["database"],holder["database"])
                    self.assertEqual(diagnostics["observer"]["user"],holder["user"])
                    self.assertEqual(len({ready["pid"],holder["pid"],diagnostics["observer"]["pid"]}),3)
                    deadline=time.monotonic()+8;blocked=False
                    while time.monotonic()<deadline:
                        if future.done():
                            diagnostics["worker_completed_before_positive_wait"]=True
                            break
                        with observer.cursor() as cursor:
                            cursor.execute("SELECT pid,datname,usename,state,wait_event_type,wait_event,query,pg_blocking_pids(pid) "
                                           "FROM pg_stat_activity WHERE pid=%s",[ready["pid"]])
                            row=cursor.fetchone()
                        sample=dict(at=time.monotonic(),backend=None)
                        if row:
                            sample["backend"]=dict(zip(("pid","database","user","state","wait_event_type","wait_event","query","blocking_pids"),row))
                            activity=sample["backend"]
                            blocked=(activity["pid"]==ready["pid"] and activity["database"]==holder["database"]
                                     and activity["user"]==holder["user"] and activity["state"]=="active"
                                     and activity["wait_event_type"]=="Lock" and holder["pid"] in activity["blocking_pids"]
                                     and get_user_model()._meta.db_table in activity["query"]
                                     and "FOR NO KEY UPDATE" in activity["query"])
                        diagnostics["samples"].append(sample)
                        if blocked:
                            diagnostics["positive_wait"]=sample
                            break
                        time.sleep(0.05)
                    self.assertTrue(blocked,"must observe actual PostgreSQL actor-row lock wait")
                    now[0]=now[0]+timedelta(hours=2)
                    diagnostics["clock_advanced_after_positive_wait"]=True
            except BaseException as error:
                primary=error
                diagnostics["primary_failure"]=describe(error)
            finally:
                # The atomic holder scope has exited before result/exception retrieval.
                diagnostics["holder_scope_exited"]=diagnostics.get("holder_scope_entered",False)
                if future is not None:
                    try:
                        worker_result=future.result(timeout=8)
                        diagnostics["worker_result"]=worker_result
                    except BaseException as error:
                        worker_error=error
                        diagnostics["worker_future_exception"]=describe(error)
                    diagnostics["worker_done_after_collection"]=future.done()
                if observer is not None:
                    try:observer.close()
                    except BaseException as error:
                        diagnostics["observer_close_exception"]=describe(error)
                        if primary is None:primary=error
                pool.shutdown(wait=False,cancel_futures=True)
                while True:
                    try:diagnostics["events"].append(channel.get_nowait())
                    except Empty:break
                print("A153_LOCKWAIT_DIAGNOSTICS "+json.dumps(diagnostics,default=str,sort_keys=True),flush=True)
            if primary is not None:
                if worker_error is not None:raise primary.with_traceback(primary.__traceback__) from worker_error
                raise primary.with_traceback(primary.__traceback__)
            if worker_error is None:self.fail("worker returned without source_expired: "+repr(worker_result))
            if not isinstance(worker_error,CommandError):raise worker_error.with_traceback(worker_error.__traceback__)
            self.assertEqual(str(worker_error),"source_expired")
        self.assertEqual(self.state(),before)
