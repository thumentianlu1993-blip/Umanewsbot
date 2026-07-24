"""
Normalize race and career fields for historical data.

Default mode is dry-run (no database writes).  Use --apply-manifest +
--expected-sha256 + --confirm-apply to apply changes.  Use --rollback to
revert changes recorded by apply receipts.

Usage:
  # Dry-run (default):
  python manage.py normalize_race_and_career_fields \\
      --model horse-race-record --output-dir /tmp/norm-out

  # Apply:
  python manage.py normalize_race_and_career_fields \\
      --apply-manifest /tmp/norm-out/manifest.json \\
      --expected-sha256 <64hex> --confirm-apply

  # Rollback:
  python manage.py normalize_race_and_career_fields --rollback
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.db.models import Max, Min, QuerySet
from django.utils import timezone

from stable.models import (
    HorseRaceRecord,
    RaceEvent,
    RaceFieldNormalizationReceipt,
    RaceFieldNormalizationRun,
    TermAlias,
    TermEntry,
)
from stable.services.race_field_normalization import (
    PROVIDER_LANGUAGE_MAP,
    RACE_FIELD_NORMALIZATION_VERSION,
    NormalizedRaceType,
    compute_input_sha256,
    normalize_distance,
    normalize_eligibility,
    normalize_finish_position,
    normalize_surface_race_type_layout_going,
)

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    """Return the current git HEAD hash (empty string on failure)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent.parent.parent,
            timeout=10,
        )
        return result.stdout.strip()[:40]
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _migration_list() -> list[str]:
    """Return the sorted list of applied migration keys ('app.name')."""
    try:
        from django.db.migrations.recorder import MigrationRecorder

        return sorted(
            f"{app}.{name}"
            for app, name in MigrationRecorder.Migration.objects.values_list(
                "app", "name"
            )
        )
    except Exception:
        return []


def _build_term_snapshot() -> list[dict]:
    """Return a deterministic snapshot of active TermEntry/TermAlias rows."""
    snapshot: list[dict] = []
    for entry in TermEntry.objects.filter(is_active=True).order_by("pk"):
        snapshot.append({
            "id": entry.pk,
            "term_type": entry.term_type,
            "region": entry.racing_region or "",
            "language": entry.source_language,
            "source_text": entry.source_ja,
            "target_zh": entry.target_zh or "",
            "is_active": entry.is_active,
            "alias_term_id": None,
        })
    for alias in TermAlias.objects.filter(is_active=True).order_by("pk"):
        snapshot.append({
            "id": alias.pk,
            "term_type": "alias",
            "region": alias.source_language or "",
            "language": alias.source_language,
            "source_text": alias.text,
            "target_zh": alias.term.target_zh if alias.term_id else "",
            "is_active": alias.is_active,
            "alias_term_id": alias.term_id,
        })
    return snapshot


def _term_snapshot_digest(snapshot: list[dict]) -> str:
    raw = json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Normalization helpers (no DB writes)
# ---------------------------------------------------------------------------


def _compute_input_sha_for_record(record: HorseRaceRecord | RaceEvent) -> str:
    """Compute deterministic input SHA-256 for a record."""
    if isinstance(record, HorseRaceRecord):
        return compute_input_sha256(
            finish_position=record.finish_position,
            distance_text=record.distance_text,
            distance_meters=record.distance_meters,
            surface=record.surface,
            race_type_text=record.race_type_text,
            eligibility_text=record.eligibility_text,
        )
    return compute_input_sha256(
        distance_text=record.distance_text,
        surface=record.surface,
        racecourse=record.racecourse,
        eligibility_text=record.eligibility_text,
    )


def _compute_hrr_normalized(
    record: HorseRaceRecord,
) -> tuple[dict[str, Any], str, str]:
    """Compute normalized values for a HorseRaceRecord without saving.

    Returns (after_vals, input_sha, recovered_region).
    """
    source_name = (record.source_name or "").strip()
    source_language = PROVIDER_LANGUAGE_MAP.get(source_name, "")

    # Recover historical context (region, language) from linked event and source refs
    from stable.services.race_field_normalization import normalize_context

    linked_event_region = ""
    if record.event:
        linked_event_region = record.event.country_region or ""
    context = normalize_context(
        raw_region=record.race_region or "",
        provider=source_name or "",
        linked_event_region=linked_event_region,
    )
    source_region = context.region or record.race_region or ""
    if not source_language:
        source_language = context.source_language

    input_sha = _compute_input_sha_for_record(record)
    # ... rest unchanged

    finish = normalize_finish_position(
        record.finish_position, source_kind=source_name
    )
    distance = normalize_distance(
        record.distance_text,
        source_language=source_language or None,
        source_region=source_region or None,
        official_metric_meters=record.distance_meters,
    )
    surface = normalize_surface_race_type_layout_going(
        record.surface,
        source_language=source_language or None,
        source_region=source_region or None,
    )
    eligibility = normalize_eligibility(
        record.eligibility_text,
        source_language=source_language or None,
        source_region=source_region or None,
    )

    # Refine race type from race_type_text
    race_type = surface.race_type
    race_type_text = (record.race_type_text or "").strip()
    if race_type_text:
        tt = normalize_surface_race_type_layout_going(
            race_type_text,
            source_language=source_language or None,
            source_region=source_region or None,
        )
        if tt.race_type != NormalizedRaceType.UNKNOWN:
            race_type = tt.race_type

    issues: list[str] = []
    for tag, result in (
        ("finish", finish),
        ("distance", distance),
        ("surface", surface),
        ("eligibility", eligibility),
    ):
        if result.reason.status not in ("normalized",):
            issues.append(f"{tag}:{result.reason.status}:{result.reason.reason_code}")

    return {
        "normalized_finish_position": finish.position,
        "normalized_result_status": (
            finish.status.value if hasattr(finish.status, "value") else finish.status
        ),
        "distance_meters_normalized": (
            float(distance.meters) if distance.meters is not None else None
        ),
        "distance_precision": (
            distance.precision.value
            if hasattr(distance.precision, "value")
            else distance.precision
        ),
        "normalized_surface": (
            surface.surface.value
            if hasattr(surface.surface, "value")
            else surface.surface
        ),
        "normalized_race_type": (
            race_type.value if hasattr(race_type, "value") else race_type
        ),
        "course_layout_text": surface.course_layout,
        "going_text": surface.going_text,
        "minimum_age": eligibility.min_age,
        "maximum_age": eligibility.max_age,
        "age_open_ended": eligibility.age_open_ended,
        "sex_restriction": (
            eligibility.sex.value
            if hasattr(eligibility.sex, "value")
            else eligibility.sex
        ),
        "eligibility_constraints": eligibility.extra_constraints,
        "normalization_version": RACE_FIELD_NORMALIZATION_VERSION,
        "normalization_input_sha256": input_sha,
        "normalization_issues": issues,
    }, input_sha, source_region, source_language


def _compute_event_normalized(record: RaceEvent) -> tuple[dict[str, Any], str]:
    """Compute normalized values for a RaceEvent without saving."""
    source_language = ""
    source_region = record.country_region or ""

    input_sha = _compute_input_sha_for_record(record)

    distance = normalize_distance(
        record.distance_text,
        source_language=source_language or None,
        source_region=source_region or None,
    )
    surface = normalize_surface_race_type_layout_going(
        record.surface,
        source_language=source_language or None,
        source_region=source_region or None,
    )
    eligibility = normalize_eligibility(
        record.eligibility_text,
        source_language=source_language or None,
        source_region=source_region or None,
    )

    issues: list[str] = []
    for tag, result in (
        ("distance", distance),
        ("surface", surface),
        ("eligibility", eligibility),
    ):
        if result.reason.status not in ("normalized",):
            issues.append(f"{tag}:{result.reason.status}:{result.reason.reason_code}")

    return {
        "distance_meters_normalized": (
            float(distance.meters) if distance.meters is not None else None
        ),
        "distance_precision": (
            distance.precision.value
            if hasattr(distance.precision, "value")
            else distance.precision
        ),
        "normalized_surface": (
            surface.surface.value
            if hasattr(surface.surface, "value")
            else surface.surface
        ),
        "normalized_race_type": (
            surface.race_type.value
            if hasattr(surface.race_type, "value")
            else surface.race_type
        ),
        "course_layout_text": surface.course_layout,
        "going_text": surface.going_text,
        "minimum_age": eligibility.min_age,
        "maximum_age": eligibility.max_age,
        "age_open_ended": eligibility.age_open_ended,
        "sex_restriction": (
            eligibility.sex.value
            if hasattr(eligibility.sex, "value")
            else eligibility.sex
        ),
        "eligibility_constraints": eligibility.extra_constraints,
        "normalization_version": RACE_FIELD_NORMALIZATION_VERSION,
        "normalization_input_sha256": input_sha,
        "normalization_issues": issues,
    }, input_sha


def _current_snapshot(record: HorseRaceRecord | RaceEvent) -> dict[str, Any]:
    """Snapshot of current normalization fields (for before/after)."""
    base = {
        "distance_meters_normalized": (
            float(record.distance_meters_normalized)
            if record.distance_meters_normalized is not None
            else None
        ),
        "distance_precision": record.distance_precision or "",
        "normalized_surface": record.normalized_surface or "",
        "normalized_race_type": record.normalized_race_type or "",
        "course_layout_text": record.course_layout_text or "",
        "going_text": record.going_text or "",
        "minimum_age": record.minimum_age,
        "maximum_age": record.maximum_age,
        "age_open_ended": record.age_open_ended,
        "sex_restriction": record.sex_restriction or "",
        "eligibility_constraints": (
            record.eligibility_constraints
            if isinstance(record.eligibility_constraints, dict)
            else {}
        ),
        "normalization_version": record.normalization_version or "",
        "normalization_input_sha256": record.normalization_input_sha256 or "",
        "normalization_issues": (
            record.normalization_issues
            if isinstance(record.normalization_issues, list)
            else []
        ),
    }
    if isinstance(record, HorseRaceRecord):
        base["normalized_finish_position"] = record.normalized_finish_position
        base["normalized_result_status"] = record.normalized_result_status or ""
    return base


def _snapshots_equivalent(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Check if current snapshot matches expected (normalization-version
    and -input_sha256 are excluded from comparison for idempotency)."""
    for key in expected:
        if key in ("normalization_version", "normalization_input_sha256",
                   "normalization_issues"):
            continue
        cv = current.get(key)
        ev = expected.get(key)
        if cv is None and ev in ("", None):
            continue
        if ev is None and cv in ("", None):
            continue
        if cv != ev:
            return False
    return True


def _apply_normalized_to_record(
    record: HorseRaceRecord | RaceEvent, after: dict[str, Any]
) -> None:
    """Set normalized fields on a record from the after dict."""
    if isinstance(record, HorseRaceRecord):
        record.normalized_finish_position = after.get("normalized_finish_position")
        record.normalized_result_status = after.get("normalized_result_status", "")
        record.distance_meters_normalized = after.get("distance_meters_normalized")
        record.distance_precision = after.get("distance_precision", "")
        record.normalized_surface = after.get("normalized_surface", "")
        record.normalized_race_type = after.get("normalized_race_type", "")
        record.course_layout_text = after.get("course_layout_text", "")
        record.going_text = after.get("going_text", "")
        record.minimum_age = after.get("minimum_age")
        record.maximum_age = after.get("maximum_age")
        record.age_open_ended = after.get("age_open_ended", False)
        record.sex_restriction = after.get("sex_restriction", "")
        record.eligibility_constraints = after.get("eligibility_constraints", {})
        record.normalization_version = after.get(
            "normalization_version", RACE_FIELD_NORMALIZATION_VERSION
        )
        record.normalization_input_sha256 = after.get(
            "normalization_input_sha256", ""
        )
        record.normalization_issues = after.get("normalization_issues", [])
        record.normalized_at = timezone.now()
        record.save(update_fields=[
            "normalized_finish_position",
            "normalized_result_status",
            "distance_meters_normalized",
            "distance_precision",
            "normalized_surface",
            "normalized_race_type",
            "course_layout_text",
            "going_text",
            "minimum_age",
            "maximum_age",
            "age_open_ended",
            "sex_restriction",
            "eligibility_constraints",
            "normalization_version",
            "normalization_input_sha256",
            "normalization_issues",
            "normalized_at",
            "updated_at",
        ])
    elif isinstance(record, RaceEvent):
        record.distance_meters_normalized = after.get("distance_meters_normalized")
        record.distance_precision = after.get("distance_precision", "")
        record.normalized_surface = after.get("normalized_surface", "")
        record.normalized_race_type = after.get("normalized_race_type", "")
        record.course_layout_text = after.get("course_layout_text", "")
        record.going_text = after.get("going_text", "")
        record.minimum_age = after.get("minimum_age")
        record.maximum_age = after.get("maximum_age")
        record.age_open_ended = after.get("age_open_ended", False)
        record.sex_restriction = after.get("sex_restriction", "")
        record.eligibility_constraints = after.get("eligibility_constraints", {})
        record.normalization_version = after.get(
            "normalization_version", RACE_FIELD_NORMALIZATION_VERSION
        )
        record.normalization_input_sha256 = after.get(
            "normalization_input_sha256", ""
        )
        record.normalization_issues = after.get("normalization_issues", [])
        record.normalized_at = timezone.now()
        record.save(update_fields=[
            "distance_meters_normalized",
            "distance_precision",
            "normalized_surface",
            "normalized_race_type",
            "course_layout_text",
            "going_text",
            "minimum_age",
            "maximum_age",
            "age_open_ended",
            "sex_restriction",
            "eligibility_constraints",
            "normalization_version",
            "normalization_input_sha256",
            "normalization_issues",
            "normalized_at",
            "updated_at",
        ])


def _build_term_lookup(
    names: set[tuple[str, str, str]], term_type: str
) -> dict[tuple[str, str, str], int | None]:
    """Batch-resolve (name, region, source_language) triples to TermEntry IDs.

    Key invariant: any key must have EXACTLY ONE candidate.
    - zero candidates → unresolved (None)
    - exactly one  → resolved (term ID)
    - multiple candidates (different source_language, or same-language
      duplicates) → unresolved (None — conflict, preserve original)

    Uses active TermEntry.source_ja first, then TermAlias for fallback.
    """
    if not names:
        return {}
    lookup: dict[tuple[str, str, str], int | None] = {
        triple: None for triple in names
    }

    unique_names = {n for n, _, _ in names if n}
    if not unique_names:
        return lookup

    def _strict_resolve(
        rows, name_col: str, region_col: str, lang_col: str, id_col: str
    ) -> dict[tuple[str, str, str], int]:
        """Group by (name, region, language) and keep only singletons."""
        counts: dict[tuple[str, str, str], int] = {}
        ids: dict[tuple[str, str, str], int] = {}
        for r in rows:
            key = (
                r[name_col],
                r[region_col] or "",
                r[lang_col] or "",
            )
            counts[key] = counts.get(key, 0) + 1
            ids[key] = r[id_col]
        return {k: v for k, v in ids.items() if counts.get(k) == 1}

    # ── TermEntry ──
    entries = TermEntry.objects.filter(
        is_active=True,
        term_type=term_type,
        source_ja__in=unique_names,
    ).values("id", "source_ja", "racing_region", "source_language")
    entry_ids = _strict_resolve(
        entries,
        name_col="source_ja",
        region_col="racing_region",
        lang_col="source_language",
        id_col="id",
    )
    for name, region, lang in names:
        if (name, region, lang) in entry_ids:
            lookup[(name, region, lang)] = entry_ids[(name, region, lang)]

    # ── TermAlias fallback ──
    still = {n for n, r, l in names if lookup[(n, r, l)] is None}
    if still:
        aliases = TermAlias.objects.filter(
            is_active=True,
            term__is_active=True,
            term__term_type=term_type,
            text__in=still,
        ).values("term_id", "text", "term__racing_region", "source_language")
        alias_ids = _strict_resolve(
            aliases,
            name_col="text",
            region_col="term__racing_region",
            lang_col="source_language",
            id_col="term_id",
        )
        for name, region, lang in names:
            if lookup[(name, region, lang)] is None:
                lookup[(name, region, lang)] = alias_ids.get((name, region, lang))

    return lookup


def _classify_issues(issues: list[str]) -> str:
    """Classify a list of normalization issues into a status string."""
    for issue in issues:
        if "conflict" in issue:
            return "conflict"
    for issue in issues:
        if "unknown" in issue:
            return "unknown"
    for issue in issues:
        if "preserved" in issue:
            return "preserved"
    return "normalized"


# ===========================================================================
# Command
# ===========================================================================


class Command(BaseCommand):
    help = "Normalize race and career fields for historical data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            choices=["race-event", "horse-race-record", "all"],
            default="all",
        )
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--after-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--output-dir", type=str, default="")
        parser.add_argument("--apply-manifest", type=str, default="")
        parser.add_argument("--expected-sha256", type=str, default="")
        parser.add_argument("--confirm-apply", action="store_true")
        parser.add_argument("--rollback", action="store_true")
        parser.add_argument("--rollback-run-id", type=int, default=0,
                            help="Target a specific run for rollback (required with --rollback)")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        if options.get("rollback"):
            return self._run_rollback(options)
        if options.get("apply_manifest"):
            return self._run_apply(options)
        return self._run_dry_run(options)

    # ------------------------------------------------------------------
    # Dry-run
    # ------------------------------------------------------------------

    def _run_dry_run(self, options: dict[str, Any]) -> None:
        model = options.get("model", "all")
        after_id = options.get("after_id", 0)
        limit = options.get("limit", 0)
        batch_size = options.get("batch_size", 500)

        output_dir_raw = options.get("output_dir", "")
        output_path: Path | None = None
        if output_dir_raw:
            output_path = Path(output_dir_raw).resolve()
            if output_path.exists() and any(output_path.iterdir()):
                raise CommandError(
                    f"Output directory already exists and is not empty: "
                    f"{output_dir_raw}"
                )
            output_path.mkdir(parents=True, exist_ok=True)

        production_head = _git_head()

        # Applied migrations (sorted for deterministic comparison with apply)
        migration_list = _migration_list()

        # Term snapshot
        term_snapshot = _build_term_snapshot()
        ts_digest = _term_snapshot_digest(term_snapshot)

        # Determine scopes
        scopes: list[type] = []
        if model in ("horse-race-record", "all"):
            scopes.append(HorseRaceRecord)
        if model in ("race-event", "all"):
            scopes.append(RaceEvent)

        scope_name = model.replace("-", "_") if model != "all" else "all"

        # Process each scope
        all_changes: list[dict] = []
        all_unresolved: list[dict] = []
        all_conflicts: list[dict] = []
        combined_cat_counts: dict[str, int] = {}
        global_min_id = 0
        global_max_id = 0
        global_row_count = 0

        for model_class in scopes:
            model_label = (
                "HorseRaceRecord"
                if model_class is HorseRaceRecord
                else "RaceEvent"
            )

            qs = model_class.objects.all().order_by("pk")
            # Preload linked event to avoid N+1 in normalize_context()
            if model_class is HorseRaceRecord:
                qs = qs.select_related("event")
            if after_id > 0:
                qs = qs.filter(pk__gt=after_id)
            if limit > 0:
                qs = qs[:limit]

            row_count = qs.count()
            if row_count == 0:
                continue

            agg = qs.aggregate(min_id=Min("pk"), max_id=Max("pk"))
            local_min = agg["min_id"] or 0
            local_max = agg["max_id"] or 0

            if global_min_id == 0 or local_min < global_min_id:
                global_min_id = local_min
            if local_max > global_max_id:
                global_max_id = local_max
            global_row_count += row_count

            # Pre-collect (name, region, source_language) triples for batch
            # term lookup.  Include linked-event regions so that records whose
            # own race_region is empty can still match via event context.
            all_race_pairs: set[tuple[str, str, str]] = set()
            all_course_pairs: set[tuple[str, str, str]] = set()
            if model_class is HorseRaceRecord:
                lang_defaults: dict[int, str] = {}
                for r in qs.values("pk", "source_name").iterator():
                    p = PROVIDER_LANGUAGE_MAP.get(
                        (r["source_name"] or "").strip(), ""
                    )
                    if p:
                        lang_defaults[r["pk"]] = p
                for r in qs.select_related("event").values(
                    "pk", "race_name", "racecourse", "race_region",
                    "source_name", "event__country_region",
                ).iterator():
                    raw_region = r["race_region"] or ""
                    ev_region = r["event__country_region"] or ""
                    region = raw_region or ev_region
                    lang = lang_defaults.get(r["pk"], "")
                    name = (r["race_name"] or "").strip()
                    course = (r["racecourse"] or "").strip()
                    if name:
                        all_race_pairs.add((name, region, lang))
                        if ev_region and ev_region != raw_region:
                            all_race_pairs.add((name, ev_region, lang))
                    if course:
                        all_course_pairs.add((course, region, lang))
                        if ev_region and ev_region != raw_region:
                            all_course_pairs.add((course, ev_region, lang))

            term_lookup_3: dict[tuple[str, str, str], int | None] = {}
            racecourse_lookup_3: dict[tuple[str, str, str], int | None] = {}
            if model_class is HorseRaceRecord:
                term_lookup_3 = _build_term_lookup(all_race_pairs, "race")
                racecourse_lookup_3 = _build_term_lookup(all_course_pairs, "racecourse")

            # Single-pass streaming — no in-memory accumulation of ORM objects
            for record in qs.iterator(chunk_size=batch_size):
                if isinstance(record, HorseRaceRecord):
                    after_vals, input_sha, recovered_region, rec_lang = (
                        _compute_hrr_normalized(record)
                    )
                else:
                    after_vals, input_sha = _compute_event_normalized(record)
                    recovered_region = ""
                    rec_lang = ""

                before_vals = _current_snapshot(record)
                issues = after_vals.get("normalization_issues", []) or []
                status = _classify_issues(issues)

                before_vals = _current_snapshot(record)
                issues = after_vals.get("normalization_issues", []) or []
                status = _classify_issues(issues)

                # Resolve term identities using (name, region, source_language)
                race_term_id = None
                racecourse_term_id = None
                if model_class is HorseRaceRecord:
                    race_name = (record.race_name or "").strip()
                    course_name = (record.racecourse or "").strip()
                    region = recovered_region or getattr(record, "race_region", "") or ""
                    lang = rec_lang or ""
                    if race_name:
                        race_term_id = term_lookup_3.get(
                            (race_name, region, lang)
                        )
                    if course_name:
                        racecourse_term_id = racecourse_lookup_3.get(
                            (course_name, region, lang)
                        )

                row = {
                    "model_label": model_label,
                    "object_pk": record.pk,
                    "before": before_vals,
                    "after": after_vals,
                    "input_sha256": input_sha,
                    "race_term_id": race_term_id,
                    "racecourse_term_id": racecourse_term_id,
                }

                combined_cat_counts[status] = (
                    combined_cat_counts.get(status, 0) + 1
                )

                if status == "conflict":
                    all_conflicts.append(row)
                elif status in ("unknown", "preserved"):
                    all_unresolved.append(row)

                all_changes.append(row)

        # Input digest
        input_digest_obj = hashlib.sha256()
        for row in all_changes:
            input_digest_obj.update(
                f"{row['model_label']}|{row['object_pk']}|"
                f"{row['input_sha256']}|".encode("utf-8")
            )
        input_digest = input_digest_obj.hexdigest()

        # Build manifest (without file_sha256 / digest)
        manifest: dict[str, Any] = {
            "production_head": production_head,
            "migrations": migration_list,
            "normalizer_version": RACE_FIELD_NORMALIZATION_VERSION,
            "scope": scope_name,
            "min_id": global_min_id,
            "max_id": global_max_id,
            "row_count": global_row_count,
            "batch_size": batch_size,
            "input_digest": input_digest,
            "term_snapshot_digest": ts_digest,
            "category_counts": combined_cat_counts,
        }

        # Compute canonical digest
        manifest_digest = self._canonical_digest(manifest)
        manifest["digest"] = manifest_digest

        if output_path:
            self._write_artifacts(
                output_path,
                manifest,
                term_snapshot,
                all_changes,
                all_unresolved,
                all_conflicts,
            )
        else:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "scope": scope_name,
                        "row_count": global_row_count,
                        "digest": manifest_digest,
                        "category_counts": combined_cat_counts,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

    def _canonical_digest(self, manifest: dict[str, Any]) -> str:
        """Compute deterministic SHA-256 of manifest excluding file_sha256/digest."""
        excluding = {
            k: v
            for k, v in manifest.items()
            if k not in ("file_sha256", "digest")
        }
        raw = json.dumps(
            excluding,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _write_artifacts(
        self,
        output_path: Path,
        manifest: dict[str, Any],
        term_snapshot: list[dict],
        changes: list[dict],
        unresolved: list[dict],
        conflicts: list[dict],
    ) -> None:
        # Write term_snapshot.json
        (output_path / "term_snapshot.json").write_text(
            json.dumps(term_snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Write summary.json
        summary = {
            "scope": manifest.get("scope", ""),
            "row_count": manifest.get("row_count", 0),
            "category_counts": manifest.get("category_counts", {}),
            "changes_count": len(changes),
            "unresolved_count": len(unresolved),
            "conflicts_count": len(conflicts),
        }
        (output_path / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Write jsonl files
        self._write_jsonl(output_path / "changes.jsonl", changes)
        self._write_jsonl(output_path / "unresolved.jsonl", unresolved)
        self._write_jsonl(output_path / "conflicts.jsonl", conflicts)

        # Compute file hashes (all data files only — not manifest.json itself)
        file_sha256 = {
            "summary.json": _sha256_file(output_path / "summary.json"),
            "changes.jsonl": _sha256_file(output_path / "changes.jsonl"),
            "unresolved.jsonl": _sha256_file(output_path / "unresolved.jsonl")
            if (output_path / "unresolved.jsonl").stat().st_size > 0
            else _empty_sha(),
            "conflicts.jsonl": _sha256_file(output_path / "conflicts.jsonl")
            if (output_path / "conflicts.jsonl").stat().st_size > 0
            else _empty_sha(),
            "term_snapshot.json": _sha256_file(
                output_path / "term_snapshot.json"
            ),
        }

        manifest["file_sha256"] = file_sha256
        manifest["digest"] = self._canonical_digest(manifest)

        # Write manifest ONCE (exactly one write, no rewrite)
        manifest_path = output_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Record manifest.json hash separately (not inside manifest itself — circular)
        manifest_hash_path = output_path / "manifest.json.sha256"
        manifest_hash_path.write_text(
            _sha256_file(manifest_path) + "\n", encoding="utf-8"
        )

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                )

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _run_apply(self, options: dict[str, Any]) -> None:
        manifest_path_str = options.get("apply_manifest", "")
        expected_sha = options.get("expected_sha256", "")
        confirm = options.get("confirm_apply", False)
        batch_size = options.get("batch_size", 500)

        if not manifest_path_str:
            raise CommandError("--apply-manifest is required")
        if not expected_sha:
            raise CommandError("--expected-sha256 is required")
        if not confirm:
            raise CommandError("--confirm-apply is required")

        manifest_path = Path(manifest_path_str).resolve()
        if not manifest_path.is_file():
            raise CommandError(
                f"Manifest file not found: {manifest_path}"
            )

        # Verify file SHA
        actual_sha = _sha256_file(manifest_path)
        if actual_sha != expected_sha:
            raise CommandError(
                f"Manifest SHA mismatch: expected {expected_sha}, "
                f"got {actual_sha}"
            )

        try:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(
                f"Failed to read manifest: {exc}"
            ) from exc

        # Verify term snapshot digest
        current_ts = _build_term_snapshot()
        current_ts_digest = _term_snapshot_digest(current_ts)
        expected_ts_digest = manifest.get("term_snapshot_digest", "")
        if current_ts_digest != expected_ts_digest:
            raise CommandError(
                f"Term snapshot digest mismatch: "
                f"expected {expected_ts_digest}, got {current_ts_digest}"
            )

        # Concurrency lock: prevent simultaneous apply for same scope.
        scope_name = manifest.get("scope", "")
        from django.db import transaction as db_transaction

        # --- Load and verify changes.jsonl BEFORE creating run ---
        changes_path = manifest_path.parent / "changes.jsonl"
        if not changes_path.is_file():
            raise CommandError(
                f"Changes file not found: {changes_path}"
            )

        # Verify changes.jsonl hash against manifest file_sha256 binding
        manifest_expected_file_sha = manifest.get("file_sha256", {})
        expected_changes_sha = manifest_expected_file_sha.get("changes.jsonl", "")
        if expected_changes_sha:
            actual_changes_sha = _sha256_file(changes_path)
            if actual_changes_sha != expected_changes_sha:
                raise CommandError(
                    f"changes.jsonl hash mismatch: "
                    f"expected {expected_changes_sha}, "
                    f"got {actual_changes_sha}"
                )

        # Verify manifest HEAD, migrations, and normalizer version match current state
        manifest_normalizer = manifest.get("normalizer_version", "")
        if manifest_normalizer and manifest_normalizer != RACE_FIELD_NORMALIZATION_VERSION:
            raise CommandError(
                f"Normalizer version mismatch: "
                f"manifest={manifest_normalizer}, "
                f"current={RACE_FIELD_NORMALIZATION_VERSION}"
            )

        manifest_head = manifest.get("production_head", "")
        if manifest_head:
            current_head = _git_head()
            if manifest_head != current_head:
                raise CommandError(
                    f"Production HEAD mismatch: "
                    f"manifest={manifest_head}, current={current_head}"
                )

        manifest_migrations = manifest.get("migrations", [])
        if manifest_migrations:
            current_migrations = _migration_list()
            if manifest_migrations != current_migrations:
                raise CommandError(
                    f"Migration set mismatch: "
                    f"manifest has {len(manifest_migrations)} entries, "
                    f"current has {len(current_migrations)}"
                )

        changes_rows: list[dict] = []
        with changes_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    changes_rows.append(json.loads(line))

        if not changes_rows:
            self.stdout.write("No changes to apply.")
            return

        # --- Create run with concurrency protection ---
        # Uses PostgreSQL advisory lock (transaction-scoped) for cross-process
        # serialization.  On SQLite the transaction isolation is sufficient.
        from django.db import connections

        # Deterministic lock key (hashlib, not Python hash() which is per-process)
        lock_bytes = hashlib.sha256(
            f"normalize_{scope_name}".encode()
        ).digest()[:8]
        lock_id = int.from_bytes(lock_bytes, "big") % 2147483647
        with db_transaction.atomic():
            conn = connections["default"]
            if conn.vendor == "postgresql":
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(%s)", [lock_id]
                    )
            # Re-check after acquiring the lock
            if RaceFieldNormalizationRun.objects.filter(
                status=RaceFieldNormalizationRun.Status.RUNNING,
                model_scope=scope_name,
            ).exists():
                raise CommandError(
                    f"Another normalization run is already in progress "
                    f"for scope '{scope_name}'."
                )
            run = RaceFieldNormalizationRun.objects.create(
                status=RaceFieldNormalizationRun.Status.RUNNING,
                model_scope=scope_name,
                manifest_sha256=expected_sha,
                normalizer_version=RACE_FIELD_NORMALIZATION_VERSION,
                term_snapshot_digest=expected_ts_digest,
                checkpoint_data={
                    "last_pk": 0,
                    "batches_completed": 0,
                    "last_model": "",
                },
                planned_count=len(changes_rows),
            )

        # Check for existing run with same manifest for checkpoint recovery
        existing_run = RaceFieldNormalizationRun.objects.filter(
            model_scope=scope_name,
            manifest_sha256=expected_sha,
        ).exclude(status=RaceFieldNormalizationRun.Status.RUNNING).order_by("-pk").first()

        checkpoint_start = 0
        if existing_run and existing_run.checkpoint_data:
            cp = existing_run.checkpoint_data
            last_pk = cp.get("last_pk", 0)
            last_model = cp.get("last_model", "")
            batches_completed = cp.get("batches_completed", 0)
            if last_pk and last_model:
                # Find where we left off
                for idx, row in enumerate(changes_rows):
                    model_label = row.get("model_label", "")
                    object_pk = row.get("object_pk", 0)
                    if (model_label > last_model) or (
                        model_label == last_model and object_pk > last_pk
                    ):
                        checkpoint_start = idx
                        break
                self.stdout.write(
                    f"Resuming from checkpoint: batch {batches_completed}, "
                    f"last {last_model}:{last_pk}"
                )

        skipped_count = 0
        actual_count = 0

        try:
            for i in range(checkpoint_start, len(changes_rows), batch_size):
                batch = changes_rows[i : i + batch_size]
                batch_num = (i // batch_size) + 1

                with transaction.atomic():
                    for row in batch:
                        row_skipped = self._apply_row(
                            run, row, batch_num
                        )
                        if row_skipped:
                            skipped_count += 1
                        else:
                            actual_count += 1

                    # Update checkpoint
                    if batch:
                        last_row = batch[-1]
                        run.checkpoint_data = {
                            "last_pk": last_row["object_pk"],
                            "batches_completed": batch_num,
                            "last_model": last_row["model_label"],
                        }
                        run.save(update_fields=["checkpoint_data"])

            # Success
            run.status = RaceFieldNormalizationRun.Status.COMPLETED
            run.actual_count = actual_count
            run.skipped_count = skipped_count
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "actual_count",
                    "skipped_count",
                    "finished_at",
                ]
            )

            if skipped_count > 0:
                raise CommandError(
                    f"Apply completed with {skipped_count} skipped "
                    f"row(s) (input drift)."
                )

        except (DatabaseError, CommandError) as exc:
            run.refresh_from_db()
            run.status = RaceFieldNormalizationRun.Status.FAILED
            run.actual_count = actual_count
            run.skipped_count = skipped_count
            run.error_message = str(exc)
            run.save(
                update_fields=[
                    "status",
                    "actual_count",
                    "skipped_count",
                    "error_message",
                ]
            )
            raise

    def _apply_row(
        self,
        run: RaceFieldNormalizationRun,
        row: dict[str, Any],
        batch_num: int,
    ) -> bool:
        """Apply a single manifest row. Returns True if skipped."""
        model_label = row.get("model_label", "")
        object_pk = row.get("object_pk", 0)

        if model_label == "HorseRaceRecord":
            model_class = HorseRaceRecord
        elif model_label == "RaceEvent":
            model_class = RaceEvent
        else:
            return True  # skip unknown model

        try:
            record = model_class.objects.select_for_update().get(
                pk=object_pk
            )
        except model_class.DoesNotExist:
            return True  # skip deleted record

        # Recompute input SHA for drift detection
        current_input_sha = _compute_input_sha_for_record(record)
        expected_input_sha = row.get("input_sha256", "")
        if current_input_sha != expected_input_sha:
            return True  # input drifted

        # Idempotency: skip if already applied
        current_snapshot = _current_snapshot(record)
        after = row.get("after", {})
        if _snapshots_equivalent(current_snapshot, after):
            return False  # already applied (no-op, but not skipped)

        # Apply normalized values
        _apply_normalized_to_record(record, after)

        # Create receipt
        RaceFieldNormalizationReceipt.objects.create(
            run=run,
            batch_number=batch_num,
            model_label=model_label,
            object_pk=object_pk,
            before_snapshot=row.get("before", {}),
            after_snapshot=after,
            input_sha256=expected_input_sha,
            race_term_id=row.get("race_term_id"),
            racecourse_term_id=row.get("racecourse_term_id"),
            normalizer_version=RACE_FIELD_NORMALIZATION_VERSION,
        )
        return False  # not skipped

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def _run_rollback(self, options: dict[str, Any]) -> None:
        run_id = options.get("rollback_run_id", 0)
        if not run_id:
            raise CommandError(
                "--rollback requires --rollback-run-id to target a "
                "specific completed normalization run."
            )

        run = RaceFieldNormalizationRun.objects.filter(
            pk=run_id,
            status=RaceFieldNormalizationRun.Status.COMPLETED,
        ).first()
        if not run:
            raise CommandError(
                f"No completed normalization run found with ID {run_id}."
            )

        receipts = list(run.receipts.order_by("-batch_number", "-pk"))
        if not receipts:
            self.stdout.write(
                f"Run {run_id} has no receipts. Nothing to roll back."
            )
            return

        restored_count = 0
        drifted_count = 0

        with transaction.atomic():
            for receipt in receipts:
                model_label = receipt.model_label
                object_pk = receipt.object_pk

                if model_label == "HorseRaceRecord":
                    model_class = HorseRaceRecord
                elif model_label == "RaceEvent":
                    model_class = RaceEvent
                else:
                    continue

                try:
                    record = (
                        model_class.objects.select_for_update().get(
                            pk=object_pk
                        )
                    )
                except model_class.DoesNotExist:
                    continue

                # Verify current value still matches receipt.after
                current = _current_snapshot(record)
                after = receipt.after_snapshot

                if not _snapshots_equivalent(current, after):
                    drifted_count += 1
                    continue

                # Restore before values
                before = receipt.before_snapshot
                _apply_normalized_to_record(record, before)
                restored_count += 1

            run.status = RaceFieldNormalizationRun.Status.FAILED
            run.error_message = (
                f"Rolled back: {restored_count} restored, "
                f"{drifted_count} drifted"
            )
            run.save(update_fields=["status", "error_message"])

            self.stdout.write(
                f"Run {run.pk}: restored {restored_count}, "
                f"drifted {drifted_count}"
            )


def _empty_sha() -> str:
    """SHA-256 of empty string."""
    return hashlib.sha256(b"").hexdigest()
