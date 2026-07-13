from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("stable", "0027_p0_horse_profile_completion")]

    operations = [
        migrations.CreateModel(
            name="TermGateReprocessRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mode", models.CharField(choices=[("dry_run", "Dry run"), ("commit", "Commit")], max_length=16)),
                ("selectors", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "待执行"), ("running", "执行中"), ("succeeded", "已完成"), ("failed", "失败"), ("rejected", "已拒绝"), ("committed", "已提交")], default="pending", max_length=16)),
                ("cursor", models.TextField(blank=True)),
                ("rule_version", models.CharField(blank=True, max_length=64)),
                ("settings_sha256", models.CharField(blank=True, max_length=64)),
                ("term_snapshot_sha256", models.CharField(blank=True, max_length=64)),
                ("candidate_payload", models.JSONField(blank=True, default=list)),
                ("result_payload", models.JSONField(blank=True, default=dict)),
                ("manifest_sha256", models.CharField(blank=True, max_length=64)),
                ("statistics", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ("-started_at", "-id")},
        ),
        migrations.CreateModel(
            name="TermGateReprocessLock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.CharField(max_length=64, unique=True)),
                ("owner_token", models.CharField(blank=True, max_length=64)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("locked_by_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="leases", to="stable.termgatereprocessrun")),
            ],
            options={"ordering": ("key",)},
        ),
        migrations.AddIndex(model_name="termgatereprocessrun", index=models.Index(fields=["status", "-started_at"], name="termgate_run_status_idx")),
        migrations.AddIndex(model_name="termgatereprocessrun", index=models.Index(fields=["mode", "-started_at"], name="termgate_run_mode_idx")),
    ]
