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
