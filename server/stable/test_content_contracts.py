"""F01 approved fixtures exercise the application contract, without Django setup."""
import copy
import json
from pathlib import Path
import unittest

from stable.services import content_contracts as contracts

FIXTURES = Path(__file__).resolve().parents[2] / 'docs/changes/next-version-capabilities/lanes/A/F01-contract-examples.json'


class ContentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURES.read_text())['cases']

    def test_approved_four_groups_roundtrip(self):
        for case in self.cases:
            with self.subTest(case=case['case_id']):
                document = contracts.parse_input(case['input'])
                self.assertEqual(document.to_dict(), case['input'])
                self.assertEqual(contracts.parse_input(document.to_json()).to_dict(), case['input'])
                decision = contracts.parse_decision(case['output'], input_document=document)
                self.assertEqual(decision.to_dict(), case['output'])
                self.assertIsNone(decision.to_dict()['public_summary'])

    def test_unknown_is_distinct_from_known_zero(self):
        data = contracts.parse_input(self.cases[3]['input']).to_dict()['snapshot']['materials']
        career = next(m['data'] for m in data if m['capability'] == 'career')
        self.assertIsNone(career['official_or_source_start_count'])
        self.assertEqual(career['known_zero_control']['official_or_source_start_count'], 0)
        self.assertIs(type(career['known_zero_control']['official_or_source_start_count']), int)

    def test_dto_owns_immutable_snapshot(self):
        original = copy.deepcopy(self.cases[0]['input'])
        document = contracts.parse_input(original)
        original['snapshot']['entity']['canonical_id'] = 'tampered'
        detached = document.to_dict()
        detached['snapshot']['entity']['canonical_id'] = 'changed'
        self.assertEqual(document.to_dict(), self.cases[0]['input'])
        with self.assertRaises((AttributeError, TypeError)):
            document.wire_json = '{}'

    def _bad_input(self, mutate):
        raw = copy.deepcopy(self.cases[1]['input'])
        mutate(raw)
        with self.assertRaises(contracts.ContractError):
            contracts.parse_input(raw)

    def test_strict_schema_required_fields_and_enums(self):
        for mutate in (
            lambda v: v.pop('policy_ref'),
            lambda v: v.update(secret_token='do-not-echo'),
            lambda v: v.update(schema_version='future.v2'),
            lambda v: v['snapshot']['entity'].update(kind='person'),
            lambda v: v['snapshot']['entity'].update(identity_state=None),
            lambda v: v['snapshot']['entity'].update(canonical_id='guessed'),
            lambda v: v['snapshot']['entity']['source_refs'][0].pop('source'),
            lambda v: v['snapshot']['protection'].update(paused=1),
            lambda v: v['input_version']['generations'].update(owner=True),
            lambda v: v.update(evaluated_at='2026-10-03'),
        ):
            with self.subTest(mutation=mutate):
                self._bad_input(mutate)

    def test_hash_protection_scope_and_reference_guards(self):
        for mutate in (
            lambda v: v['input_version']['scope'].reverse(),
            lambda v: v['input_version'].update(scope=['entity']),
            lambda v: v['input_version'].update(content_sha256='a' * 64),
            lambda v: v['snapshot']['protection'].pop('protection_sha256'),
            lambda v: v['snapshot']['protection'].update(fields=['horse.original_name']),
            lambda v: v['snapshot']['materials'][0]['evidence_refs'].append('missing'),
            lambda v: v['snapshot']['evidence'].append(v['snapshot']['evidence'][0]),
        ):
            with self.subTest(mutation=mutate):
                self._bad_input(mutate)

    def test_json_boundary_and_error_redaction(self):
        for raw in ('{"schema_version":1,"schema_version":2}', '{"x":NaN}', '{}', '[]', '{bad'):
            with self.subTest(raw=raw), self.assertRaises(contracts.ContractError) as exc:
                contracts.parse_input(raw)
            self.assertNotIn(raw, str(exc.exception))
        with self.assertRaises(contracts.ContractError):
            contracts.parse_input(' ' * (contracts.MAX_WIRE_BYTES + 1))
        cyclic = {}; cyclic['cycle'] = cyclic
        with self.assertRaises(contracts.ContractError):
            contracts.parse_input(cyclic)
        deep = None
        for _ in range(contracts.MAX_DEPTH + 2):
            deep = [deep]
        with self.assertRaises(contracts.ContractError):
            contracts.parse_input({'nested': deep})

    def test_producer_normalization_and_business_order(self):
        raw = self.cases[2]['input']
        snapshot = copy.deepcopy(raw['snapshot'])
        snapshot['evidence'].reverse()
        snapshot['materials'].reverse()
        built = contracts.build_input(snapshot, evaluated_at=raw['evaluated_at'],
            policy_ref=raw['policy_ref'], generations=raw['input_version']['generations'],
            scope=list(reversed(raw['input_version']['scope'])))
        self.assertEqual(built.to_dict(), raw)
        confirmed = next(m for m in snapshot['materials'] if m['maturity'] == 'confirmed')
        confirmed['data']['participants'].reverse()
        rebuilt = contracts.build_input(snapshot, evaluated_at=raw['evaluated_at'],
            policy_ref=raw['policy_ref'], generations=raw['input_version']['generations'],
            scope=raw['input_version']['scope'])
        self.assertNotEqual(rebuilt.to_dict()['input_version']['content_sha256'], raw['input_version']['content_sha256'])

    def test_decision_cannot_substitute_entity_version_or_private_fields(self):
        case = self.cases[1]
        document = contracts.parse_input(case['input'])
        for mutate in (
            lambda v: v.update(input_fingerprint='a' * 64),
            lambda v: v['entity']['source_refs'][0].pop('source'),
            lambda v: v['actions'][0]['expected_input_version'].update(content_sha256='b' * 64),
            lambda v: v.update(next_due_at='2026-10-03T02:00:00Z'),
            lambda v: v.update(execution_state='published'),
            lambda v: v.update(public_summary={'raw_artifact': '/private/source'}),
        ):
            candidate = copy.deepcopy(case['output']); mutate(candidate)
            with self.subTest(mutation=mutate), self.assertRaises(contracts.ContractError):
                contracts.parse_decision(candidate, input_document=document)

    def test_public_summary_has_no_private_evidence_or_protection(self):
        raw = dict(entity_ref=copy.deepcopy(self.cases[0]['input']['snapshot']['entity']),
            public_version='fixture-public-v1', material_state='confirmed', fact_phase='unknown',
            clock_hint='unknown', updated_at='2026-10-03T01:10:00Z', completeness='complete', gaps=[])
        public = contracts.parse_public_summary(raw)
        self.assertEqual(public.to_dict(), raw)
        for field in ('evidence', 'protection', 'raw_artifact', 'actions'):
            bad = copy.deepcopy(raw);bad[field] = 'secret'
            with self.subTest(field=field), self.assertRaises(contracts.ContractError):
                contracts.parse_public_summary(bad)
        bad = copy.deepcopy(raw);bad['entity_ref']['evidence_refs'] = ['private-proof']
        with self.assertRaises(contracts.ContractError):
            contracts.parse_public_summary(bad)

    def test_invalid_data_cannot_be_hidden_behind_recomputed_hash(self):
        raw = self.cases[3]['input']
        for bad in (-1, True, '0'):
            snapshot = copy.deepcopy(raw['snapshot'])
            career = next(m['data'] for m in snapshot['materials'] if m['capability'] == 'career')
            career['official_or_source_start_count'] = bad
            with self.subTest(value=bad), self.assertRaises(contracts.ContractError):
                contracts.build_input(snapshot, evaluated_at=raw['evaluated_at'],policy_ref=raw['policy_ref'],
                    generations=raw['input_version']['generations'],scope=raw['input_version']['scope'])
        snapshot = copy.deepcopy(raw['snapshot']);snapshot['materials'][0]['data']['execute_shell'] = 'never'
        with self.assertRaises(contracts.ContractError):
            contracts.build_input(snapshot, evaluated_at=raw['evaluated_at'],policy_ref=raw['policy_ref'],
                generations=raw['input_version']['generations'],scope=raw['input_version']['scope'])

    def test_direct_dto_constructor_cannot_bypass_validation(self):
        for cls in (contracts.LoaderInput, contracts.DecisionOutput):
            with self.subTest(cls=cls), self.assertRaises(contracts.ContractError):
                cls('{}')

    def test_public_entity_must_match_decision_and_lacks_private_source_refs(self):
        case = self.cases[0]
        public = dict(entity_ref=copy.deepcopy(case['input']['snapshot']['entity']),public_version='v1',
            material_state='confirmed',fact_phase='unknown',clock_hint='unknown',updated_at='2026-10-03T01:10:00Z',completeness='complete',gaps=[])
        output = copy.deepcopy(case['output']);public['entity_ref']['canonical_id'] = 'another-horse';output['public_summary'] = public
        with self.assertRaises(contracts.ContractError):
            contracts.parse_decision(output,input_document=contracts.parse_input(case['input']))
        public['entity_ref']['source_refs'] = [{'source':'private','namespace':'registry','external_id':'hidden'}]
        with self.assertRaises(contracts.ContractError):
            contracts.parse_public_summary(public)

    def test_future_schema_and_malformed_nested_decision_never_fall_back(self):
        case = self.cases[0]
        for mutate in (
            lambda v: v.update(schema_version='f01.v99'),
            lambda v: v['actions'][0].update(deadline=17),
            lambda v: v['entity'].update(source_refs=[{'source':'p','namespace':'n','external_id':17}]),
            lambda v: v['input_version']['generations'].update(owner=-1),
        ):
            bad = copy.deepcopy(case['output']);mutate(bad)
            with self.subTest(mutation=mutate), self.assertRaises(contracts.ContractError):
                contracts.parse_decision(bad,input_document=contracts.parse_input(case['input']))

    def test_empty_and_duplicate_roster_slots_and_source_times_are_rejected(self):
        case = self.cases[2]
        for kind in ('duplicate_slot','invalid_time','correction_without_evidence'):
            snapshot = copy.deepcopy(case['input']['snapshot'])
            if kind == 'duplicate_slot':
                material = next(m for m in snapshot['materials'] if m['maturity'] == 'confirmed')
                material['data']['participants'].append(material['data']['participants'][0])
            elif kind == 'invalid_time':
                snapshot['evidence'][0]['source_time'].update(precision='interval',last_absent_at='2026-10-04T00:00:00Z',first_seen_at='2026-10-03T00:00:00Z')
            else:
                snapshot['materials'][0].update(maturity='corrected',supersedes_ref=None,evidence_refs=[])
            with self.subTest(kind=kind), self.assertRaises(contracts.ContractError):
                contracts.build_input(snapshot,evaluated_at=case['input']['evaluated_at'],policy_ref=case['input']['policy_ref'],generations=case['input']['input_version']['generations'])

    def test_no_framework_or_io_dependency_is_loaded(self):
        import ast
        source = Path(contracts.__file__).read_text()
        imported = [n.module.split('.')[0] for n in ast.walk(ast.parse(source)) if isinstance(n,ast.ImportFrom)]
        imported += [alias.name.split('.')[0] for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Import) for alias in n.names]
        self.assertFalse(set(imported) & {'django','celery','requests','socket','urllib','stable'})

    def test_action_generation_types_are_strict_before_equality(self):
        case = copy.deepcopy(self.cases[0])
        original = case['input']
        original['input_version']['generations']['owner'] = 1
        document = contracts.parse_input(original)
        output = case['output']
        output['input_version'] = copy.deepcopy(original['input_version'])
        import hashlib
        output['input_fingerprint'] = hashlib.sha256(document.to_json().encode()).hexdigest()
        for action in output['actions']:
            action['expected_input_version'] = copy.deepcopy(original['input_version'])
            action['expected_generations'] = copy.deepcopy(original['input_version']['generations'])
        for key in ('expected_generations', 'expected_input_version'):
            for bad in (True, 1.0):
                candidate = copy.deepcopy(output)
                target = candidate['actions'][0][key]
                if key == 'expected_input_version':
                    target = target['generations']
                target['owner'] = bad
                with self.subTest(field=key,bad=bad), self.assertRaises(contracts.ContractError):
                    contracts.parse_decision(candidate,input_document=document)

    def test_public_identity_state_must_match_internal_entity(self):
        original = self.cases[0]['input']
        for internal_state in ('verified', 'unresolved', 'revoked'):
            snapshot = copy.deepcopy(original['snapshot'])
            snapshot['entity']['identity_state'] = internal_state
            document = contracts.build_input(snapshot,evaluated_at=original['evaluated_at'],
                policy_ref=original['policy_ref'],generations=original['input_version']['generations'])
            import hashlib
            for public_state in ('verified', 'unresolved', 'revoked'):
                output = copy.deepcopy(self.cases[0]['output'])
                output['entity'] = copy.deepcopy(snapshot['entity'])
                output['input_version'] = document.to_dict()['input_version']
                output['input_fingerprint'] = hashlib.sha256(document.to_json().encode()).hexdigest()
                for action in output['actions']:
                    action['expected_input_version'] = copy.deepcopy(output['input_version'])
                public_entity = copy.deepcopy(snapshot['entity'])
                public_entity['identity_state'] = public_state
                output['public_summary'] = dict(entity_ref=public_entity,public_version='v1',
                    material_state='confirmed',fact_phase='unknown',clock_hint='unknown',
                    updated_at='2026-10-03T01:10:00Z',completeness='complete',gaps=[])
                with self.subTest(internal=internal_state,public=public_state):
                    if internal_state == public_state:
                        contracts.parse_decision(output,input_document=document)
                    else:
                        with self.assertRaises(contracts.ContractError):
                            contracts.parse_decision(output,input_document=document)
