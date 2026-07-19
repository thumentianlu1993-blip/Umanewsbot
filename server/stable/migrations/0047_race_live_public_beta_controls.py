import django.db.models.deletion
from django.db import migrations, models


def backfill_last_provisional_result_revision(apps, schema_editor):
    Control = apps.get_model("stable", "RaceEventProjectionControl")
    Revision = apps.get_model("stable", "RaceEventRevision")
    for control in Control.objects.all().iterator():
        revision_id = (
            Revision.objects.filter(
                event_id=control.event_id,
                kind="result",
                phase="provisional",
                published_at__isnull=False,
                publication__isnull=False,
            )
            .order_by("-published_at", "-revision_no", "-pk")
            .values_list("pk", flat=True)
            .first()
        )
        if revision_id is not None:
            Control.objects.filter(pk=control.pk).update(
                last_provisional_result_revision_id=revision_id
            )


class Migration(migrations.Migration):

    dependencies = [
        ("stable", "0046_race_live_manual_verification_contract"),
    ]

    operations = [
        migrations.AddField(
            model_name="raceeventprojectioncontrol",
            name="last_provisional_result_revision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="last_provisional_result_projection_controls",
                to="stable.raceeventrevision",
            ),
        ),
        migrations.AddField(
            model_name="raceeventrevisionpublication",
            name="authorization_kind",
            field=models.CharField(
                choices=[
                    ("provisional_policy", "暂定赛果策略"),
                    ("official_route", "官方来源授权"),
                ],
                default="provisional_policy",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="raceeventrevisionpublication",
            name="official_authorization_version",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="RaceLiveAlertIncident",
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
                    "alert_type",
                    models.CharField(
                        choices=[
                            ("provisional_overdue", "暂定赛果逾期"),
                            ("official_overdue", "正式赛果逾期"),
                            ("source_failures", "来源连续失败"),
                            ("pagination_overflow", "分页越界"),
                            ("host_circuit", "来源熔断"),
                            ("queue_age", "队列积压"),
                        ],
                        max_length=32,
                    ),
                ),
                ("scope_type", models.CharField(max_length=32)),
                ("scope_key", models.CharField(max_length=255)),
                ("reference_version", models.CharField(blank=True, max_length=128)),
                ("dedupe_key", models.CharField(max_length=64, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "待处理"),
                            ("sending", "发送中"),
                            ("sent", "已发送"),
                            ("failed", "发送失败"),
                            ("resolved", "已解决"),
                        ],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("deadline_at", models.DateTimeField(blank=True, null=True)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("delivery_attempts", models.PositiveIntegerField(default=0)),
                ("delivery_token", models.CharField(blank=True, max_length=64)),
                (
                    "delivery_lease_expires_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("alert_sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=64)),
                ("details", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["status", "next_attempt_at"],
                        name="race_alert_delivery_due_idx",
                    ),
                    models.Index(
                        fields=["alert_type", "scope_type", "scope_key"],
                        name="race_alert_scope_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            alert_type__in=[
                                "provisional_overdue",
                                "official_overdue",
                                "source_failures",
                                "pagination_overflow",
                                "host_circuit",
                                "queue_age",
                            ]
                        ),
                        name="race_alert_type_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            status__in=[
                                "open",
                                "sending",
                                "sent",
                                "failed",
                                "resolved",
                            ]
                        ),
                        name="race_alert_status_valid",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RaceLiveOfficialPublicationAuthorization",
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
                ("route", models.CharField(max_length=255)),
                ("route_version", models.CharField(max_length=64)),
                ("route_registry_digest", models.CharField(max_length=64)),
                ("contract_digest", models.CharField(max_length=64)),
                ("terms_evidence_digest", models.CharField(max_length=64)),
                ("coverage_proof_digest", models.CharField(max_length=64)),
                (
                    "max_phase",
                    models.CharField(
                        choices=[
                            ("official", "正式"),
                            ("corrected", "改判"),
                        ],
                        default="official",
                        max_length=16,
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("version", models.PositiveBigIntegerField(default=1)),
                ("valid_until", models.DateTimeField(blank=True, null=True)),
                (
                    "event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="official_publication_authorization",
                        to="stable.raceevent",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=~models.Q(source_key=""),
                        name="race_official_auth_src_nonempty",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(route=""),
                        name="race_official_auth_route_nonempty",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            max_phase__in=["official", "corrected"]
                        ),
                        name="race_official_auth_phase_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(version__gte=1),
                        name="race_official_auth_version_gte1",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                route_registry_digest__regex=(
                                    "^[0-9a-f]{64}$"
                                )
                            )
                            & models.Q(
                                contract_digest__regex="^[0-9a-f]{64}$"
                            )
                            & models.Q(
                                terms_evidence_digest__regex=(
                                    "^[0-9a-f]{64}$"
                                )
                            )
                            & models.Q(
                                coverage_proof_digest__regex=(
                                    "^[0-9a-f]{64}$"
                                )
                            )
                        ),
                        name="race_official_auth_digests_valid",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="raceeventrevisionpublication",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    authorization_kind__in=[
                        "provisional_policy",
                        "official_route",
                    ]
                ),
                name="race_pub_auth_kind_valid",
            ),
        ),
        migrations.RunPython(
            backfill_last_provisional_result_revision,
            migrations.RunPython.noop,
        ),
    ]
