from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0067_historical_calendar_release_a"),
    ]

    operations = [
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="celery_task_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="contract_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="contract_version",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="decision",
            field=models.CharField(blank=True, max_length=16),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="normalized_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="observation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="field_changes",
                to="stable.raceresultobservation",
            ),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="parser_version",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="raw_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="registry_digest",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="source_class",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="raceeventfieldchange",
            name="source_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
