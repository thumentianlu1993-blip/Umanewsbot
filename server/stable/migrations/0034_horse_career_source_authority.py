from django.db import migrations, models


def downgrade_unverified_complete_careers(apps, schema_editor):
    HorseProfile = apps.get_model("stable", "HorseProfile")
    affected = HorseProfile.objects.filter(
        career_history_status="complete",
    ).exclude(
        career_record_authority_status="source_records_verified",
    )
    affected.filter(
        completeness_status="complete_profile_full",
    ).update(
        completeness_status="complete_pedigree_2gen",
    )
    affected.update(
        career_history_status="needs_review",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0033_merge_historical_detail_and_horse_career"),
    ]

    operations = [
        migrations.AddField(
            model_name="horseprofile",
            name="official_start_count_source",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="horseprofile",
            name="official_start_count_source_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="horseprofile",
            name="official_start_count_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="horseprofile",
            name="career_record_authority_status",
            field=models.CharField(
                choices=[
                    ("unknown", "逐场权威性待确认"),
                    ("source_records_verified", "逐场来源已核验"),
                    (
                        "count_aligned_records_unverified",
                        "数量已对齐、逐场官方性待确认",
                    ),
                    ("source_blocked", "逐场权威来源受阻"),
                ],
                default="unknown",
                max_length=32,
            ),
        ),
        migrations.RunPython(
            downgrade_unverified_complete_careers,
            migrations.RunPython.noop,
        ),
    ]
