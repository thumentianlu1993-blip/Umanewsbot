from __future__ import annotations

import importlib
from contextlib import contextmanager

from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError
from django.test import SimpleTestCase


migration = importlib.import_module(
    "stable.migrations.0077_racing_api_horse_identity_staging"
)


class _FakeConnection:
    def __init__(self, vendor: str):
        self.vendor = vendor
        self.statements: list[str] = []
        self.cursor_opened = False

    @contextmanager
    def cursor(self):
        self.cursor_opened = True
        connection = self

        class _Cursor:
            def execute(self, statement):
                connection.statements.append(statement)

        yield _Cursor()


class _FakeSchemaEditor:
    def __init__(self, vendor: str):
        self.connection = _FakeConnection(vendor)


class RacingApiHorseStagingMigrationTests(SimpleTestCase):
    def test_timeout_guard_is_first_atomic_migration_operation(self):
        self.assertTrue(migration.Migration.atomic)
        first = migration.Migration.operations[0]
        self.assertIsInstance(first, migrations.RunPython)
        self.assertIs(first.code, migration.set_postgresql_migration_timeouts)

    def test_postgresql_timeout_guard_sets_local_limits(self):
        schema_editor = _FakeSchemaEditor("postgresql")

        migration.set_postgresql_migration_timeouts(None, schema_editor)

        self.assertTrue(schema_editor.connection.cursor_opened)
        self.assertEqual(
            schema_editor.connection.statements,
            [
                "SET LOCAL lock_timeout = '5s'",
                "SET LOCAL statement_timeout = '5min'",
            ],
        )

    def test_timeout_guard_is_noop_for_sqlite(self):
        schema_editor = _FakeSchemaEditor("sqlite")

        migration.set_postgresql_migration_timeouts(None, schema_editor)

        self.assertFalse(schema_editor.connection.cursor_opened)
        self.assertEqual(schema_editor.connection.statements, [])

    def test_reverse_is_explicitly_forbidden_before_reverse_ddl(self):
        last = migration.Migration.operations[-1]

        self.assertIsInstance(last, migrations.RunPython)
        self.assertIs(last.reverse_code, migration.forbid_reverse)
        with self.assertRaises(IrreversibleError):
            migration.forbid_reverse(None, None)
