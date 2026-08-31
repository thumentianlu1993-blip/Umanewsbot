from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stable', '0075_race_data_source_priority_and_reported_position'),
    ]

    operations = [
        migrations.AlterField(
            model_name='externaldataimporterror',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externaldataimportlock',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externaldataimportrun',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externalhorse',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externalhorsealias',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externalhorsehistory',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externalrace',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externalraceentry',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externalraceodds',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='externalraceresult',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='historicalraceeventtarget',
            name='country_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='horsep0source',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='horseprofile',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='horseracerecord',
            name='race_region',
            field=models.CharField(blank=True, choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='majorraceevent',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='newsarticle',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='newsarticlerelatedregion',
            name='region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='newssource',
            name='racing_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='japan', max_length=32),
        ),
        migrations.AlterField(
            model_name='productionwindow',
            name='racing_region',
            field=models.CharField(blank=True, choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='raceevent',
            name='country_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='raceeventparticipant',
            name='country_region',
            field=models.CharField(blank=True, choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='raceliveofficialmarkercontract',
            name='country_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='racereferencecollectionrun',
            name='country_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='raceseries',
            name='country_region',
            field=models.CharField(choices=[('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], max_length=32),
        ),
        migrations.AlterField(
            model_name='termentry',
            name='racing_region',
            field=models.CharField(blank=True, choices=[('', '全局通用'), ('japan', '日本'), ('hong_kong', '中国香港'), ('united_kingdom', '英国'), ('ireland', '爱尔兰'), ('france', '法国'), ('united_states', '美国'), ('australia', '澳大利亚'), ('germany', '德国'), ('middle_east', '中东'), ('other', '其他')], default='', max_length=32),
        ),
    ]
