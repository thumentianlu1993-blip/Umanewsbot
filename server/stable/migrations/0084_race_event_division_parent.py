from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("stable", "0082_france_basic_fields")]
    operations = [migrations.AddField(
        model_name="raceevent", name="division_parent",
        field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name="divisions", to="stable.raceevent", verbose_name="同届分场年度入口"),
    )]
