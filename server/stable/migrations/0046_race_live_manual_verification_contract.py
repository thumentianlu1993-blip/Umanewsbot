from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("stable", "0045_raceliveofficialverificationmodels"),
    ]

    operations = [
        migrations.AddField(
            model_name="raceliveeventpublicationallowlist",
            name="official_terms_evidence_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="raceliveeventpublicationallowlist",
            name="official_verification_contract_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="raceliveofficialverificationincident",
            name="manual_verification_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="raceliveofficialverificationincident",
            name="official_route_contract_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="raceliveofficialverificationincident",
            name="official_terms_evidence_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
