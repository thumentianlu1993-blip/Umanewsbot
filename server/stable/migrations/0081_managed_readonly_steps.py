"""B048：独立只读预算/step schema前置，无回填或生产入口。"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("stable", "0080_translation_retry_budget")]
    operations = [
        migrations.CreateModel(
            name='ManagedReadonlyTaskBudget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('parent_budget', models.OneToOneField('stable.translationretrybudget', on_delete=models.PROTECT, related_name='readonly_task_budget')),
                ('operation_uuid', models.UUIDField(unique=True)),
                ('read_budget_uuid', models.UUIDField(unique=True)),
                ('article_pk_snapshot', models.BigIntegerField()),
                ('source_site_snapshot', models.CharField(max_length=32)),
                ('source_article_id_snapshot', models.CharField(max_length=255)),
                ('source_sha256', models.CharField(max_length=64)),
                ('workflow_version', models.CharField(max_length=64)),
                ('query_version', models.CharField(max_length=64)),
                ('result_version', models.CharField(max_length=64)),
                ('permission_epoch', models.PositiveIntegerField(default=1)),
                ('allowed_tools', models.JSONField(default=list)),
                ('opened_at', models.DateTimeField()),
                ('deadline_at', models.DateTimeField()),
                ('tool_read_limit', models.PositiveSmallIntegerField()),
                ('tool_reads_reserved', models.PositiveSmallIntegerField(default=0)),
                ('state', models.CharField(max_length=32, default='open')),
                ('blocked_reason', models.CharField(max_length=128, blank=True)),
            ],
            options={
                'base_manager_name': 'objects',
                'default_manager_name': 'objects',
                'constraints': [
                    models.CheckConstraint(condition=models.Q(tool_read_limit__lte=2), name='ck_ro_limit_fixture_bound'),
                    models.CheckConstraint(condition=models.Q(tool_reads_reserved__lte=models.F('tool_read_limit')), name='ck_ro_counter_bounds'),
                    models.CheckConstraint(condition=models.Q(deadline_at__gt=models.F('opened_at')), name='ck_ro_deadline'),
                    models.CheckConstraint(condition=models.Q(permission_epoch__gte=1), name='ck_ro_permission_epoch'),
                    models.CheckConstraint(condition=models.Q(state__in=['open', 'revoked', 'blocked_unknown', 'expired']), name='ck_ro_root_state'),
                ],
            },
        ),
        migrations.CreateModel(
            name='ManagedReadonlyStep',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('read_budget', models.ForeignKey('stable.managedreadonlytaskbudget', on_delete=models.PROTECT, related_name='steps')),
                ('step_uuid', models.UUIDField(unique=True)),
                ('logical_step_name', models.CharField(max_length=32)),
                ('idempotency_sha256', models.CharField(max_length=64)),
                ('envelope', models.JSONField(default=dict)),
                ('params_sha256', models.CharField(max_length=64)),
                ('reservation_token', models.UUIDField(unique=True)),
                ('state', models.CharField(max_length=32, default='inflight')),
                ('reserved_at', models.DateTimeField()),
                ('read_at', models.DateTimeField(null=True, blank=True)),
                ('completed_at', models.DateTimeField(null=True, blank=True)),
                ('result', models.JSONField(default=dict)),
                ('result_sha256', models.CharField(max_length=64, blank=True)),
                ('error_reason', models.CharField(max_length=128, blank=True)),
            ],
            options={
                'base_manager_name': 'objects',
                'default_manager_name': 'objects',
                'constraints': [
                    models.UniqueConstraint(fields=('read_budget', 'logical_step_name'), name='uq_ro_logical_step'),
                    models.CheckConstraint(condition=models.Q(logical_step_name='source_excerpt:1'), name='ck_ro_fixed_logical_step'),
                    models.CheckConstraint(condition=models.Q(state__in=['inflight', 'completed', 'unknown', 'failed', 'expired', 'denied']), name='ck_ro_step_state'),
                    models.CheckConstraint(condition=~models.Q(state='completed') | models.Q(read_at__isnull=False) & models.Q(completed_at__isnull=False) & models.Q(result_sha256__regex='^[0-9a-f]{64}$') & ~models.Q(result={}), name='ck_ro_completed_result'),
                ],
            },
        ),
    ]
