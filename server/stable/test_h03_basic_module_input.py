"""A148 test-source only: module preparation, old whole gate, public fixed denial.

All material is synthetic. Permission bytes are inert hash-binding fixtures,
never an authority grant. Missing future APIs are NOT_READY skips, not business
RED or PASS; no allowed_skips policy is added. No private transaction is tested.

Frozen proposed API calls (review together with this source):
  produce_hkjc_basic_module(raw, *, expected_sha256, source_ref, permission_binding)
  basic_module_to_h02_record(module, *, raw_bytes, expected_sha256,
                            source_ref, permission_binding)
  _prepare_basic_module(packet, raw, source_sha, *, permission_raw)
  consume_reviewed_basic_module(request)
"""
import hashlib
import json
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from stable import models
from stable.services import horse_basic_profile_from_cache as consumer
from stable.services import horse_basic_profile_prepare_input as preparation
from stable.services import horse_source_cache_reuse_adapter as adapter
from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.services.p0_horse_completion_source_clients import (
    P0HorseSourceBlocked, validate_p0_horse_source_cache,
)
from stable.test_horse_target_inventory import document, event, identity, row

FIXTURE = Path(__file__).parent / "fixtures/h03_basic_profile/hkjc_synthetic.json"
FIXTURE_SHA = "2ba3faa4706c64f4da1e8c0967713d51cc5cc776264cfccbc317e4638acec7bb"
AS_OF = "2026-10-03T01:00:00+00:00"
MAX_AGE = 77 * 86400 + 3600
SOURCE_REF = "fixture:a148-source"
PERMISSION_REF = "fixture:a148-inert-binding"
PERMISSION_RAW = b"A148 isolated fixture only; not a source permission grant.\n"
VERSION = "h03-basic-v1:a148-generation-1"
FIELDS = ("country", "sex", "color", "birth_date", "owner_name", "trainer_name", "breeder_name")
EXPECTED_BASIC = dict(country="AUS", sex="gelding", color="brown", birth_date="2020-09-14",
                      owner_name="Hong Kong Owner", trainer_name="Hong Kong Trainer",
                      breeder_name="Hong Kong Breeder")
DENIED = dict(status="blocked", reason="permission_authority_unavailable", applied=False,
              committed=False, published=False, candidate_id=None)
DOMAIN_ERRORS = (ValueError, CommandError)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


class ModuleFixture:
    def setUp(self):
        super().setUp()
        # Guards return no source data and never replace a new module producer.
        for target in ("urllib.request.urlopen",
                       "stable.services.p0_horse_completion_source_clients._HKJCClient._fetch",
                       "stable.services.p0_horse_completion_adapters.run_p0_horse_completion_adapter"):
            guard = patch(target, side_effect=AssertionError("A148 source/network execution forbidden"))
            mocked = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(mocked.assert_not_called)

    def need(self, module, *names):
        missing = [name for name in names if not hasattr(module, name)]
        if missing:
            self.skipTest("NOT_READY: " + module.__name__ + ":" + ",".join(missing)
                          + "; absent interface is not business RED")
        result = [getattr(module, name) for name in names]
        for name, value in zip(names, result):
            self.assertTrue(callable(value), name + " must be a callable interface")
        return result

    def whole(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(digest(raw), FIXTURE_SHA)
        return json.loads(raw)

    def carrier(self, variant="both"):
        value = self.whole()
        if variant in ("both", "missing_pedigree"):
            value.pop("pedigree")
        if variant in ("both", "partial_career"):
            # One actual PU start and a WV non-start remain; source declares two.
            value["career"]["source_start_count"] = 2
        return value

    def permission(self):
        return dict(reference=PERMISSION_REF, sha256=digest(PERMISSION_RAW))

    def source_kwargs(self, raw):
        return dict(expected_sha256=digest(raw), source_ref=SOURCE_REF,
                    permission_binding=self.permission())

    def make_module(self, raw):
        produce, = self.need(adapter, "produce_hkjc_basic_module")
        return produce(raw, **self.source_kwargs(raw))

    def bridge(self, raw, module=None):
        bridge, = self.need(adapter, "basic_module_to_h02_record")
        module = self.make_module(raw) if module is None else module
        return bridge(module, raw_bytes=raw, **self.source_kwargs(raw))

    def snapshot(self, profile_id=1):
        value = document()
        value.update(events=[event(region="hong_kong")],
                     participations=[row(horse_key="hkjc:HK-001", birth_year=2020)],
                     identities=[identity("hkjc:HK-001", profile=profile_id)],
                     layers=[dict(target_key=f"profile:{profile_id}", cache="present",
                                  staging="matched", profile_exists=True,
                                  public_state="unpublished", starts=None,
                                  incomplete_modules=None)])
        return value

    def plan(self, record, profile_id=1, snapshot=None, versions=None, max_age=MAX_AGE):
        return plan_cache_reuse(snapshot or self.snapshot(profile_id), [record],
                                {f"profile:{profile_id}": VERSION} if versions is None else versions,
                                as_of=AS_OF, max_age_seconds=max_age)

    def packet(self, raw, profile_id=1, baseline="2026-10-03T00:30:00+00:00"):
        return dict(schema_version="h03-basic-module-input.v1",
                    producer_version="h03-hkjc-basic-producer.v1", source_file="source.json",
                    source_ref=SOURCE_REF, expected_source_sha256=digest(raw),
                    permission_file="inert-binding.txt", permission_ref=PERMISSION_REF,
                    expected_permission_sha256=digest(PERMISSION_RAW), snapshot=self.snapshot(profile_id),
                    entity_versions={f"profile:{profile_id}": VERSION}, as_of=AS_OF,
                    max_age_seconds=MAX_AGE, profile_baseline=baseline)

    def prepared(self, raw, packet=None):
        self.need(adapter, "produce_hkjc_basic_module", "basic_module_to_h02_record")
        prepare, = self.need(preparation, "_prepare_basic_module")
        return prepare(packet or self.packet(raw), raw, digest(raw), permission_raw=PERMISSION_RAW)

    def expected_module(self, raw):
        value = json.loads(raw)
        return dict(schema_version="hkjc-basic-profile-module.v1",
                    producer_version="h03-hkjc-basic-producer.v1", module="basic_profile",
                    source_binding=dict(source_sha256=digest(raw), source_ref=SOURCE_REF,
                                        carrier_schema="p0-horse-source-cache.v2", provider="hkjc",
                                        external_horse_id="HK-001", source_url=value["source"]["url"],
                                        fetched_at=value["source"]["fetched_at"]),
                    permission_binding=self.permission(), projection=deepcopy(EXPECTED_BASIC),
                    projection_sha256=digest(canonical(EXPECTED_BASIC)),
                    coverage=dict(basic_profile="validated_complete",
                                  pedigree=dict(status="missing" if "pedigree" not in value else "present_unassessed",
                                                raw_path="$.pedigree"),
                                  career=dict(status="missing" if "career" not in value else "present_unassessed", raw_path="$.career"),
                                  whole_canonical="not_assessed"))


class BasicModuleProducerPrepareTests(ModuleFixture, SimpleTestCase):
    databases = set()

    def test_partial_carrier_produces_exact_seven_field_module_without_laundering_coverage(self):
        raw = encoded(self.carrier())
        before = bytes(raw)
        module = self.make_module(raw)
        self.assertEqual(module, self.expected_module(raw))
        self.assertEqual(raw, before)
        self.assertEqual(json.loads(raw)["career"]["source_start_count"], 2)
        self.assertNotIn("pedigree", json.loads(raw))
        self.assertNotIn("failure_reason", module)
        self.assertNotIn("authorized", module)
        self.assertNotIn("identity_verified", module)
        self.assertNotEqual(digest(raw), digest(canonical(module)))
        whole_raw = encoded(self.whole())
        self.assertEqual(self.make_module(whole_raw), self.expected_module(whole_raw))

    def test_missing_nonselected_modules_stay_missing_without_zero_or_complete_claims(self):
        value = self.carrier(); value.pop("career")
        raw = encoded(value)
        module = self.make_module(raw)
        self.assertEqual(module, self.expected_module(raw))
        self.assertEqual(module["coverage"]["career"]["status"], "missing")
        self.assertEqual(module["coverage"]["pedigree"]["status"], "missing")
        self.assertNotIn("source_start_count", module)
        self.assertNotIn("race_records", module)

    def test_bridge_is_new_content_and_actual_h02_reuses_it_without_relabeling_old_raw(self):
        raw = encoded(self.carrier())
        module = self.make_module(raw)
        record = self.bridge(raw, module)
        module_bytes = canonical(module)
        self.assertEqual(set(record), {"ref", "horse_key", "profile_id", "source_time", "source_ref",
                                       "content", "content_sha256", "parse_status"})
        self.assertEqual(record, dict(ref="h03-basic:" + digest(module_bytes), horse_key="hkjc:HK-001",
                                      profile_id=None, source_time="2026-07-18T00:00:00Z",
                                      source_ref=SOURCE_REF, content=module_bytes.decode(),
                                      content_sha256=digest(module_bytes), parse_status="complete"))
        self.assertNotEqual(record["content"].encode(), raw)
        plan = self.plan(record)
        self.assertEqual(plan["decisions"][0]["status"], "reusable")
        self.assertEqual(plan["candidates"][0]["content"], record["content"])
        self.assertEqual(plan["candidates"][0]["identity_evidence"], self.snapshot()["identities"])
        self.assertFalse(plan["complete"])
        self.assertFalse(plan["published"])
        with self.assertRaises(adapter.CacheReuseAdapterError) as caught:
            adapter.adapt_hkjc_source_cache(raw, expected_sha256=digest(raw), ref="cache:a148", source_ref=SOURCE_REF)
        self.assertEqual(caught.exception.code, "cache_validation")

    def test_all_seven_fields_are_required_and_must_be_nonempty_strings(self):
        produce, = self.need(adapter, "produce_hkjc_basic_module")
        for field in FIELDS:
            for invalid in (None, "", "  ", 0, False):
                with self.subTest(field=field, invalid=invalid):
                    value = self.carrier(); value["basic_profile"][field] = invalid
                    raw = encoded(value)
                    with self.assertRaises(DOMAIN_ERRORS):
                        produce(raw, **self.source_kwargs(raw))
            with self.subTest(field=field, missing=True):
                value = self.carrier(); value["basic_profile"].pop(field)
                raw = encoded(value)
                with self.assertRaises(DOMAIN_ERRORS):
                    produce(raw, **self.source_kwargs(raw))

    def test_dates_model_lengths_and_existing_birth_year_consistency_are_checked(self):
        produce, = self.need(adapter, "produce_hkjc_basic_module")
        for field, invalid in (("birth_date", "2020-02-30"), ("birth_date", "2021-09-14"),
                               ("country", "x" * 129), ("sex", "x" * 65), ("color", "x" * 129),
                               ("owner_name", "x" * 256), ("trainer_name", "x" * 256),
                               ("breeder_name", "x" * 256)):
            with self.subTest(field=field, invalid=invalid):
                value = self.carrier(); value["basic_profile"][field] = invalid
                raw = encoded(value)
                with self.assertRaises(DOMAIN_ERRORS):
                    produce(raw, **self.source_kwargs(raw))

    def test_provider_identity_scope_and_source_time_cannot_be_inferred(self):
        produce, = self.need(adapter, "produce_hkjc_basic_module")
        cases = (("region", "japan"), ("adapter_key", "other"), ("schema_version", "other"),
                 ("source.name", "other"), ("source.external_horse_id", ""),
                 ("source.external_horse_id", "OTHER"),
                 ("source.external_horse_id", "__legacy_existing_cache_validation_only__"),
                 ("source.url", "https://example.test/Horse.aspx?HorseId=HK-001"),
                 ("source.url", "https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=OTHER"),
                 ("source.url", "http://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK-001"),
                 ("source.url", "https://user:pass@racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK-001"),
                 ("source.url", "https://racing.hkjc.com:444/racing/information/English/Horse/Horse.aspx?HorseId=HK-001"),
                 ("source.url", "https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK-001#x"),
                 ("source.url", "https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK-001&HorseId=HK-001"),
                 ("source.fetched_at", "2026-07-18T00:00:00"),
                 ("source.fetched_at", "2026-07-18T08:00:00+08:00"), ("source.fetched_at", None))
        for key, invalid in cases:
            with self.subTest(key=key, invalid=invalid):
                value = self.carrier()
                if key.startswith("source."):
                    value["source"][key.split(".")[1]] = invalid
                else:
                    value[key] = invalid
                raw = encoded(value)
                with self.assertRaises(DOMAIN_ERRORS):
                    produce(raw, **self.source_kwargs(raw))

    def test_explicit_selected_failures_and_manual_markers_are_not_erased(self):
        produce, = self.need(adapter, "produce_hkjc_basic_module")
        for change in (dict(failure_reason=["identity_mismatch"]), dict(manual_supplements=[{}]),
                       dict(coverage={"basic_profile": {"complete": False}}),
                       dict(coverage={"source_evidence": {"complete": False}}),
                       dict(coverage={"basic_profile": {"complete": True, "failure_reason": ["source_conflict"]}})):
            with self.subTest(change=change):
                value = self.carrier(); value.update(change)
                raw = encoded(value)
                with self.assertRaises(DOMAIN_ERRORS):
                    produce(raw, **self.source_kwargs(raw))
                self.assertEqual(json.loads(raw), value)

    def test_original_hash_json_and_permission_binding_shape_are_checked(self):
        produce, = self.need(adapter, "produce_hkjc_basic_module")
        raw = encoded(self.carrier())
        with self.assertRaises(DOMAIN_ERRORS):
            produce(raw + b" ", **self.source_kwargs(raw))
        for bad_sha in (None, "", True, "bad"):
            with self.subTest(expected_sha=bad_sha), self.assertRaises(DOMAIN_ERRORS):
                produce(raw, **dict(self.source_kwargs(raw), expected_sha256=bad_sha))
        # Keep valid module premises when testing raw JSON guards.
        value = self.carrier(); value["raw_payload"] = {"unselected_score": 1.5}
        finite = encoded(value)
        self.assertEqual(produce(finite, **self.source_kwargs(finite)), self.expected_module(finite))
        value["raw_payload"]["unselected_score"] = float("nan")
        nonfinite = (json.dumps(value, allow_nan=True) + "\n").encode()
        duplicate = raw.replace(b'"schema_version": "p0-horse-source-cache.v2",',
                                b'"schema_version": "p0-horse-source-cache.v2", "schema_version": "p0-horse-source-cache.v2",', 1)
        self.assertNotEqual(duplicate, raw)
        nested = "leaf"
        for _ in range(70): nested = [nested]
        value = self.carrier(); value["raw_payload"] = nested
        overdeep = encoded(value)
        for bad in (duplicate, nonfinite, overdeep, b"\xff", b'{"x":1,"x":2}', b'{"x":NaN}', b"x" * 131073):
            with self.subTest(raw=bad[:30]), self.assertRaises(DOMAIN_ERRORS):
                produce(bad, **self.source_kwargs(bad))
        for binding in ({}, dict(reference=PERMISSION_REF, sha256="bad"), dict(reference="/path", sha256="a" * 64)):
            with self.subTest(binding=binding), self.assertRaises(DOMAIN_ERRORS):
                produce(raw, **dict(self.source_kwargs(raw), permission_binding=binding))

    def test_bridge_rebuilds_projection_source_and_permission_binding_not_self_reported_complete(self):
        raw = encoded(self.carrier())
        original = self.make_module(raw)
        bridge, = self.need(adapter, "basic_module_to_h02_record")
        for changed in ("projection", "source", "permission", "schema", "producer"):
            module = deepcopy(original)
            if changed == "projection":
                module["projection"]["owner_name"] = "Forged"
                module["projection_sha256"] = digest(canonical(module["projection"]))
            elif changed == "source":
                module["source_binding"]["source_sha256"] = "a" * 64
            elif changed == "permission":
                module["permission_binding"]["sha256"] = "b" * 64
            elif changed == "schema":
                module["schema_version"] = "p0-horse-source-cache.v2"
            else:
                module["producer_version"] = "unreviewed.v2"
            with self.subTest(changed=changed), self.assertRaises(DOMAIN_ERRORS):
                bridge(module, raw_bytes=raw, **self.source_kwargs(raw))
        whole_raw = encoded(self.whole())
        whole_record = adapter.adapt_hkjc_source_cache(whole_raw, expected_sha256=digest(whole_raw),
                                                      ref="cache:whole", source_ref=SOURCE_REF)
        with self.assertRaises(DOMAIN_ERRORS):
            bridge(whole_record, raw_bytes=whole_raw, **self.source_kwargs(whole_raw))

    def test_actual_h02_keeps_identity_revocation_and_missing_versions_closed(self):
        record = self.bridge(encoded(self.carrier()))
        for status in ("observed", "retired", "rejected"):
            snapshot = self.snapshot(); snapshot["identities"][0]["status"] = status
            snapshot["layers"] = []
            with self.subTest(status=status):
                plan = self.plan(record, snapshot=snapshot, versions={})
                self.assertEqual(plan["decisions"][0]["status"], "insufficient")
                self.assertIn("strong_identity_missing", plan["decisions"][0]["reasons"])
                self.assertEqual(plan["candidates"], [])
        plan = self.plan(record, versions={})
        self.assertIn("entity_version_missing", plan["decisions"][0]["reasons"])
        self.assertEqual(plan["candidates"], [])
        snapshot = self.snapshot(); snapshot["layers"] = []
        snapshot["identities"].append(identity("hkjc:HK-001", profile=2))
        conflict = self.plan(record, snapshot=snapshot, versions={})
        self.assertEqual(conflict["decisions"][0]["status"], "identity_conflict")
        self.assertEqual(conflict["candidates"], [])

    def test_actual_h02_hash_ttl_future_and_latest_partial_rules_remain(self):
        record = self.bridge(encoded(self.carrier()))
        bad = dict(record, content=record["content"] + " ")
        plan = self.plan(bad)
        self.assertIn("content_hash_mismatch", plan["decisions"][0]["reasons"])
        self.assertIsNone(plan["candidates"][0]["content"])
        self.assertEqual(self.plan(record)["decisions"][0]["status"], "reusable")
        self.assertIn("cache_expired", self.plan(record, max_age=MAX_AGE - 1)["decisions"][0]["reasons"])
        future = dict(record, source_time="2026-10-04T00:00:00Z")
        self.assertIn("source_time_future", self.plan(future)["decisions"][0]["reasons"])
        newer_partial = dict(record, ref="cache:new-partial", source_time="2026-10-03T00:00:00Z", parse_status="partial")
        plan = plan_cache_reuse(self.snapshot(), [record, newer_partial], {"profile:1": VERSION},
                                as_of=AS_OF, max_age_seconds=MAX_AGE)
        self.assertIn("cache_partial", plan["decisions"][0]["reasons"])
        self.assertEqual(plan["decisions"][0]["cache_refs"], ["cache:new-partial"])
        self.assertIsNone(plan["candidates"][0]["content"])

    def test_actual_h02_same_time_conflict_and_explicit_module_versions_remain(self):
        first_raw = encoded(self.carrier())
        second_value = self.carrier(); second_value["basic_profile"]["owner_name"] = "Another fixture owner"
        first, second = self.bridge(first_raw), self.bridge(encoded(second_value))
        plan = plan_cache_reuse(self.snapshot(), [first, second], {"profile:1": VERSION},
                                as_of=AS_OF, max_age_seconds=MAX_AGE)
        self.assertEqual(plan["decisions"][0]["status"], "cache_conflict")
        self.assertEqual(plan["candidates"], [])
        original = self.plan(first)["candidates"][0]
        changed = self.plan(first, versions={"profile:1": "h03-basic-v1:a148-generation-2"})["candidates"][0]
        self.assertNotEqual(original["idempotency_key"], changed["idempotency_key"])

    def test_module_packet_reader_is_explicit_and_does_not_reinterpret_legacy_schema(self):
        read, = self.need(preparation, "_strict_basic_module_packet")
        raw = encoded(self.carrier())
        packet = self.packet(raw)
        self.assertEqual(read(encoded(packet)), packet)
        for change in ("legacy", "extra", "missing", "bool_age", "negative_age"):
            value = deepcopy(packet)
            if change == "legacy": value["schema_version"] = "h03-prepare-input.v1"
            elif change == "extra": value["synthetic"] = True
            elif change == "missing": value.pop("expected_source_sha256")
            elif change == "bool_age": value["max_age_seconds"] = True
            else: value["max_age_seconds"] = -1
            with self.subTest(change=change), self.assertRaises(DOMAIN_ERRORS):
                read(encoded(value))
        with self.assertRaises(DOMAIN_ERRORS):
            read(b'{"schema_version":1,"schema_version":2}')

    def test_prepare_rebuilds_actual_producer_and_h02_without_full_payload_laundering(self):
        raw = encoded(self.carrier())
        module, plan, candidate = self.prepared(raw)
        self.assertEqual(module, self.expected_module(raw))
        self.assertEqual(plan, self.plan(self.bridge(raw)))
        self.assertEqual(candidate, plan["candidates"][0])
        self.assertEqual(candidate["action"], "reusable")
        self.assertEqual(candidate["entity_version"], VERSION)
        self.assertNotIn("failure_reason", module)
        self.assertFalse(plan["published"])

    def test_prepare_rejects_binding_scope_version_identity_and_private_state_drift(self):
        prepare, = self.need(preparation, "_prepare_basic_module")
        raw = encoded(self.carrier())
        # A positive precondition is essential before each one-field negative group.
        self.prepared(raw)
        for change in ("source_sha", "permission_sha", "producer", "old_schema", "version", "identity", "public"):
            packet = self.packet(raw)
            if change == "source_sha": packet["expected_source_sha256"] = "a" * 64
            elif change == "permission_sha": packet["expected_permission_sha256"] = "b" * 64
            elif change == "producer": packet["producer_version"] = "other.v2"
            elif change == "old_schema": packet["schema_version"] = "h03-prepare-input.v1"
            elif change == "version": packet["entity_versions"] = {"profile:1": "old-whole-generation"}
            elif change == "identity": packet["snapshot"]["identities"][0]["status"] = "retired"
            else: packet["snapshot"]["layers"][0]["public_state"] = "visible"
            with self.subTest(change=change), self.assertRaises(DOMAIN_ERRORS):
                prepare(packet, raw, digest(raw), permission_raw=PERMISSION_RAW)
        with self.assertRaises(DOMAIN_ERRORS):
            prepare(self.packet(raw), raw, digest(raw), permission_raw=PERMISSION_RAW + b"changed")


class RealProfileFixture(ModuleFixture):
    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            self.fail("A148 ORM controls require a dedicated isolated PostgreSQL test database")
        self.actor = get_user_model().objects.create_user(username="a148-staff", is_staff=True, is_active=True)
        self.term = models.TermEntry.objects.create(term_type="horse", source_language="en",
                                                    source_ja="HARBOUR TEST", target_zh="", racing_region="hong_kong")
        self.profile = models.HorseProfile.objects.create(primary_term=self.term, original_name="HARBOUR TEST",
                                                          racing_region="hong_kong",
                                                          source_refs={"horse_identity_verified_keys": ["hkjc:HK-001"]})

    def state(self):
        return dict(profile=models.HorseProfile.objects.values().get(pk=self.profile.pk),
                    term=models.TermEntry.objects.values().get(pk=self.term.pk),
                    records=list(models.HorseRaceRecord.objects.filter(horse_profile=self.profile).values().order_by("pk")),
                    candidates=list(models.HorseProfileDataCandidate.objects.values().order_by("pk")),
                    logs=list(models.OperationLog.objects.values().order_by("pk")))

    def assert_real_premises(self):
        actor = get_user_model().objects.get(pk=self.actor.pk)
        profile = models.HorseProfile.objects.get(pk=self.profile.pk)
        self.assertTrue(actor.is_active and actor.is_staff)
        self.assertEqual(profile.review_status, models.HorseProfileStatus.DRAFT)
        self.assertIsNone(profile.hidden_at)
        self.assertEqual(profile.source_refs["horse_identity_verified_keys"], ["hkjc:HK-001"])
        self.assertEqual(profile.birth_date, None)
        self.assertTrue(all(not getattr(profile, key) for key in FIELDS if key != "birth_date"))
        # Actual H01/H02 proves the target binding even before any module cache exists.
        # This refresh candidate is not passed off as a reusable partial-module candidate.
        plan = plan_cache_reuse(self.snapshot(profile.pk), [], {f"profile:{profile.pk}": VERSION},
                                as_of=AS_OF, max_age_seconds=MAX_AGE)
        decision = plan["decisions"][0]
        self.assertEqual(decision["entity_key"], f"profile:{profile.pk}")
        self.assertEqual(decision["status"], "refresh_required")
        self.assertEqual(decision["reasons"], ["cache_missing"])
        self.assertTrue(decision["profile_exists"])
        self.assertEqual(decision["public_state"], "unpublished")
        self.assertIsNone(plan["candidates"][0]["content"])
        return profile


class LegacyWholeGateControls(RealProfileFixture, TransactionTestCase):
    def test_whole_source_has_real_h01_staff_private_profile_and_unchanged_h02_positive_control(self):
        self.assert_real_premises()
        before = self.state()
        raw = encoded(self.whole())
        record = adapter.adapt_hkjc_source_cache(raw, expected_sha256=digest(raw), ref="cache:whole", source_ref=SOURCE_REF)
        plan = self.plan(record, self.profile.pk)
        self.assertEqual(plan["decisions"][0]["status"], "reusable")
        self.assertEqual(plan["candidates"][0]["entity_key"], f"profile:{self.profile.pk}")
        self.assertEqual(record["content"].encode(), raw)
        self.assertEqual(self.state(), before)

    def test_original_partial_carriers_hit_exact_existing_whole_validator_and_adapter_gates(self):
        self.assert_real_premises()
        before = self.state()
        cases = (("missing_pedigree", "missing_two_generation_pedigree"),
                 ("partial_career", "partial_career: source_start_count does not match complete records"))
        for variant, reason in cases:
            raw = encoded(self.carrier(variant))
            with self.subTest(variant=variant):
                self.assertEqual(json.loads(raw)["basic_profile"], EXPECTED_BASIC)
                with self.assertRaises(P0HorseSourceBlocked) as caught:
                    validate_p0_horse_source_cache(json.loads(raw), allow_manual_supplements=False)
                self.assertEqual(str(caught.exception), reason)
                with self.assertRaises(adapter.CacheReuseAdapterError) as caught:
                    adapter.adapt_hkjc_source_cache(raw, expected_sha256=digest(raw), ref="cache:partial", source_ref=SOURCE_REF)
                self.assertEqual(caught.exception.code, "cache_validation")
                self.assertEqual(self.state(), before)

    def test_actual_new_module_candidate_and_original_partial_bytes_still_hit_old_writer_gate(self):
        self.assert_real_premises()
        raw = encoded(self.carrier())
        record = self.bridge(raw)  # Missing real producer/bridge => NOT_READY, never fabricated candidate.
        plan = self.plan(record, self.profile.pk)
        self.assertEqual(plan["decisions"][0]["status"], "reusable")
        self.assertEqual(plan["candidates"][0]["entity_key"], f"profile:{self.profile.pk}")
        self.assertEqual(json.loads(raw)["basic_profile"], EXPECTED_BASIC)
        before = self.state()
        result = consumer.apply_basic_profile_from_cache(
            snapshot=self.snapshot(self.profile.pk), candidate=plan["candidates"][0], raw_bytes=raw,
            expected_sha256=digest(raw), ref=record["ref"], source_ref=SOURCE_REF,
            entity_versions={f"profile:{self.profile.pk}": VERSION}, as_of=AS_OF, max_age_seconds=MAX_AGE,
            expected_updated_at=self.profile.updated_at, actor=self.actor,
        )
        self.assertEqual(result, dict(status="blocked", reason="input_invalid", published=False))
        self.assertEqual(self.state(), before)


class PublicModulePermissionDenialTests(RealProfileFixture, TransactionTestCase):
    def assert_fixed_denial(self, request):
        public, = self.need(consumer, "consume_reviewed_basic_module")
        before = self.state()
        with ExitStack() as stack:
            guards = []
            for name in ("apply_basic_profile_from_cache", "_apply_basic_module_transaction", "_apply_prepared_basic"):
                if hasattr(consumer, name):
                    guards.append(stack.enter_context(patch.object(consumer, name,
                                  side_effect=AssertionError("public consumer must not delegate"))))
            with CaptureQueriesContext(connection) as queries:
                result = public(request)
            self.assertEqual(result, DENIED)
            self.assertEqual(len(queries), 0, "public denial must not query actor/profile or write")
            for guard in guards:
                guard.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_public_entry_denies_modes_hashes_staff_synthetic_and_allow_flags_with_zero_db_or_delegation(self):
        self.need(consumer, "consume_reviewed_basic_module")
        self.assert_real_premises()
        base = dict(actor_id=self.actor.pk, profile_id=self.profile.pk, permission_binding=self.permission())
        callback_calls = []
        def untrusted_allow_callback():
            callback_calls.append(True)
            return True
        requests = [None, {}, base, dict(base, actor_id=999999),
                    dict(base, permission_checker=untrusted_allow_callback)]
        for key, value in (("synthetic", True), ("approved", True), ("allow", True),
                           ("trusted", True), ("authority_verified", True),
                           ("mode", "dry-run"), ("mode", "ignore"), ("mode", "commit"),
                           ("permission_file", "apparently-real-permission.json")):
            requests.append(dict(base, **{key: value}))
        for index, request in enumerate(requests):
            with self.subTest(request=index):
                self.assert_fixed_denial(request)
        self.assertEqual(callback_calls, [])

    def test_even_actual_module_prepare_and_live_staff_cannot_enable_public_application(self):
        self.need(consumer, "consume_reviewed_basic_module")
        self.assert_real_premises()
        raw = encoded(self.carrier())
        packet = self.packet(raw, self.profile.pk, self.profile.updated_at.isoformat())
        module, plan, candidate = self.prepared(raw, packet)
        self.assertEqual(module, self.expected_module(raw))
        self.assertEqual(candidate, plan["candidates"][0])
        self.assertEqual(candidate["action"], "reusable")
        self.assert_fixed_denial(dict(packet=packet, source_bytes=raw, module=module, plan=plan,
                                     candidate=candidate, actor_id=self.actor.pk,
                                     permission_bytes=PERMISSION_RAW, mode="commit"))
