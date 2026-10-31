"""P02独立发布合同的拒绝条件；不访问业务数据库或外部服务。"""

import unittest

from stable.services import release_p02_recovery as c


class PrefixTests(unittest.TestCase):
    def setUp(self):
        self.base = [("stable", c.SOURCE), ("sessions", "0001_initial")]

    def test_only_exact_continuous_prefixes_are_accepted(self):
        for count in range(len(c.STEPS) + 1):
            with self.subTest(count=count):
                recorded = self.base + [("stable", name) for name in c.STEPS[:count]]
                self.assertEqual(c.applied_prefix(self.base, recorded), count)

    def test_gap_unknown_other_app_and_duplicate_recorders_are_rejected(self):
        for recorded in (
            self.base + [("stable", c.STEPS[1])],
            self.base + [("stable", "0082_other_project")],
            self.base + [("sessions", "0002_unknown")],
            self.base + [self.base[0]],
            self.base[1:],
        ):
            with self.subTest(recorded=recorded), self.assertRaisesRegex(ValueError, "recorder"):
                c.applied_prefix(self.base, recorded)


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.expected = {
            "candidate_commit": "a" * 40,
            "candidate_image_id": "sha256:" + "b" * 64,
            "database_identity_sha256": "c" * 64,
            "config_sha256": "d" * 64,
            "migration_contract_sha256": "e" * 64,
        }

    def test_every_identity_is_exact_and_required(self):
        c.validate_bindings(self.expected, dict(self.expected))
        for key in self.expected:
            for value in (None, "", "wrong"):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, "binding"):
                    c.validate_bindings(self.expected, {**self.expected, key: value})

    def test_expected_identity_itself_cannot_be_empty_or_malformed(self):
        for key in self.expected:
            bad = {**self.expected, key: ""}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "binding"):
                c.validate_bindings(bad, bad)


class RoleRestoreTests(unittest.TestCase):
    def test_only_exact_existing_bootstrap_create_is_removed(self):
        raw = b'CREATE ROLE postgres;\nALTER ROLE postgres SUPERUSER;\nCREATE ROLE pgapp;\nGRANT pgapp TO postgres GRANTED BY postgres;\n'
        restored = c.restore_roles_sql(raw, "postgres")
        self.assertNotIn(b"CREATE ROLE postgres;", restored)
        self.assertIn(b"ALTER ROLE postgres SUPERUSER;", restored)
        self.assertIn(b"CREATE ROLE pgapp;", restored)
        self.assertIn(b"GRANT pgapp TO postgres GRANTED BY postgres;", restored)
        quoted = b'CREATE ROLE "Boot""strap";\nALTER ROLE "Boot""strap" SUPERUSER;\n'
        self.assertIn(b'ALTER ROLE "Boot""strap"', c.restore_roles_sql(quoted, 'Boot"strap'))

    def test_missing_duplicate_and_multiline_bootstrap_are_rejected(self):
        for raw, role in ((b"CREATE ROLE other;\n", "postgres"),
                          (b"CREATE ROLE postgres;\nCREATE ROLE postgres;\n", "postgres"),
                          (b"", "line\nbreak")):
            with self.subTest(role=role), self.assertRaises(ValueError):
                c.restore_roles_sql(raw, role)


if __name__ == "__main__":
    unittest.main()
