import csv
import json
from pathlib import Path

from django.core.serializers.json import DjangoJSONEncoder

from stable.models import (
    ArticleRaceLink,
    RaceEvent,
    RaceEventAlias,
    RaceEventDataCandidate,
    RaceEventHistoryWinner,
    RaceEventResult,
    RaceEventRunner,
)


out = Path("/tmp/race_event_full_export_20260706")
out.mkdir(parents=True, exist_ok=True)

event_fields = [field.name for field in RaceEvent._meta.concrete_fields]
alias_fields = [field.name for field in RaceEventAlias._meta.concrete_fields]

events = list(
    RaceEvent.objects.order_by(
        "country_region",
        "local_date",
        "local_start_time",
        "year",
        "slug",
    ).prefetch_related("aliases")
)

with (out / "race_events_full.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=event_fields + ["public_path", "aliases_count", "aliases_json"])
    writer.writeheader()
    for event in events:
        row = {}
        for field in event_fields:
            value = getattr(event, field)
            if field in {"source_refs", "manual_lock_flags"}:
                value = json.dumps(value, ensure_ascii=False, cls=DjangoJSONEncoder, separators=(",", ":"))
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            row[field] = value
        aliases = [
            {
                "id": alias.id,
                "text": alias.text,
                "source_language": alias.source_language,
                "alias_type": alias.alias_type,
                "source": alias.source,
                "is_active": alias.is_active,
            }
            for alias in event.aliases.all()
        ]
        row["public_path"] = event.public_path
        row["aliases_count"] = len(aliases)
        row["aliases_json"] = json.dumps(aliases, ensure_ascii=False, cls=DjangoJSONEncoder, separators=(",", ":"))
        writer.writerow(row)

with (out / "race_events_full.jsonl").open("w", encoding="utf-8") as handle:
    for event in events:
        obj = {}
        for field in event_fields:
            value = getattr(event, field)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            obj[field] = value
        obj["public_path"] = event.public_path
        obj["aliases"] = [
            {
                "id": alias.id,
                "text": alias.text,
                "source_language": alias.source_language,
                "alias_type": alias.alias_type,
                "source": alias.source,
                "is_active": alias.is_active,
                "created_at": alias.created_at.isoformat() if alias.created_at else None,
                "updated_at": alias.updated_at.isoformat() if alias.updated_at else None,
            }
            for alias in event.aliases.all()
        ]
        handle.write(json.dumps(obj, ensure_ascii=False, cls=DjangoJSONEncoder, separators=(",", ":")) + "\n")

aliases = RaceEventAlias.objects.select_related("event").order_by(
    "event__country_region",
    "event__local_date",
    "event__slug",
    "source_language",
    "alias_type",
    "text",
)
with (out / "race_event_aliases_full.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=alias_fields + ["event_year", "event_slug", "event_chinese_name", "event_original_name"],
    )
    writer.writeheader()
    for alias in aliases:
        row = {}
        for field in alias_fields:
            value = getattr(alias, field)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            row[field] = value
        row["event_year"] = alias.event.year
        row["event_slug"] = alias.event.slug
        row["event_chinese_name"] = alias.event.chinese_name
        row["event_original_name"] = alias.event.original_name
        writer.writerow(row)

summary = {
    "exported_at": "2026-07-06",
    "race_event_count": len(events),
    "race_event_alias_count": RaceEventAlias.objects.count(),
    "runner_count": RaceEventRunner.objects.count(),
    "result_count": RaceEventResult.objects.count(),
    "history_winner_count": RaceEventHistoryWinner.objects.count(),
    "candidate_count": RaceEventDataCandidate.objects.count(),
    "article_link_count": ArticleRaceLink.objects.count(),
    "race_event_fields": event_fields,
    "alias_fields": alias_fields,
}
(out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, cls=DjangoJSONEncoder, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, cls=DjangoJSONEncoder))
