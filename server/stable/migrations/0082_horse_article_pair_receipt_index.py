"""C256：私有首次 pair 归档；仅 schema/PG 行拒改，无回填或角色授权。"""
from django.db import migrations, models
from django.db.models.lookups import GreaterThan, LessThanOrEqual
import django.utils.timezone


class PostgresOnlyRunSQL(migrations.RunSQL):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_backwards(app_label, schema_editor, from_state, to_state)


CREATE_GUARD = """
CREATE FUNCTION stable_reject_horse_pair_receipt_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'HorseArticlePairReceiptIndex is append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER stable_horse_pair_receipt_append_only
BEFORE UPDATE OR DELETE ON stable_horsearticlepairreceiptindex
FOR EACH ROW EXECUTE FUNCTION stable_reject_horse_pair_receipt_mutation();
"""
DROP_GUARD = """
DROP TRIGGER IF EXISTS stable_horse_pair_receipt_append_only ON stable_horsearticlepairreceiptindex;
DROP FUNCTION IF EXISTS stable_reject_horse_pair_receipt_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("stable", "0081_managed_readonly_steps")]
    operations = [
        migrations.CreateModel(
            name="HorseArticlePairReceiptIndex",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("article_id_snapshot", models.BigIntegerField()),
                ("profile_id_snapshot", models.BigIntegerField()),
                ("producer_namespace", models.CharField(max_length=255)),
                ("request_id", models.CharField(max_length=255)),
                ("request_key", models.CharField(max_length=64)),
                ("operation_log_id_snapshot", models.BigIntegerField()),
                ("original_link_id", models.BigIntegerField()),
                ("original_actor_id", models.BigIntegerField()),
                ("receipt_detail", models.TextField()),
                ("receipt_detail_sha256", models.CharField(max_length=64)),
                ("protocol_version", models.CharField(max_length=64)),
                ("recorded_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("article_id_snapshot", "profile_id_snapshot"),
                                        name="uq_horse_pair_receipt_pair"),
                models.UniqueConstraint(fields=("request_key",), name="uq_horse_pair_receipt_key"),
                models.UniqueConstraint(fields=("operation_log_id_snapshot",), name="uq_horse_pair_receipt_log"),
                models.CheckConstraint(condition=models.Q(article_id_snapshot__gt=0, profile_id_snapshot__gt=0,
                    operation_log_id_snapshot__gt=0, original_link_id__gt=0, original_actor_id__gt=0),
                    name="ck_hpair_index_ids"),
                models.CheckConstraint(condition=models.Q(request_key__regex=r"^[0-9a-f]{64}$",
                    receipt_detail_sha256__regex=r"^[0-9a-f]{64}$"), name="ck_hpair_index_hashes"),
                models.CheckConstraint(condition=(
                    GreaterThan(models.Func(models.F("receipt_detail"), function="OCTET_LENGTH", output_field=models.BigIntegerField()), 0)
                    & LessThanOrEqual(models.Func(models.F("receipt_detail"), function="OCTET_LENGTH", output_field=models.BigIntegerField()), 4_194_304)),
                    name="ck_hpair_index_bytes"),
            ]},
        ),
        # Does not cover TRUNCATE/DROP/owner bypass or authenticate INSERT.
        PostgresOnlyRunSQL(sql=CREATE_GUARD, reverse_sql=DROP_GUARD),
    ]
