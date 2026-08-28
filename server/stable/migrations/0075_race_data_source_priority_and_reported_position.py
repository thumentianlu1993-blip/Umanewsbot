from django.db import migrations, models
from django.db.models.functions import Coalesce


def backfill_reported_finish_positions(apps, schema_editor):
    RevisionItem = apps.get_model("stable", "RaceEventRevisionItem")
    Result = apps.get_model("stable", "RaceEventResult")
    RevisionItem.objects.filter(reported_finish_position__isnull=True).update(
        reported_finish_position=models.F("official_finish_position")
    )
    Result.objects.filter(reported_finish_position__isnull=True).update(
        reported_finish_position=Coalesce(
            "official_finish_position",
            "finish_position",
        )
    )


class Migration(migrations.Migration):
    dependencies = [("stable", "0074_race_data_sync_r0_control_plane")]

    operations = [
        migrations.AddField(
            model_name="raceeventfieldauthority",
            name="source_class",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="raceeventrevisionitem",
            name="reported_finish_position",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="raceeventresult",
            name="reported_finish_position",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(
            backfill_reported_finish_positions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
