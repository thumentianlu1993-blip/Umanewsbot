"""Offline external identity enrichment for the P0 horse queue.

Generates external identity candidates from local evidence only (no network
requests): netkeiba ExternalHorse/Alias matches, race runner/result
source_refs horse IDs, and (via runtime tools) NAR/HKJC HTML cache reparse.
Unique strong matches are written back through a dry-run -> approved
manifest -> chunked commit gate; ambiguity always fails closed into
HorseIdentityConflict with deterministic offline fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from django.core.exceptions import ValidationError
from django.utils import timezone as dj_timezone

from stable.models import (
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalRaceEntry,
    ExternalRaceResult,
    HorseIdentityConflict,
    HorseIdentityConflictStatus,
    HorseP0Source,
    HorseP0SourceStatus,
    HorseProfile,
    RaceEvent,
    RaceEventResult,
    RaceEventRunner,
    RacingRegion,
)
from stable.services.p0_horse_profiles import _normalize_identity_name, _source_namespace

ENRICHMENT_SCHEMA_VERSION = "p0-horse-identity-enrichment.v1"
RESOLUTION_SCHEMA_VERSION = "p0-horse-identity-resolution.v1"
AGGREGATION_SCHEMA_VERSION = "p0-horse-identity-aggregation.v1"
ENRICHMENT_COMMIT_CHUNK_SIZE = 500

_MAPPED_SOURCE_URLS = {
    "netkeiba": "https://db.netkeiba.com/horse/{id}/",
    "sporting_life": "https://www.sportinglife.com/racing/profiles/horse/{id}",
    "hkjc": "https://racing.hkjc.com/racing/information/english/horse/horse.aspx?horseid={id}",
    "nar": "https://www.keiba.go.jp/KeibaWeb/DataRoom/HorseMarkInfo?k_lineageLoginCode={id}",
}

# Regions whose profiles may receive cache-reparse candidates, keyed by the
# evidence namespace produced by the HTML cache reparse tool.
_CACHE_EVIDENCE_REGIONS = {
    "hkjc": RacingRegion.HONG_KONG,
    "nar": RacingRegion.JAPAN,
}


class P0HorseIdentityEnrichmentError(Exception):
    """Raised when an enrichment operation must fail closed."""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _write_json(path: Path, payload: Any) -> str:
    content = _canonical_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)
    return hashlib.sha256(content).hexdigest()


def _offline_fingerprint(
    *,
    namespace: str,
    candidate_external_ids: Iterable[str],
    profile_ids: Iterable[int],
    reason: str,
) -> str:
    # The "offline" scope lives inside the hashed content so the digest stays
    # within HorseIdentityConflict.fingerprint max_length=64 while remaining
    # isolated from event-level conflict fingerprints.
    content = {
        "scope": "offline",
        "namespace": namespace,
        "candidate_external_ids": sorted(str(value) for value in candidate_external_ids),
        "profile_ids": sorted(int(value) for value in profile_ids),
        "reason": reason,
    }
    return _sha256(content)


def _profile_names(profile: HorseProfile) -> set[str]:
    names = set()
    for value in (
        profile.original_name,
        profile.english_name,
        profile.japanese_name,
        profile.display_name_zh,
    ):
        text = str(value or "").strip()
        if text:
            names.add(text)
    term = getattr(profile, "primary_term", None)
    if term is not None:
        for value in (term.source_ja, term.target_zh):
            text = str(value or "").strip()
            if text:
                names.add(text)
    return names


def _alias_index() -> dict[str, list[ExternalHorseAlias]]:
    index: dict[str, list[ExternalHorseAlias]] = {}
    queryset = ExternalHorseAlias.objects.filter(
        source=ExternalDataSource.NETKEIBA,
    ).select_related("horse")
    for alias in queryset.iterator():
        key = _normalize_identity_name(alias.normalized_name)
        if key:
            index.setdefault(key, []).append(alias)
    return index


def _external_horses_by_id() -> dict[tuple[str, str], ExternalHorse]:
    return {
        (horse.source, horse.horse_id): horse
        for horse in ExternalHorse.objects.filter(
            source=ExternalDataSource.NETKEIBA,
        ).iterator()
    }


def _existing_key_index(profiles: list[HorseProfile]) -> dict[str, set[int]]:
    index: dict[str, set[int]] = {}
    for profile in profiles:
        refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
        for key in refs.get("horse_identity_keys") or []:
            index.setdefault(str(key).casefold(), set()).add(profile.pk)
    return index


def _japan_alias_evidence(
    profiles: list[HorseProfile],
    *,
    alias_index: dict[str, list[ExternalHorseAlias]],
    horses_by_id: dict[tuple[str, str], ExternalHorse],
    key_index: dict[str, set[int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    already_present = 0
    for profile in profiles:
        matched: dict[str, ExternalHorseAlias] = {}
        for name in _profile_names(profile):
            for alias in alias_index.get(_normalize_identity_name(name), []):
                matched.setdefault(alias.external_horse_id, alias)
        if not matched:
            continue
        external_ids = sorted(matched)
        if len(external_ids) > 1:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": external_ids,
                }
            )
            continue
        external_id = external_ids[0]
        key = f"netkeiba:{external_id}".casefold()
        refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
        existing_keys = {str(k).casefold() for k in refs.get("horse_identity_keys") or []}
        if key in existing_keys:
            already_present += 1
            continue
        same_namespace = {k for k in existing_keys if k.startswith("netkeiba:")}
        if same_namespace:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "contradictory_identity",
                    "candidate_external_ids": external_ids,
                }
            )
            continue
        other_profiles = key_index.get(key, set()) - {profile.pk}
        if other_profiles:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": external_ids,
                    "related_profile_ids": sorted(other_profiles),
                }
            )
            continue
        horse = horses_by_id.get((ExternalDataSource.NETKEIBA, external_id))
        four_fields = _four_fields_from_horse(horse)
        mismatched = _pedigree_contradicts(profile, four_fields)
        if mismatched:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "four_field_mismatch",
                    "candidate_external_ids": external_ids,
                    "mismatched_fields": mismatched,
                }
            )
            continue
        candidates.append(
            {
                "profile_id": profile.pk,
                "horse_name": profile.original_name,
                "region": RacingRegion.JAPAN,
                "namespace": "netkeiba",
                "external_id": external_id,
                "identity_key": f"netkeiba:{external_id}",
                "source_url": _MAPPED_SOURCE_URLS["netkeiba"].format(id=external_id),
                "evidence_kind": "external_horse_alias",
                "evidence_refs": {
                    "original_namespace": "netkeiba",
                    "original_id": external_id,
                    "alias_ids": [matched[external_id].pk],
                },
                "four_fields": four_fields,
            }
        )
    return candidates, conflicts, already_present


def _profile_name_index(profiles: list[HorseProfile]) -> dict[str, list[HorseProfile]]:
    index: dict[str, list[HorseProfile]] = {}
    for profile in profiles:
        for name in _profile_names(profile):
            key = _normalize_identity_name(name)
            if key:
                index.setdefault(key, []).append(profile)
    return index


def _profile_existing_keys(profile: HorseProfile) -> set[str]:
    refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
    return {str(key).casefold() for key in refs.get("horse_identity_keys") or []}


def _four_fields_from_horse(horse: ExternalHorse | None) -> dict[str, str]:
    return {
        "sire_text": str(getattr(horse, "father_name", "") or "").strip(),
        "dam_text": str(getattr(horse, "mother_name", "") or "").strip(),
        "birth_date": (
            horse.birth_date.isoformat()
            if horse is not None and horse.birth_date
            else ""
        ),
    }


def _pedigree_contradicts(profile: HorseProfile, four_fields: dict[str, str]) -> list[str]:
    """Fields where the profile already has a value that disagrees with evidence."""
    mismatched: list[str] = []
    for column, key in (("sire_text", "sire_text"), ("dam_text", "dam_text")):
        current = str(getattr(profile, column) or "").strip()
        evidence = four_fields.get(key) or ""
        if current and evidence and _normalize_identity_name(current) != _normalize_identity_name(evidence):
            mismatched.append(column)
    if profile.birth_date and four_fields.get("birth_date"):
        if profile.birth_date.isoformat()[:4] != four_fields["birth_date"][:4]:
            mismatched.append("birth_date")
    return mismatched


def _japan_race_entry_evidence(
    profiles: list[HorseProfile],
    *,
    horses_by_id: dict[tuple[str, str], ExternalHorse],
    key_index: dict[str, set[int]],
    skip_profile_ids: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Back-infer netkeiba horse IDs from ExternalRaceEntry/Result rows.

    A row only counts when its race aligns to exactly one RaceEvent
    (race date + normalized race name, falling back to a uniquely-held
    date+venue pair) AND the horse name appears among that event's
    runners/results. Ambiguous alignment discards the row into a conflict;
    ExternalHorse pedigree values that contradict the profile also fail
    closed into a conflict instead of producing a candidate.
    """
    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    stats = {
        "rows_matched": 0,
        "rows_aligned": 0,
        "rows_unaligned": 0,
        "rows_ambiguous_alignment": 0,
    }
    eligible: list[HorseProfile] = []
    for profile in profiles:
        if profile.pk in skip_profile_ids:
            continue
        existing = _profile_existing_keys(profile)
        if any(key.startswith("netkeiba:") for key in existing):
            continue
        eligible.append(profile)
    name_index = _profile_name_index(eligible)
    if not name_index:
        return candidates, conflicts, stats

    event_name_index: dict[tuple[Any, str], list[int]] = {}
    event_venue_index: dict[tuple[Any, str], list[int]] = {}
    events = RaceEvent.objects.filter(
        country_region=RacingRegion.JAPAN,
        local_date__isnull=False,
    )
    for event in events.iterator():
        name_key = _normalize_identity_name(event.original_name)
        if name_key:
            event_name_index.setdefault((event.local_date, name_key), []).append(event.pk)
        venue_key = _normalize_identity_name(event.racecourse)
        if venue_key:
            event_venue_index.setdefault((event.local_date, venue_key), []).append(event.pk)
    participant_names: dict[int, set[str]] = {}
    for model in (RaceEventRunner, RaceEventResult):
        rows = model.objects.filter(
            event__country_region=RacingRegion.JAPAN,
            event__local_date__isnull=False,
        ).values("event_id", "horse_name")
        for row in rows.iterator():
            participant_names.setdefault(row["event_id"], set()).add(
                _normalize_identity_name(row["horse_name"])
            )

    # profile_id -> horse_id -> {"aligned": int, "ambiguous": int, "events": set}
    evidence: dict[int, dict[str, dict[str, Any]]] = {}

    def _record(row: Any) -> None:
        stats["rows_matched"] += 1
        race = row.race
        name_key = _normalize_identity_name(row.normalized_horse_name or row.horse_name)
        matched_profiles = name_index.get(name_key) or []
        if race is None or race.race_date is None:
            stats["rows_unaligned"] += 1
            return
        aligned: set[int] = set()
        race_name_key = _normalize_identity_name(race.race_name)
        if race_name_key:
            aligned.update(event_name_index.get((race.race_date, race_name_key), []))
        if not aligned:
            venue_key = _normalize_identity_name(race.venue or race.course)
            venue_events = event_venue_index.get((race.race_date, venue_key), []) if venue_key else []
            if len(set(venue_events)) == 1:
                aligned.update(venue_events)
        if len(aligned) > 1:
            stats["rows_ambiguous_alignment"] += 1
            for profile in matched_profiles:
                bucket = evidence.setdefault(profile.pk, {}).setdefault(
                    row.horse_id, {"aligned": 0, "ambiguous": 0, "events": set()}
                )
                bucket["ambiguous"] += 1
            return
        if not aligned:
            stats["rows_unaligned"] += 1
            return
        event_id = next(iter(aligned))
        if name_key not in participant_names.get(event_id, set()):
            stats["rows_unaligned"] += 1
            return
        stats["rows_aligned"] += 1
        for profile in matched_profiles:
            bucket = evidence.setdefault(profile.pk, {}).setdefault(
                row.horse_id, {"aligned": 0, "ambiguous": 0, "events": set()}
            )
            bucket["aligned"] += 1
            bucket["events"].add(event_id)

    for model in (ExternalRaceEntry, ExternalRaceResult):
        queryset = (
            model.objects.filter(source=ExternalDataSource.NETKEIBA)
            .exclude(horse_id="")
            .select_related("race")
        )
        for row in queryset.iterator():
            name_key = _normalize_identity_name(row.normalized_horse_name or row.horse_name)
            if name_key in name_index:
                _record(row)

    for profile in eligible:
        horse_ids = evidence.get(profile.pk)
        if not horse_ids:
            continue
        tainted = sorted(
            horse_id for horse_id, bucket in horse_ids.items() if bucket["ambiguous"]
        )
        valid = sorted(
            horse_id
            for horse_id, bucket in horse_ids.items()
            if not bucket["ambiguous"] and bucket["aligned"]
        )
        for horse_id in tainted:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "ambiguous_race_alignment",
                    "candidate_external_ids": [horse_id],
                }
            )
        if not valid:
            continue
        if len(valid) > 1:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": valid,
                }
            )
            continue
        external_id = valid[0]
        other_profiles = key_index.get(f"netkeiba:{external_id}".casefold(), set()) - {
            profile.pk
        }
        if other_profiles:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": [external_id],
                    "related_profile_ids": sorted(other_profiles),
                }
            )
            continue
        horse = horses_by_id.get((ExternalDataSource.NETKEIBA, external_id))
        four_fields = _four_fields_from_horse(horse)
        mismatched = _pedigree_contradicts(profile, four_fields)
        if mismatched:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": "netkeiba",
                    "reason": "four_field_mismatch",
                    "candidate_external_ids": [external_id],
                    "mismatched_fields": mismatched,
                }
            )
            continue
        candidates.append(
            {
                "profile_id": profile.pk,
                "horse_name": profile.original_name,
                "region": RacingRegion.JAPAN,
                "namespace": "netkeiba",
                "external_id": external_id,
                "identity_key": f"netkeiba:{external_id}",
                "source_url": _MAPPED_SOURCE_URLS["netkeiba"].format(id=external_id),
                "evidence_kind": "external_race_entry",
                "evidence_refs": {
                    "original_namespace": "netkeiba",
                    "original_id": external_id,
                    "aligned_event_ids": sorted(horse_ids[external_id]["events"]),
                },
                "four_fields": four_fields,
            }
        )
    return candidates, conflicts, stats


def _cache_link_evidence(
    profiles: list[HorseProfile],
    *,
    namespace: str,
    evidence_rows: list[dict[str, Any]],
    key_index: dict[str, set[int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Candidates from reparsed local HTML caches (HKJC horseid / NAR codes)."""
    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    already_present = 0
    region = _CACHE_EVIDENCE_REGIONS[namespace]
    name_index = _profile_name_index(profiles)
    rows_by_name: dict[str, set[str]] = {}
    row_names: dict[str, str] = {}
    for row in evidence_rows:
        if str(row.get("namespace") or "") != namespace:
            continue
        external_id = str(row.get("external_id") or "").strip()
        if not external_id:
            continue
        name_key = _normalize_identity_name(row.get("normalized_name") or row.get("name"))
        if not name_key:
            continue
        rows_by_name.setdefault(name_key, set()).add(external_id)
        row_names.setdefault(external_id, str(row.get("name") or ""))
    for profile in profiles:
        external_ids: set[str] = set()
        for name in _profile_names(profile):
            external_ids.update(rows_by_name.get(_normalize_identity_name(name), set()))
        if not external_ids:
            continue
        sorted_ids = sorted(external_ids)
        if len(sorted_ids) > 1:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": namespace,
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": sorted_ids,
                }
            )
            continue
        external_id = sorted_ids[0]
        key = f"{namespace}:{external_id}".casefold()
        existing_keys = _profile_existing_keys(profile)
        if key in existing_keys:
            already_present += 1
            continue
        if {item for item in existing_keys if item.startswith(f"{namespace}:")}:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": namespace,
                    "reason": "contradictory_identity",
                    "candidate_external_ids": sorted_ids,
                }
            )
            continue
        other_profiles = key_index.get(key, set()) - {profile.pk}
        if other_profiles:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": namespace,
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": sorted_ids,
                    "related_profile_ids": sorted(other_profiles),
                }
            )
            continue
        candidates.append(
            {
                "profile_id": profile.pk,
                "horse_name": profile.original_name,
                "region": region,
                "namespace": namespace,
                "external_id": external_id,
                "identity_key": key,
                "source_url": _MAPPED_SOURCE_URLS[namespace].format(id=external_id),
                "evidence_kind": "html_cache_reparse",
                "evidence_refs": {
                    "original_namespace": namespace,
                    "original_id": external_id,
                    "source_name": row_names.get(external_id, ""),
                },
                "four_fields": {"sire_text": "", "dam_text": "", "birth_date": ""},
            }
        )
    return candidates, conflicts, already_present


def _nar_evidence_enabled(nar_probe: dict[str, Any] | None) -> bool:
    """NAR evidence requires a probe showing locally parseable pages (task 1.7)."""
    if not isinstance(nar_probe, dict):
        return False
    return bool(
        nar_probe.get("files_with_matches", 0) > 0
        and nar_probe.get("named_ids", 0) > 0
    )


def _race_source_ref_evidence(
    profiles: list[HorseProfile],
    *,
    region: str,
    key_index: dict[str, set[int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """UK Sporting Life horse_id (key) and France ZEturf horse_id (evidence only)."""
    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    already_present = 0
    profile_ids = [profile.pk for profile in profiles]
    sources = HorseP0Source.objects.filter(
        profile_id__in=profile_ids,
        status=HorseP0SourceStatus.ACTIVE,
    ).values("profile_id", "evidence_payload")
    runner_ids: set[int] = set()
    result_ids: set[int] = set()
    links: dict[int, dict[str, set[int]]] = {}
    for row in sources:
        evidence = row["evidence_payload"] or {}
        bucket = links.setdefault(row["profile_id"], {"runners": set(), "results": set()})
        if evidence.get("race_runner_id"):
            runner_ids.add(evidence["race_runner_id"])
            bucket["runners"].add(evidence["race_runner_id"])
        if evidence.get("race_result_id"):
            result_ids.add(evidence["race_result_id"])
            bucket["results"].add(evidence["race_result_id"])
    runner_refs = {
        runner.pk: runner.source_refs
        for runner in RaceEventRunner.objects.filter(pk__in=runner_ids)
    }
    result_refs = {
        result.pk: result.source_refs
        for result in RaceEventResult.objects.filter(pk__in=result_ids)
    }

    expected_namespace = "sporting_life" if region == RacingRegion.UNITED_KINGDOM else "zeturf"

    def _horse_ids(refs: Any) -> set[str]:
        if not isinstance(refs, dict):
            return set()
        detected = _source_namespace(refs)
        # A detectable namespace from another provider must not be mislabeled
        # as this region's expected provider; unlabeled rows keep prior behavior.
        if detected and detected != expected_namespace:
            return set()
        ids = set()
        for key in ("horse_id", "external_horse_id", "horseId", "id_horse"):
            value = str(refs.get(key) or "").strip()
            if value:
                ids.add(value)
        return ids

    namespace = expected_namespace
    for profile in profiles:
        link = links.get(profile.pk, {"runners": set(), "results": set()})
        found: set[str] = set()
        for runner_id in link["runners"]:
            found |= _horse_ids(runner_refs.get(runner_id))
        for result_id in link["results"]:
            found |= _horse_ids(result_refs.get(result_id))
        if not found:
            continue
        external_ids = sorted(found)
        if len(external_ids) > 1:
            conflicts.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "namespace": namespace,
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": external_ids,
                }
            )
            continue
        external_id = external_ids[0]
        if region == RacingRegion.UNITED_KINGDOM:
            existing_keys = _profile_existing_keys(profile)
            key = f"sporting_life:{external_id}".casefold()
            if key in existing_keys:
                already_present += 1
                continue
            if {k for k in existing_keys if k.startswith("sporting_life:")}:
                conflicts.append(
                    {
                        "profile_id": profile.pk,
                        "horse_name": profile.original_name,
                        "namespace": namespace,
                        "reason": "contradictory_identity",
                        "candidate_external_ids": external_ids,
                    }
                )
                continue
            other_profiles = key_index.get(key, set()) - {profile.pk}
            if other_profiles:
                conflicts.append(
                    {
                        "profile_id": profile.pk,
                        "horse_name": profile.original_name,
                        "namespace": namespace,
                        "reason": "ambiguous_external_identity",
                        "candidate_external_ids": external_ids,
                        "related_profile_ids": sorted(other_profiles),
                    }
                )
                continue
            candidates.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "region": region,
                    "namespace": "sporting_life",
                    "external_id": external_id,
                    "identity_key": key,
                    "source_url": _MAPPED_SOURCE_URLS["sporting_life"].format(id=external_id),
                    "evidence_kind": "race_source_refs",
                    "evidence_refs": {
                        "original_namespace": "sporting_life",
                        "original_id": external_id,
                    },
                    "four_fields": {"sire_text": "", "dam_text": "", "birth_date": ""},
                }
            )
        else:
            candidates.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "region": region,
                    "namespace": "zeturf",
                    "external_id": external_id,
                    "identity_key": "",
                    "source_url": "",
                    "evidence_kind": "race_source_refs",
                    "evidence_refs": {
                        "original_namespace": "zeturf",
                        "original_id": external_id,
                    },
                    "four_fields": {"sire_text": "", "dam_text": "", "birth_date": ""},
                }
            )
    return candidates, conflicts, already_present


def build_region_identity_metrics(regions: Iterable[str]) -> dict[str, Any]:
    """Queue-level identity evidence coverage per region (task 5.1).

    ``needs_identity_enrichment`` counts active-queue profiles with no
    credible ``horse_identity_keys`` in ``source_refs``.
    """
    region_metrics: dict[str, Any] = {}
    for region in regions:
        profiles = (
            HorseProfile.objects.filter(
                racing_region=region,
                p0_sources__status=HorseP0SourceStatus.ACTIVE,
            )
            .distinct()
            .only("id", "source_refs", "sire_text", "dam_text", "birth_date")
            .iterator()
        )
        total = with_keys = with_urls = with_four_fields = 0
        for profile in profiles:
            total += 1
            refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
            if refs.get("horse_identity_keys"):
                with_keys += 1
            if refs.get("horse_source_urls"):
                with_urls += 1
            if profile.sire_text and profile.dam_text and profile.birth_date:
                with_four_fields += 1
        needs = total - with_keys
        region_metrics[region] = {
            "profiles_total": total,
            "with_identity_keys": with_keys,
            "with_source_urls": with_urls,
            "with_four_fields": with_four_fields,
            "needs_identity_enrichment": needs,
            "identity_key_coverage": (with_keys / total) if total else None,
            "needs_identity_enrichment_ratio": (needs / total) if total else None,
        }
    return {
        "schema_version": f"{ENRICHMENT_SCHEMA_VERSION}-metrics",
        "generated_at": _utcnow_iso(),
        "regions": region_metrics,
    }


def build_dry_run_artifact(
    *,
    regions: Iterable[str],
    profile_ids: Iterable[int] | None = None,
    cache_evidence: list[dict[str, Any]] | None = None,
    nar_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    region_list = list(regions)
    profiles = list(
        HorseProfile.objects.filter(
            racing_region__in=region_list,
            p0_sources__status=HorseP0SourceStatus.ACTIVE,
        )
        .select_related("primary_term")
        .distinct()
        .order_by("racing_region", "id")
    )
    if profile_ids is not None:
        wanted = {int(value) for value in profile_ids}
        profiles = [profile for profile in profiles if profile.pk in wanted]

    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    already_present = 0
    evidence_stats: dict[str, Any] = {}

    japan_profiles = [p for p in profiles if p.racing_region == RacingRegion.JAPAN]
    key_index = _existing_key_index(profiles)
    if japan_profiles:
        horses_by_id = _external_horses_by_id()
        japan_candidates, japan_conflicts, japan_present = _japan_alias_evidence(
            japan_profiles,
            alias_index=_alias_index(),
            horses_by_id=horses_by_id,
            key_index=key_index,
        )
        candidates.extend(japan_candidates)
        conflicts.extend(japan_conflicts)
        already_present += japan_present
        alias_handled = {item["profile_id"] for item in japan_candidates}
        alias_handled.update(item["profile_id"] for item in japan_conflicts)
        entry_candidates, entry_conflicts, entry_stats = _japan_race_entry_evidence(
            japan_profiles,
            horses_by_id=horses_by_id,
            key_index=key_index,
            skip_profile_ids=alias_handled,
        )
        candidates.extend(entry_candidates)
        conflicts.extend(entry_conflicts)
        evidence_stats["external_race_entry"] = entry_stats

    for region in (RacingRegion.UNITED_KINGDOM, RacingRegion.FRANCE):
        region_profiles = [p for p in profiles if p.racing_region == region]
        if not region_profiles:
            continue
        region_candidates, region_conflicts, region_present = _race_source_ref_evidence(
            region_profiles,
            region=region,
            key_index=key_index,
        )
        candidates.extend(region_candidates)
        conflicts.extend(region_conflicts)
        already_present += region_present

    cache_rows = cache_evidence or []
    for namespace in ("hkjc", "nar"):
        region = _CACHE_EVIDENCE_REGIONS[namespace]
        region_profiles = [p for p in profiles if p.racing_region == region]
        if not region_profiles:
            continue
        namespace_rows = [row for row in cache_rows if row.get("namespace") == namespace]
        if namespace == "nar":
            evidence_stats["nar_probe"] = nar_probe or None
            if not namespace_rows:
                evidence_stats["nar_status"] = "no_cache_evidence"
                continue
            if not _nar_evidence_enabled(nar_probe):
                evidence_stats["nar_status"] = "disabled_insufficient_cache_coverage"
                continue
            evidence_stats["nar_status"] = "enabled"
        elif not namespace_rows:
            continue
        cache_candidates, cache_conflicts, cache_present = _cache_link_evidence(
            region_profiles,
            namespace=namespace,
            evidence_rows=namespace_rows,
            key_index=key_index,
        )
        candidates.extend(cache_candidates)
        conflicts.extend(cache_conflicts)
        already_present += cache_present
        evidence_stats[f"{namespace}_cache"] = {
            "evidence_rows": len(namespace_rows),
            "candidates": len(cache_candidates),
            "conflicts": len(cache_conflicts),
        }

    # Batch-level reverse uniqueness: one external ID must not resolve to
    # multiple profiles, even when none of them has keys recorded yet.
    by_key: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        if candidate["identity_key"]:
            by_key.setdefault(candidate["identity_key"].casefold(), []).append(candidate)
    demoted: list[dict[str, Any]] = []
    for key, grouped in by_key.items():
        if len(grouped) < 2:
            continue
        for candidate in grouped:
            demoted.append(
                {
                    "profile_id": candidate["profile_id"],
                    "horse_name": candidate["horse_name"],
                    "namespace": candidate["namespace"],
                    "reason": "ambiguous_external_identity",
                    "candidate_external_ids": [candidate["external_id"]],
                    "related_profile_ids": sorted(
                        item["profile_id"] for item in grouped
                    ),
                }
            )
    if demoted:
        demoted_profiles = {(item["profile_id"], item["namespace"]) for item in demoted}
        candidates = [
            candidate
            for candidate in candidates
            if (candidate["profile_id"], candidate["namespace"]) not in demoted_profiles
        ]
        conflicts.extend(demoted)

    for conflict in conflicts:
        conflict["fingerprint"] = _offline_fingerprint(
            namespace=conflict["namespace"],
            candidate_external_ids=conflict["candidate_external_ids"],
            profile_ids=[conflict["profile_id"]],
            reason=conflict["reason"],
        )

    stats = {
        "profiles_evaluated": len(profiles),
        "candidates": len(candidates),
        "conflicts": len(conflicts),
        "already_present": already_present,
        "evidence": evidence_stats,
        "by_region": {},
    }
    profile_regions = {profile.pk: profile.racing_region for profile in profiles}
    for region in region_list:
        stats["by_region"][region] = {
            "profiles": sum(1 for p in profiles if p.racing_region == region),
            "candidates": sum(1 for c in candidates if c["region"] == region),
            "conflicts": sum(
                1
                for c in conflicts
                if profile_regions.get(c["profile_id"]) == region
            ),
        }

    return {
        "schema_version": ENRICHMENT_SCHEMA_VERSION,
        "generated_at": _utcnow_iso(),
        "regions": region_list,
        "candidates": candidates,
        "conflicts": conflicts,
        "stats": stats,
        "metrics_before": build_region_identity_metrics(region_list),
    }


def write_dry_run_artifact(
    artifact: dict[str, Any],
    *,
    output_dir: str | Path,
) -> Path:
    out = Path(output_dir)
    artifact_sha = _write_json(out / "enrichment_artifact.json", artifact)
    manifest = {
        "schema_version": f"{ENRICHMENT_SCHEMA_VERSION}-manifest",
        "status": "pending",
        "created_at": _utcnow_iso(),
        "regions": artifact["regions"],
        "artifact_path": str(out / "enrichment_artifact.json"),
        "artifact_sha256": artifact_sha,
        "stats": artifact["stats"],
        "approval": None,
    }
    _write_json(out / "enrichment_manifest.json", manifest)
    return out / "enrichment_manifest.json"


def approve_enrichment_manifest(
    manifest_path: str | Path,
    *,
    reviewer: str,
) -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    reviewer_text = str(reviewer or "").strip()
    if not reviewer_text:
        raise P0HorseIdentityEnrichmentError("approval requires a reviewer")
    if manifest.get("status") != "pending":
        raise P0HorseIdentityEnrichmentError("manifest is not pending")
    manifest["approval"] = {
        "reviewer": reviewer_text,
        "approved_at": _utcnow_iso(),
    }
    manifest["status"] = "approved"
    manifest["approved_sha256"] = _sha256(
        {key: value for key, value in manifest.items() if key != "approved_sha256"}
    )
    _write_json(path, manifest)
    return manifest


def _load_approved_artifact(
    manifest_path: str | Path,
    *,
    approved_sha256: str,
    expected_schema: str,
) -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    schema = str(manifest.get("schema_version") or "")
    if not schema.startswith(expected_schema):
        raise P0HorseIdentityEnrichmentError(
            f"manifest schema mismatch: expected {expected_schema}, got {schema or 'unknown'}"
        )
    if manifest.get("status") != "approved" or not (manifest.get("approval") or {}).get(
        "reviewer"
    ):
        raise P0HorseIdentityEnrichmentError("manifest is not approved")
    # Recompute the approved hash so post-approval manifest edits (e.g. a
    # swapped artifact_path) are detected instead of trusted blindly.
    recomputed = _sha256(
        {key: value for key, value in manifest.items() if key != "approved_sha256"}
    )
    if manifest.get("approved_sha256") != recomputed:
        raise P0HorseIdentityEnrichmentError("manifest drifted after approval")
    if manifest.get("approved_sha256") != approved_sha256:
        raise P0HorseIdentityEnrichmentError("approved SHA-256 mismatch")
    artifact_path = Path(manifest["artifact_path"])
    artifact_bytes = artifact_path.read_bytes()
    actual_sha = hashlib.sha256(artifact_bytes).hexdigest()
    if actual_sha != manifest["artifact_sha256"]:
        raise P0HorseIdentityEnrichmentError("artifact SHA-256 drift")
    return json.loads(artifact_bytes)


def _merge_evidence(source: HorseP0Source, candidate: dict[str, Any]) -> bool:
    evidence = dict(source.evidence_payload or {})
    changed = False
    if candidate["identity_key"]:
        keys = list(evidence.get("horse_identity_keys") or [])
        key = candidate["identity_key"].casefold()
        normalized = {str(k).casefold() for k in keys}
        if key not in normalized:
            keys.append(key)
            evidence["horse_identity_keys"] = keys
            changed = True
    identity_evidence = list(evidence.get("identity_evidence") or [])
    refs = candidate["evidence_refs"]
    if not any(
        item.get("original_namespace") == refs["original_namespace"]
        and str(item.get("original_id")) == str(refs["original_id"])
        for item in identity_evidence
    ):
        identity_evidence.append(dict(refs))
        evidence["identity_evidence"] = identity_evidence
        changed = True
    if changed:
        source.evidence_payload = evidence
        source.save(update_fields=["evidence_payload", "updated_at"])
    return changed


def _record_offline_conflict(conflict: dict[str, Any]) -> bool:
    existing = HorseIdentityConflict.objects.filter(
        fingerprint=conflict["fingerprint"],
    ).first()
    if existing is not None:
        if existing.status != HorseIdentityConflictStatus.PENDING:
            return False
        evidence = dict(existing.evidence_payload or {})
        evidence["identity_status"] = conflict["reason"]
        evidence["offline_candidate_external_ids"] = conflict["candidate_external_ids"]
        existing.evidence_payload = evidence
        existing.save(update_fields=["evidence_payload", "updated_at"])
        return True
    profile = HorseProfile.objects.filter(pk=conflict["profile_id"]).first()
    if profile is None:
        return False
    record = HorseIdentityConflict.objects.create(
        fingerprint=conflict["fingerprint"],
        status=HorseIdentityConflictStatus.PENDING,
        horse_name=conflict.get("horse_name", ""),
        evidence_payload={
            "identity_status": conflict["reason"],
            "offline_candidate_external_ids": conflict["candidate_external_ids"],
            "namespace": conflict["namespace"],
        },
    )
    record.candidate_profiles.add(profile)
    return True


def commit_approved_artifact(
    manifest_path: str | Path,
    *,
    approved_sha256: str,
) -> dict[str, Any]:
    from django.db import transaction

    artifact = _load_approved_artifact(
        manifest_path,
        approved_sha256=approved_sha256,
        expected_schema=ENRICHMENT_SCHEMA_VERSION,
    )
    candidates = artifact["candidates"]
    conflicts = artifact["conflicts"]
    report: dict[str, Any] = {"regions": {}}

    for conflict in conflicts:
        _record_offline_conflict(conflict)

    for region in artifact["regions"]:
        region_candidates = [c for c in candidates if c["region"] == region]
        applied = skipped = 0
        for start in range(0, len(region_candidates), ENRICHMENT_COMMIT_CHUNK_SIZE):
            chunk = region_candidates[start : start + ENRICHMENT_COMMIT_CHUNK_SIZE]
            with transaction.atomic():
                for candidate in chunk:
                    profile = (
                        HorseProfile.objects.select_for_update()
                        .filter(pk=candidate["profile_id"])
                        .first()
                    )
                    if profile is None:
                        skipped += 1
                        continue
                    # Drift defense: re-validate the four fields at write time.
                    # A contradiction discards the whole candidate (no keys,
                    # no evidence) instead of writing a partial identity.
                    four = candidate["four_fields"]
                    four_conflicts = []
                    updates = {}
                    for column, value in (
                        ("sire_text", four["sire_text"]),
                        ("dam_text", four["dam_text"]),
                        ("birth_date", four["birth_date"]),
                    ):
                        if not value:
                            continue
                        current = getattr(profile, column)
                        current_text = current.isoformat() if column == "birth_date" and current else str(current or "")
                        if not current_text:
                            updates[column] = value
                        elif current_text != value:
                            four_conflicts.append(column)
                    if four_conflicts:
                        _record_offline_conflict(
                            {
                                "profile_id": profile.pk,
                                "horse_name": profile.original_name,
                                "namespace": candidate["namespace"],
                                "reason": "four_field_mismatch",
                                "candidate_external_ids": [candidate["external_id"]],
                                "fingerprint": _offline_fingerprint(
                                    namespace=candidate["namespace"],
                                    candidate_external_ids=[candidate["external_id"]],
                                    profile_ids=[profile.pk],
                                    reason="four_field_mismatch",
                                ),
                            }
                        )
                        skipped += 1
                        continue
                    changed = False
                    if candidate["identity_key"]:
                        refs = dict(profile.source_refs or {})
                        keys = list(refs.get("horse_identity_keys") or [])
                        key = candidate["identity_key"].casefold()
                        normalized_existing = {str(k).casefold() for k in keys}
                        namespace_prefix = f"{candidate['namespace']}:".casefold()
                        if key not in normalized_existing and any(
                            existing.startswith(namespace_prefix)
                            for existing in normalized_existing
                        ):
                            # Profile drifted since dry-run: another same-namespace
                            # key appeared. Fail closed instead of writing.
                            _record_offline_conflict(
                                {
                                    "profile_id": profile.pk,
                                    "horse_name": profile.original_name,
                                    "namespace": candidate["namespace"],
                                    "reason": "contradictory_identity",
                                    "candidate_external_ids": [candidate["external_id"]],
                                    "fingerprint": _offline_fingerprint(
                                        namespace=candidate["namespace"],
                                        candidate_external_ids=[candidate["external_id"]],
                                        profile_ids=[profile.pk],
                                        reason="contradictory_identity",
                                    ),
                                }
                            )
                            skipped += 1
                            continue
                        if key not in normalized_existing:
                            keys.append(key)
                            refs["horse_identity_keys"] = keys
                            changed = True
                        # Fail-closed enrichment writes verified provenance;
                        # only verified keys may satisfy the publish gate.
                        # Idempotent: re-running an approved commit backfills
                        # provenance for keys written before provenance existed.
                        verified = list(refs.get("horse_identity_verified_keys") or [])
                        if key not in {str(item).casefold() for item in verified}:
                            verified.append(key)
                            refs["horse_identity_verified_keys"] = verified
                            changed = True
                        if candidate["source_url"]:
                            urls = list(refs.get("horse_source_urls") or [])
                            if candidate["source_url"] not in urls:
                                urls.append(candidate["source_url"])
                                refs["horse_source_urls"] = urls
                                changed = True
                        if changed:
                            profile.source_refs = refs
                    if updates:
                        for column, value in updates.items():
                            if column == "birth_date":
                                value = date.fromisoformat(value)
                            setattr(profile, column, value)
                        changed = True
                    if changed:
                        profile.save()
                    for source in HorseP0Source.objects.filter(
                        profile=profile,
                        status=HorseP0SourceStatus.ACTIVE,
                    ):
                        _merge_evidence(source, candidate)
                    if changed:
                        applied += 1
                    else:
                        skipped += 1
        report["regions"][region] = {"applied": applied, "skipped": skipped}
    conflict_profile_regions = {
        row["pk"]: row["racing_region"]
        for row in HorseProfile.objects.filter(
            pk__in={conflict["profile_id"] for conflict in conflicts}
        ).values("pk", "racing_region")
    }
    for region in artifact["regions"]:
        report["regions"][region]["conflicts"] = sum(
            1
            for conflict in conflicts
            if conflict_profile_regions.get(conflict["profile_id"]) == region
        )
    report["conflict_records_written"] = len(conflicts)
    report["metrics_after"] = build_region_identity_metrics(artifact["regions"])
    return report


def aggregate_identity_conflicts() -> dict[str, Any]:
    groups: dict[tuple, dict[str, Any]] = {}
    queryset = (
        HorseIdentityConflict.objects.filter(status="pending")
        .prefetch_related("candidate_profiles")
        .order_by("id")
    )
    total = 0
    for conflict in queryset.iterator(chunk_size=500):
        total += 1
        reason = str(
            (conflict.evidence_payload or {}).get("identity_status") or "unknown"
        )
        candidate_ids = sorted(
            conflict.candidate_profiles.values_list("id", flat=True)
        )
        key = (
            _normalize_identity_name(conflict.horse_name),
            tuple(candidate_ids),
            reason,
        )
        group = groups.setdefault(
            key,
            {
                "normalized_horse_name": key[0],
                "candidate_profile_ids": list(candidate_ids),
                "reason": reason,
                "conflict_count": 0,
                "race_event_ids": set(),
                "has_strong_identity_evidence": False,
            },
        )
        group["conflict_count"] += 1
        if conflict.race_event_id:
            group["race_event_ids"].add(conflict.race_event_id)
        if conflict.sire_name and conflict.dam_name and conflict.birth_year:
            group["has_strong_identity_evidence"] = True
        elif len(_aligned_profiles_for_conflict(conflict)) == 1:
            # Post-backfill evidence: one candidate profile now uniquely
            # aligns via identity keys or the four-field lock.
            group["has_strong_identity_evidence"] = True

    result_groups = []
    for group in groups.values():
        if group["has_strong_identity_evidence"]:
            action = "resolvable_with_identity"
        elif group["candidate_profile_ids"]:
            action = "needs_admin_review"
        else:
            action = "insufficient_evidence"
        result_groups.append(
            {
                "normalized_horse_name": group["normalized_horse_name"],
                "candidate_profile_ids": group["candidate_profile_ids"],
                "reason": group["reason"],
                "conflict_count": group["conflict_count"],
                "race_event_count": len(group["race_event_ids"]),
                "suggested_action": action,
            }
        )
    result_groups.sort(key=lambda item: (-item["conflict_count"], item["normalized_horse_name"]))
    return {
        "total_pending": total,
        "group_count": len(result_groups),
        "groups": result_groups,
    }


def write_aggregation_artifact(
    report: dict[str, Any],
    *,
    output_dir: str | Path,
) -> Path:
    """Persist the read-only conflict aggregation with a SHA-256 manifest (task 4.1)."""
    payload = {
        "schema_version": AGGREGATION_SCHEMA_VERSION,
        "generated_at": _utcnow_iso(),
        **report,
    }
    out = Path(output_dir)
    artifact_sha = _write_json(out / "conflict_aggregation.json", payload)
    manifest = {
        "schema_version": f"{AGGREGATION_SCHEMA_VERSION}-manifest",
        "created_at": _utcnow_iso(),
        "artifact_path": str(out / "conflict_aggregation.json"),
        "artifact_sha256": artifact_sha,
        "total_pending": report["total_pending"],
        "group_count": report["group_count"],
    }
    _write_json(out / "conflict_aggregation_manifest.json", manifest)
    return out / "conflict_aggregation_manifest.json"


def _aligned_profiles_for_conflict(conflict: HorseIdentityConflict) -> list[HorseProfile]:
    """Candidate profiles whose post-backfill identity uniquely matches a conflict.

    Alignment evidence is either a shared external identity key, or the full
    four-field lock (sire + dam + birth year) against the profile columns.
    """
    aligned: list[HorseProfile] = []
    conflict_keys = {str(key).casefold() for key in conflict.identity_keys or []}
    has_pedigree = bool(conflict.sire_name and conflict.dam_name and conflict.birth_year)
    for profile in conflict.candidate_profiles.all():
        profile_keys = _profile_existing_keys(profile)
        if conflict_keys and profile_keys & conflict_keys:
            aligned.append(profile)
            continue
        if (
            has_pedigree
            and _normalize_identity_name(profile.sire_text)
            == _normalize_identity_name(conflict.sire_name)
            and _normalize_identity_name(profile.dam_text)
            == _normalize_identity_name(conflict.dam_name)
            and profile.birth_date
            and profile.birth_date.year == conflict.birth_year
        ):
            aligned.append(profile)
    return aligned


def build_resolution_suggestions() -> dict[str, Any]:
    """Resolved suggestions for pending conflicts with unique identity alignment.

    Only conflicts whose candidate profiles align to exactly one profile via
    post-backfill external identity keys or the four-field lock produce a
    suggestion. Pairing conflicts additionally require the recorded horse
    number to be one of the conflict's candidate numbers; otherwise the
    conflict is skipped and reported. Nothing is written to the database.
    """
    suggestions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    queryset = (
        HorseIdentityConflict.objects.filter(status=HorseIdentityConflictStatus.PENDING)
        .prefetch_related("candidate_profiles")
        .order_by("id")
    )
    for conflict in queryset.iterator(chunk_size=500):
        aligned = _aligned_profiles_for_conflict(conflict)
        if len(aligned) != 1:
            continue
        profile = aligned[0]
        pairing = (conflict.evidence_payload or {}).get("pairing_conflict") or {}
        horse_number = ""
        if pairing:
            number = str(conflict.horse_number or "").strip()
            candidate_numbers = {str(value) for value in pairing.get("horse_numbers") or []}
            if number and number in candidate_numbers:
                horse_number = number
            else:
                skipped.append(
                    {
                        "fingerprint": conflict.fingerprint,
                        "horse_name": conflict.horse_name,
                        "reason": "pairing_conflict_without_candidate_horse_number",
                    }
                )
                continue
        suggestions.append(
            {
                "fingerprint": conflict.fingerprint,
                "horse_name": conflict.horse_name,
                "resolved_profile_id": profile.pk,
                "resolved_horse_number": horse_number,
            }
        )
    return {
        "schema_version": RESOLUTION_SCHEMA_VERSION,
        "generated_at": _utcnow_iso(),
        "suggestions": suggestions,
        "skipped": skipped,
        "stats": {
            "suggestions": len(suggestions),
            "skipped": len(skipped),
        },
    }


def write_resolution_artifact(
    artifact: dict[str, Any],
    *,
    output_dir: str | Path,
) -> Path:
    out = Path(output_dir)
    artifact_sha = _write_json(out / "resolution_artifact.json", artifact)
    manifest = {
        "schema_version": f"{RESOLUTION_SCHEMA_VERSION}-manifest",
        "status": "pending",
        "created_at": _utcnow_iso(),
        "artifact_path": str(out / "resolution_artifact.json"),
        "artifact_sha256": artifact_sha,
        "stats": artifact["stats"],
        "approval": None,
    }
    _write_json(out / "resolution_manifest.json", manifest)
    return out / "resolution_manifest.json"


def commit_resolution_suggestions(
    manifest_path: str | Path,
    *,
    approved_sha256: str,
    resolved_by: Any,
) -> dict[str, Any]:
    """Write approved resolution suggestions back through the resolved channel.

    Every write goes through ``full_clean()`` (same rules as the admin
    resolution flow) and only touches PENDING records, so RESOLVED/IGNORED
    adjudication evidence and the ``_reopen_identity_conflict`` protection
    stay intact.
    """
    artifact = _load_approved_artifact(
        manifest_path,
        approved_sha256=approved_sha256,
        expected_schema=RESOLUTION_SCHEMA_VERSION,
    )
    if resolved_by is None:
        raise P0HorseIdentityEnrichmentError("resolution commit requires a reviewer user")
    report: dict[str, Any] = {
        "resolved": 0,
        "skipped_not_pending": 0,
        "missing": 0,
        "failed_validation": [],
    }
    for suggestion in artifact["suggestions"]:
        conflict = HorseIdentityConflict.objects.filter(
            fingerprint=suggestion["fingerprint"],
        ).first()
        if conflict is None:
            report["missing"] += 1
            continue
        if conflict.status != HorseIdentityConflictStatus.PENDING:
            report["skipped_not_pending"] += 1
            continue
        profile = HorseProfile.objects.filter(pk=suggestion["resolved_profile_id"]).first()
        if profile is None:
            report["failed_validation"].append(
                {
                    "fingerprint": suggestion["fingerprint"],
                    "reason": "resolved_profile_missing",
                }
            )
            continue
        conflict.status = HorseIdentityConflictStatus.RESOLVED
        conflict.resolved_profile = profile
        conflict.resolved_horse_number = str(suggestion.get("resolved_horse_number") or "")
        conflict.resolved_by = resolved_by
        conflict.resolved_at = dj_timezone.now()
        note = (
            "offline identity adjudication "
            f"(manifest sha256 {approved_sha256})"
        )
        conflict.resolution_notes = (
            f"{conflict.resolution_notes}\n{note}".strip()
            if conflict.resolution_notes
            else note
        )
        try:
            conflict.full_clean()
        except ValidationError as exc:
            report["failed_validation"].append(
                {
                    "fingerprint": suggestion["fingerprint"],
                    "reason": exc.message_dict if hasattr(exc, "message_dict") else str(exc),
                }
            )
            continue
        conflict.save()
        report["resolved"] += 1
    return report
