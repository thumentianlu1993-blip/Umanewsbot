from __future__ import annotations

import hashlib
import json
from typing import Literal

from django.db import connection
from django.db.models import Count
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from stable.models import HistoricalRaceEventTarget, RaceEvent


SCHEMA_VERSION = "historical-calendar-release-b-preflight/v1"


def _digest(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _migration_state() -> tuple[str, list[str]]:
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    recorded = {
        node
        for node in MigrationRecorder(connection).applied_migrations()
        if node[0] == "stable"
    }
    unknown = sorted(recorded - set(loader.graph.node_map))
    applied = recorded - set(unknown)
    leaves = sorted(
        node
        for node in applied
        if not any(child in applied for child in loader.graph.node_map[node].children)
    )
    return (
        ",".join(f"{app}.{name}" for app, name in leaves),
        [f"{app}.{name}" for app, name in unknown],
    )


def _database_identity_sha256() -> str:
    settings = connection.settings_dict
    return _digest(
        {
            "engine": settings.get("ENGINE", ""),
            "host": settings.get("HOST", ""),
            "name": settings.get("NAME", ""),
            "port": str(settings.get("PORT", "")),
            "vendor": connection.vendor,
        }
    )


def _event_conflicts(direction: str) -> list[dict]:
    field = "edition_year" if direction == "forward" else "year"
    queryset = RaceEvent._base_manager.filter(race_series__isnull=False)
    if direction == "forward":
        queryset = queryset.filter(edition_year__isnull=False)
    groups = (
        queryset.values("race_series_id", field)
        .annotate(row_count=Count("pk"))
        .filter(row_count__gt=1)
        .order_by("race_series_id", field)
    )
    rows = []
    for group in groups.iterator(chunk_size=500):
        identity_value = group[field]
        ids = list(
            queryset.filter(
                race_series_id=group["race_series_id"],
                **{field: identity_value},
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        rows.append(
            {
                "race_series_id": group["race_series_id"],
                field: identity_value,
                "event_ids": ids,
            }
        )
    return rows


def _target_conflicts(direction: str) -> list[dict]:
    queryset = HistoricalRaceEventTarget._base_manager.all()
    if direction == "forward":
        queryset = queryset.exclude(resolution_status="superseded")
    groups = (
        queryset.values("race_series_id", "year")
        .annotate(row_count=Count("pk"))
        .filter(row_count__gt=1)
        .order_by("race_series_id", "year")
    )
    rows = []
    for group in groups.iterator(chunk_size=500):
        ids = list(
            queryset.filter(
                race_series_id=group["race_series_id"],
                year=group["year"],
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        rows.append(
            {
                "race_series_id": group["race_series_id"],
                "year": group["year"],
                "target_ids": ids,
            }
        )
    return rows


def check_release_b_schema_compatibility(
    *, direction: Literal["forward", "reverse"]
) -> dict:
    if direction not in {"forward", "reverse"}:
        raise ValueError("direction must be forward or reverse")
    event_conflicts = _event_conflicts(direction)
    target_conflicts = _target_conflicts(direction)
    migration_leaf, unknown_applied_migrations = _migration_state()
    rows = {
        "event_conflicts": event_conflicts,
        "target_conflicts": target_conflicts,
        "unknown_applied_migrations": unknown_applied_migrations,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "direction": direction,
        "migration_leaf": migration_leaf,
        "migration_graph_known": not unknown_applied_migrations,
        "unknown_applied_migrations": unknown_applied_migrations,
        "database_identity_sha256": _database_identity_sha256(),
        "event_conflict_count": len(event_conflicts),
        "target_conflict_count": len(target_conflicts),
        "rows_sha256": _digest(rows),
        "ok": (
            not unknown_applied_migrations
            and not event_conflicts
            and not target_conflicts
        ),
    }
