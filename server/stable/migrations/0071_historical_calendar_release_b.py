from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0070_horse_identity_evidence_commit_receipt"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="raceevent",
            name="uq_race_event_series_year",
        ),
        migrations.AddConstraint(
            model_name="raceevent",
            constraint=models.UniqueConstraint(
                fields=("race_series", "edition_year"),
                condition=models.Q(
                    race_series__isnull=False,
                    edition_year__isnull=False,
                ),
                name="uq_race_event_series_edition",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="historicalraceeventtarget",
            name="uq_historical_target_series_year",
        ),
        migrations.AddConstraint(
            model_name="historicalraceeventtarget",
            constraint=models.UniqueConstraint(
                fields=("race_series", "year"),
                condition=~models.Q(resolution_status="superseded"),
                name="uq_hist_target_active_series_year",
            ),
        ),
    ]
