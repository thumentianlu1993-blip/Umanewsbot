from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0052_horse_career_source_authority"),
    ]

    operations = [
        migrations.AddField(
            model_name="newsarticle",
            name="publish_ready_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="newsarticle",
            index=models.Index(
                fields=["racing_region", "automation_status", "publish_ready_at"],
                name="news_region_ready_at_idx",
            ),
        ),
    ]
