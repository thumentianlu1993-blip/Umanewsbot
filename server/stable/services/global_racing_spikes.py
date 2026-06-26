from __future__ import annotations

from typing import Any

from stable.models import ExternalHorse, ExternalHorseAlias, ExternalRace, ExternalRaceEntry, ExternalRaceResult


SUPPORTED_SPIKE_SOURCES = {"equibase", "sporting_life_bha", "france_galop"}


def formal_table_counts() -> dict[str, int]:
    return {
        "ExternalRace": ExternalRace.objects.count(),
        "ExternalRaceEntry": ExternalRaceEntry.objects.count(),
        "ExternalRaceResult": ExternalRaceResult.objects.count(),
        "ExternalHorse": ExternalHorse.objects.count(),
        "ExternalHorseAlias": ExternalHorseAlias.objects.count(),
    }


def run_source_spike(
    *,
    source: str,
    fixture_payload: dict[str, Any] | None = None,
    dry_run: bool = True,
    commit: bool = False,
) -> dict[str, Any]:
    if source not in SUPPORTED_SPIKE_SOURCES:
        raise ValueError(f"unsupported spike source: {source}")
    if commit or not dry_run:
        raise ValueError("UK/FR/US database source spike is read-only spike and cannot commit")

    payload = fixture_payload or {}
    before_counts = formal_table_counts()
    fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
    readiness_status = "ready_for_formal_import" if fields and all(fields.values()) else "needs_more_spike"
    after_counts = formal_table_counts()

    return {
        "source": source,
        "dry_run": True,
        "sample_url": payload.get("sample_url", ""),
        "request_count": payload.get("request_count", 0),
        "field_coverage": fields,
        "readiness_status": readiness_status,
        "before_counts": before_counts,
        "after_counts": after_counts,
        "wrote_formal_tables": before_counts != after_counts,
    }
