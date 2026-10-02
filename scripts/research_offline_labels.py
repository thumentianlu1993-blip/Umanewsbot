#!/usr/bin/env python3
"""手动研究入口与 PR 共用纯离线模块清单；P0 编译器/账本只有一个归属。"""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def labels():
    catalog=json.loads((ROOT/'tools/test_impact/catalog.json').read_text())
    return sorted({label for domain in ('research_contracts','p0_bridge') for label in catalog['domains'][domain]
                   if label.startswith('runtime.research.')})


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(labels()))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
