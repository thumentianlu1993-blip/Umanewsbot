from unittest.mock import patch

from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase

from stable.test_migration_database_helpers import isolated_migration_database


class HistoricalMigrationDatabaseIsolationTests(TransactionTestCase):
    def test_real_migration_and_reconnect_leave_the_suite_database_unchanged(self):
        original = connections["default"]
        applied = MigrationRecorder(original).applied_migrations()
        tables = set(original.introspection.table_names())
        schema = None
        with isolated_migration_database() as temporary:
            self.assertIs(connections["default"], temporary)
            self.assertFalse(any(app == "stable" for app, _ in MigrationRecorder(temporary).applied_migrations()))
            executor = MigrationExecutor(temporary)
            executor.migrate([("stable", "0001_initial")])
            self.assertIn(("stable", "0001_initial"), MigrationRecorder(temporary).applied_migrations())
            if temporary.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_schema()")
                    schema = cursor.fetchone()[0]
                temporary.close()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_schema()")
                    self.assertEqual(cursor.fetchone()[0], schema)
                self.assertIn(("stable", "0001_initial"), MigrationRecorder(temporary).applied_migrations())
        self.assertIs(connections["default"], original)
        self.assertEqual(MigrationRecorder(original).applied_migrations(), applied)
        self.assertEqual(set(original.introspection.table_names()), tables)
        self.assertIsNone(temporary.connection)
        if schema:
            with original.cursor() as cursor:
                cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = %s)", [schema])
                self.assertFalse(cursor.fetchone()[0])

    def test_bootstrap_failure_restores_connection_and_discards_private_database(self):
        original = connections["default"]
        applied = MigrationRecorder(original).applied_migrations()
        temporary = None
        schema = None

        def fail_bootstrap(*args, **kwargs):
            nonlocal temporary, schema
            temporary = connections["default"]
            if temporary.vendor == "postgresql":
                with temporary.cursor() as cursor:
                    cursor.execute("SELECT current_schema()")
                    schema = cursor.fetchone()[0]
            raise RuntimeError("injected fixture bootstrap failure")

        with patch.object(MigrationExecutor, "migrate", side_effect=fail_bootstrap):
            with self.assertRaisesRegex(RuntimeError, "injected fixture bootstrap failure"):
                with isolated_migration_database():
                    self.fail("bootstrap failure must not enter the migration test")
        self.assertIs(connections["default"], original)
        self.assertEqual(MigrationRecorder(original).applied_migrations(), applied)
        self.assertIsNotNone(temporary)
        self.assertIsNone(temporary.connection)
        if schema:
            with original.cursor() as cursor:
                cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = %s)", [schema])
                self.assertFalse(cursor.fetchone()[0])
