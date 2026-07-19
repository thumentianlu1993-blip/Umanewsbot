from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0050_backfill_horse_career_history"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="horseprofile",
            index=models.Index(
                fields=["career_history_status", "racing_region"],
                name="horse_career_region_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="horseracerecord",
            index=models.Index(
                fields=["horse_profile", "start_status"],
                name="horse_record_start_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="horseracerecord",
            index=models.Index(
                fields=["horse_profile", "canonical_race_key"],
                name="horse_record_canon_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="horseracerecord",
            constraint=models.UniqueConstraint(
                condition=~models.Q(canonical_race_key=""),
                fields=("horse_profile", "canonical_race_key"),
                name="uq_horse_record_canonical",
            ),
        ),
    ]
