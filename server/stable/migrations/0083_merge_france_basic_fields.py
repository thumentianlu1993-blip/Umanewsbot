"""仓库汇合；法国生产窄候选不携带其它lane迁移。"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('stable', '0081_managed_readonly_steps'), ('stable', '0082_france_basic_fields')]
    operations = []
