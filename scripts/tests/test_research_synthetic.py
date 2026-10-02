"""共享 synthetic CLI 合同：首次安全停止，续跑产物逐字节一致。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]


class ResearchSyntheticTests(unittest.TestCase):
    def test_stop_resume_and_seven_final_files(self):
        with tempfile.TemporaryDirectory() as raw:
            from scripts.research_synthetic import run
            report=run(Path(raw))
            self.assertIs(report['byte_equivalent'],True)
            self.assertEqual(len(report['final_files']),7)


if __name__=='__main__':unittest.main()
