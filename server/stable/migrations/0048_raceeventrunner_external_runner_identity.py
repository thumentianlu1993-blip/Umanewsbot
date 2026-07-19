from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stable", "0047_race_live_public_beta_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="raceeventrunner",
            name="external_runner_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.RemoveConstraint(
            model_name="raceeventrunner",
            name="uq_race_runner_event_no",
        ),
        migrations.AddConstraint(
            model_name="raceeventrunner",
            constraint=models.UniqueConstraint(
                condition=~models.Q(external_runner_id=""),
                fields=("event", "external_runner_id"),
                name="uq_race_runner_event_external_id",
            ),
        ),
    ]
