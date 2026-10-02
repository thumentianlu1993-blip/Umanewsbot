"""真实临时 Git 仓库验证输入边界，不接触业务数据库。"""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.test_impact.git_input import inputs


class GitInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.git('init','-q');self.git('config','user.email','synthetic@example.invalid');self.git('config','user.name','test')
        (self.root/'deploy.sh').write_text('echo safe\n');(self.root/'guide.md').write_text('old\n')
        self.git('add','.');self.git('commit','-qm','base');self.base=self.git('rev-parse','HEAD').strip()

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.root),*args],text=True,stderr=subprocess.DEVNULL)

    def test_mode_only_change_is_not_documentation(self):
        (self.root/'deploy.sh').chmod(0o755);(self.root/'guide.md').write_text('new\n')
        self.git('add','.');self.git('commit','-qm','change');head=self.git('rev-parse','HEAD').strip()
        result=inputs(self.root,self.base,head,head)
        self.assertEqual({c['path'] for c in result['changes']},{'deploy.sh','guide.md'})

    def test_local_tracks_index_even_if_worktree_restored(self):
        p=self.root/'deploy.sh';p.write_text('echo indexed\n');self.git('add','deploy.sh');p.write_text('echo safe\n')
        result=inputs(self.root,self.base,self.base,self.base,local=True)
        self.assertIn('deploy.sh',[c['path'] for c in result['changes']])

    def test_deleted_renamed_untracked_included(self):
        (self.root/'deploy.sh').rename(self.root/'renamed.sh');(self.root/'new.py').write_text('x=1')
        result=inputs(self.root,self.base,self.base,self.base,local=True)
        self.assertEqual({c['path'] for c in result['changes']},{'deploy.sh','renamed.sh','new.py'})

    def test_symlink_and_short_sha_refused(self):
        with self.assertRaisesRegex(ValueError,'40-character'):inputs(self.root,'HEAD',self.base,self.base)
        (self.root/'escape').symlink_to('/tmp')
        with self.assertRaisesRegex(ValueError,'unsafe'):inputs(self.root,self.base,self.base,self.base,local=True)
