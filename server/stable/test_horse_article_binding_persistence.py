"""C235冻结机制oracle；仅隔离合成责任域，不证明真实来源/许可。此卡不执行。"""
import base64
import copy
import hashlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from stable.models import ArticleHorseLink, HorseExternalIdentity, HorseProfile, NewsArticle, OperationLog, TermEntry
from stable.services import content_contracts as f01
from stable.services.horse_article_binding_persistence import commit_strong_horse_binding
from stable.test_article_entity_binding import LITERAL
from stable.views import _public_horse_article_entries, _public_published_articles


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def snapshot(instance):
    # Oracle reads actual concrete columns, independently of adapter helpers.
    return json.loads(json.dumps({f.attname: getattr(instance, f.attname) for f in instance._meta.concrete_fields},
                                 default=lambda value: value.isoformat()))


class HorseArticleBindingPersistenceTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires isolated PostgreSQL")
        self.actor = get_user_model().objects.create_user(username="c235-scope", is_staff=True)
        self.other = get_user_model().objects.create_user(username="c235-outsider", is_staff=True)
        self.term = TermEntry.objects.create(term_type="horse", source_ja="Aurora", target_zh="极光", source_language="en")
        self.horse = HorseProfile.objects.create(primary_term=self.term, original_name="Aurora", review_status="published")
        self.article = NewsArticle.objects.create(source_site="tdn", source_mode="latest", source_article_id="c235",
            source_url="https://example.invalid/c235", title_ja="", body_ja_raw="Aurora won.", source_language="en",
            published_at=timezone.now(), workflow_status="published", published_to_web_at=timezone.now())
        self.identity_bytes = raw(dict(source="the_racing_api", namespace="horse", external_id="hrs_235", horse_profile_id=self.horse.pk))
        self.identity = HorseExternalIdentity.objects.create(horse_profile=self.horse, source="the_racing_api", namespace="horse",
            external_id="hrs_235", status="verified", evidence_url="https://example.invalid/identity/235",
            payload_sha256=hashlib.sha256(self.identity_bytes).hexdigest(), verified_at=timezone.now(), verified_by=self.actor)
        self.pack = self.make_bundle()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "server-synthetic.json"
        self.scope = dict(bundle_path=str(self.path), bundle_sha256="", producer_namespace="synthetic-server",
            request_id="c235-one", article_id=self.article.pk, profile_id=self.horse.pk, identity_id=self.identity.pk,
            actor_ids=[self.actor.pk], not_before=(timezone.now()-timedelta(days=1)).isoformat(),
            expires_at=(timezone.now()+timedelta(days=1)).isoformat(), revoked=False,
            contract_refs=[copy.deepcopy(LITERAL["article_input"]["snapshot"]["evidence"][0]["contract_ref"])],
            responsibility=dict(identity_producer="isolated-fixture", relationship_owner="isolated-fixture",
                                write_owner="explicit-test-domain"))
        self.write_pack()
        self.settings_context = override_settings(HORSE_ARTICLE_BINDING_HANDLES={"synthetic-one": self.scope})
        self.settings_context.enable()
        self.addCleanup(self.settings_context.disable)

    def make_bundle(self):
        c = copy.deepcopy(LITERAL)
        c["resolution_payload"]["entities"][0]["confidence"] = 99
        self.article.translation_metadata = {"article_entity_resolution": c["resolution_payload"]}
        self.article.save(update_fields=["translation_metadata", "updated_at"])
        article_ref, horse_ref = "article:"+str(self.article.pk), "horse:"+str(self.horse.pk)
        provider = dict(source=self.identity.source, namespace=self.identity.namespace, external_id=self.identity.external_id)
        a, i, r = c["article_input"], c["identity_inputs"][0], c["relation_inputs"][0]
        a["snapshot"]["entity"]["canonical_id"] = article_ref
        i["snapshot"]["entity"].update(canonical_id=horse_ref, source_refs=[provider])
        i["snapshot"]["evidence"][0]["artifact_sha256"] = self.identity.payload_sha256
        i["snapshot"]["evidence"][0]["locator"] = "/external_id"
        def doc(value):
            return f01.build_input(value["snapshot"], evaluated_at=value["evaluated_at"], policy_ref=value["policy_ref"],
                                   generations=value["input_version"]["generations"]).to_dict()
        a, i = doc(a), doc(i)
        artifact = next(iter(c["relationship_artifacts"].values()))
        claim = artifact["assertions"][0]
        claim["article"].update(canonical_id=article_ref, input_wire_sha256=digest(a))
        claim["target"].update(canonical_id=horse_ref, source_ref=provider, identity_input_wire_sha256=digest(i))
        r["snapshot"]["entity"].update(canonical_id=horse_ref, source_refs=[provider])
        r["snapshot"]["materials"][0]["data"].update(source_ref=article_ref, target_ref=horse_ref)
        r["snapshot"]["evidence"][0]["artifact_sha256"] = digest(artifact)
        r = doc(r)
        context = c["contexts"][0]
        context.update(target_identity_input_wire_sha256=digest(i), relation_input_wire_sha256=digest(r), source_ref=provider)
        return dict(schema_version="l01.horse-link-bundle.v1", producer_namespace="synthetic-server", request_id="c235-one",
            payload_revision=1, article_id=self.article.pk, profile_id=self.horse.pk, identity_id=self.identity.pk,
            expected=dict(article=snapshot(self.article), profile=snapshot(self.horse), identity=snapshot(self.identity), pair="absent"),
            resolution_payload=c["resolution_payload"], article_input=a, identity_inputs=[i], relation_inputs=[r],
            source_document_base64=base64.b64encode(raw(c["source_document"])).decode(),
            identity_artifact_base64=base64.b64encode(self.identity_bytes).decode(),
            relationship_artifacts_base64={digest(artifact): base64.b64encode(raw(artifact)).decode()}, contexts=[context])

    def write_pack(self):
        self.path.write_bytes(raw(self.pack))
        self.path.chmod(0o600)
        self.scope["bundle_sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def call(self, actor=None):
        return commit_strong_horse_binding("synthetic-one", self.actor if actor is None else actor)

    def logs(self):
        return list(OperationLog.objects.filter(action_type="horse_binding_committed", target_type="horse_binding_request"))

    def assert_no_write(self, expected, *, actor=None):
        before = (list(ArticleHorseLink.objects.order_by("pk").values()), list(OperationLog.objects.order_by("pk").values()))
        result = self.call(actor)
        self.assertEqual(result["status"], expected)
        self.assertEqual(before, (list(ArticleHorseLink.objects.order_by("pk").values()), list(OperationLog.objects.order_by("pk").values())))
        return result

    def created(self):
        result = self.call()
        self.assertEqual(result["status"], "created")
        link = ArticleHorseLink.objects.get(article=self.article, horse_profile=self.horse)
        self.assertEqual(link.pk, result["link_id"])
        self.assertEqual(link.status, "auto")
        self.assertEqual(link.source, "strong_identity.v1")
        self.assertEqual(len(self.logs()), 1)
        self.assertEqual(link.metadata["provider_ref"]["external_id"], "hrs_235")
        return link

    def test_create_real_link_receipt_readers_and_repeat(self):
        link = self.created()
        self.assertEqual([x.pk for x in _public_published_articles().get(pk=self.article.pk).public_horse_links], [link.pk])
        self.assertEqual([x["article"].pk for x in _public_horse_article_entries(self.horse)], [self.article.pk])
        result = self.assert_no_write("replayed")
        self.assertEqual(result["link_id"], link.pk)
        self.assertEqual(result["receipt_id"], self.logs()[0].pk)

    def test_current_authority_checked_before_receipt_replay(self):
        self.created()
        self.assert_no_write("blocked_current_authority", actor=self.other)
        self.scope["revoked"] = True
        self.assert_no_write("blocked_current_authority")

    def test_actor_reloaded_and_scope_expiry_checked(self):
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        self.assert_no_write("blocked_current_authority")
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=True)
        self.scope["expires_at"] = (timezone.now()-timedelta(seconds=1)).isoformat()
        self.assert_no_write("blocked_current_authority")

    def test_historical_missing_never_recreated(self):
        link = self.created()
        old_pk = link.pk
        link.delete()
        result = self.assert_no_write("historical_applied_missing")
        self.assertEqual(result["link_id"], old_pk)

    def test_historical_replacement_and_metadata_drift_never_repaired(self):
        link = self.created()
        ArticleHorseLink.objects.filter(pk=link.pk).update(metadata={"changed": True})
        self.assert_no_write("historical_applied_drifted")
        link.delete()
        ArticleHorseLink.objects.create(article=self.article, horse_profile=self.horse, status="auto")
        self.assert_no_write("historical_applied_drifted")

    def test_manual_removed_full_row_protection_before_and_after_receipt(self):
        link = ArticleHorseLink.objects.create(article=self.article, horse_profile=self.horse, status="removed", metadata={"keep": [1]})
        self.assert_no_write("protected_current")
        link.delete()
        link = self.created()
        for status in ["manual", "removed"]:
            ArticleHorseLink.objects.filter(pk=link.pk).update(status=status)
            self.assert_no_write("protected_current")

    def test_existing_auto_and_candidate_without_receipt_conflict(self):
        link = ArticleHorseLink.objects.create(article=self.article, horse_profile=self.horse, status="auto")
        self.assert_no_write("existing_pair_conflict")
        ArticleHorseLink.objects.filter(pk=link.pk).update(status="candidate")
        self.assert_no_write("existing_pair_conflict")

    def test_same_request_changed_payload_and_duplicate_receipt_conflict(self):
        self.created()
        self.pack["payload_revision"] = 2
        self.write_pack()
        self.assert_no_write("history_conflict")
        self.pack["payload_revision"] = 1
        self.write_pack()
        receipt = self.logs()[0]
        OperationLog.objects.create(admin=receipt.admin, action_type=receipt.action_type, target_type=receipt.target_type,
                                    target_id=receipt.target_id, detail=receipt.detail)
        self.assert_no_write("history_conflict")

    def test_snapshot_CAS_first_apply_and_historical_inputs_drift(self):
        HorseProfile.objects.filter(pk=self.horse.pk).update(original_name="Changed")
        self.assert_no_write("stale_first_apply")
        HorseProfile.objects.filter(pk=self.horse.pk).update(original_name="Aurora")
        self.created()
        NewsArticle.objects.filter(pk=self.article.pk).update(title_zh="new input")
        self.assert_no_write("historical_applied_drifted")

    def test_stable_provider_identity_not_name_or_term(self):
        HorseExternalIdentity.objects.filter(pk=self.identity.pk).update(status="retired")
        self.assert_no_write("blocked_current_authority")

    def test_same_name_other_profile_is_not_a_target(self):
        other_term = TermEntry.objects.create(term_type="horse", source_ja="Aurora II", target_zh="另一极光")
        other_horse = HorseProfile.objects.create(primary_term=other_term, original_name="Aurora", review_status="published")
        self.created()
        self.assertFalse(ArticleHorseLink.objects.filter(article=self.article, horse_profile=other_horse).exists())

    def test_receipt_database_failure_rolls_back_link(self):
        def fail_receipt(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "stable_operationlog"'):
                # Real SQL constraint violation, not a mocked successful ORM call.
                return execute('INSERT INTO "stable_operationlog" ("action_type") VALUES (NULL)', None, False, context)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(fail_receipt):
            with self.assertRaises(IntegrityError):
                self.call()
        self.assertFalse(ArticleHorseLink.objects.filter(article=self.article, horse_profile=self.horse).exists())
        self.assertEqual(self.logs(), [])

    def test_unique_violation_savepoint_recovers_with_no_row_and_no_retry(self):
        inserts = []
        def duplicate_insert(execute, sql, params, many, context):
            if sql.startswith('INSERT INTO "stable_articlehorselink"'):
                inserts.append(sql)
                # Both SQL INSERTs are real; savepoint must roll back the first
                # as well as the duplicate. No concurrent writer is claimed.
                execute(sql, params, many, context)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(duplicate_insert):
            self.assert_no_write("concurrent_state_changed")
        self.assertEqual(len(inserts), 1)
        self.assertEqual(self.logs(), [])

    def test_source_tamper_and_unregistered_handle_rejected(self):
        self.path.write_bytes(self.path.read_bytes()+b" ")
        self.assert_no_write("blocked_current_authority")
        self.assertEqual(commit_strong_horse_binding("not-registered", self.actor)["status"], "blocked_current_authority")

    def test_bad_occurrence_is_real_decision_rejection_not_auto(self):
        self.pack["contexts"][0]["occurrence"]["matched_text"] = "Other"
        self.write_pack()
        self.assert_no_write("blocked_decision")

    def test_forged_payload_authorization_field_not_admitted(self):
        self.pack["approved"] = True
        self.write_pack()
        self.assert_no_write("blocked_current_authority")
