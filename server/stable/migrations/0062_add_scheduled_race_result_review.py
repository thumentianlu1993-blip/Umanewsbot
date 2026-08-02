from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("stable", "0061_add_race_reference_observations")]

    operations = [
        migrations.CreateModel(
            name="RaceResultReviewRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("schedule_slot", models.DateTimeField(unique=True)),
                ("status", models.CharField(default="claimed", max_length=32)),
                ("selector_sha256", models.CharField(blank=True, max_length=64)),
                ("bundle_sha256", models.CharField(blank=True, max_length=64)),
                ("cursor", models.JSONField(blank=True, default=dict)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("terminal_summary", models.JSONField(blank=True, default=dict)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ("-schedule_slot", "-id")},
        ),
        migrations.CreateModel(
            name="RaceResultReviewPendingEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("first_seen_at", models.DateTimeField()),
                ("last_seen_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("reason_code", models.CharField(max_length=64)),
                ("snapshot_sha256", models.CharField(max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                ("event", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="result_review_pending", to="stable.raceevent")),
            ],
            options={"ordering": ("first_seen_at", "event_id")},
        ),
        migrations.CreateModel(
            name="RaceResultReviewDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bundle_sha256", models.CharField(max_length=64)),
                ("recipient", models.EmailField(max_length=254)),
                ("status", models.CharField(default="queued", max_length=16)),
                ("message_id", models.CharField(blank=True, max_length=255)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=64)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "constraints": [models.UniqueConstraint(fields=("bundle_sha256", "recipient"), name="uq_result_review_delivery_bundle_recipient")],
            },
        ),
        migrations.CreateModel(
            name="RaceResultReviewApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bundle_sha256", models.CharField(max_length=64)),
                ("reviewed_row_digest", models.CharField(max_length=64)),
                ("authority", models.CharField(choices=[("official", "官方"), ("human_reviewed_reference", "人工审核参考来源")], max_length=32)),
                ("reviewer", models.CharField(max_length=255)),
                ("confirmed_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="result_review_approvals", to="stable.raceevent")),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "constraints": [models.UniqueConstraint(fields=("bundle_sha256", "event", "reviewed_row_digest"), name="uq_result_review_approval_exact_scope")],
            },
        ),
    ]
