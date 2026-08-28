from django.db import migrations, models


def backfill_reported_finish_positions(apps, schema_editor):
    RevisionItem = apps.get_model("stable", "RaceEventRevisionItem")
    Result = apps.get_model("stable", "RaceEventResult")
    RevisionItem.objects.filter(reported_finish_position__isnull=True).update(
        reported_finish_position=models.F("official_finish_position")
    )
    Result.objects.filter(
        reported_finish_position__isnull=True,
        official_finish_position__isnull=False,
    ).update(
        reported_finish_position=models.F("official_finish_position")
    )


class Migration(migrations.Migration):
    dependencies = [("stable", "0074_race_data_sync_r0_control_plane")]

    operations = [
        migrations.CreateModel(
            name="RaceDataTransportCapacityLedger",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(max_length=64)),
                ("region_code", models.CharField(max_length=32)),
                ("usage_date", models.DateField()),
                ("request_count", models.PositiveIntegerField(default=0)),
                (
                    "budgeted_response_bytes",
                    models.PositiveBigIntegerField(default=0),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["usage_date", "provider", "region_code"],
                        name="race_data_capacity_day_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("provider", "region_code", "usage_date"),
                        name="race_data_capacity_day_uq",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(provider=""),
                        name="race_data_capacity_provider_nonempty",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(region_code=""),
                        name="race_data_capacity_region_nonempty",
                    ),
                ],
            },
        ),
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
