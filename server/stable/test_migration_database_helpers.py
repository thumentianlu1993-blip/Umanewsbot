"""Private test fixture for real historical migrations, without rewinding the suite DB."""

from contextlib import contextmanager
from uuid import uuid4

from django.db import connections
from django.db.migrations.executor import MigrationExecutor


@contextmanager
def isolated_migration_database():
    original = connections["default"]
    if original.in_atomic_block:
        raise RuntimeError("historical migration fixtures require TransactionTestCase")
    if original.vendor not in {"postgresql", "sqlite"}:
        raise RuntimeError("unsupported historical migration test database")

    temporary = original.copy(alias="default")
    schema = None
    created = False
    if original.vendor == "postgresql":
        schema = "migration_test_" + uuid4().hex
        options = temporary.settings_dict.setdefault("OPTIONS", {})
        # Keep reconnects inside the private schema, without a public fallback.
        options["options"] = (options.get("options", "") + f" -c search_path={schema}").strip()
    else:
        temporary.settings_dict["NAME"] = ":memory:"

    connections["default"] = temporary
    try:
        if schema:
            with temporary.cursor() as cursor:
                cursor.execute(f"CREATE SCHEMA {temporary.ops.quote_name(schema)}")
            created = True
        executor = MigrationExecutor(temporary)
        dependencies = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "stable"]
        if any(migration.app_label == "stable" for migration, _ in executor.migration_plan(dependencies)):
            raise RuntimeError("non-stable bootstrap unexpectedly depends on stable migrations")
        # Auth/contenttypes stay current; each test really migrates stable from
        # its own declared historical state, starting with no stable tables.
        executor.migrate(dependencies)
        yield temporary
    finally:
        connections["default"] = original
        try:
            if created:
                with temporary.cursor() as cursor:
                    cursor.execute(f"DROP SCHEMA {temporary.ops.quote_name(schema)} CASCADE")
        finally:
            if temporary.vendor == "sqlite" and temporary.connection is not None:
                # Django deliberately ignores close() on an in-memory database.
                temporary.connection.close()
                temporary.connection = None
            else:
                temporary.close()
