import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('stable', '0085_race_observation_acquisition')]
    operations = [
        migrations.AddField(
            model_name='racelifecyclepublicstate', name=f'{kind}_latest_observation',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='+', to='stable.raceresultobservation'))
        for kind in ('racecard', 'result')
    ]
