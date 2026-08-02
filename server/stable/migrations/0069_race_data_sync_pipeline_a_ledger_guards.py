from django.db import migrations, models


class PostgresOnlyRunSQL(migrations.RunSQL):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_backwards(app_label, schema_editor, from_state, to_state)


CREATE_LEDGER_GUARD_SQL = """
CREATE OR REPLACE FUNCTION stable_reject_race_field_change_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'RaceEventFieldChange is append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER stable_race_field_change_append_only
BEFORE UPDATE OR DELETE ON stable_raceeventfieldchange
FOR EACH ROW EXECUTE FUNCTION stable_reject_race_field_change_mutation();
"""

DROP_LEDGER_GUARD_SQL = """
DROP TRIGGER IF EXISTS stable_race_field_change_append_only
    ON stable_raceeventfieldchange;
DROP FUNCTION IF EXISTS stable_reject_race_field_change_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0068_race_data_sync_pipeline_a_field_audit"),
    ]

    operations = [
        migrations.AlterField(
            model_name="raceeventfieldchange",
            name="decision",
            field=models.CharField(
                blank=True,
                choices=[
                    ("applied", "已应用"),
                    ("replayed", "重放"),
                    ("needs_review", "待审核"),
                    ("rejected", "已拒绝"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="raceeventfieldchange",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(decision="")
                    | models.Q(
                        decision__in=(
                            "applied",
                            "replayed",
                            "needs_review",
                            "rejected",
                        )
                    )
                ),
                name="race_field_change_decision_valid",
            ),
        ),
        PostgresOnlyRunSQL(
            sql=CREATE_LEDGER_GUARD_SQL,
            reverse_sql=DROP_LEDGER_GUARD_SQL,
        ),
    ]
