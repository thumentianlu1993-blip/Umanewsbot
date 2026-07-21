from django.db import migrations
from django.db.models import Count, Q


ACTUAL_START_RESULTS = {
    "won",
    "placed",
    "unplaced",
    "did_not_finish",
    "disqualified",
}
NON_START_RESULTS = {"scratched", "withdrawn"}


def backfill_career_history_semantics(apps, schema_editor):
    HorseProfile = apps.get_model("stable", "HorseProfile")
    HorseRaceRecord = apps.get_model("stable", "HorseRaceRecord")

    HorseRaceRecord.objects.filter(
        result_status__in=ACTUAL_START_RESULTS,
    ).update(start_status="started")
    HorseRaceRecord.objects.filter(
        result_status__in=NON_START_RESULTS,
    ).update(start_status="did_not_start")
    HorseRaceRecord.objects.filter(
        race_date__isnull=False,
    ).update(race_date_precision="exact")
    HorseRaceRecord.objects.filter(
        race_date__isnull=True,
        race_year__isnull=False,
    ).update(race_date_precision="year")

    snapshots = (
        HorseRaceRecord.objects.values("horse_profile_id")
        .annotate(
            collected=Count("id", filter=Q(start_status="started")),
            linked=Count("id", filter=Q(event_id__isnull=False)),
            unlinked=Count("id", filter=Q(event_id__isnull=True)),
        )
        .iterator()
    )
    for snapshot in snapshots:
        HorseProfile.objects.filter(pk=snapshot["horse_profile_id"]).update(
            career_history_status="partial",
            collected_start_count=snapshot["collected"],
            linked_race_event_count=snapshot["linked"],
            unlinked_race_record_count=snapshot["unlinked"],
            career_history_gap_count=1,
            career_history_gap_reasons=["source_total_unknown"],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0049_horse_career_history"),
    ]

    operations = [
        migrations.RunPython(
            backfill_career_history_semantics,
            migrations.RunPython.noop,
        ),
    ]
