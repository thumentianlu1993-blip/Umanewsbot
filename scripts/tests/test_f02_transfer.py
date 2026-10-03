"""仅合成目录及注入动作，不调用真实数据库/网络/进程。"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from scripts import f02_readonly_export as export
from scripts import f02_transfer as transfer
from scripts.tests.test_f02_readonly_export import source_metadata_package, sample_content


def read_json(path):
    return json.loads(path.read_bytes())


def write_json(path, value):
    path.write_bytes(export.encoded(value))
    path.chmod(0o600)


def rehash(directory):
    manifest = read_json(directory / 'manifest.json')
    manifest['files'] = {name: export.digest((directory / name).read_bytes()) for name in manifest['files']}
    write_json(directory / 'manifest.json', manifest)
    return export.digest((directory / 'manifest.json').read_bytes())


def fixture(base, kind='metadata'):
    root = base.resolve() / 'producer/runtime/next_version/F02'
    metadata, selection = source_metadata_package(root)
    receipt = read_json(metadata / 'receipt.json')
    receipt['observation']['script_sha256'] = 'b' * 64
    write_json(metadata / 'receipt.json', receipt)
    selection['source_metadata_manifest_sha256'] = rehash(metadata)
    directory = metadata
    if kind == 'sealed_content':
        row, _ = sample_content()
        export.publish_content([row], selection, root, 'synthetic-content')
        directory = root / 'synthetic-content'
    capsule = {'schema_version': 1, 'verifier_sha256': transfer.verifier_sha(), 'kind': kind, 'observation_id': directory.name,
               'container_id': 'c' * 64, 'image_id': 'sha256:' + 'd' * 64,
               'release_sha': 'a' * 40, 'exporter_script_sha256': 'b' * 64,
               'manifest_sha256': export.digest((directory / 'manifest.json').read_bytes()),
               'source_schema_sha256': selection['source_schema_sha256'],
               'container_output_root': '/tmp/f02-capsule/runtime/next_version/F02',
               'execution_uid': 0, 'copy_timeout_seconds': 60, 'verify_timeout_seconds': 60}
    if kind == 'sealed_content':
        capsule['selection'] = selection
    return directory, capsule, metadata


class VerifierTests(unittest.TestCase):
    def test_valid_metadata_and_content_have_only_summary(self):
        for kind in ('metadata', 'sealed_content'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                directory, capsule, metadata = fixture(Path(temp), kind)
                result = transfer.verify_bundle(directory, capsule, metadata)
                self.assertEqual(result['manifest_sha256'], capsule['manifest_sha256'])
                self.assertEqual(result['kind'], kind)
                self.assertNotIn('Synthetic First', json.dumps(result))
                self.assertEqual(result['human_verification_status'], 'not_reviewed')

    def test_manifest_hash_files_receipt_counts_and_source_rejected(self):
        mutations = [
            lambda d, c: (d / 'cohort_metadata.jsonl').write_text('PRIVATE CORRUPTION'),
            lambda d, c: (d / 'extra').write_text('PRIVATE'),
            lambda d, c: c.update(release_sha='e' * 40),
            lambda d, c: c.update(exporter_script_sha256='e' * 64),
            lambda d, c: c.update(source_schema_sha256='e' * 64),
            lambda d, c: c.update(observation_id='other'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temp:
                directory, capsule, _ = fixture(Path(temp))
                mutate(directory, capsule)
                with self.assertRaises(transfer.TransferError):
                    transfer.verify_bundle(directory, capsule)
        for field, value in [('counts', {'cohort': 2}), ('region_counts', {'japan': 2})]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                directory, capsule, _ = fixture(Path(temp))
                receipt = read_json(directory / 'receipt.json')
                receipt[field] = value
                write_json(directory / 'receipt.json', receipt)
                capsule['manifest_sha256'] = rehash(directory)
                with self.assertRaises(transfer.TransferError):
                    transfer.verify_bundle(directory, capsule)

    def test_content_requires_full_source_and_selection_chain(self):
        for mutation in ('missing_source', 'selection', 'content_hash', 'content_count', 'source_file'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                directory, capsule, metadata = fixture(Path(temp), 'sealed_content')
                if mutation == 'missing_source':
                    metadata = None
                elif mutation == 'selection':
                    capsule['selection']['samples'][0]['input_sha256'] = 'f' * 64
                elif mutation == 'source_file':
                    (metadata / 'cohort_metadata.jsonl').write_text('PRIVATE')
                elif mutation == 'content_hash':
                    row = json.loads((directory / 'content.jsonl').read_text())
                    row['body_ja_raw'] = 'PRIVATE changed'
                    write_json(directory / 'content.jsonl', row)
                    capsule['manifest_sha256'] = rehash(directory)
                else:
                    receipt = read_json(directory / 'receipt.json')
                    receipt['counts']['articles'] = 2
                    write_json(directory / 'receipt.json', receipt)
                    capsule['manifest_sha256'] = rehash(directory)
                with self.assertRaises(transfer.TransferError):
                    transfer.verify_bundle(directory, capsule, metadata)

    def test_paths_permissions_links_and_special_files_rejected(self):
        for kind in ('symlink_file', 'hardlink', 'fifo', 'file_mode', 'dir_mode', 'ancestor_link', 'dotdot'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                base = Path(temp).resolve()
                directory, capsule, _ = fixture(base)
                target = directory / 'sources.jsonl'
                if kind in ('symlink_file', 'hardlink', 'fifo'):
                    saved = base / 'saved'
                    target.rename(saved)
                    if kind == 'symlink_file':
                        target.symlink_to(saved)
                    elif kind == 'hardlink':
                        os.link(saved, target)
                    else:
                        os.mkfifo(target, 0o600)
                elif kind == 'file_mode':
                    target.chmod(0o644)
                elif kind == 'dir_mode':
                    directory.chmod(0o755)
                elif kind == 'ancestor_link':
                    (base / 'alias').symlink_to(directory.parent, target_is_directory=True)
                    directory = base / 'alias' / directory.name
                else:
                    directory = directory / '..' / directory.name
                with self.assertRaises(transfer.TransferError):
                    transfer.verify_bundle(directory, capsule)

    def test_file_and_total_byte_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, _ = fixture(Path(temp))
            size = sum(f.stat().st_size for f in directory.iterdir())
            with patch.object(transfer, 'METADATA_TOTAL_MAX', size):
                transfer.verify_bundle(directory, capsule)
            with patch.object(transfer, 'METADATA_TOTAL_MAX', size - 1):
                with self.assertRaises(transfer.TransferError):
                    transfer.verify_bundle(directory, capsule)
            max_file = max(f.stat().st_size for f in directory.iterdir())
            with patch.object(transfer, 'FILE_MAX', max_file):
                transfer.verify_bundle(directory, capsule)
            with patch.object(transfer, 'FILE_MAX', max_file - 1):
                with self.assertRaises(transfer.TransferError):
                    transfer.verify_bundle(directory, capsule)


class FakeAdapter:
    def __init__(self, directory, capsule):
        self.directory = directory
        self.capsule = capsule
        self.copies = 0
        self.probes = 0
        self.lost = False
        self.after = None
        self.interrupt = None

    def probe(self, *, timeout):
        self.probes += 1
        if self.lost:
            return {'state': 'source_lost'}
        result = {key: self.capsule[key] for key in transfer.IDENTITY}
        result.update(state='complete', execution_uid=0)
        if self.probes > 1 and self.after:
            result.update(self.after)
        return result

    def copy(self, destination, *, timeout):
        self.copies += 1
        if self.interrupt == 'partial':
            shutil.copy2(self.directory / 'manifest.json', destination / 'manifest.json')
            raise TimeoutError('PRIVATE transport detail')
        shutil.copytree(self.directory, destination, dirs_exist_ok=True)
        if self.interrupt == 'complete':
            raise TimeoutError('PRIVATE lost acknowledgement')


class TransferTests(unittest.TestCase):
    def prepare(self, base):
        directory, capsule, metadata = fixture(base)
        adapter = FakeAdapter(directory, capsule)
        root = base.resolve() / 'host-artifacts'
        return directory, capsule, adapter, root

    def run_transfer(self, capsule, root, adapter, **kwargs):
        return transfer.transfer(capsule, root, adapter, 'attempt1', disk_free=lambda _: 10**10, **kwargs)

    def test_host_verified_atomic_and_idempotent_without_copy_or_R_self_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, adapter, root = self.prepare(Path(temp))
            result = self.run_transfer(capsule, root, adapter)
            self.assertEqual(result['state'], 'host_verified')
            self.assertFalse(result['delivered_to_R'])
            final = root / transfer.capsule_sha(capsule) / 'runtime/next_version/F02' / capsule['observation_id']
            self.assertEqual((final / 'manifest.json').read_bytes(), (directory / 'manifest.json').read_bytes())
            result = self.run_transfer(capsule, root, adapter)
            self.assertEqual(result['state'], 'host_verified')
            self.assertEqual(adapter.copies, 1)
            self.assertEqual(adapter.probes, 2)
            (final / 'sources.jsonl').write_text('PRIVATE changed')
            result = self.run_transfer(capsule, root, adapter)
            self.assertEqual(result['state'], 'invalid_package')
            self.assertEqual(adapter.copies, 1)
            self.assertEqual((final / 'sources.jsonl').read_text(), 'PRIVATE changed')

    def test_interrupted_partial_not_recopied_and_complete_copy_ack_loss_recovers(self):
        for mode in ('partial', 'complete'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                _, capsule, adapter, root = self.prepare(Path(temp))
                adapter.interrupt = mode
                result = self.run_transfer(capsule, root, adapter)
                self.assertEqual(result['state'], 'transfer_unknown')
                adapter.interrupt = None
                result = self.run_transfer(capsule, root, adapter)
                self.assertEqual(result['state'], 'host_verified' if mode == 'complete' else 'transfer_unknown')
                self.assertEqual(adapter.copies, 1)
                different = transfer.transfer(capsule, root, adapter, 'attempt2', disk_free=lambda _: 10**10)
                self.assertEqual(different['state'], 'host_verified' if mode == 'complete' else 'transfer_unknown')
                self.assertEqual(adapter.copies, 1)

    def test_post_copy_identity_or_hash_drift_never_publishes(self):
        for field in transfer.IDENTITY:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                _, capsule, adapter, root = self.prepare(Path(temp))
                adapter.after = {field: 'PRIVATE DIFFERENT'}
                result = self.run_transfer(capsule, root, adapter)
                self.assertEqual(result['state'], 'invalid_package')
                self.assertFalse((root / transfer.capsule_sha(capsule) / 'transfer.complete').exists())
                adapter.after = None
                self.assertEqual(self.run_transfer(capsule, root, adapter)['state'], 'invalid_package')
                self.assertEqual(adapter.copies, 1)

    def test_no_space_or_phase_timeout_prevents_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            _, capsule, adapter, root = self.prepare(Path(temp))
            result = transfer.transfer(capsule, root, adapter, 'attempt1', disk_free=lambda _: 0)
            self.assertEqual(result['state'], 'produced_not_transferred')
            self.assertEqual(result['code'], 'insufficient_space')
            self.assertEqual(adapter.copies, 0)
        with tempfile.TemporaryDirectory() as temp:
            _, capsule, adapter, root = self.prepare(Path(temp))
            clock = iter([0, 61])
            result = self.run_transfer(capsule, root, adapter, clock=lambda: next(clock))
            self.assertEqual(result['state'], 'transfer_unknown')
            self.assertFalse((root / transfer.capsule_sha(capsule) / 'transfer.complete').exists())

    def test_source_lost_with_and_without_committed_complete_stage(self):
        for prior in ('none', 'complete', 'partial', 'uncommitted'):
            with self.subTest(prior=prior), tempfile.TemporaryDirectory() as temp:
                directory, capsule, adapter, root = self.prepare(Path(temp))
                if prior in ('complete', 'partial'):
                    adapter.interrupt = prior
                    self.assertEqual(self.run_transfer(capsule, root, adapter)['state'], 'transfer_unknown')
                elif prior == 'uncommitted':
                    attempt = root / transfer.capsule_sha(capsule) / 'attempts/attempt1'
                    stage = attempt / 'runtime/next_version/F02' / capsule['observation_id']
                    stage.mkdir(parents=True, mode=0o700)
                    # Caller-created dirs are made private for the uncommitted-stage case.
                    for path in (root, root / transfer.capsule_sha(capsule), *stage.parents):
                        if path == root or root in path.parents:
                            path.chmod(0o700)
                    shutil.copytree(directory, stage, dirs_exist_ok=True)
                adapter.lost = True
                result = self.run_transfer(capsule, root, adapter)
                self.assertEqual(result['state'], {'none': 'source_lost', 'complete': 'host_verified',
                                                 'partial': 'source_lost', 'uncommitted': 'transfer_unknown'}[prior])
                self.assertLessEqual(adapter.copies, 1)

    def test_receipt_atomic_failure_retains_final_and_recovers_without_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            _, capsule, adapter, root = self.prepare(Path(temp))
            def fail_complete(path, value):
                if path.name == 'transfer.complete':
                    raise OSError('PRIVATE no space')
                return transfer.atomic_json(path, value)
            result = self.run_transfer(capsule, root, adapter, writer=fail_complete)
            self.assertEqual(result['state'], 'transfer_unknown')
            final = root / transfer.capsule_sha(capsule) / 'runtime/next_version/F02' / capsule['observation_id']
            self.assertTrue(final.exists())
            result = self.run_transfer(capsule, root, adapter)
            self.assertEqual(result['state'], 'host_verified')
            self.assertEqual(adapter.copies, 1)

    def test_concurrent_lock_does_not_copy_and_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            _, capsule, adapter, root = self.prepare(Path(temp))
            root.mkdir(mode=0o700)
            with transfer.artifact_lock(root):
                result = self.run_transfer(capsule, root, adapter)
                self.assertEqual(result['state'], 'transfer_unknown')
                self.assertEqual(result['code'], 'busy')
            self.assertEqual(self.run_transfer(capsule, root, adapter)['state'], 'host_verified')


class DeliveryAndCLITests(unittest.TestCase):
    def test_producer_cannot_self_sign_R_delivery_and_authenticated_ack_is_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            _, capsule, _ = fixture(Path(temp))
            root = Path(temp).resolve() / 'host'
            directory = Path(temp).resolve() / 'producer/runtime/next_version/F02' / capsule['observation_id']
            adapter = FakeAdapter(directory, capsule)
            transfer.transfer(capsule, root, adapter, 'attempt1', disk_free=lambda _: 10**10)
            ack = {'schema_version': 1, 'issuer': 'R', 'capsule_sha256': transfer.capsule_sha(capsule),
                   'manifest_sha256': capsule['manifest_sha256'], 'observation_id': capsule['observation_id'],
                   'received_at': '2026-10-03T00:00:00+00:00', 'signature': '0' * 64}
            with self.assertRaises(transfer.TransferError):
                transfer.record_delivery(capsule, root, ack, r_key=None)
            key = b'R-only-offline-synthetic-key-32bytes'
            # Test custodian is the only caller with the key, outside capsule/producer/adapter.
            import hmac
            unsigned = dict(ack)
            unsigned.pop('signature')
            ack['signature'] = hmac.new(key, export.encoded(unsigned), hashlib.sha256).hexdigest()
            bad = dict(ack, manifest_sha256='f' * 64)
            with self.assertRaises(transfer.TransferError):
                transfer.record_delivery(capsule, root, bad, r_key=key)
            result = transfer.record_delivery(capsule, root, ack, r_key=key)
            self.assertEqual(result['state'], 'delivered_to_R')
            self.assertTrue(result['delivered_to_R'])
            self.assertNotIn(key.decode(), json.dumps(result))
            self.assertEqual(transfer.record_delivery(capsule, root, ack, r_key=key), result)
            # Producer host receipt remains separate, never changes to R delivery.
            host = read_json(root / transfer.capsule_sha(capsule) / 'transfer.complete')
            self.assertFalse(host['delivered_to_R'])

    def test_cli_verify_outputs_only_summary_and_errors_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, _ = fixture(Path(temp))
            capsule_path = Path(temp).resolve() / 'capsule.json'
            write_json(capsule_path, capsule)
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = transfer.main(['verify', '--capsule', str(capsule_path), '--bundle', str(directory)])
            self.assertEqual(code, 0)
            self.assertNotIn('Synthetic First', stdout.getvalue())
            with patch.object(transfer, 'verify_bundle', side_effect=OSError('PRIVATE token=SECRET')):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    code = transfer.main(['verify', '--capsule', str(capsule_path), '--bundle', str(directory)])
                self.assertEqual(code, 2)
                self.assertNotIn('PRIVATE', stdout.getvalue())
                self.assertNotIn('SECRET', stdout.getvalue())
                self.assertEqual(json.loads(stdout.getvalue())['code'], 'operation_failed')

    def test_mapping_behavior_domains_and_python_profiles_include_fixture(self):
        proposal = read_json(Path(__file__).resolve().parents[2] /
                             'docs/changes/next-version-capabilities/lanes/B/B-002-test-mapping-proposal.json')
        domain = 'module:scripts.tests.test_f02_transfer'
        for path in ('scripts/f02_transfer.py', 'scripts/tests/test_f02_transfer.py'):
            self.assertIn(domain, proposal['rules_paths_additions'].get(path, []))
        fixture_path = 'docs/changes/next-version-capabilities/lanes/B/B-002-test-mapping-proposal.json'
        self.assertIn(domain, proposal['rules_paths_additions'][fixture_path])
        self.assertIn('module:scripts.tests.test_f02_readonly_export', proposal['rules_paths_additions'][fixture_path])
        self.assertEqual(proposal['catalog_profiles_additions']['scripts.tests.test_f02_transfer'], 'python')
        self.assertEqual(proposal['catalog_domains_additions'][domain], ['scripts.tests.test_f02_transfer'])
        self.assertEqual(set(proposal['catalog_tests_additions']['scripts/tests/test_f02_transfer.py']['domains']),
                         {domain, 'module:scripts.tests.test_f02_docker_adapter', 'module:scripts.tests.test_f02_receipt_bridge'})


class AdditionalFailureTests(unittest.TestCase):
    def test_verifier_identity_is_bound_before_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, _ = fixture(Path(temp))
            capsule['verifier_sha256'] = 'e' * 64
            adapter = FakeAdapter(directory, capsule)
            result = transfer.transfer(capsule, Path(temp).resolve() / 'host', adapter, 'attempt1')
            self.assertEqual(result['state'], 'invalid_package')
            self.assertEqual(adapter.copies, 0)
            self.assertEqual(result['code'], 'verifier_identity_mismatch')

    def test_bad_capsule_and_unsafe_host_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, _ = fixture(Path(temp))
            adapter = FakeAdapter(directory, capsule)
            for value in ({}, dict(capsule, observation_id='PRIVATE/secret'), dict(capsule, copy_timeout_seconds=61)):
                result = transfer.transfer(value, Path(temp).resolve() / 'host', adapter, 'attempt1')
                self.assertEqual(result['state'], 'invalid_package')
                self.assertNotIn('PRIVATE', json.dumps(result))
            host = Path(temp).resolve() / 'public'
            host.mkdir(mode=0o755)
            self.assertEqual(transfer.transfer(capsule, host, adapter, 'attempt1')['state'], 'invalid_package')
            self.assertEqual(adapter.copies, 0)

    def test_capture_unknown_and_transport_exception_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, _ = fixture(Path(temp))
            adapter = FakeAdapter(directory, capsule)
            root = Path(temp).resolve() / 'host'
            with patch.object(adapter, 'probe', return_value={'state': 'running'}):
                self.assertEqual(transfer.transfer(capsule, root, adapter, 'attempt1')['state'], 'capture_unknown')
            with patch.object(adapter, 'probe', side_effect=TimeoutError('PRIVATE PASSWORD')):
                result = transfer.transfer(capsule, root, adapter, 'attempt1')
                self.assertEqual(result['state'], 'transfer_unknown')
                self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertEqual(adapter.copies, 0)

    def test_copy_extra_file_and_fsync_failure_never_publish_receipt(self):
        for fault in ('extra', 'fsync'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                directory, capsule, _ = fixture(Path(temp))
                adapter = FakeAdapter(directory, capsule)
                root = Path(temp).resolve() / 'host'
                original_copy = adapter.copy
                def extra(destination, *, timeout):
                    original_copy(destination, timeout=timeout)
                    (destination / 'extra.json').write_text('PRIVATE')
                if fault == 'extra':
                    with patch.object(adapter, 'copy', side_effect=extra):
                        result = transfer.transfer(capsule, root, adapter, 'attempt1', disk_free=lambda _: 10**10)
                    self.assertEqual(result['state'], 'invalid_package')
                else:
                    with patch.object(transfer, 'fsync_payload', side_effect=OSError('PRIVATE IO')):
                        result = transfer.transfer(capsule, root, adapter, 'attempt1', disk_free=lambda _: 10**10)
                    self.assertEqual(result['state'], 'transfer_unknown')
                self.assertFalse((root / transfer.capsule_sha(capsule) / 'transfer.complete').exists())
                self.assertEqual(adapter.copies, 1)

    def test_inspect_refuses_tampered_receipt_without_adapter_and_R_ack_wrong_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, _ = fixture(Path(temp))
            adapter = FakeAdapter(directory, capsule)
            root = Path(temp).resolve() / 'host'
            transfer.transfer(capsule, root, adapter, 'attempt1', disk_free=lambda _: 10**10)
            self.assertEqual(transfer.inspect_host(capsule, root)['state'], 'host_verified')
            ack = {'schema_version': 1, 'issuer': 'R', 'capsule_sha256': transfer.capsule_sha(capsule),
                   'manifest_sha256': capsule['manifest_sha256'], 'observation_id': capsule['observation_id'],
                   'received_at': '2026-10-03T00:00:00+00:00', 'signature': '0' * 64}
            with self.assertRaises(transfer.TransferError):
                transfer.record_delivery(capsule, root, ack, r_key=b'X' * 32)
            receipt = root / transfer.capsule_sha(capsule) / 'transfer.complete'
            value = read_json(receipt)
            value['container_id'] = 'f' * 64
            write_json(receipt, value)
            with self.assertRaises(transfer.TransferError):
                transfer.inspect_host(capsule, root)


class ContentTransportTests(unittest.TestCase):
    def test_sealed_content_transfer_stays_R_unreceived_and_requires_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, metadata = fixture(Path(temp), 'sealed_content')
            adapter = FakeAdapter(directory, capsule)
            root = Path(temp).resolve() / 'host'
            result = transfer.transfer(capsule, root, adapter, 'attempt1', source_metadata_dir=metadata,
                                       disk_free=lambda _: 10**10)
            self.assertEqual(result['state'], 'host_verified')
            self.assertFalse(result['delivered_to_R'])
            self.assertNotIn('Synthetic First', json.dumps(result))
            self.assertEqual(transfer.inspect_host(capsule, root, metadata)['state'], 'host_verified')
            with self.assertRaises(transfer.TransferError):
                transfer.inspect_host(capsule, root)

    def test_copy_timeout_and_verification_timeout_stop_before_final(self):
        for phase in ('copy', 'verify'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                directory, capsule, _ = fixture(Path(temp))
                adapter = FakeAdapter(directory, capsule)
                root = Path(temp).resolve() / 'host'
                # Probe pair, copy pair, post-probe pair, verify pair.
                timestamps = [0, 0, 0, 61] if phase == 'copy' else [0, 0, 0, 0, 0, 0, 0, 61]
                iterator = iter(timestamps)
                result = transfer.transfer(capsule, root, adapter, 'attempt1', clock=lambda: next(iterator),
                                           disk_free=lambda _: 10**10)
                self.assertEqual(result['state'], 'transfer_unknown')
                self.assertEqual(result['code'], phase + '_timeout')
                self.assertFalse((root / transfer.capsule_sha(capsule) / 'transfer.complete').exists())
                self.assertEqual(adapter.copies, 1)


class VerificationTimerTests(unittest.TestCase):
    def test_wall_clock_expiry_restores_timer_and_nested_budget(self):
        import signal
        with tempfile.TemporaryDirectory() as temp:
            directory, capsule, metadata = fixture(Path(temp), 'sealed_content')
            previous = signal.getsignal(signal.SIGALRM)
            def expire(*args):
                signal.raise_signal(signal.SIGALRM)
            with patch.object(transfer, '_verify_bundle', side_effect=expire):
                with self.assertRaisesRegex(transfer.TransferError, 'verify_timeout'):
                    transfer.verify_bundle(directory, capsule, metadata)
            self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))
            self.assertEqual(transfer.verify_bundle(directory, capsule, metadata)['kind'], 'sealed_content')


class CountsSchemaReviewFixTests(unittest.TestCase):
    def mutated(self, base, kind, mutate):
        directory, capsule, metadata = fixture(base, kind)
        receipt = read_json(directory / 'receipt.json')
        mutate(receipt)
        write_json(directory / 'receipt.json', receipt)
        capsule['manifest_sha256'] = rehash(directory)
        return directory, capsule, metadata

    def test_extra_string_or_nested_counts_rejected_without_CLI_leak_or_host_receipt(self):
        for kind in ('metadata', 'sealed_content'):
            for injected in ('SYNTHETIC_PRIVATE_COUNT_PAYLOAD', {'body': 'SYNTHETIC_PRIVATE_COUNT_PAYLOAD'}):
                with self.subTest(kind=kind, injected=injected), tempfile.TemporaryDirectory() as temp:
                    base = Path(temp).resolve()
                    directory, capsule, metadata = self.mutated(
                        base, kind, lambda receipt: receipt['counts'].update(extra_text=injected))
                    capsule_path = base / 'capsule.json'
                    write_json(capsule_path, capsule)
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        code = transfer.main(['verify', '--capsule', str(capsule_path), '--bundle', str(directory),
                                              '--source-metadata-dir', str(metadata)])
                    with self.subTest(boundary='CLI_exit'):
                        self.assertNotEqual(code, 0)
                    with self.subTest(boundary='CLI_content'):
                        self.assertNotIn('SYNTHETIC_PRIVATE_COUNT_PAYLOAD', stdout.getvalue())
                    with self.subTest(boundary='CLI_code'):
                        self.assertEqual(json.loads(stdout.getvalue()).get('code'), 'invalid_counts_schema')
                    adapter = FakeAdapter(directory, capsule)
                    root = base / 'host'
                    result = transfer.transfer(capsule, root, adapter, 'attempt1', source_metadata_dir=metadata,
                                               disk_free=lambda _: 10**10)
                    with self.subTest(boundary='transfer_state'):
                        self.assertEqual(result['state'], 'invalid_package')
                    with self.subTest(boundary='transfer_content'):
                        self.assertNotIn('SYNTHETIC_PRIVATE_COUNT_PAYLOAD', json.dumps(result))
                    with self.subTest(boundary='host_receipt'):
                        self.assertFalse((root / transfer.capsule_sha(capsule) / 'transfer.complete').exists())

    def test_counts_exact_keys_strict_integer_and_budgets(self):
        for kind in ('metadata', 'sealed_content'):
            key = 'cohort' if kind == 'metadata' else 'articles'
            limit = export.LIMITS[key] if kind == 'metadata' else 150
            mutations = [lambda r: r.update(counts='SYNTHETIC_PRIVATE_COUNT_PAYLOAD'),
                         lambda r: r['counts'].pop(key),
                         *[lambda r, value=value: r['counts'].update({key: value})
                           for value in (True, 1.0, '1', None, {}, -1, limit + 1)]]
            for mutate in mutations:
                with self.subTest(kind=kind, mutate=mutate), tempfile.TemporaryDirectory() as temp:
                    directory, capsule, metadata = self.mutated(Path(temp), kind, mutate)
                    with self.assertRaisesRegex(transfer.TransferError, 'invalid_counts_schema'):
                        transfer.verify_bundle(directory, capsule, metadata)
        for kind in ('metadata', 'sealed_content'):
            with self.subTest(valid=kind), tempfile.TemporaryDirectory() as temp:
                directory, capsule, metadata = fixture(Path(temp), kind)
                result = transfer.verify_bundle(directory, capsule, metadata)
                expected_keys = set(export.LIMITS) if kind == 'metadata' else {'articles'}
                self.assertEqual(set(result['counts']), expected_keys)
                self.assertTrue(all(type(value) is int for value in result['counts'].values()))
