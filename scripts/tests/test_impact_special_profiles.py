"""专用执行身份必须绑定精确测试，不能扩大到同模块其他用例。"""
import unittest

from tools.test_impact.special_profiles import ROOT_TEST, IMAGE_TEST, profile_for, validate_special_batch


class SpecialProfileTests(unittest.TestCase):
    def test_exact_ids_get_dedicated_profiles(self):
        self.assertEqual(profile_for(ROOT_TEST, 'django'), 'root-django')
        self.assertEqual(profile_for(IMAGE_TEST, 'django'), 'application-image')

    def test_neighbors_keep_original_identity(self):
        self.assertEqual(profile_for(ROOT_TEST + '_neighbor', 'django'), 'django')
        self.assertEqual(profile_for(IMAGE_TEST + '_neighbor', 'django'), 'django')

    def test_special_batch_cannot_mix_or_substitute_ids(self):
        for profile, ident in [('root-django', ROOT_TEST), ('application-image', IMAGE_TEST)]:
            validate_special_batch({'profile': profile, 'ids': [ident]})
            for ids in [[ident, 'other.test'], ['other.test'], [], [ident, ident]]:
                with self.assertRaises(ValueError):
                    validate_special_batch({'profile': profile, 'ids': ids})

    def test_special_test_cannot_fall_back_to_regular_profile(self):
        for ident in [ROOT_TEST, IMAGE_TEST]:
            with self.assertRaises(ValueError):
                validate_special_batch({'profile': 'django', 'ids': [ident]})


class SpecialIdentityTests(unittest.TestCase):
    def test_root_rejects_each_residual_capability(self):
        from tools.test_impact.special_profiles import validate_root_status
        clean = dict.fromkeys(['CapBnd', 'CapPrm', 'CapEff', 'CapInh', 'CapAmb'], '0')
        clean['NoNewPrivs'] = '1'
        validate_root_status(clean, 0, 0)
        for key in ['CapBnd', 'CapPrm', 'CapEff', 'CapInh', 'CapAmb']:
            with self.assertRaises(ValueError): validate_root_status({**clean, key: '1'}, 0, 0)
        with self.assertRaises(ValueError): validate_root_status(clean, 10001, 0)
        with self.assertRaises(ValueError): validate_root_status(clean, 0, 10001)
        with self.assertRaises(ValueError): validate_root_status({**clean, 'NoNewPrivs': '0'}, 0, 0)

    def test_application_image_never_falls_back_to_dependency_image(self):
        from tools.test_impact.special_profiles import expected_image
        batch = {'profile': 'application-image', 'ids': [IMAGE_TEST]}
        with self.assertRaises(ValueError): expected_image({'image_id': 'sha256:' + 'a'*64}, batch)
        plan = {'image_id': 'sha256:' + 'a'*64, 'application_image_id': 'sha256:' + 'b'*64}
        self.assertEqual(expected_image(plan, batch), plan['application_image_id'])

    def test_final_verifier_rejects_missing_replaced_or_crossed_image(self):
        import copy
        from tools.test_impact.core import digest, verify_results
        image = 'sha256:' + 'b'*64
        batch = dict(key='batch-000', profile='application-image', ids=[IMAGE_TEST], image_id=image)
        plan = dict(batches=[batch], image_id='sha256:'+'a'*64, application_image_id=image,
                    run_id='1', run_attempt='1', test_tree='c'*40, test_sha='e'*40, mode='full')
        report = dict(key=batch['key'], profile=batch['profile'], plan_digest=digest(plan),
                      run_id='1', run_attempt='1', test_tree='c'*40, executed=[IMAGE_TEST],
                      exit_code=0, lifecycle='complete', failures=[], errors=[], skips=[],
                      unexpected_successes=[], expected_failures=[], image_id=image, actual_image_id=image, application_revision='e'*40)
        self.assertEqual(verify_results(plan, [report])['status'], 'passed')
        for field in ['image_id', 'actual_image_id', 'application_revision']:
            for wrong in [None, plan['image_id'], 'sha256:'+'d'*64]:
                with self.assertRaises(ValueError): verify_results(plan, [{**report, field: wrong}])
        bad = copy.deepcopy(plan); bad['batches'][0]['image_id'] = plan['image_id']
        with self.assertRaises(ValueError): verify_results(bad, [{**report, 'plan_digest': digest(bad)}])

    def test_real_cache_mutation_is_rejected(self):
        import importlib.util
        from pathlib import Path
        import shutil
        import tempfile
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location('fixture_under_test', root/'server/stable/real_cache_test_fixture.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.verify_real_cache_fixtures()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'fixtures'; shutil.copytree(module.FIXTURES, target)
            page = next(target.rglob('*.html')); page.write_bytes(page.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                module.verify_real_cache_fixtures(target)

    def test_missing_plan_image_identity_is_rejected(self):
        import json
        from tools.test_impact.core import digest, verify_results
        plan = dict(mode='full', batches=[dict(key='batch-000', profile='django', ids=['m.C.test_x'], image_id='sha256:'+'a'*64)],
                    run_id='1', run_attempt='1', test_tree='c'*40)
        report = dict(key='batch-000', profile='django', executed=['m.C.test_x'], plan_digest=digest(plan),
                      run_id='1', run_attempt='1', test_tree='c'*40, exit_code=0, lifecycle='complete',
                      failures=[], errors=[], skips=[], expected_failures=[], unexpected_successes=[],
                      image_id='sha256:'+'a'*64, actual_image_id='sha256:'+'a'*64)
        with self.assertRaises(ValueError): verify_results(plan, [report])

    def test_raw_fixture_attributes_have_explicit_full_selection(self):
        import json
        from pathlib import Path
        from tools.test_impact.core import select_changes
        root = Path(__file__).resolve().parents[2]
        rules = json.loads((root/'tools/test_impact/rules.json').read_text())
        catalog = json.loads((root/'tools/test_impact/catalog.json').read_text())
        result = select_changes([{'path': '.gitattributes', 'before': '', 'after': '*.html -whitespace'}], rules, catalog)
        self.assertEqual(result['mode'], 'full')

    def test_tar_must_contain_both_images_even_if_daemon_has_them(self):
        import hashlib
        import io
        import json
        from pathlib import Path
        import tarfile
        import tempfile
        from scripts.verify_delivery_test_evidence import verify_image_archive
        configs = [b'{"image":"dependency"}', b'{"image":"application"}']
        ids = {'sha256:'+hashlib.sha256(c).hexdigest() for c in configs}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'images.tar'
            def archive(values):
                with tarfile.open(path, 'w') as tar:
                    manifest = []
                    for body in values:
                        name = hashlib.sha256(body).hexdigest()+'.json'
                        info = tarfile.TarInfo(name); info.size=len(body); tar.addfile(info, io.BytesIO(body))
                        manifest.append({'Config': name, 'Layers': [], 'RepoTags': None})
                    body=json.dumps(manifest).encode(); info=tarfile.TarInfo('manifest.json'); info.size=len(body);tar.addfile(info, io.BytesIO(body))
            archive(configs)
            self.assertEqual(set(verify_image_archive(path, ids)), ids)
            # 无论daemon中是否已缓存应用镜像，归档内容缺少它必须直接拒绝。
            archive(configs[:1])
            with self.assertRaises(ValueError): verify_image_archive(path, ids)
            archive(configs + [b'{"unexpected":true}'])
            with self.assertRaises(ValueError): verify_image_archive(path, ids)
