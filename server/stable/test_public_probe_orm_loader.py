from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Thread
from unittest.mock import patch

from django.db import connection, connections, transaction, IntegrityError
from django.test import SimpleTestCase, TransactionTestCase, Client, override_settings
from stable import models as m
from stable.public_probe_orm_fixture import create_public_result_fixture
from stable.services import public_probe_orm_loader as loader
from stable.services.race_events import resolve_race_live_public_read
from stable.services.race_data_source_adapters import canonical_sha

NOW=datetime(2026,10,5,6,20,tzinfo=dt_timezone.utc)


class PublicProbeOrmInputTests(SimpleTestCase):
    def test_invalid_inputs_rejected_without_query(self):
        valid=dict(event_id=1,canonical_subject="/races/2026/local/",audience="anonymous",as_of=NOW)
        for key, value in (("event_id",True),("event_id",0),("event_id","1"),("as_of",NOW.replace(tzinfo=None)),
            ("audience","staff"),("canonical_subject","https://example.test/races/2026/local/"),
            ("canonical_subject","/races/2026/local/?x=1"),("canonical_subject","/races/2026/a%2fb/")):
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                loader.load_public_result_snapshot(**(valid|{key:value}))


@override_settings(ALLOWED_HOSTS=["testserver"], RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True)
class PublicProbeOrmPostgresTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,"postgresql","C026 requires the allocated isolated PostgreSQL runner")
        self.enterContext(patch("django.utils.timezone.now",return_value=NOW))
        self.event,self.source,self.observation,self.revision,self.control,self.path=create_public_result_fixture(NOW)
        self.client=Client()

    def load(self, **changes):
        snapshot=loader.load_public_result_snapshot(**(dict(event_id=self.event.pk,canonical_subject=self.path,audience="anonymous",as_of=NOW)|changes))
        self.assertIsNotNone(snapshot,"published gate needs an independent bounded read snapshot")
        return snapshot

    def test_fixture_passes_existing_read_gate(self):
        decision=resolve_race_live_public_read(event_id=self.event.pk,now=NOW)
        self.assertTrue(decision.visible,decision.reason)
        self.assertEqual(self.client.get(self.path).status_code,200)

    def test_loaded_rows_match_real_anonymous_detail_without_public_proof(self):
        decision=resolve_race_live_public_read(event_id=self.event.pk,now=NOW)
        self.assertTrue(decision.visible,decision.reason)
        snapshot=self.load()
        self.assertEqual(snapshot.status,"read_boundary_loaded")
        self.assertEqual(snapshot.revision_id,self.revision.pk)
        self.assertEqual([r.external_runner_id for r in snapshot.rows],["c026-runner-1","c026-runner-2"])
        self.assertEqual(len({r.participant_id for r in snapshot.rows}),2)
        response=self.client.get(self.path)
        self.assertEqual(response.status_code,200)
        self.assertEqual([(r.horse_name,r.jockey_name,r.is_confirmed) for r in response.context["results"]],
            [(r.horse_name,r.jockey_name,r.is_confirmed) for r in snapshot.rows])
        self.assertContains(response,"Same Name")
        self.assertNotContains(response,"DO_NOT_EXPORT")
        self.assertNotIn(b'data-public-probe',response.content)
        self.assertEqual(snapshot.real_source_proof,"unverified")
        self.assertEqual(snapshot.response_binding,"unverified")
        self.assertFalse(snapshot.projection_complete)
        self.assertIn("execution_unbound",snapshot.missing)
        self.assertIn("f01_generations_unbound",snapshot.missing)
        self.assertIn("source_time_unknown",snapshot.missing)
        self.assertNotIn("raw_payload",repr(snapshot))
        self.assertNotIn("/forbidden/raw",repr(snapshot))
        with self.assertRaises(FrozenInstanceError): snapshot.status="public_verified"

    def test_hidden_draft_unknown_and_wrong_canonical_scope(self):
        for visibility in ("hidden","draft"):
            m.RaceEvent.objects.filter(pk=self.event.pk).update(visibility_status=visibility)
            self.assertEqual(self.load().status,"not_public")
            self.assertEqual(self.client.get(self.path).status_code,404)
        self.assertEqual(self.load(event_id=999999).status,"not_public")
        m.RaceEvent.objects.filter(pk=self.event.pk).update(visibility_status="published")
        self.assertEqual(self.load(canonical_subject="/races/2026/different/").status,"unverified")

    def test_legacy_redirect_and_historical_missing_lineage_keep_view_semantics(self):
        legacy=m.RaceEventPublicPath.objects.create(event=self.event,year=2026,slug="c026-old",path_kind="legacy")
        path=f"/races/{legacy.year}/{legacy.slug}/"
        response=self.client.get(path)
        self.assertEqual(response.status_code,301)
        self.assertEqual(response["Location"],self.path)
        self.assertEqual(self.load(canonical_subject=path).status,"unverified")
        self.control.delete()
        self.assertEqual(self.load().status,"unverified")
        self.assertEqual(self.client.get(self.path).status_code,200)

    def test_expired_or_revoked_live_source_hides_results(self):
        for change in ({"valid_until":NOW-timedelta(seconds=1)},{"valid_until":NOW+timedelta(days=1),"review_status":"revoked"}):
            # 用枚举的 rejected 值表达撤销，避免非法 fixture constraint。
            if change.get("review_status"): change["review_status"]="rejected"
            m.RaceResultSourceIdentity.objects.filter(pk=self.source.pk).update(**change)
            decision=resolve_race_live_public_read(event_id=self.event.pk,now=NOW)
            self.assertFalse(decision.visible)
            self.assertEqual(self.load().status,"not_public")
            response=self.client.get(self.path)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context["results"],[])
            self.assertNotContains(response,"Same Name")

    def test_missing_publication_and_observation_drift_fail_closed(self):
        m.RaceResultObservation.objects.filter(pk=self.observation.pk).update(normalized_sha256="f"*64)
        self.assertEqual(self.load().status,"not_public")
        m.RaceResultObservation.objects.filter(pk=self.observation.pk).update(normalized_sha256=self.revision.content_sha256)
        # 已发表 audit 受真实PG约束保护：非法缺件不能在fixture中伪造。
        with self.assertRaises(IntegrityError):
            m.RaceEventRevisionPublication.objects.filter(revision=self.revision).delete()
        self.assertEqual(self.load().status,"read_boundary_loaded")

    def test_rows_require_explicit_unique_source_identity_and_equal_fields(self):
        row=m.RaceEventResult.objects.filter(event=self.event).first()
        m.RaceEventResult.objects.filter(pk=row.pk).update(source_refs={})
        self.assertEqual(self.load().reason,"ambiguous_row_identity")
        m.RaceEventResult.objects.filter(pk=row.pk).update(source_refs={"source_key":self.source.source_key,
            "external_race_id":self.source.external_race_id,"external_runner_id":"c026-runner-1"},jockey_name="Mismatch")
        self.assertEqual(self.load().reason,"projection_mismatch")

    def test_outer_transaction_rejected(self):
        with transaction.atomic():
            self.assertEqual(self.load().reason,"outer_transaction_unsupported")
        self.assertTrue(connection.get_autocommit())

    def test_snapshot_is_read_only_repeatable_read_and_exception_restores_connection(self):
        real=loader._materialize
        def inspect(*args,**kwargs):
            with connection.cursor() as c:
                c.execute("SHOW transaction_isolation"); self.assertEqual(c.fetchone()[0],"repeatable read")
                c.execute("SHOW transaction_read_only"); self.assertEqual(c.fetchone()[0],"on")
            return real(*args,**kwargs)
        with patch.object(loader,"_materialize",side_effect=inspect): self.load()
        with patch.object(loader,"_materialize",side_effect=RuntimeError("local read failure")):
            with self.assertRaises(RuntimeError): self.load()
        self.assertTrue(connection.get_autocommit())
        self.assertFalse(connection.in_atomic_block)
        self.assertEqual(self.load().status,"read_boundary_loaded")

    def test_committed_writer_detected_after_repeatable_read_snapshot(self):
        real=loader._materialize; errors=[]
        def materialize(*args,**kwargs):
            value=real(*args,**kwargs)
            def writer():
                try: m.RaceEventProjectionControl.objects.filter(pk=self.control.pk).update(owner_generation=2)
                except BaseException as e: errors.append(e)
                finally: connections.close_all()
            thread=Thread(target=writer);thread.start();thread.join(timeout=5)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            self.assertEqual(m.RaceEventProjectionControl.objects.get(pk=self.control.pk).owner_generation,1)
            return value
        with patch.object(loader,"_materialize",side_effect=materialize):
            snapshot=self.load()
        self.assertEqual(snapshot.reason,"input_changed")
        self.assertEqual(m.RaceEventProjectionControl.objects.get(pk=self.control.pk).owner_generation,2)

    def test_policy_visibility_and_projection_changes_detected_in_new_read(self):
        real=loader._materialize
        mutations=[(m.RaceLivePublicationPolicy.objects.filter(scope_type="event"),{"version":2}),
            (m.RaceEvent.objects.filter(pk=self.event.pk),{"chinese_name":"Changed"}),
            (m.RaceEventResult.objects.filter(event=self.event,finish_position=1),{"jockey_name":"Changed"})]
        for queryset, values in mutations:
            def changed(*args,**kwargs):
                result=real(*args,**kwargs)
                # 独立连接的真正提交；不会借 snapshot 主连接写入。
                errors=[]
                def writer():
                    try: queryset.update(**values)
                    except BaseException as e: errors.append(e)
                    finally: connections.close_all()
                t=Thread(target=writer);t.start();t.join(timeout=5)
                self.assertFalse(t.is_alive());self.assertEqual(errors,[])
                return result
            with patch.object(loader,"_materialize",side_effect=changed):
                self.assertEqual(self.load().reason,"input_changed")
            # 下一子例先恢复合法 projection，版本增量保留即可。
            m.RaceEventResult.objects.filter(event=self.event,finish_position=1).update(jockey_name="Local Jockey 1")

    def test_multisource_published_fetch_expiry_does_not_revoke_but_identity_revocation_does(self):
        self.event,self.source,self.observation,self.revision,self.control,self.path=create_public_result_fixture(NOW,multisource=True,suffix="-multi")
        m.RaceResultSourceIdentity.objects.filter(pk=self.source.pk).update(valid_until=NOW-timedelta(seconds=1))
        decision=resolve_race_live_public_read(event_id=self.event.pk,now=NOW)
        self.assertTrue(decision.visible,decision.reason)
        self.assertEqual(self.load().status,"read_boundary_loaded")
        m.RaceResultSourceIdentity.objects.filter(pk=self.source.pk).update(identity_fields={"publication_revoked":True})
        self.assertFalse(resolve_race_live_public_read(event_id=self.event.pk,now=NOW).visible)
        self.assertEqual(self.load().status,"not_public")

    def test_bounded_rows_are_rejected_not_truncated(self):
        with patch.object(loader,"MAX_ROWS",1):
            snapshot=self.load()
        self.assertEqual(snapshot.reason,"snapshot_too_large")
        self.assertEqual(snapshot.rows,())

    def test_final_permission_recheck_uses_fresh_time_not_historical_as_of(self):
        real=loader._materialize
        def delayed(*args,**kwargs):
            snapshot=real(*args,**kwargs)
            self.enterContext(patch("django.utils.timezone.now",return_value=NOW+timedelta(days=2)))
            return snapshot
        with patch.object(loader,"_materialize",side_effect=delayed):
            snapshot=self.load()
        self.assertEqual(snapshot.as_of,NOW)
        self.assertEqual(snapshot.reason,"input_changed")
        self.assertEqual(snapshot.rows,())
        self.assertGreater(snapshot.revalidated_at,snapshot.snapshot_finished_at)


    def test_provisional_projection_cannot_claim_confirmed_winner(self):
        self.assertEqual(self.revision.phase,"provisional")
        self.assertTrue(resolve_race_live_public_read(event_id=self.event.pk,now=NOW).visible)
        # 独立期望来自既有writer phase规则；合法暂定表格保持可读。
        self.assertEqual(self.load().status,"read_boundary_loaded")
        self.assertTrue(all(row.is_confirmed is False for row in self.load().rows))
        m.RaceEventResult.objects.filter(event=self.event,finish_position=1).update(is_confirmed=True)
        snapshot=self.load()
        self.assertEqual(snapshot.status,"unverified")
        self.assertEqual(snapshot.reason,"projection_mismatch")
        self.assertEqual(snapshot.rows,())

    def test_official_projection_cannot_lose_confirmation(self):
        self.event,self.source,self.observation,self.revision,self.control,self.path=create_public_result_fixture(NOW,multisource=True,suffix="-confirmed")
        self.assertEqual(self.revision.phase,"official")
        self.assertTrue(resolve_race_live_public_read(event_id=self.event.pk,now=NOW).visible)
        # official的正确值必须为True，不能从Client或被破坏的projection反推。
        self.assertEqual(self.load().status,"read_boundary_loaded")
        self.assertTrue(all(row.is_confirmed is True for row in self.load().rows))
        m.RaceEventResult.objects.filter(event=self.event,finish_position=1).update(is_confirmed=False)
        snapshot=self.load()
        self.assertEqual(snapshot.status,"unverified")
        self.assertEqual(snapshot.reason,"projection_mismatch")
        self.assertEqual(snapshot.rows,())
