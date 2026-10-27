"""准备回执的负向合同，真实镜像读取另由原 native 用例验证。"""
import copy
import hashlib
import json
import unittest
from pathlib import Path
import tempfile
import subprocess
import sys
from unittest.mock import Mock, patch
import time
import ast
from types import SimpleNamespace
from tools.test_impact import image_contract as contract


class ImageProofTests(unittest.TestCase):
    def test_non_owned_preparation_uses_verified_exact_cleanup_protocol(self):
        proof, plan = self.fixture()
        image_id = proof['image_id']
        cleanup_calls = []
        def fake_command(command, **kwargs):
            if command[1:3] == ['image','ls']:
                return subprocess.CompletedProcess(command,0,'','')
            if command[1] == 'build':
                Path(command[command.index('--iidfile')+1]).write_text(image_id)
                proof['inspect']['Config']['Labels']['org.umanews.test-preparation'] = command[command.index('--label')+1].split('=',1)[1]
                return subprocess.CompletedProcess(command,0,'built','')
            if command[1:3] == ['image','inspect']:
                return subprocess.CompletedProcess(command,0,json.dumps([proof['inspect']]),'')
            if command[1] == 'run':
                return subprocess.CompletedProcess(command,0,json.dumps(proof['runtime']),'')
            self.fail('unexpected preparation command')
        def cleanup(command, **kwargs):
            cleanup_calls.append(command)
            if command[1] == 'rm' or command[1:3] == ['image','rm']:
                return subprocess.CompletedProcess(command,0,'removed\n','')
            if command[1:3] == ['container','inspect']:
                return subprocess.CompletedProcess(command,1,'[]\n','Error response from daemon: No such container: '+command[-1]+'\n')
            self.assertEqual(command[1:4],['inspect','--format','{{.Id}}'])
            return subprocess.CompletedProcess(command,1,'\n','error: no such object: '+command[-1]+'\n')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(contract,'_migration_image_source',return_value=contract._MIGRATION_IMAGE_SOURCE), \
                patch.object(contract,'_migration_image_archive_context'), \
                patch.object(contract,'_assert_migration_image_context'), \
                patch.object(contract.subprocess,'check_output',return_value=b'fixed archive'), \
                patch.object(contract,'preparation_command',side_effect=fake_command), \
                patch.object(contract.subprocess,'run',side_effect=cleanup):
            raw, descriptor = contract.prepare_image_proof(Path(directory),plan,Path(directory))
            self.assertEqual(contract.validate_proof(raw,{**plan,'migration_image_proof':descriptor})['cleanup'],
                             {'created_image':True,'removed':True})
            self.assertEqual(cleanup_calls[0][-1],cleanup_calls[1][-1])

    def test_current_docker_absence_dialect_requires_exact_cid_and_no_other_error(self):
        from tools.test_impact.serial_ci import absent
        cid = 'c'*64
        def result(code=1, stdout='\n', stderr=None):
            return subprocess.CompletedProcess([],code,stdout,stderr or 'error: no such object: '+cid+'\n')
        self.assertTrue(absent(result(),cid))
        for value in (result(code=0), result(stdout='unexpected'),
                      result(stderr='error: no such object: '+'d'*64),
                      result(stderr='permission denied'), result(stderr='Cannot connect to the Docker daemon'),
                      result(stderr='error: no such object: '+cid+'\npermission denied')):
            with self.subTest(result=value):
                self.assertFalse(absent(value,cid))

    def test_outside_verifier_pg_program_preserves_image_descriptor(self):
        from tools.test_impact.core import digest
        from tools.test_impact.test_pg_lifecycle import save_synthetic_lifecycle
        from tools.test_impact.serial_ci import save
        proof, selection = self.fixture()
        selection.update(source='git',mode='full',run_id='9',run_attempt='1',control_blobs={},
                         domains=[],labels=[contract.NATIVE_ID],hashes={},changed_paths=[],content_digest='fixture',
                         allowed_skips={},deleted_test_modules=[],deleted_declared_test_ids=[],superseded_test_labels={},bootstrap=False)
        raw, bound = self.bind(proof, selection); bound['image_id']='sha256:'+'f'*64
        plan = {**bound,'count':1,'batches':[dict(key='batch-000',profile='django',ids=[contract.NATIVE_ID])]}
        report = dict(key='batch-000',profile='django',plan_digest=digest(plan),run_id='9',run_attempt='1',test_tree='b'*40,exit_code=0)
        root = Path(__file__).resolve().parents[2]
        tree = ast.parse((root/'scripts/verify_delivery_test_evidence.py').read_text())
        program = next(node.value.value for node in ast.walk(tree) if isinstance(node,ast.Assign)
                       and any(isinstance(t,ast.Name) and t.id=='program' for t in node.targets))
        original_path = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory); artifact=out/'artifact'; independent=out/'independent'
                artifact.mkdir(); independent.mkdir()
                for target in (artifact, independent):
                    save(target/'execution-plan.json', plan)
                (artifact/'migration-image-proof.json').write_bytes(raw)
                save(artifact/'batch-000.json',report)
                save_synthetic_lifecycle(artifact,bound,'collect')
                save_synthetic_lifecycle(artifact,plan,'run','batch-000','django')
                save_synthetic_lifecycle(independent,plan,'collect')
                config=out/'config.json'
                save(config,dict(root=str(root),base='a'*40,head='a'*40,test='a'*40,plan=plan,reports=[],
                                 artifact_pg=str(artifact),independent_pg=str(independent)))
                fake_module=SimpleNamespace(create_plan=lambda *args,**kwargs:selection)
                with patch.dict(sys.modules,{'plan_affected_tests':fake_module}), \
                        patch.object(sys,'argv',['verifier',str(root),str(config),'pg']):
                    exec(compile(program,'actual-outside-verifier-pg','exec'),{})
        finally:
            sys.path[:] = original_path

    def test_serial_collect_verifies_original_proof_bound_request(self):
        from tools.test_impact.serial_ci import Serial, save
        from tools.test_impact.test_serial_ci import FakeExecutor
        from tools.test_impact.test_pg_lifecycle import save_synthetic_lifecycle
        from tools.test_impact.core import digest
        proof, selection = self.fixture()
        selection.update(base_sha='a'*40, mode='full',source='git',run_id='9',run_attempt='1',labels=[contract.NATIVE_ID])
        raw, with_proof = self.bind(proof, selection)
        class PreparedExecutor(FakeExecutor):
            def run(self, command, deadline, ledger):
                result = super().run(command, deadline, ledger)
                if '--collect-only' in command:
                    self_case.assertIn('--prepare-images', command)
                    out = Path(command[command.index('--output')+1])
                    plan = json.loads((out/'execution-plan.json').read_text())
                    plan['migration_image_proof'] = with_proof['migration_image_proof']
                    save(out/'execution-plan.json', plan)
                    (out/'migration-image-proof.json').write_bytes(raw)
                    save_synthetic_lifecycle(out,{**with_proof,'image_id':plan['image_id']},'collect')
                return result
        self_case = self
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); selected = root/'selection.json'; save(selected, selection)
            serial = Serial(root/'evidence', {'start':0}, PreparedExecutor(root), clock=lambda:0)
            serial.collect(selected, root/'image.tar')
            self.assertFalse(serial.status['fatal'])
            self.assertEqual(serial.status['collection_pg_lifecycle']['input_plan_digest'],
                             digest({**with_proof,'image_id':'sha256:'+'f'*64}))

    def test_reader_timeout_preserves_primary_and_cleans_reader_and_image(self):
        observer = Mock(deadline=time.monotonic()+600)
        observer.cleanup.side_effect = RuntimeError('reader cleanup failed')
        image_id = 'sha256:'+'f'*64
        owner = None
        def fake_command(command, **kwargs):
            nonlocal owner
            self.assertIs(kwargs['observer'], observer)
            if command[1:3] == ['image','ls']:
                return subprocess.CompletedProcess(command,0,'','')
            if command[1] == 'build':
                Path(command[command.index('--iidfile')+1]).write_text(image_id)
                owner = command[command.index('--label')+1].split('=',1)[1]
                return subprocess.CompletedProcess(command,0,'built','')
            if command[1:3] == ['image','inspect']:
                return subprocess.CompletedProcess(command,0,json.dumps([{'Config': {'Labels': {'org.umanews.test-preparation': owner}}}]),'')
            if command[1] == 'run':
                self.assertIn('--cidfile', command)
                self.assertNotIn('--rm', command)
                observer.start.assert_called_once()
                raise subprocess.TimeoutExpired(command, 1)
            self.fail('unexpected preparation command')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(contract, '_migration_image_source', return_value=contract._MIGRATION_IMAGE_SOURCE), \
                patch.object(contract, '_migration_image_archive_context'), \
                patch.object(contract, '_assert_migration_image_context'), \
                patch.object(contract.subprocess, 'check_output', return_value=b'fixed archive'), \
                patch.object(contract, 'preparation_command', side_effect=fake_command), \
                patch.object(contract.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'','')) as cleanup:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                contract.prepare_image_proof(Path(directory), {'test_sha':'a'*40,'test_tree':'b'*40}, Path(directory), observer)
            observer.admission.assert_called_once_with(600)
            observer.cleanup.assert_called_once()
            self.assertEqual(cleanup.call_args.args[0], ['docker','image','rm',image_id])
            self.assertTrue(any('reader cleanup failed' in note for note in caught.exception.__notes__))

    def test_collect_only_has_no_image_preparation_without_explicit_stage(self):
        plan = {'labels': [contract.NATIVE_ID]}
        self.assertFalse(contract.needs_preparation(plan, collect_only=True, prepare_images=False, batch=None))
        self.assertTrue(contract.needs_preparation(plan, collect_only=True, prepare_images=True, batch=None))
        self.assertTrue(contract.needs_preparation(plan, collect_only=False, prepare_images=False, batch=None))
        self.assertFalse(contract.needs_preparation(plan, collect_only=False, prepare_images=False, batch='batch-000'))

    def test_collection_input_preserves_verified_proof_and_rejects_missing_file(self):
        proof, selected = self.fixture()
        selected['labels'] = [contract.NATIVE_ID]
        raw, collected = self.bind(proof, selected)
        collected.update(image_id='sha256:'+'f'*64, batches=[], count=0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                contract.collection_input(selected, collected, root)
            (root/'migration-image-proof.json').write_bytes(raw)
            bound = contract.collection_input(selected, collected, root)
            self.assertEqual(bound, {**selected, 'image_id': collected['image_id'],
                                     'migration_image_proof': collected['migration_image_proof']})
            (root/'migration-image-proof.json').write_bytes(raw+b' ')
            with self.assertRaises(ValueError):
                contract.collection_input(selected, collected, root)

    def test_preparation_processes_use_owned_observer_without_pipe_deadlock(self):
        observer = Mock()
        def observed(command, stage, **kwargs):
            self.assertEqual(stage, 'migration-image-preparation')
            self.assertNotIn('capture_output', kwargs)
            return subprocess.run(command, **kwargs)
        observer.run.side_effect = observed
        result = contract.preparation_command([sys.executable, '-c', 'print("owned")'], observer=observer, timeout=5)
        self.assertEqual(result.stdout, 'owned\n')
        observer.run.assert_called_once()

    def fixture(self):
        sha = contract._MIGRATION_IMAGE_SOURCE['sha']
        proof = {'version': 1, 'test_sha': 'a'*40, 'test_tree': 'b'*40,
                 'source': contract._MIGRATION_IMAGE_SOURCE,
                 'image_id': 'sha256:'+'c'*64,
                 'inspect': {'Id': 'sha256:'+'c'*64, 'Config': {
                     'Labels': {'org.opencontainers.image.revision': sha, 'org.umanews.test-preparation': 'd'*32},
                     'Env': ['UMANEWS_RELEASE_COMMIT='+sha]}},
                 'runtime': {'release_commit': sha, 'marker_hex': (sha+'\n').encode().hex(),
                             'audit_files': [contract.AUDIT_RELATIVE],
                             'audit_sha256': contract._MIGRATION_IMAGE_SOURCE['pins']['docs/'+contract.AUDIT_RELATIVE],
                             'database_identity_sha256': contract.DATABASE_IDENTITY},
                 'cleanup': {'created_image': True, 'removed': True}}
        return proof, {'test_sha': 'a'*40, 'test_tree': 'b'*40}

    def bind(self, proof, plan):
        raw = json.dumps(proof).encode()
        plan = {**plan, 'migration_image_proof': {'version': 1, 'sha256': hashlib.sha256(raw).hexdigest()}}
        return raw, plan

    def test_complete_bound_proof_accepted(self):
        proof, plan = self.fixture()
        self.assertEqual(contract.validate_proof(*self.bind(proof, plan)), proof)

    def test_mutation_rejected_even_if_content_hash_recomputed(self):
        proof, plan = self.fixture()
        for field, value in (('test_sha', 'd'*40), ('test_tree', 'e'*40), ('version', 2),
                             ('image_id', 'latest'), ('source', {}), ('runtime', {}),
                             ('cleanup', {'created_image': True, 'removed': False})):
            bad = copy.deepcopy(proof); bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                contract.validate_proof(*self.bind(bad, plan))
        for field in ('audit_files', 'audit_sha256', 'database_identity_sha256', 'release_commit', 'marker_hex'):
            bad = copy.deepcopy(proof); bad['runtime'][field] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                contract.validate_proof(*self.bind(bad, plan))

    def test_missing_wrong_hash_oversize_duplicate_keys_rejected(self):
        proof, plan = self.fixture(); raw, bound = self.bind(proof, plan)
        for data, input_plan in ((raw, plan), (raw+b' ', bound), (b'x'*65537, bound),
                                 (b'{"version":1,"version":1}', bound)):
            with self.assertRaises(ValueError):
                contract.validate_proof(data, input_plan)
