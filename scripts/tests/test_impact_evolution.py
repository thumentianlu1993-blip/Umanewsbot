"""真实Git差异验证映射演进；不执行应用。"""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.plan_affected_tests import create_plan


class PlanEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.git('init','-q');self.git('config','user.email','ci@example.invalid');self.git('config','user.name','ci')
        self.rules={'schema_version':1,'docs':['docs/*.md'],'high_risk':['tools/test_impact/**'],
                    'paths':{},'symbols':{'server/stable/views.py':{'old':['horse']}}}
        self.catalog={'schema_version':1,'domains':{'core':['stable.test_core'],'horse':['stable.test_a','stable.test_b']},
                      'tests':{'server/stable/test_a.py':{'label':'stable.test_a','domains':['horse']},
                               'server/stable/test_b.py':{'label':'stable.test_b','domains':['horse']}},'dependencies':{}}
        for p in ('server/stable/test_a.py','server/stable/test_b.py'):self.write(p,'class T:\n def test_x(self): pass\n')
        self.write('server/stable/views.py','def old(): return 1\n');self.save();self.base=self.commit()

    def git(self,*args):return subprocess.check_output(['git','-C',str(self.root),*args],text=True,stderr=subprocess.DEVNULL).strip()
    def write(self,p,text):
        file=self.root/p;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(text)
    def save(self):
        for name,value in [('rules',self.rules),('catalog',self.catalog)]:self.write('tools/test_impact/'+name+'.json',json.dumps(value))
    def commit(self):self.git('add','-A');self.git('commit','-qm','fixture');return self.git('rev-parse','HEAD')
    def plan(self):
        head=self.commit()
        try:return create_plan(self.root,self.base,head,head)
        except ValueError as exc:self.fail('合法映射演进被拒绝: '+str(exc))

    def test_registered_new_symbol_preserves_old_full_requirements(self):
        self.rules['symbols']['server/stable/views.py']['new']=['horse'];self.save()
        self.write('server/stable/views.py','def old(): return 1\ndef new(): return 2\n')
        p=self.plan();self.assertEqual(p['mode'],'full');self.assertIn('stable.test_b',p['labels'])

    def test_deleted_test_is_recorded_and_remaining_domain_is_tested(self):
        (self.root/'server/stable/test_a.py').unlink();del self.catalog['tests']['server/stable/test_a.py']
        self.catalog['domains']['horse'].remove('stable.test_a');self.save()
        p=self.plan();self.assertEqual(p['deleted_test_modules'],['stable.test_a'])
        self.assertIn('stable.test_b',p['labels']);self.assertNotIn('stable.test_a',p['labels'])

    def test_new_registered_test_is_collected(self):
        self.write('server/stable/test_c.py','class T:\n def test_x(self): pass\n')
        self.catalog['domains']['horse'].append('stable.test_c')
        self.catalog['tests']['server/stable/test_c.py']={'label':'stable.test_c','domains':['horse']};self.save()
        self.assertIn('stable.test_c',self.plan()['labels'])

    def test_deleting_reexport_preserves_existing_canonical_module(self):
        alias='server/stable/tests/__init__.py'
        self.write(alias,'from stable.test_a import *\n')
        self.catalog['tests'][alias]={'label':'stable.test_a','domains':['horse']}
        self.save();self.base=self.commit()
        (self.root/alias).unlink();del self.catalog['tests'][alias];self.save()
        p=self.plan()
        self.assertIn('stable.test_a',p['labels'])
        self.assertNotIn('stable.test_a',p['deleted_test_modules'])

    def test_renamed_class_or_method_expands_old_requirement_to_live_module(self):
        old_labels=['stable.test_a.T','stable.test_b.T.test_x']
        self.catalog['domains']['horse']=old_labels;self.save();self.base=self.commit()
        self.write('server/stable/test_a.py','class Renamed:\n def test_x(self): pass\n')
        self.write('server/stable/test_b.py','class T:\n def test_renamed(self): pass\n')
        self.catalog['domains']['horse']=['stable.test_a.Renamed','stable.test_b.T.test_renamed']
        self.save();p=self.plan()
        for label in old_labels:self.assertNotIn(label,p['labels'])
        self.assertIn('stable.test_a',p['labels']);self.assertIn('stable.test_b',p['labels'])
        self.assertEqual(set(p['superseded_test_labels']),set(old_labels))

    def test_explicit_release_same_sha_does_not_require_a_diff(self):
        from unittest.mock import patch
        from scripts import impact_ci
        self.catalog['domains']['release']=['stable.test_b'];self.save();head=self.commit()
        output=self.root/'release.json'
        argv=['impact_ci','--base',head,'--head',head,'--test',head,'--scope','release','--reason','missing release evidence','--output',str(output)]
        with patch.object(impact_ci,'ROOT',self.root),patch('sys.argv',argv),patch.dict('os.environ',{},clear=True):
            impact_ci.main()
        plan=json.loads(output.read_text());self.assertEqual(plan['mode'],'validation-only');self.assertEqual(plan['labels'],['stable.test_b'])
        with self.assertRaisesRegex(ValueError,'empty diff'):create_plan(self.root,head,head,head)

class ScopedPlanIntegrationTests(unittest.TestCase):
    setUp = PlanEvolutionTests.setUp
    git = PlanEvolutionTests.git
    write = PlanEvolutionTests.write
    save = PlanEvolutionTests.save
    commit = PlanEvolutionTests.commit
    def test_new_scope_exact_binding_full_override_and_future_default(self):
        from tools.test_impact.git_input import inputs
        from tools.test_impact.reviewed_scope import FIELDS
        path='docs/scoped.json'
        self.rules['reviewed_change_scopes']=[path]
        self.rules['paths'][path]=['horse'];self.save()
        self.write('server/stable/views.py','def old(): return 2\n')
        head=self.commit();data=inputs(self.root,self.base,head,head)
        manifest={'schema_version':1,'base_sha':self.base,'reason':'explicit scoped acceptance',
                  'domains':['horse'],'changes':[{k:r[k] for k in FIELDS} for r in data['changes']]}
        self.write(path,json.dumps(manifest));head=self.commit()
        plan=create_plan(self.root,self.base,head,head)
        self.assertEqual(plan['mode'],'targeted');self.assertIn('reviewed_scope_sha256',plan)
        full=create_plan(self.root,self.base,head,head,full_reason='explicit full request')
        self.assertEqual(full['mode'],'full');self.assertNotIn('reviewed_scope_sha256',full)
        self.write('server/stable/views.py','def old(): return 3\n');changed=self.commit()
        with self.assertRaisesRegex(ValueError,'scope changed'):
            create_plan(self.root,self.base,changed,changed)
        later=create_plan(self.root,head,changed,changed)
        self.assertNotIn('reviewed_scope_sha256',later)


class ReviewedScopeTests(unittest.TestCase):
    def setUp(self):
        self.change={'path':'server/x.py','status':'modified','before_hash':'a'*64,'after_hash':'b'*64,'before_mode':'100644','after_mode':'100644'}
        self.manifest={'schema_version':1,'base_sha':'c'*40,'reason':'用户明确要求本次按实际影响范围验证',
            'changes':[self.change.copy()],'domains':['race']}
        self.catalog={'domains':{'core':['core.tests'],'race':['race.tests'],'dependency':['dep.tests'],'other':['other.tests']},'dependencies':{'race':['dependency']}}
        self.old={'mode':'full','domains':list(self.catalog['domains']),'labels':['old'],'reasons':[]}
    def apply(self,changes=None,manifest=None,base=None):
        from tools.test_impact.reviewed_scope import apply_reviewed_scope
        return apply_reviewed_scope(self.old,changes=changes or [self.change],manifest=manifest or self.manifest,
            base_sha=base or 'c'*40,catalog=self.catalog)
    def test_exact_scope_keeps_core_and_dependency_and_records_digest(self):
        value=self.apply();self.assertEqual(value['mode'],'targeted')
        self.assertEqual(value['labels'],['core.tests','dep.tests','race.tests'])
        self.assertEqual(len(value['reviewed_scope_sha256']),64)
    def test_extra_path_content_mode_base_or_domain_drift_is_rejected(self):
        for field,value in [('path','server/other.py'),('after_hash','d'*64),('after_mode','100755'),('status','deleted')]:
            with self.subTest(field=field),self.assertRaises(ValueError):self.apply(changes=[{**self.change,field:value}])
        with self.assertRaises(ValueError):self.apply(changes=[self.change,{**self.change,'path':'extra'}])
        with self.assertRaises(ValueError):self.apply(base='e'*40)
        with self.assertRaises(ValueError):self.apply(manifest={**self.manifest,'domains':['unknown']})
    def test_empty_reason_or_duplicate_scope_rows_is_rejected(self):
        with self.assertRaises(ValueError):self.apply(manifest={**self.manifest,'reason':''})
        with self.assertRaises(ValueError):self.apply(manifest={**self.manifest,'changes':[self.change,self.change]})
