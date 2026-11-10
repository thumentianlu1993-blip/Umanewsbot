"""法国赛事奖金与完整条件；从当前生产0079增量升级，无数据回填。"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('stable', '0079_multisource_race_enrollment')]
    operations = [
        migrations.AddField(model_name='raceevent', name='prize_amount', field=models.DecimalField(
            max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='总奖金')),
        migrations.AddField(model_name='raceevent', name='prize_currency', field=models.CharField(
            max_length=3, blank=True, default='', verbose_name='奖金币种')),
        migrations.AlterField(model_name='raceevent', name='eligibility_text', field=models.TextField(blank=True)),
    ]
