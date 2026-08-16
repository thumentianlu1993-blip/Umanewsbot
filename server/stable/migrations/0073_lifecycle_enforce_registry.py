from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("stable", "0072_add_extended_racing_regions")]

    operations = [
        migrations.CreateModel(
            name="RaceEventLifecycleEnforceRegistry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("root_sha256", models.CharField(max_length=64, unique=True)),
                ("generation", models.PositiveBigIntegerField(unique=True)),
                ("membership_sha256", models.CharField(max_length=64)),
                ("member_count", models.PositiveIntegerField()),
                ("state", models.CharField(default="inactive", max_length=16)),
                ("is_active", models.BooleanField(default=False)),
                ("activation_id", models.CharField(blank=True, max_length=64)),
                ("approved_commit", models.CharField(max_length=40)),
                ("selector_scope", models.JSONField(default=dict)),
                ("scope_sha256", models.CharField(max_length=64)),
                ("census_cutoff", models.DateTimeField()),
                ("apply_expires_at", models.DateTimeField()),
                ("runtime_valid_until", models.DateTimeField()),
                ("artifact_receipt", models.JSONField(blank=True, default=dict)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("retired_at", models.DateTimeField(blank=True, null=True)),
                ("predecessor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="successors", to="stable.raceeventlifecycleenforceregistry")),
            ],
        ),
        migrations.CreateModel(
            name="RaceEventLifecycleEnforceMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("state", models.CharField(default="active", max_length=16)),
                ("entry_sha256", models.CharField(max_length=64)),
                ("source_enrollment_sha256", models.CharField(max_length=64)),
                ("schedule_generation", models.PositiveBigIntegerField()),
                ("schedule_hash", models.CharField(max_length=64)),
                ("country_region", models.CharField(max_length=32)),
                ("timezone_name", models.CharField(max_length=64)),
                ("frozen_snapshot", models.JSONField(blank=True, default=dict)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lifecycle_enforce_memberships", to="stable.raceevent")),
                ("registry", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="stable.raceeventlifecycleenforceregistry")),
            ],
        ),
        migrations.AddConstraint(
            model_name="raceeventlifecycleenforceregistry",
            constraint=models.UniqueConstraint(condition=models.Q(("is_active", True)), fields=("is_active",), name="uq_lifecycle_registry_active"),
        ),
        migrations.AddIndex(
            model_name="raceeventlifecycleenforceregistry",
            index=models.Index(fields=["state", "generation"], name="lifecycle_reg_state_gen_idx"),
        ),
        migrations.AddConstraint(
            model_name="raceeventlifecycleenforcemembership",
            constraint=models.UniqueConstraint(fields=("registry", "event"), name="uq_lifecycle_registry_event"),
        ),
        migrations.AddIndex(
            model_name="raceeventlifecycleenforcemembership",
            index=models.Index(fields=["registry", "event"], name="lifecycle_member_reg_evt_idx"),
        ),
        migrations.AddIndex(
            model_name="raceeventlifecycleenforcemembership",
            index=models.Index(fields=["registry", "state", "event"], name="lifecycle_member_state_idx"),
        ),
    ]
