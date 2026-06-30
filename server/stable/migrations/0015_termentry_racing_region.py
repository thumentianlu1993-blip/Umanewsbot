from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stable", "0014_multiregion_news_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="termentry",
            name="racing_region",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "全局通用"),
                    ("japan", "日本"),
                    ("hong_kong", "中国香港"),
                    ("united_kingdom", "英国"),
                    ("france", "法国"),
                    ("united_states", "美国"),
                    ("other", "其他"),
                ],
                default="",
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="termentry",
            index=models.Index(fields=["racing_region", "source_language", "term_type"], name="term_region_lang_type_idx"),
        ),
    ]
