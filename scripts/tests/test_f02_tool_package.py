import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from scripts import f02_tool_package as package

class PackageTests(unittest.TestCase):
    def payloads(self):
        return {name: b'# synthetic module\n' for name in package.MODULE_FILES}

    def test_private_exact_package_and_hash_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'tools'
            receipt = package.build_package(self.payloads(), root, 'a'*40)
            self.assertNotEqual(receipt['manifest_sha256'], 'not_implemented')
            verified = package.verify_package(root, receipt['manifest_sha256'])
            self.assertEqual(verified['git_sha'], 'a'*40)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            for path in root.rglob('*'):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
            (root / package.MODULE_FILES[0]).write_bytes(b'PRIVATE changed')
            with self.assertRaises(package.PackageError):
                package.verify_package(root, receipt['manifest_sha256'])

    def test_missing_extra_symlink_existing_and_isolated_bootstrap(self):
        for fault in ('missing', 'extra', 'link', 'none'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve() / 'tools'
                receipt = package.build_package(self.payloads(), root, 'a'*40)
                if fault == 'missing':
                    (root/package.MODULE_FILES[0]).unlink()
                elif fault == 'extra':
                    (root/'extra.py').write_text('PRIVATE')
                elif fault == 'link':
                    path = root/package.MODULE_FILES[0]; path.unlink(); path.symlink_to(root/'entry.py')
                if fault != 'none':
                    with self.assertRaises(package.PackageError):
                        package.verify_package(root, receipt['manifest_sha256'])
                result = subprocess.run([sys.executable, '-I', '-B', str(root/'entry.py'), receipt['manifest_sha256'], 'verify'],
                                        capture_output=True, timeout=3)
                self.assertEqual(result.returncode, 0 if fault == 'none' else 2)
                self.assertNotIn(b'PRIVATE', result.stdout + result.stderr)
                with self.assertRaises(package.PackageError):
                    package.build_package(self.payloads(), root, 'a'*40)
