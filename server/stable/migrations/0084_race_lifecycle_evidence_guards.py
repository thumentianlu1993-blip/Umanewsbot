from django.db import migrations


TABLES = ("stable_racelifecycleepochpublication", "stable_racelifecyclereceipt")


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE FUNCTION stable_lifecycle_evidence_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'lifecycle evidence is immutable';
        END; $$;
    """)
    for table in TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER lifecycle_evidence_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION stable_lifecycle_evidence_immutable()"
        )


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER lifecycle_evidence_immutable ON {table}")
    schema_editor.execute("DROP FUNCTION stable_lifecycle_evidence_immutable()")


class Migration(migrations.Migration):
    dependencies = [("stable", "0083_race_lifecycle_publication")]
    operations = [migrations.RunPython(install, uninstall)]
