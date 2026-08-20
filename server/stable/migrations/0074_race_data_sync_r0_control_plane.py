from django.db import migrations, models
import django.db.models.deletion


def adopt_source_identity_scope(apps, schema_editor):
    SourceIdentity = apps.get_model("stable", "RaceResultSourceIdentity")
    for source in SourceIdentity.objects.select_related("event").iterator(chunk_size=500):
        identity_fields = (
            dict(source.identity_fields)
            if isinstance(source.identity_fields, dict)
            else {}
        )
        region = identity_fields.get("region")
        namespace = identity_fields.get("identity_namespace")
        update_fields = []
        if isinstance(region, str) and region.strip() and len(region.strip()) <= 32:
            source.region_code = region.strip()
            update_fields.append("region_code")
        if (
            isinstance(namespace, str)
            and namespace.strip()
            and len(namespace.strip()) <= 64
        ):
            source.identity_namespace = namespace.strip()
            update_fields.append("identity_namespace")
        if not source.region_code or not source.identity_namespace:
            if source.automation_allowed:
                source.automation_allowed = False
                update_fields.append("automation_allowed")
            identity_fields["race_data_sync_adoption"] = "review_required"
            source.identity_fields = identity_fields
            update_fields.append("identity_fields")
        if update_fields:
            source.save(update_fields=tuple(dict.fromkeys(update_fields)))


class Migration(migrations.Migration):
    dependencies = [("stable", "0073_lifecycle_enforce_registry")]

    operations = [
        migrations.AddField(
            model_name="raceresultsourceidentity",
            name="identity_namespace",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="raceresultsourceidentity",
            name="region_code",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.RunPython(
            adopt_source_identity_scope,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name="raceresultsourceidentity",
            name="uq_race_srcid_source_external",
        ),
        migrations.RemoveConstraint(
            model_name="raceresultsourceidentity",
            name="uq_race_srcid_event_source",
        ),
        migrations.AddConstraint(
            model_name="raceresultsourceidentity",
            constraint=models.UniqueConstraint(
                fields=(
                    "source_key",
                    "region_code",
                    "identity_namespace",
                    "external_race_id",
                ),
                name="uq_race_srcid_route_external",
            ),
        ),
        migrations.AddConstraint(
            model_name="raceresultsourceidentity",
            constraint=models.UniqueConstraint(
                fields=(
                    "event",
                    "source_key",
                    "region_code",
                    "identity_namespace",
                ),
                name="uq_race_srcid_event_route",
            ),
        ),
        migrations.AlterField(
            model_name="raceeventprojectioncontrol",
            name="write_owner",
            field=models.CharField(
                choices=[
                    ("unmanaged", "未启用"),
                    ("historical", "历史导入"),
                    ("live", "准实时"),
                    ("data_sync", "赛事数据同步"),
                    ("manual_paused", "人工暂停"),
                ],
                default="unmanaged",
                max_length=16,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="raceeventprojectioncontrol",
            name="race_projection_owner_valid",
        ),
        migrations.AddConstraint(
            model_name="raceeventprojectioncontrol",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    write_owner__in=(
                        "unmanaged",
                        "historical",
                        "live",
                        "data_sync",
                        "manual_paused",
                    )
                ),
                name="race_projection_owner_valid",
            ),
        ),
        migrations.CreateModel(
            name="RaceDataSnapshotLease",
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
                ("cache_key", models.CharField(max_length=255, unique=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("claimed", "采集中"),
                            ("complete", "已完成"),
                            ("failed", "失败"),
                        ],
                        default="claimed",
                        max_length=16,
                    ),
                ),
                ("owner_token", models.CharField(blank=True, max_length=64)),
                ("lease_generation", models.PositiveBigIntegerField(default=1)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("artifact_sha256", models.CharField(blank=True, max_length=64)),
                ("manifest_data", models.JSONField(blank=True, default=dict)),
                ("retry_after", models.DateTimeField(blank=True, null=True)),
                ("error_code", models.CharField(blank=True, max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name="RaceEventLiveProviderCheckpoint",
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
                ("source_key", models.CharField(max_length=64)),
                (
                    "data_kind",
                    models.CharField(
                        choices=[
                            ("race_time", "开跑时间"),
                            ("racecard", "出马表"),
                            ("result", "赛果"),
                        ],
                        max_length=16,
                    ),
                ),
                ("next_poll_at", models.DateTimeField(blank=True, null=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_observation_hash", models.CharField(blank=True, max_length=64)),
                ("last_source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("circuit_reason", models.CharField(blank=True, max_length=64)),
                ("stale_at", models.DateTimeField(blank=True, null=True)),
                ("contract_digest", models.CharField(blank=True, max_length=64)),
                ("registry_digest", models.CharField(blank=True, max_length=64)),
                ("lock_version", models.PositiveBigIntegerField(default=0)),
                (
                    "tracking",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="provider_checkpoints",
                        to="stable.raceeventlivetracking",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="RaceDataSyncEnrollment",
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
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("proposed", "待纳管"),
                            ("enrolled", "已纳管"),
                            ("paused", "已暂停"),
                            ("retired", "已退出"),
                        ],
                        default="proposed",
                        max_length=16,
                    ),
                ),
                ("standing_policy_digest", models.CharField(max_length=64)),
                ("route_digest", models.CharField(max_length=64)),
                ("event_snapshot_sha256", models.CharField(max_length=64)),
                (
                    "projection_owner_generation",
                    models.PositiveBigIntegerField(default=0),
                ),
                ("enrollment_generation", models.PositiveBigIntegerField(default=1)),
                ("manifest_sha256", models.CharField(max_length=64)),
                ("entry_sha256", models.CharField(max_length=64)),
                ("reason_code", models.CharField(blank=True, max_length=64)),
                ("effective_at", models.DateTimeField(blank=True, null=True)),
                ("retired_at", models.DateTimeField(blank=True, null=True)),
                (
                    "event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="race_data_sync_enrollment",
                        to="stable.raceevent",
                    ),
                ),
                (
                    "source_identity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="race_data_sync_enrollments",
                        to="stable.raceresultsourceidentity",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="racedatasnapshotlease",
            constraint=models.CheckConstraint(
                condition=models.Q(state__in=("claimed", "complete", "failed")),
                name="race_data_snapshot_state_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="racedatasnapshotlease",
            constraint=models.CheckConstraint(
                condition=models.Q(lease_generation__gte=1),
                name="race_data_snapshot_generation_gte1",
            ),
        ),
        migrations.AddConstraint(
            model_name="racedatasnapshotlease",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        state="claimed",
                        owner_token__gt="",
                        lease_expires_at__isnull=False,
                        artifact_sha256="",
                        retry_after__isnull=True,
                        error_code="",
                    )
                    | models.Q(
                        state="complete",
                        owner_token="",
                        lease_expires_at__isnull=False,
                        artifact_sha256__gt="",
                        retry_after__isnull=True,
                        error_code="",
                    )
                    | models.Q(
                        state="failed",
                        owner_token="",
                        lease_expires_at__isnull=True,
                        artifact_sha256="",
                        retry_after__isnull=False,
                        error_code__gt="",
                    )
                ),
                name="race_data_snapshot_state_shape",
            ),
        ),
        migrations.AddIndex(
            model_name="racedatasnapshotlease",
            index=models.Index(
                fields=["state", "lease_expires_at"],
                name="race_data_snapshot_lease_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="raceeventliveprovidercheckpoint",
            constraint=models.UniqueConstraint(
                fields=("tracking", "source_key", "data_kind"),
                name="uq_race_data_ckpt_route_kind",
            ),
        ),
        migrations.AddConstraint(
            model_name="raceeventliveprovidercheckpoint",
            constraint=models.CheckConstraint(
                condition=models.Q(data_kind__in=("race_time", "racecard", "result")),
                name="race_data_ckpt_kind_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="raceeventliveprovidercheckpoint",
            index=models.Index(
                fields=["next_poll_at", "tracking"],
                name="race_data_ckpt_due_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="racedatasyncenrollment",
            constraint=models.CheckConstraint(
                condition=models.Q(state__in=("proposed", "enrolled", "paused", "retired")),
                name="race_data_enroll_state_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="racedatasyncenrollment",
            constraint=models.CheckConstraint(
                condition=models.Q(enrollment_generation__gte=1),
                name="race_data_enroll_gen_gte1",
            ),
        ),
        migrations.AddIndex(
            model_name="racedatasyncenrollment",
            index=models.Index(
                fields=["state", "event"],
                name="race_data_enroll_state_evt_idx",
            ),
        ),
    ]
