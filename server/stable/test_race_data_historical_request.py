"""一次性历史结果请求合同；纯离线，不接触数据库或真实transport。"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from stable.services.race_data_historical_request import validate_manifest, reserve_request, validate_live_entry

NOW = datetime(2026, 11, 6, 15, 50, tzinfo=timezone.utc)
CODE = 'd' * 40


def manifest(directory):
    return {'schema_version': 1, 'purpose': 'historical_result_backfill', 'code_sha': CODE,
        'issued_at': '2026-11-06T15:45:00+00:00', 'expires_at': '2026-11-06T16:15:00+00:00',
        'endpoint': 'result_by_id', 'max_requests': 1, 'receipt_directory': str(directory),
        'entries': [{'event_id': 19, 'source_id': 23, 'provider': 'the_racing_api',
            'identity_namespace': 'tra-race-v1', 'external_race_id': 'race_123',
            'region': 'united_kingdom', 'local_date': '2026-10-03',
            'owner_generation': 3, 'enrollment_generation': 4,
            'standing_policy_sha256': 'a'*64, 'registry_sha256': 'b'*64,
            'route_sha256': 'c'*64}]}


def encode(value):
    raw = json.dumps(value, sort_keys=True).encode()
    return raw, hashlib.sha256(raw).hexdigest()


class HistoricalRequestContractTests(unittest.TestCase):
    def validate(self, value, directory, **changes):
        raw, sha = encode(value)
        args = dict(raw=raw, expected_sha256=sha, expected_code_sha=CODE,
                    now=NOW, receipt_directory=directory)
        args.update(changes)
        return validate_manifest(**args)

    def test_valid_historical_request_is_independent_of_p02_cohort(self):
        with TemporaryDirectory() as root:
            directory=Path(root)
            value=manifest(directory)
            self.assertEqual(self.validate(value,directory),value)

    def test_digest_code_expiry_and_receipt_root_drift_rejected(self):
        with TemporaryDirectory() as root:
            directory=Path(root)
            value=manifest(directory)
            for changes in ({'expected_sha256':'0'*64},{'expected_code_sha':'e'*40},
                {'now':datetime(2026,11,7,tzinfo=timezone.utc)},
                {'receipt_directory':directory/'other'}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.validate(value,directory,**changes)

    def test_twentieth_request_and_duplicate_event_rejected(self):
        with TemporaryDirectory() as root:
            directory=Path(root)
            value=manifest(directory)
            value['entries']=[dict(value['entries'][0],event_id=i+1,source_id=i+1) for i in range(20)]
            value['max_requests']=20
            with self.assertRaises(ValueError):self.validate(value,directory)
            value['entries']=value['entries'][:2];value['entries'][1]=copy.deepcopy(value['entries'][0]);value['max_requests']=2
            with self.assertRaises(ValueError):self.validate(value,directory)

    def test_reservation_persists_before_transport_and_replay_refused(self):
        with TemporaryDirectory() as root:
            directory=Path(root);value=self.validate(manifest(directory),directory)
            _,sha=encode(value)
            receipt=reserve_request(value,manifest_sha256=sha,event_id=19,receipt_directory=directory)
            self.assertEqual(json.loads(receipt.read_text())['status'],'reserved_outcome_unknown')
            with self.assertRaises(ValueError):reserve_request(value,manifest_sha256=sha,event_id=19,receipt_directory=directory)

    def test_out_of_manifest_event_does_not_create_reservation(self):
        with TemporaryDirectory() as root:
            directory=Path(root);value=self.validate(manifest(directory),directory);_,sha=encode(value)
            with self.assertRaises(ValueError):reserve_request(value,manifest_sha256=sha,event_id=20,receipt_directory=directory)
            self.assertEqual(list(directory.iterdir()),[])

    def test_concurrent_reservations_allow_exactly_one_request(self):
        from concurrent.futures import ThreadPoolExecutor
        with TemporaryDirectory() as root:
            directory=Path(root);value=self.validate(manifest(directory),directory);_,sha=encode(value)
            def attempt(_):
                try:
                    reserve_request(value,manifest_sha256=sha,event_id=19,receipt_directory=directory)
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(sum(pool.map(attempt,range(8))),1)
            self.assertEqual(len(list(directory.iterdir())),1)

    def test_live_identity_generation_or_permission_drift_rejected(self):
        with TemporaryDirectory() as root:
            value=manifest(Path(root));entry=value['entries'][0]
            current={'entry':copy.deepcopy(entry),'authority_version':1,'enrollment_state':'enrolled',
                     'write_owner':'data_sync','manual_blocked':False,'admitted':True}
            self.assertEqual(validate_live_entry(value,event_id=19,current=current),entry)
            for field in entry:
                changed=copy.deepcopy(current)
                changed['entry'][field]='drift'
                with self.subTest(field=field),self.assertRaises(ValueError):
                    validate_live_entry(value,event_id=19,current=changed)
            for field,bad in [('authority_version',2),('enrollment_state','retired'),
                              ('write_owner','historical'),('manual_blocked',True),('admitted',False)]:
                changed=copy.deepcopy(current);changed[field]=bad
                with self.subTest(field=field),self.assertRaises(ValueError):
                    validate_live_entry(value,event_id=19,current=changed)


class HistoricalRequestPreparationTests(unittest.TestCase):
    def test_live_drift_never_consumes_request_and_success_reserves_once(self):
        from unittest.mock import patch
        from stable.services.race_data_historical_request import prepare_request
        with TemporaryDirectory() as root:
            value = manifest(Path(root))
            raw, sha = encode(value)
            current = {'entry': copy.deepcopy(value['entries'][0]), 'authority_version': 1,
                       'enrollment_state': 'enrolled', 'write_owner': 'data_sync',
                       'manual_blocked': False, 'admitted': True}
            args = dict(raw=raw, expected_sha256=sha, expected_code_sha=CODE,
                        now=NOW, receipt_directory=Path(root), event_id=19)
            with patch('stable.services.race_data_historical_request.read_live_entry', return_value=(current, 'route')):
                current['entry']['owner_generation'] += 1
                with self.assertRaises(ValueError):
                    prepare_request(**args)
                self.assertEqual(list(Path(root).iterdir()), [])
                current['entry']['owner_generation'] -= 1
                prepared, route, receipt = prepare_request(**args)
                self.assertEqual(prepared, value)
                self.assertEqual(route, 'route')
                self.assertTrue(receipt.is_file())
                with self.assertRaisesRegex(ValueError, 'already_reserved'):
                    prepare_request(**args)
