from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('stable', '0084_race_lifecycle_evidence_guards')]
    operations = [
        migrations.AddField(model_name='raceresultobservation', name='acquisition_key',
            field=models.CharField(max_length=64, blank=True, default='')),
        migrations.RemoveConstraint(model_name='raceresultobservation', name='uq_race_obs_source_hash_phase'),
        migrations.AddConstraint(model_name='raceresultobservation', constraint=models.UniqueConstraint(
            fields=('source_identity', 'normalized_sha256', 'result_phase', 'acquisition_key'),
            name='uq_race_obs_source_hash_phase')),
    ]
