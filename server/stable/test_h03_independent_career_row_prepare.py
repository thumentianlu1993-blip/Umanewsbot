"""A156 frozen test source: private offline career-row preparation only.

Proposed private API in stable.services.horse_independent_career_row_prepare:
  _project_hkjc_career_row(raw_bytes, *, expected_sha256, selected_row_sha256,
                         source_ref, permission_binding) -> module dict
  _career_row_h02_record(module, *, raw_bytes, expected_sha256,
                        selected_row_sha256, source_ref, permission_binding)
  _prepare_independent_career_row(*, packet, source_raw,
      expected_source_sha256, selected_row_sha256, permission_binding)

The existing h03-prepare-input.v1 packet is original bytes, not a new schema.
Module shape and fixed refusal reasons are frozen below for source review.
Absent APIs are NOT_READY skips; signature/dependency/system errors propagate.
Only actual callable business behavior can reach a RED/GREEN oracle. No stub,
old whole rejection PASS, or missing interface is historical business RED.
All data/permission references are inert synthetic fixtures, never grants.
"""
import hashlib
import importlib
import json
import re
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from stable.services.horse_cache_reuse import plan_cache_reuse
from stable.services.horse_target_inventory import plan_inventory
from stable.services.p0_horse_completion_adapters import (
    _normalize_race_record, normalize_p0_horse_race_records,
)
from stable.services import horse_source_cache_reuse_adapter as legacy
from stable.test_horse_target_inventory import document, event, identity, row

MODULE = "stable.services.horse_independent_career_row_prepare"
FIXTURE = Path(__file__).parent / "fixtures/h03_career_link/hkjc_synthetic.json"
FIXTURE_SHA = "a047233319c9e7764821331b9a532f876b1bd1fcdd7abd5f4586a2b73a3cbc32"
PARTIAL_RAW_SHA = "1bfde1336db9dc19c589f70bffd766d59591bc564bfe78c102dcae7af2321222"
SELECTED_SHA = "7bcf0992b12689f00ccb8dfa3462532e27182b9da64fb14b295f102067b7bf76"
AS_OF = "2026-07-18T00:01:00Z"
SOURCE_TIME = "2026-07-18T00:00:00Z"
TTL = 3600  # Explicit 60-second historical age; no claim of present freshness.
PROFILE = "profile:7"
VERSION = "h03-career-row-v1:a156-generation-1"
SOURCE_REF = "fixture:a156-hkjc-carrier"
PERMISSION_RAW = b"A156 inert digest binding, not source permission.\n"
DOMAIN_ERRORS = (ValueError, CommandError)
LABELS = dict(preparation_capability_only=True, source_permission_status="not_evaluated",
              public_consumer_authorized=False)
H02_FIELDS = {"ref", "horse_key", "profile_id", "source_time", "source_ref",
              "content", "content_sha256", "parse_status"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


class IndependentCareerRowPrepareTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        # Failure sentinels, never replacements for projection/identity success.
        for target in (
            "urllib.request.urlopen",
            "stable.services.p0_horse_completion_source_clients._HKJCClient._fetch",
            "stable.services.p0_horse_completion_adapters.run_p0_horse_completion_adapter",
            "stable.services.horse_race_records.upsert_race_record",
            "stable.services.horse_career_record_from_review._apply",
            "stable.services.horse_career_record_link_from_cache.apply_career_record_link_from_cache",
            "stable.services.horse_profiles.apply_data_candidate",
            "stable.services.horse_profile_publish.auto_publish_profiles",
        ):
            guard = patch(target, side_effect=AssertionError("A156 network/write/consumer forbidden"))
            mocked = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(mocked.assert_not_called)
        fixture_raw = FIXTURE.read_bytes()
        self.assertEqual(digest(fixture_raw), FIXTURE_SHA)
        self.carrier = json.loads(fixture_raw)
        self.carrier["career"]["records"] = self.carrier["career"]["records"][:1]
        self.carrier["career"]["source_start_count"] = 2
        self.raw = encoded(self.carrier)
        self.selected = deepcopy(self.carrier["career"]["records"][0])
        self.row_sha = digest(canonical(self.selected))
        self.permission = dict(reference="fixture:a156-inert-permission", sha256=digest(PERMISSION_RAW))
        self.assertEqual(digest(self.raw), PARTIAL_RAW_SHA)
        self.assertEqual(self.row_sha, SELECTED_SHA)
        # These are real existing H01/normalizer preconditions, not mocked new APIs.
        normalized = _normalize_race_record(self.selected)
        self.assertEqual((normalized["start_status"], normalized["result_status"],
                          normalized["race_date_precision"]), ("started", "did_not_finish", "exact"))
        parent = self.parent_history(self.raw)
        self.assertEqual((parent["official_or_source_start_count"], parent["collected_start_count"],
                          parent["missing_start_count"], parent["gap_count"], parent["status"]), (2, 1, 1, 1, "partial"))
        inventory = plan_inventory(self.snapshot())
        self.assertEqual([(t["key"], t["resolved"]) for t in inventory["targets"]], [(PROFILE, True)])

    def need(self):
        try:
            module = importlib.import_module(MODULE)
        except ModuleNotFoundError as error:
            if error.name == MODULE:
                self.skipTest("NOT_READY: " + MODULE)
            raise  # A missing transitive dependency is an ERROR, not NOT_READY.
        names = ("_project_hkjc_career_row", "_career_row_h02_record", "_prepare_independent_career_row")
        missing = [name for name in names if not hasattr(module, name)]
        if missing:
            self.skipTest("NOT_READY: " + MODULE + ":" + ",".join(missing))
        functions = tuple(getattr(module, name) for name in names)
        if not all(callable(function) for function in functions):
            raise TypeError("A156 private API attribute is not callable")
        return functions

    def snapshot(self):
        value = document()
        value.update(as_of="2026-07-18", snapshot_at=AS_OF,
                     events=[event(region="hong_kong", local_date="2026-07-17")],
                     participations=[row(horse_key="hkjc:HK-001", birth_year=2020)],
                     identities=[identity("hkjc:HK-001", profile=7, verified_at=SOURCE_TIME)],
                     layers=[dict(target_key=PROFILE, cache="present", staging="matched",
                                  profile_exists=True, public_state="unpublished", starts=None,
                                  incomplete_modules=None)])
        return value

    def packet(self, row_sha=None):
        return dict(schema_version="h03-prepare-input.v1", source_file="source.json",
                    cache_ref="h03-career-row:" + (row_sha or self.row_sha), source_ref=SOURCE_REF,
                    snapshot=self.snapshot(), entity_versions={PROFILE: VERSION}, as_of=AS_OF,
                    max_age_seconds=TTL, profile_baseline=SOURCE_TIME)

    def source_args(self, raw=None, row_sha=None):
        raw = self.raw if raw is None else raw
        return dict(expected_sha256=digest(raw), selected_row_sha256=row_sha or self.row_sha,
                    source_ref=SOURCE_REF, permission_binding=deepcopy(self.permission))

    def project(self, raw=None, row_sha=None, **changes):
        produce, _, _ = self.need()
        raw = self.raw if raw is None else raw
        return produce(raw, **dict(self.source_args(raw, row_sha), **changes))

    def bridge(self, raw=None, row_sha=None, module=None, **changes):
        _, bridge, _ = self.need()
        raw = self.raw if raw is None else raw
        module = self.project(raw, row_sha) if module is None else module
        return bridge(module, raw_bytes=raw, **dict(self.source_args(raw, row_sha), **changes))

    def prepare(self, raw=None, row_sha=None, packet=None, **changes):
        _, _, prepare = self.need()
        raw = self.raw if raw is None else raw
        row_sha = row_sha or self.row_sha
        args = dict(packet=encoded(self.packet(row_sha) if packet is None else packet),
                    source_raw=raw, expected_source_sha256=digest(raw), selected_row_sha256=row_sha,
                    permission_binding=deepcopy(self.permission))
        return prepare(**dict(args, **changes))

    def parent_history(self, raw):
        career = json.loads(raw)["career"]
        return normalize_p0_horse_race_records(
            career["records"], source_start_count=career["source_start_count"],
            official_start_count_source=career.get("official_start_count_source", ""),
            official_start_count_source_url=career.get("official_start_count_source_url", ""),
            official_start_count_verified_at=career.get("official_start_count_verified_at", ""),
            record_authority_status=career.get("record_authority_status", "unknown"))["career_history"]

    def assert_refused(self, invoke, reason):
        # TypeError/AttributeError/RuntimeError must remain ERRORs, not business RED.
        with self.assertRaisesRegex(DOMAIN_ERRORS, "^" + re.escape(reason) + "$"):
            invoke()

    def assert_module(self, module, raw=None, row_sha=None):
        raw = self.raw if raw is None else raw
        row_sha = row_sha or self.row_sha
        source = json.loads(raw)
        selected = [r for r in source["career"]["records"] if digest(canonical(r)) == row_sha]
        self.assertEqual(len(selected), 1)
        projection = _normalize_race_record(selected[0])
        expected = dict(validation_scope="career_row",
                        source_binding=dict(source_ref=SOURCE_REF, raw_sha256=digest(raw), source_name="hkjc",
                                            external_horse_id="HK-001", horse_key="hkjc:HK-001",
                                            url=source["source"]["url"], fetched_at=source["source"]["fetched_at"]),
                        selected_row=selected[0], selected_row_sha256=row_sha,
                        projection=projection, projection_sha256=digest(canonical(projection)),
                        coverage=dict(parent_career=self.parent_history(raw),
                                      selected_row=dict(status="complete", record_count=1, actual_start_count=1)),
                        permission_binding=self.permission, **LABELS)
        self.assertEqual(module, expected)
        self.assertIsNone(module["projection"]["event_id"])
        self.assertIsNone(module["projection"]["result_id"])
        self.assertNotIn("basic_profile", module["projection"])
        self.assertNotIn("pedigree", module["projection"])
        self.assertEqual(canonical(module), canonical(expected))  # Includes exact JSON scalar types.

    def test_valid_pu_row_is_complete_while_parent_total_two_observed_one_stays_partial(self):
        module = self.project()
        self.assert_module(module)
        for overrides in ({}, dict(start_status="started"),
                          dict(start_status="started", result_status="did_not_finish")):
            value = deepcopy(self.carrier);selected = value["career"]["records"][0]
            selected.update(overrides);raw = encoded(value);row_sha = digest(canonical(selected))
            self.assert_module(self.project(raw, row_sha), raw, row_sha)
            for fields in ((), ("start_status",), ("start_status", "result_status")):
                inferred = _normalize_race_record({k: v for k, v in selected.items() if k not in fields})
                self.assertEqual((inferred["start_status"], inferred["result_status"]), ("started", "did_not_finish"))
        coverage = module["coverage"]["parent_career"]
        self.assertIn("source_start_count_missing:1", coverage["blocker_reasons"])
        self.assertEqual(json.loads(self.raw)["career"]["source_start_count"], 2)
        # This is a legacy compatibility assertion after the new positive oracle.
        # Its existing refusal PASS must never be counted as new business RED.
        with self.assertRaisesRegex(legacy.CacheReuseAdapterError, "^cache_validation$"):
            legacy.adapt_hkjc_source_cache(self.raw, expected_sha256=digest(self.raw),
                                          ref="cache:a156-old-whole", source_ref=SOURCE_REF)

    def test_bridge_uses_exact_h02_eight_fields_and_complete_only_for_scoped_content(self):
        record = self.bridge()
        module = self.project()
        self.assertEqual(set(record), H02_FIELDS)
        self.assertEqual(record, dict(ref="h03-career-row:" + self.row_sha, horse_key="hkjc:HK-001",
                                     profile_id=None, source_time=SOURCE_TIME, source_ref=SOURCE_REF,
                                     content=canonical(module).decode(), content_sha256=digest(canonical(module)),
                                     parse_status="complete"))
        self.assertNotEqual(record["content"], self.raw.decode())
        self.assertNotEqual(record["content_sha256"], digest(self.raw))
        content = json.loads(record["content"])
        self.assertEqual(content["validation_scope"], "career_row")
        self.assertEqual(content["coverage"]["parent_career"]["status"], "partial")
        actual = plan_cache_reuse(self.snapshot(), [record], {PROFILE: VERSION}, as_of=AS_OF, max_age_seconds=TTL)
        self.assertEqual((actual["decisions"][0]["status"], actual["candidates"][0]["action"]), ("reusable", "reusable"))
        self.assertEqual(actual["candidates"][0]["entity_key"], PROFILE)

    def test_prepare_rebuilds_real_h01_h02_and_binds_raw_row_projection_packet_and_version(self):
        packet = self.packet()
        result = self.prepare(packet=packet)
        module, record = self.project(), self.bridge()
        plan = plan_cache_reuse(packet["snapshot"], [record], packet["entity_versions"], as_of=AS_OF, max_age_seconds=TTL)
        candidate = plan["candidates"][0]
        self.assertEqual(set(result), {"row_module", "record", "plan", "candidate", "binding", "writer_payload",
                                      *LABELS, "committed", "published", "record_id", "candidate_id"})
        self.assertEqual((result["row_module"], result["record"], result["plan"], result["candidate"]),
                         (module, record, plan, candidate))
        self.assertEqual(result["writer_payload"], module["projection"])
        self.assertEqual(result["binding"], dict(
            source_sha256=digest(self.raw), selected_row_sha256=self.row_sha,
            projection_sha256=module["projection_sha256"], module_sha256=digest(canonical(module)),
            packet_sha256=digest(encoded(packet)), entity_versions_sha256=digest(canonical(packet["entity_versions"])),
            entity_key=PROFILE, entity_version=VERSION, h02_idempotency_key=candidate["idempotency_key"],
            h02_plan_sha256=plan["content_sha256"], permission_binding=self.permission, source_ref=SOURCE_REF))
        for key, value in LABELS.items(): self.assertIs(result[key], value) if isinstance(value, bool) else self.assertEqual(result[key], value)
        self.assertIs(result["committed"], False);self.assertIs(result["published"], False)
        self.assertIsNone(result["record_id"]);self.assertIsNone(result["candidate_id"])
        self.assertEqual(candidate["identity_evidence"], [identity("hkjc:HK-001", profile=7, verified_at=SOURCE_TIME)])

    def test_original_byte_digests_and_unique_selected_row_are_required(self):
        produce, _, _ = self.need()
        for args, reason in ((dict(expected_sha256="0" * 64), "row_source_digest"),
                             (dict(expected_sha256=True), "row_source_digest"),
                             (dict(selected_row_sha256="bad"), "row_selected_digest"),
                             (dict(selected_row_sha256="0" * 64), "row_selection_missing_or_ambiguous")):
            with self.subTest(args=args): self.assert_refused(lambda: self.project(**args), reason)
        duplicate = deepcopy(self.carrier);duplicate["career"]["records"].append(deepcopy(self.selected))
        self.assert_refused(lambda: self.project(encoded(duplicate)), "row_selection_missing_or_ambiguous")
        self.assert_refused(lambda: produce("not bytes", **self.source_args()), "row_input_bytes")
        self.assert_refused(lambda: self.project(b" " * (128 * 1024 + 1)), "row_input_bytes")
        self.assert_refused(lambda: self.project(self.raw + b" ", expected_sha256=digest(self.raw)), "row_source_digest")

    def test_strict_original_json_manual_markers_explicit_failure_and_source_scope_reject(self):
        self.need()
        malformed = (b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff', b'[]')
        for raw in malformed:
            with self.subTest(raw=raw): self.assert_refused(lambda: self.project(raw), "row_json")
        for marker in (dict(manual_supplements=[]), dict(manual_supplement_outcomes={}),
                       dict(entry_method="manual_review"), dict(evidence_role="manual_supplement")):
            value = deepcopy(self.carrier);value["unselected_metadata"] = marker
            with self.subTest(marker=marker): self.assert_refused(lambda: self.project(encoded(value)), "row_manual_marker")
        for where in ("root", "source"):
            value = deepcopy(self.carrier)
            (value if where == "root" else value["source"])["failure_reason"] = "synthetic-failure"
            with self.subTest(where=where): self.assert_refused(lambda: self.project(encoded(value)), "row_source_failed")
        for changes in (dict(region="japan"), dict(adapter_key="japan_netkeiba"), dict(schema_version="other")):
            value = deepcopy(self.carrier);value.update(changes)
            with self.subTest(changes=changes): self.assert_refused(lambda: self.project(encoded(value)), "row_source_scope")

    def test_provider_and_row_strong_identity_never_use_name_or_filled_event(self):
        self.need()
        for changes in (dict(external_horse_id="other"), dict(url="https://example.test/HorseId=HK-001"),
                        dict(url=self.carrier["source"]["url"] + "&HorseId=other")):
            value = deepcopy(self.carrier);value["source"].update(changes)
            with self.subTest(source=changes): self.assert_refused(lambda: self.project(encoded(value)), "row_source_identity")
        for field in ("provider", "region", "operator", "identity_namespace", "external_horse_id",
                      "external_race_id", "venue_key", "race_number", "timezone", "source_name", "source_url"):
            value = deepcopy(self.carrier);value["career"]["records"][0].pop(field)
            selected = value["career"]["records"][0];selected_sha = digest(canonical(selected))
            with self.subTest(missing=field): self.assert_refused(lambda: self.project(encoded(value), selected_sha), "row_identity")
        for changes in (dict(external_horse_id="HK-OTHER"), dict(provider="netkeiba"),
                        dict(timezone="UTC"), dict(event_id=1), dict(result_id=1)):
            value = deepcopy(self.carrier);value["career"]["records"][0].update(changes)
            selected_sha = digest(canonical(value["career"]["records"][0]))
            with self.subTest(row=changes): self.assert_refused(lambda: self.project(encoded(value), selected_sha), "row_identity")

    def test_finish_evidence_cannot_be_overridden_by_started_or_result_status(self):
        self.need()
        cases = (dict(finish="WV"), dict(finish="WV", start_status="started"),
                 dict(finish="WV", result_status="won"), dict(finish="UNKNOWN"),
                 dict(finish="WV", result_status="won", start_status="started"),
                 dict(finish="UNKNOWN", result_status="did_not_finish", start_status="started"),
                 dict(finish="PU", start_status="did_not_start"),
                 dict(finish="PU", result_status="withdrawn"), dict(race_date="2025"))
        for changes in cases:
            value = deepcopy(self.carrier);value["career"]["records"][0].update(changes)
            selected_sha = digest(canonical(value["career"]["records"][0]))
            with self.subTest(changes=changes): self.assert_refused(lambda: self.project(encoded(value), selected_sha), "row_not_started_exact")

    def test_original_distance_units_raw_sources_and_selected_provenance_are_preserved(self):
        self.need()
        for distance in ("1400m", "1 mile", "8 furlongs"):
            value = deepcopy(self.carrier);selected = value["career"]["records"][0]
            selected["distance_text"] = distance
            raw = encoded(value);selected_sha = digest(canonical(selected))
            module = self.project(raw, selected_sha)
            self.assert_module(module, raw, selected_sha)
            self.assertEqual(module["selected_row"], selected)
            self.assertEqual(module["projection"]["distance_text"], distance)
            self.assertEqual(module["projection"]["source_name"], selected["source_name"])
            self.assertEqual(module["projection"]["source_url"], selected["source_url"])
            self.assertIsNone(module["projection"].get("distance_meters"))
            self.assertIsNone(module["projection"].get("distance_meters_normalized"))

    def test_parent_scope_counts_all_rows_while_two_selected_rows_share_only_h02_key(self):
        self.need()
        value = deepcopy(self.carrier)
        second = dict(self.selected, race_name="Later ordinary race", race_date="2025-12-14",
                      race_number="1", external_race_id="HK-20251214-1", finish="4",
                      source_url="https://example.test/hkjc/race/HK-20251214-1")
        value["career"]["records"].append(second);raw = encoded(value)
        row_hashes = [digest(canonical(item)) for item in value["career"]["records"]]
        results = [self.prepare(raw, row_sha) for row_sha in row_hashes]
        for result in results:
            module = result["row_module"]
            parent = module["coverage"]["parent_career"]
            self.assertEqual((parent["official_or_source_start_count"], parent["collected_start_count"],
                              parent["gap_count"], parent["status"]), (2, 2, 0, "complete"))
            self.assertEqual(module["coverage"]["selected_row"], dict(status="complete", record_count=1, actual_start_count=1))
            self.assertFalse(result["committed"]);self.assertIsNone(result["record_id"])
        self.assertNotEqual(row_hashes[0], row_hashes[1])
        self.assertNotEqual(results[0]["record"]["ref"], results[1]["record"]["ref"])
        self.assertNotEqual(results[0]["binding"]["projection_sha256"], results[1]["binding"]["projection_sha256"])
        self.assertNotEqual(results[0]["binding"]["selected_row_sha256"], results[1]["binding"]["selected_row_sha256"])
        expected_key = digest(canonical(dict(entity_key=PROFILE, entity_version=VERSION)))
        self.assertEqual([r["candidate"]["idempotency_key"] for r in results], [expected_key, expected_key])

    def test_real_h01_weak_conflicting_or_future_identity_cannot_prepare_target(self):
        self.need()
        variants = []
        for status in ("observed", "rejected", "retired"):
            packet = self.packet();packet["snapshot"]["identities"][0]["status"] = status;variants.append(packet)
        packet = self.packet();packet["snapshot"]["identities"] = [];variants.append(packet)
        packet = self.packet();packet["snapshot"]["identities"].append(identity("hkjc:HK-001", profile=8, verified_at=SOURCE_TIME));variants.append(packet)
        packet = self.packet();packet["snapshot"]["identities"][0]["verified_at"] = "2026-10-02T00:00:00Z";variants.append(packet)
        for number, packet in enumerate(variants):
            with self.subTest(number=number): self.assert_refused(lambda: self.prepare(packet=packet), "row_h02_not_reusable")

    def test_preparation_requires_existing_unpublished_snapshot_and_explicit_version(self):
        self.need()
        variants = []
        for state in ("visible", "hidden", "blocked", "unknown"):
            packet = self.packet();packet["snapshot"]["layers"][0]["public_state"] = state;variants.append(packet)
        for exists in (False, None):
            packet = self.packet();packet["snapshot"]["layers"][0]["profile_exists"] = exists;variants.append(packet)
        packet = self.packet();packet["entity_versions"] = {};variants.append(packet)
        for number, packet in enumerate(variants):
            with self.subTest(number=number): self.assert_refused(lambda: self.prepare(packet=packet), "row_h02_not_reusable")

    def test_historical_ttl_boundary_keeps_original_h02_meaning_without_clock_extension(self):
        self.need()
        packet = self.packet();packet["max_age_seconds"] = 60
        result = self.prepare(packet=packet)
        self.assertEqual((result["plan"]["as_of"], result["plan"]["max_age_seconds"]), (AS_OF, 60))
        packet["max_age_seconds"] = 59
        self.assert_refused(lambda: self.prepare(packet=packet), "row_h02_not_reusable")
        value = deepcopy(self.carrier);value["source"]["fetched_at"] = "2026-07-18T00:01:01Z"
        self.assert_refused(lambda: self.prepare(encoded(value)), "row_h02_not_reusable")
        packet = self.packet();packet["max_age_seconds"] = True
        self.assert_refused(lambda: self.prepare(packet=packet), "row_input_packet")

    def test_raw_byte_and_entity_version_drift_are_separately_bound(self):
        self.need()
        first = self.prepare()
        changed_raw = self.prepare(self.raw + b" ")
        self.assertNotEqual(first["binding"]["source_sha256"], changed_raw["binding"]["source_sha256"])
        self.assertNotEqual(first["binding"]["module_sha256"], changed_raw["binding"]["module_sha256"])
        self.assertEqual(first["binding"]["projection_sha256"], changed_raw["binding"]["projection_sha256"])
        self.assertEqual(first["binding"]["selected_row_sha256"], changed_raw["binding"]["selected_row_sha256"])
        packet = self.packet();packet["entity_versions"][PROFILE] = "h03-career-row-v1:a156-generation-2"
        changed_version = self.prepare(packet=packet)
        for key in ("packet_sha256", "entity_versions_sha256", "h02_idempotency_key"):
            self.assertNotEqual(first["binding"][key], changed_version["binding"][key])
        self.assertEqual(changed_version["binding"]["entity_version"], packet["entity_versions"][PROFILE])
        self.assertEqual(first["binding"]["projection_sha256"], changed_version["binding"]["projection_sha256"])
        self.assert_refused(lambda: self.prepare(self.raw + b" ", expected_source_sha256=digest(self.raw)), "row_source_digest")

    def test_bridge_rebuild_rejects_forged_module_hash_projection_coverage_or_complete_dict(self):
        self.need()
        module = self.project()
        mutations = (
            lambda m: m["source_binding"].update(raw_sha256="0" * 64),
            lambda m: m.update(selected_row_sha256="0" * 64),
            lambda m: m["projection"].update(distance_text="fabricated"),
            lambda m: m["coverage"]["parent_career"].update(status="complete", gap_count=0),
            lambda m: m.update(source_permission_status="granted", public_consumer_authorized=True),
        )
        for number, mutate in enumerate(mutations):
            bad = deepcopy(module);mutate(bad)
            with self.subTest(number=number): self.assert_refused(lambda: self.bridge(module=bad), "row_projection_binding")
        self.assert_refused(lambda: self.bridge(module={"parse_status": "complete"}), "row_projection_binding")
        self.assert_refused(lambda: self.bridge(self.raw + b" ", module=module), "row_projection_binding")

    def test_unselected_basic_pedigree_are_not_fabricated_or_needed_for_row_projection(self):
        self.need()
        for removed in (("pedigree",), ("basic_profile",), ("basic_profile", "pedigree")):
            value = deepcopy(self.carrier)
            for field in removed: value.pop(field)
            raw = encoded(value);result = self.prepare(raw)
            self.assert_module(result["row_module"], raw)
            self.assertEqual(result["writer_payload"], _normalize_race_record(self.selected))
            self.assertEqual(result["row_module"]["coverage"]["parent_career"]["status"], "partial")
            self.assertFalse(result["published"]);self.assertFalse(result["committed"])

    def test_inert_permission_binding_determinism_and_owned_outputs_never_consume_records(self):
        self.need()
        packet = self.packet();before_packet = deepcopy(packet);before_permission = deepcopy(self.permission)
        result = self.prepare(packet=packet)
        self.assertEqual(result, self.prepare(packet=packet))
        result["row_module"]["selected_row"]["race_name"] = "caller mutation"
        result["binding"]["permission_binding"]["reference"] = "caller mutation"
        self.assertEqual(packet, before_packet);self.assertEqual(self.permission, before_permission)
        fresh = self.prepare(packet=packet)
        self.assertEqual(fresh["row_module"]["selected_row"], self.selected)
        for key, value in LABELS.items(): self.assertEqual(fresh[key], value)
        self.assertEqual((fresh["published"], fresh["committed"], fresh["record_id"], fresh["candidate_id"]), (False, False, None, None))
        for binding in (dict(reference="fixture:a156-inert-permission", sha256="bad"),
                        dict(reference="fixture:a156-inert-permission", sha256=digest(PERMISSION_RAW), grant=True)):
            with self.subTest(binding=binding): self.assert_refused(lambda: self.project(permission_binding=binding), "row_permission_binding")
