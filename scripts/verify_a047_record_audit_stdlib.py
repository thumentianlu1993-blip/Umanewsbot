"""Standalone type regression; extracts only pure functions, never imports Django.

The original PostgreSQL exact19 suite is separate and must still run under ROOT.
--baseline-source exercises the previous _json_safe(_state(record)) call path.
"""
import argparse
import ast
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def extract(path, names, namespace):
    tree = ast.parse(path.read_bytes(), filename=str(path))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == set(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)


def record(**overrides):
    values = dict(id=7, distance_meters_normalized=Decimal('1400.000'),
        race_date=date(2025, 12, 7), normalized_at=datetime(2026, 10, 3, 1, tzinfo=timezone.utc),
        event_id=None, raw_payload={'distance_text': '1400m', 'finish': 'PU'},
        normalization_issues=[])
    values.update(overrides)
    return SimpleNamespace(**values, _meta=SimpleNamespace(
        concrete_fields=[SimpleNamespace(attname=name) for name in values]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-source', type=Path)
    options = parser.parse_args()
    namespace = dict(date=date, datetime=datetime, Decimal=Decimal, deepcopy=deepcopy)
    extract(ROOT/'server/stable/services/horse_basic_profile_from_cache.py', ['_json_safe'], namespace)
    source = options.baseline_source or ROOT/'server/stable/services/horse_career_record_from_review.py'
    extract(source, ['_state'], namespace)
    if options.baseline_source:
        serialize = lambda obj: namespace['_json_safe'](namespace['_state'](obj))
    else:
        extract(source, ['_record_audit_state'], namespace)
        serialize = namespace['_record_audit_state']

    class RecordAuditTypeTests(unittest.TestCase):
        def test_decimal_field_keeps_exact_digits_and_scale(self):
            for value in ('1400.000', '1234567.891', '0.001', '-0.000'):
                with self.subTest(value=value):
                    result = serialize(record(distance_meters_normalized=Decimal(value)))
                    self.assertEqual(result['distance_meters_normalized'], value)
                    self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

        def test_none_date_and_nested_source_contract(self):
            result = serialize(record(distance_meters_normalized=None))
            self.assertIsNone(result['distance_meters_normalized'])
            self.assertEqual(result['race_date'], '2025-12-07')
            self.assertEqual(result['normalized_at'], '2026-10-03T01:00:00+00:00')
            self.assertEqual(result['raw_payload'], {'distance_text': '1400m', 'finish': 'PU'})

        def test_create_replay_snapshot_comparison_retains_drift(self):
            stored = json.loads(json.dumps(serialize(record())))
            self.assertEqual(serialize(record()), stored)
            self.assertNotEqual(serialize(record(distance_meters_normalized=Decimal('1400.001'))), stored)
            self.assertNotEqual(serialize(record(raw_payload={'distance_text': '1401m'})), stored)

        def test_nonfinite_or_wrong_distance_type_fails_closed(self):
            class DecimalSubclass(Decimal):
                pass
            for value in (Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity'), Decimal('-Infinity'),
                          1400.0, '1400.000', 1400, DecimalSubclass('1400')):
                with self.subTest(value_type=type(value).__name__, value=str(value)):
                    with self.assertRaises(ValueError):
                        serialize(record(distance_meters_normalized=value))

        def test_other_field_types_and_depth_still_refused(self):
            for value in (Decimal('1'), 1.25, object(), (1, 2), {1: 'key'}):
                with self.subTest(value_type=type(value).__name__):
                    with self.assertRaises(ValueError):
                        serialize(record(distance_meters_normalized=None, raw_payload={'unexpected': value}))
            deep = None
            for _ in range(66):
                deep = [deep]
            with self.assertRaisesRegex(ValueError, 'audit_structure_limit'):
                serialize(record(distance_meters_normalized=None, raw_payload=deep))
            with self.assertRaises(ValueError):
                namespace['_json_safe'](Decimal('1400.000'))

        def test_serialization_does_not_mutate_record(self):
            obj = record()
            original = deepcopy(vars(obj))
            result = serialize(obj)
            result['raw_payload']['finish'] = 'changed receipt only'
            self.assertEqual(vars(obj), original)
            self.assertEqual(type(obj.distance_meters_normalized), Decimal)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RecordAuditTypeTests))
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    raise SystemExit(main())
