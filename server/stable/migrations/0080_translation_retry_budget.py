"""B041：仅创建离线账 schema；无回填或生产入口。"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("stable", "0079_multisource_race_enrollment")]
    operations = [
        migrations.CreateModel(
            name="TranslationRetryBudget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation_uuid", models.UUIDField(unique=True)),
                ("budget_uuid", models.UUIDField(unique=True)),
                ("scope_kind", models.CharField(max_length=48)),
                ("article_pk_snapshot", models.BigIntegerField(null=True, blank=True)),
                ("source_site_snapshot", models.CharField(max_length=32)),
                ("source_article_id_snapshot", models.CharField(max_length=255)),
                ("identity_sha256", models.CharField(max_length=64)),
                ("source_sha256", models.CharField(max_length=64)),
                ("provider_snapshot", models.CharField(max_length=128)),
                ("model_snapshot", models.CharField(max_length=255)),
                ("policy_snapshot", models.JSONField(default=dict)),
                ("policy_sha256", models.CharField(max_length=64)),
                ("opened_at", models.DateTimeField()),
                ("deadline_at", models.DateTimeField()),
                ("request_limit", models.PositiveIntegerField()),
                ("requests_reserved", models.PositiveIntegerField(default=0)),
                ("state", models.CharField(max_length=32, default="open")),
                ("blocked_reason", models.CharField(max_length=128, blank=True)),
                ("retired_at", models.DateTimeField(null=True, blank=True)),
            ],
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(fields=("scope_kind", "source_site_snapshot", "source_article_id_snapshot"), condition=models.Q(retired_at__isnull=True), name="uq_tr_budget_active_source"),
                    models.CheckConstraint(condition=models.Q(request_limit__gt=0), name="ck_tr_budget_limit_positive"),
                    models.CheckConstraint(condition=models.Q(requests_reserved__gte=0) & models.Q(requests_reserved__lte=models.F("request_limit")), name="ck_tr_budget_reserved_bounds"),
                    models.CheckConstraint(condition=models.Q(deadline_at__gt=models.F("opened_at")), name="ck_tr_budget_deadline"),
                ],
            },
        ),
        migrations.CreateModel(
            name="TranslationRequestAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("budget", models.ForeignKey(to="stable.translationretrybudget", on_delete=django.db.models.deletion.PROTECT, related_name="request_attempts")),
                ("operation_uuid", models.UUIDField()),
                ("budget_uuid", models.UUIDField()),
                ("claim_execution_uuid", models.UUIDField()),
                ("article_pk_snapshot", models.BigIntegerField(null=True, blank=True)),
                ("run_pk_snapshot", models.BigIntegerField(null=True, blank=True)),
                ("claimed_at", models.DateTimeField()),
                ("source_site_snapshot", models.CharField(max_length=32)),
                ("source_article_id_snapshot", models.CharField(max_length=255)),
                ("identity_sha256", models.CharField(max_length=64)),
                ("source_sha256", models.CharField(max_length=64)),
                ("seq", models.PositiveIntegerField()),
                ("provider_attempt_index", models.PositiveIntegerField()),
                ("reserved_at", models.DateTimeField()),
                ("state", models.CharField(max_length=32, default="reserved")),
                ("usage_report", models.JSONField(default=dict)),
                ("usage_validation", models.CharField(max_length=32, default="unknown")),
                ("reconciliation_state", models.CharField(max_length=48, default="unreconciled")),
                ("receipt_sha256", models.CharField(max_length=64, blank=True)),
            ],
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "constraints": [
                    models.UniqueConstraint(fields=("budget", "seq"), name="uq_tr_attempt_budget_seq"),
                    models.UniqueConstraint(fields=("budget", "claim_execution_uuid", "provider_attempt_index"), name="uq_tr_attempt_claim_index"),
                    models.CheckConstraint(condition=models.Q(seq__gt=0), name="ck_tr_attempt_seq_positive"),
                    models.CheckConstraint(condition=models.Q(provider_attempt_index__gt=0), name="ck_tr_attempt_index_positive"),
                ],
            },
        ),
    ]
