from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0057_merge_20260725_0448"),
    ]

    operations = [
        migrations.CreateModel(
            name="HorseIdentityEvidenceCommitReceipt",
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
                ("approved_sha256", models.CharField(max_length=64, unique=True)),
                ("artifact_sha256", models.CharField(max_length=64)),
                ("approved_by", models.CharField(max_length=255)),
                ("approved_profile_ids", models.JSONField(default=list)),
                ("before_after", models.JSONField(default=dict)),
                ("evidence_summary", models.JSONField(default=dict)),
                ("result_payload", models.JSONField(default=dict)),
                (
                    "operation_log",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="horse_identity_evidence_receipt",
                        to="stable.operationlog",
                    ),
                ),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
    ]
