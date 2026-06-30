from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stable", "0013_alter_newsarticle_source_site_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="newsarticle",
            index=models.Index(fields=["racing_region", "workflow_status", "-first_seen_at"], name="news_region_workflow_idx"),
        ),
        migrations.AddIndex(
            model_name="newsarticle",
            index=models.Index(fields=["racing_region", "automation_status", "-auto_publish_at"], name="news_region_auto_idx"),
        ),
        migrations.AddIndex(
            model_name="newsarticle",
            index=models.Index(fields=["racing_region", "-published_to_web_at"], name="news_region_public_idx"),
        ),
        migrations.AddIndex(
            model_name="newsarticle",
            index=models.Index(fields=["racing_region", "translation_status"], name="news_region_trans_idx"),
        ),
    ]
