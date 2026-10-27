"""准备回执的负向合同，真实镜像读取另由原 native 用例验证。"""
import copy
import hashlib
import json
import unittest
from tools.test_impact import image_contract as contract


class ImageProofTests(unittest.TestCase):
    def fixture(self):
        sha = contract._MIGRATION_IMAGE_SOURCE['sha']
        proof = {'version': 1, 'test_sha': 'a'*40, 'test_tree': 'b'*40,
                 'source': contract._MIGRATION_IMAGE_SOURCE,
                 'image_id': 'sha256:'+'c'*64,
                 'inspect': {'Id': 'sha256:'+'c'*64, 'Config': {
                     'Labels': {'org.opencontainers.image.revision': sha},
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
