from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, Prefetch, Q, Value, When
from django.utils import timezone

from stable.models import (
    HorseIdentityEvidenceCommitReceipt,
    HorseP0Source,
    HorseP0SourceStatus,
    HorseP0SourceType,
    HorseProfile,
    HorseProfileCompleteness,
    OperationLog,
    RacingRegion,
)
from stable.services.p0_horse_completion_source_clients import (
    NETKEIBA_PARSER_VERSION,
    P0HorseSourceBlocked,
    _dl_values,
    _field,
    _iso_date,
    _netkeiba_page_text,
    _pedigree_from_roles,
    _text,
)
from stable.services.p0_horse_profiles import _normalize_identity_name


SCHEMA_VERSION = "p0-horse-identity-bootstrap.v1"
PARSER_VERSION = "p0-horse-identity-bootstrap-parser.v1"
DEFAULT_SCAN_LIMIT = 500
MAX_BATCH_SIZE = 100
MAX_DATABASE_QUERIES = 6
PER_URL_ATTEMPT_BUDGET = 3
TOTAL_UNIQUE_URL_BUDGET = 6
TOTAL_TRANSFER_BUDGET = 18
OFFICIAL_UNIQUE_URL_BUDGET = 3
OFFICIAL_TRANSFER_BUDGET = 6
SOURCE_CONNECT_TIMEOUT_SECONDS = 5.0
SOURCE_READ_TIMEOUT_SECONDS = 20.0
PHASE_ONE_START_DATE = date(1998, 1, 1)
PHASE_ONE_END_DATE = date(2026, 12, 31)
JRAVAN_INPUT_SCHEMA_VERSION = "jravan-horse-identity-input.v1"
JRAVAN_OUTPUT_SCHEMA_VERSION = "jravan-horse-identity-output.v1"
PHASE_ONE_GRADE_PRIORITY = {
    "G1": 1,
    "JG1": 1,
    "JPN1": 1,
    "G2": 2,
    "JG2": 2,
    "JPN2": 2,
    "G3": 3,
    "JG3": 3,
    "JPN3": 3,
}
SELECTION_SORT_FIELDS = (
    "highest_grade_priority",
    "has_official_identity_anchor",
    "has_complete_official_context",
    "has_unique_netkeiba_id",
    "is_public",
    "graded_start_count",
    "latest_start_date",
    "profile_id",
)


class P0HorseIdentityBootstrapError(Exception):
    """A fail-closed selection, evidence, approval, or commit error."""


def validate_jravan_offline_package(
    *,
    input_manifest_path: str | Path,
    identity_jsonl_path: str | Path,
    output_manifest_path: str | Path,
) -> dict[str, Any]:
    """Validate a Windows DataLab exchange without exposing raw UM records."""

    input_path = Path(input_manifest_path)
    identity_path = Path(identity_jsonl_path)
    output_path = Path(output_manifest_path)
    input_manifest = json.loads(input_path.read_text(encoding="utf-8"))
    output_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    input_sha = _file_sha256(input_path)
    identity_sha = _file_sha256(identity_path)
    input_payload = {
        key: value
        for key, value in input_manifest.items()
        if key != "manifest_sha256"
    }
    output_payload = {
        key: value
        for key, value in output_manifest.items()
        if key != "manifest_sha256"
    }
    if (
        input_manifest.get("schema_version") != JRAVAN_INPUT_SCHEMA_VERSION
        or input_manifest.get("manifest_sha256") != _sha256(input_payload)
    ):
        raise P0HorseIdentityBootstrapError("JRA-VAN input manifest drift")
    if (
        output_manifest.get("schema_version") != JRAVAN_OUTPUT_SCHEMA_VERSION
        or output_manifest.get("manifest_sha256") != _sha256(output_payload)
        or output_manifest.get("input_file_sha256") != input_sha
        or output_manifest.get("identity_file_sha256") != identity_sha
        or output_manifest.get("record_type") != "UM"
    ):
        raise P0HorseIdentityBootstrapError("JRA-VAN output manifest drift")
    data_spec_version = str(output_manifest.get("data_spec_version") or "").strip()
    snapshot_at = str(output_manifest.get("snapshot_at") or "").strip()
    try:
        parsed_snapshot = datetime.fromisoformat(snapshot_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise P0HorseIdentityBootstrapError(
            "JRA-VAN snapshot timestamp is invalid"
        ) from exc
    if not data_spec_version or parsed_snapshot.tzinfo is None:
        raise P0HorseIdentityBootstrapError(
            "JRA-VAN data spec and timezone-aware snapshot are required"
        )
    allowed = {
        (
            int(row["profile_id"]),
            str(row["candidate_key"]),
            str(row["netkeiba_id"]),
        )
        for row in input_manifest.get("records") or []
    }
    if len(allowed) != len(input_manifest.get("records") or []):
        raise P0HorseIdentityBootstrapError("JRA-VAN input contains duplicate records")
    records: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for line in identity_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row_payload = {
            key: value for key, value in row.items() if key != "record_sha256"
        }
        key = (
            int(row.get("profile_id") or 0),
            str(row.get("candidate_key") or ""),
            str(row.get("netkeiba_id") or ""),
        )
        if (
            key not in allowed
            or key in seen
            or row.get("record_type") != "UM"
            or row.get("data_spec_version") != data_spec_version
            or row.get("snapshot_at") != snapshot_at
            or row.get("record_sha256") != _sha256(row_payload)
            or any(key in row for key in ("raw_record", "raw_payload", "um_record"))
            or not all(
                str(row.get(field) or "").strip()
                for field in (
                    "blood_registration_number",
                    "registered_name",
                    "sire_name",
                    "dam_name",
                    "birth_date",
                )
            )
        ):
            raise P0HorseIdentityBootstrapError(
                "JRA-VAN record is outside manifest or incomplete"
            )
        seen.add(key)
        records.append(row)
    if int(output_manifest.get("record_count") or -1) != len(records):
        raise P0HorseIdentityBootstrapError("JRA-VAN record count drift")
    return {
        "schema_version": JRAVAN_OUTPUT_SCHEMA_VERSION,
        "input_file_sha256": input_sha,
        "identity_file_sha256": identity_sha,
        "data_spec_version": data_spec_version,
        "snapshot_at": snapshot_at,
        "records": records,
    }


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> str:
    content = _canonical_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
    return hashlib.sha256(content).hexdigest()


def _profile_name(profile: HorseProfile) -> str:
    for value in (
        profile.original_name,
        profile.japanese_name,
        profile.english_name,
        profile.display_name_zh,
        getattr(profile.primary_term, "source_ja", ""),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _identity_keys(profile: HorseProfile, sources: Iterable[HorseP0Source]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
    payloads = [refs, *(source.evidence_payload or {} for source in sources)]
    for payload in payloads:
        for value in payload.get("horse_identity_keys") or []:
            text = str(value or "").strip().casefold()
            if text and text not in seen:
                seen.add(text)
                values.append(text)
    return values


def _iter_source_urls(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("https://", "http://")):
            yield text
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_source_urls(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_source_urls(nested)


def _official_provider(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.casefold() != "https":
        return ""
    host = str(parsed.hostname or "").lower()
    if host == "jra.go.jp" or host.endswith(".jra.go.jp"):
        return "jra"
    if host == "keiba.go.jp" or host.endswith(".keiba.go.jp"):
        return "nar"
    return ""


def _is_official_horse_url(provider: str, url: str) -> bool:
    parsed = urlparse(url)
    query = parsed.query.casefold()
    path = parsed.path.casefold()
    if provider == "jra":
        return (
            "accessu.html" in path
            and bool(_official_source_horse_id(provider, url))
        )
    if provider == "nar":
        return (
            "racehorseinfo" in path
            and "k_lineagelogincode=" in query
            and bool(_official_source_horse_id(provider, url))
        )
    return False


def _official_source_horse_id(provider: str, url: str) -> str:
    parsed = urlparse(url)
    if provider == "nar":
        match = re.search(r"(?:^|&)k_lineageLoginCode=([^&]+)", parsed.query, re.I)
        return match.group(1) if match else ""
    if provider == "jra":
        match = re.search(r"(?:^|&)CNAME=([^&]+)", parsed.query, re.I)
        return match.group(1) if match else ""
    return ""


def _has_reviewed_event_time_training_evidence(
    source: HorseP0Source,
    *,
    race_date: date,
) -> bool:
    for payload in (source.evidence_payload, source.metadata):
        if not isinstance(payload, dict):
            continue
        claim = payload.get("training_scope")
        if not isinstance(claim, dict) or claim.get("status") != "confirmed_japan":
            continue
        evidence = claim.get("evidence")
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if (
                isinstance(item, dict)
                and item.get("reviewed") is True
                and str(item.get("race_date") or "") == race_date.isoformat()
                and str(item.get("source_id") or "").strip()
                and str(item.get("source_url") or "").startswith("https://")
                and str(item.get("affiliation") or "").strip()
                and str(item.get("trainer_name") or "").strip()
            ):
                return True
    return False


def _qualification_from_source(source: HorseP0Source) -> dict[str, Any] | None:
    event = source.race_event
    if event is None:
        return None
    grade = str(source.race_grade or event.normalized_grade or "").upper()
    if grade not in PHASE_ONE_GRADE_PRIORITY:
        return None
    race_date = event.local_date
    if (
        race_date is None
        or race_date < PHASE_ONE_START_DATE
        or race_date > PHASE_ONE_END_DATE
    ):
        return None
    is_overseas = event.country_region != RacingRegion.JAPAN
    if is_overseas and (
        grade not in {"G1", "G2", "G3"}
        or event.data_quality_status != "complete"
        or not str(source.source_url or "").startswith("https://")
        or not _has_reviewed_event_time_training_evidence(
            source, race_date=race_date
        )
    ):
        return None

    payloads = (
        source.source_url,
        source.evidence_payload,
        source.metadata,
        event.source_refs,
        source.race_runner.source_refs if source.race_runner else {},
        source.race_result.source_refs if source.race_result else {},
    )
    urls: list[str] = []
    for payload in payloads:
        for url in _iter_source_urls(payload):
            if url not in urls and _official_provider(url):
                urls.append(url)
    official_race_url = next(
        (url for url in urls if not _is_official_horse_url(_official_provider(url), url)),
        "",
    )
    official_horse_url = next(
        (url for url in urls if _is_official_horse_url(_official_provider(url), url)),
        "",
    )
    provider = _official_provider(official_horse_url or official_race_url)
    if is_overseas:
        official_race_url = str(source.source_url or "").strip()
        provider = str(urlparse(official_race_url).hostname or "").lower()
    runner = source.race_runner
    result = source.race_result
    horse_number = str(
        (runner.horse_number if runner else "")
        or (result.horse_number if result else "")
        or ""
    ).strip()
    horse_name = str(
        (runner.horse_name if runner else "")
        or (result.horse_name if result else "")
        or source.horse_name
        or ""
    ).strip()
    return {
        "race_series_id": event.race_series_id,
        "race_event_id": event.pk,
        "grade": grade,
        "grade_priority": PHASE_ONE_GRADE_PRIORITY[grade],
        "race_date": race_date.isoformat(),
        "racecourse": str(event.racecourse or "").strip(),
        "country_region": str(event.country_region or "").strip(),
        "official_provider": provider,
        "official_race_url": official_race_url,
        "official_horse_url": official_horse_url,
        "official_source_horse_id": _official_source_horse_id(
            provider, official_horse_url
        ),
        "horse_number": horse_number,
        "horse_name": horse_name,
        "participant_key": str(source.participant_key or "").strip(),
        "p0_source_id": source.pk,
        "race_runner_id": source.race_runner_id,
        "race_result_id": source.race_result_id,
    }


def _training_scope(
    sources: Iterable[HorseP0Source],
    *,
    has_official_route: bool,
) -> tuple[str, list[dict[str, Any]]]:
    claims: list[dict[str, Any]] = []
    for source in sources:
        for payload in (source.evidence_payload, source.metadata):
            if not isinstance(payload, dict):
                continue
            claim = payload.get("training_scope")
            if isinstance(claim, dict):
                claims.append(deepcopy(claim))

    for claim in claims:
        evidence = claim.get("evidence")
        reviewed = [
            item
            for item in evidence
            if isinstance(item, dict) and item.get("reviewed") is True
        ] if isinstance(evidence, list) else []
        if claim.get("status") == "foreign_visitor" and reviewed:
            return "foreign_visitor", reviewed

    for claim in claims:
        evidence = claim.get("evidence")
        if claim.get("status") != "confirmed_japan" or not isinstance(evidence, list):
            continue
        reviewed = [
            deepcopy(item)
            for item in evidence
            if isinstance(item, dict)
            and item.get("reviewed") is True
            and str(item.get("source_url") or "").strip()
            and str(item.get("source_id") or "").strip()
            and str(item.get("race_date") or "").strip()
            and str(item.get("affiliation") or "").strip()
            and str(item.get("trainer_name") or "").strip()
        ]
        if reviewed:
            return "confirmed_japan", reviewed

    if has_official_route:
        return "provisional_japan", []
    return "unresolved", []


def _build_selection_row(
    profile: HorseProfile,
    sources: Iterable[HorseP0Source],
) -> dict[str, Any] | None:
    source_list = list(sources)
    by_event: dict[int, dict[str, Any]] = {}
    for source in source_list:
        qualification = _qualification_from_source(source)
        if qualification is None:
            continue
        existing = by_event.get(qualification["race_event_id"])
        new_score = (
            bool(qualification["official_horse_url"]),
            bool(
                qualification["official_race_url"]
                and qualification["race_date"]
                and qualification["racecourse"]
                and qualification["horse_number"]
                and qualification["horse_name"]
            ),
            -int(qualification["p0_source_id"]),
        )
        old_score = (
            bool(existing and existing["official_horse_url"]),
            bool(
                existing
                and existing["official_race_url"]
                and existing["race_date"]
                and existing["racecourse"]
                and existing["horse_number"]
                and existing["horse_name"]
            ),
            -int(existing["p0_source_id"]) if existing else 0,
        )
        if existing is None or new_score > old_score:
            by_event[qualification["race_event_id"]] = qualification
    qualifications = sorted(
        by_event.values(),
        key=lambda item: (
            item["grade_priority"],
            item["race_date"],
            item["race_event_id"],
        ),
    )
    if not qualifications:
        return None

    keys = _identity_keys(profile, source_list)
    netkeiba = [key.split(":", 1)[1] for key in keys if key.startswith("netkeiba:")]
    if len(netkeiba) != 1 or not netkeiba[0].isdigit():
        raise P0HorseIdentityBootstrapError(
            f"profile {profile.pk} must have exactly one numeric netkeiba ID"
        )

    has_anchor = any(item["official_horse_url"] for item in qualifications)
    has_context = any(
        item["official_provider"] in {"jra", "nar"}
        and item["official_race_url"]
        and item["race_date"]
        and item["racecourse"]
        and item["horse_number"]
        and item["horse_name"]
        for item in qualifications
    )
    training_status, training_evidence = _training_scope(
        source_list,
        has_official_route=has_anchor or has_context,
    )
    if training_status == "foreign_visitor":
        return None

    refs = deepcopy(profile.source_refs if isinstance(profile.source_refs, dict) else {})
    highest = min(qualifications, key=lambda item: item["grade_priority"])
    profile_snapshot = {
        "sire_text": str(profile.sire_text or "").strip(),
        "dam_text": str(profile.dam_text or "").strip(),
        "birth_date": profile.birth_date.isoformat() if profile.birth_date else "",
        "manual_lock_flags": deepcopy(profile.manual_lock_flags or {}),
        "source_refs": refs,
        "p0_source_ids": sorted(source.pk for source in source_list),
    }
    return {
        "profile_id": profile.pk,
        "candidate_key": f"profile:{profile.pk}",
        "horse_name": _profile_name(profile),
        "netkeiba_id": netkeiba[0],
        "highest_grade": highest["grade"],
        "highest_grade_priority": highest["grade_priority"],
        "graded_start_count": len(qualifications),
        "latest_start_date": max(item["race_date"] for item in qualifications),
        "has_official_identity_anchor": has_anchor,
        "has_complete_official_context": has_context,
        "is_public": bool(profile.is_public),
        "training_scope_status": training_status,
        "training_evidence": training_evidence,
        "qualification": qualifications,
        "qualification_sha256": _sha256(qualifications),
        "queue_reasons": [
            f"highest_grade:{highest['grade']}",
            f"graded_starts:{len(qualifications)}",
            f"training_scope:{training_status}",
        ],
        "profile_snapshot": profile_snapshot,
    }


def _selection_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    latest = date.fromisoformat(row["latest_start_date"]).toordinal()
    return (
        int(row["highest_grade_priority"]),
        -int(bool(row["has_official_identity_anchor"])),
        -int(bool(row["has_complete_official_context"])),
        -int(bool(row["netkeiba_id"])),
        -int(bool(row["is_public"])),
        -int(row["graded_start_count"]),
        -latest,
        int(row["profile_id"]),
    )


def _selection_config_fingerprint() -> str:
    return _sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "phase_one_start_date": PHASE_ONE_START_DATE.isoformat(),
            "phase_one_end_date": PHASE_ONE_END_DATE.isoformat(),
            "grade_priority": PHASE_ONE_GRADE_PRIORITY,
            "sort_fields": SELECTION_SORT_FIELDS,
            "max_batch_size": MAX_BATCH_SIZE,
            "scan_limit": DEFAULT_SCAN_LIMIT,
        }
    )


def select_identity_bootstrap_batch(
    *,
    target_count: int = MAX_BATCH_SIZE,
    excluded_profile_ids: Iterable[int] = (),
    excluded_batch_id: str = "",
    exclusion_reason: str = "",
    scan_limit: int = DEFAULT_SCAN_LIMIT,
    now=None,
) -> dict[str, Any]:
    if not 1 <= int(target_count) <= MAX_BATCH_SIZE:
        raise P0HorseIdentityBootstrapError("target_count must be between 1 and 100")
    if not int(target_count) <= int(scan_limit) <= DEFAULT_SCAN_LIMIT:
        raise P0HorseIdentityBootstrapError("scan_limit must be between target_count and 500")

    excluded = sorted({int(value) for value in excluded_profile_ids})
    if excluded and (
        not str(excluded_batch_id or "").strip()
        or not str(exclusion_reason or "").strip()
    ):
        raise P0HorseIdentityBootstrapError(
            "excluded profiles require excluded_batch_id and exclusion_reason"
        )
    recent_news_cutoff = timezone.now() - timedelta(days=30)
    active_sources = (
        HorseP0Source.objects.filter(status=HorseP0SourceStatus.ACTIVE)
        .select_related("race_event", "race_runner", "race_result")
        .order_by("id")
    )
    profiles = list(
        HorseProfile.objects.filter(
            racing_region=RacingRegion.JAPAN,
            p0_sources__status=HorseP0SourceStatus.ACTIVE,
        )
        .exclude(pk__in=excluded)
        .exclude(completeness_status=HorseProfileCompleteness.COMPLETE_PROFILE_FULL)
        .exclude(
            Q(sire_text__gt="")
            & Q(dam_text__gt="")
            & Q(birth_date__isnull=False)
        )
        .select_related("primary_term")
        .prefetch_related(
            Prefetch("p0_sources", queryset=active_sources, to_attr="active_p0_sources")
        )
        .annotate(
            manual_source_count=Count(
                "p0_sources",
                filter=Q(
                    p0_sources__status=HorseP0SourceStatus.ACTIVE,
                    p0_sources__source_type=HorseP0SourceType.MANUAL,
                ),
                distinct=True,
            ),
            major_source_count=Count(
                "p0_sources",
                filter=Q(
                    p0_sources__status=HorseP0SourceStatus.ACTIVE,
                    p0_sources__source_type=HorseP0SourceType.MAJOR_RACE_PARTICIPANT,
                ),
                distinct=True,
            ),
            candidate_attention_count=Count(
                "data_candidates",
                filter=Q(data_candidates__status__in=("pending", "conflict")),
                distinct=True,
            ),
            recent_article_count=Count(
                "article_links",
                filter=Q(
                    article_links__status__in=("auto", "manual"),
                    article_links__article__published_to_web_at__gte=recent_news_cutoff,
                ),
                distinct=True,
            ),
            completion_priority=Case(
                When(completeness_status=HorseProfileCompleteness.EMPTY, then=Value(0)),
                When(
                    completeness_status=HorseProfileCompleteness.PROFILE_ONLY,
                    then=Value(1),
                ),
                When(
                    completeness_status=HorseProfileCompleteness.PARTIAL_PEDIGREE,
                    then=Value(2),
                ),
                default=Value(3),
                output_field=IntegerField(),
            ),
        )
        .distinct()
        .order_by("id")[:scan_limit]
    )

    eligible: list[dict[str, Any]] = []
    netkeiba_ids: set[str] = set()
    for profile in profiles:
        sources = list(profile.active_p0_sources)
        row = _build_selection_row(profile, sources)
        if row is None:
            continue
        if row["netkeiba_id"] in netkeiba_ids:
            raise P0HorseIdentityBootstrapError(
                f"duplicate netkeiba ID in selected input: {row['netkeiba_id']}"
            )
        netkeiba_ids.add(row["netkeiba_id"])
        eligible.append(row)
    eligible.sort(key=_selection_sort_key)
    horses = eligible[:target_count]
    if len(horses) != target_count:
        raise P0HorseIdentityBootstrapError(
            f"bounded selection found {len(horses)} of {target_count} "
            f"after scanning {len(profiles)} candidates"
        )
    profile_ids = [row["profile_id"] for row in horses]
    if len(profile_ids) != len(set(profile_ids)):
        raise P0HorseIdentityBootstrapError("duplicate profile IDs in selected input")
    candidate_keys = [row["candidate_key"] for row in horses]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise P0HorseIdentityBootstrapError("duplicate candidate keys in selected input")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "selected",
        "created_at": (now or timezone.now()).isoformat(),
        "config_fingerprint": _selection_config_fingerprint(),
        "parameters": {
            "target_count": target_count,
            "scan_limit": scan_limit,
            "max_database_queries": MAX_DATABASE_QUERIES,
            "excluded_profile_ids": excluded,
            "excluded_batch_id": str(excluded_batch_id or "").strip(),
            "exclusion_reason": str(exclusion_reason or "").strip(),
        },
        "parser_version": PARSER_VERSION,
        "horses": horses,
    }
    manifest["input_sha256"] = _sha256(manifest)
    return manifest


def validate_identity_bootstrap_snapshot(manifest: dict[str, Any]) -> None:
    frozen = deepcopy(manifest)
    supplied_sha = str(frozen.pop("input_sha256", "") or "")
    if not supplied_sha or _sha256(frozen) != supplied_sha:
        raise P0HorseIdentityBootstrapError("input manifest SHA drift")
    if manifest.get("config_fingerprint") != _selection_config_fingerprint():
        raise P0HorseIdentityBootstrapError("selection config fingerprint drift")
    frozen_rows = {
        int(row["profile_id"]): row for row in manifest.get("horses") or []
    }
    profile_ids = sorted(frozen_rows)
    active_sources = (
        HorseP0Source.objects.filter(status=HorseP0SourceStatus.ACTIVE)
        .select_related("race_event", "race_runner", "race_result")
        .order_by("id")
    )
    profiles = list(
        HorseProfile.objects.filter(pk__in=profile_ids)
        .select_related("primary_term")
        .prefetch_related(
            Prefetch("p0_sources", queryset=active_sources, to_attr="active_p0_sources")
        )
        .order_by("id")
    )
    if [profile.pk for profile in profiles] != profile_ids:
        raise P0HorseIdentityBootstrapError("profile set drift")
    frozen_fields = (
        "profile_id",
        "candidate_key",
        "horse_name",
        "netkeiba_id",
        "highest_grade",
        "highest_grade_priority",
        "graded_start_count",
        "latest_start_date",
        "has_official_identity_anchor",
        "has_complete_official_context",
        "training_scope_status",
        "training_evidence",
        "qualification",
        "qualification_sha256",
        "profile_snapshot",
    )
    for profile in profiles:
        current = _build_selection_row(profile, profile.active_p0_sources)
        frozen_row = frozen_rows[profile.pk]
        if current is None or any(
            current.get(field) != frozen_row.get(field) for field in frozen_fields
        ):
            raise P0HorseIdentityBootstrapError(
                f"profile {profile.pk} qualification or identity snapshot drift"
            )


def _source_blocker(reason: str, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "blocker", "reason": reason, "evidence": evidence or {}}


class IdentityRequestSession:
    """Bounded, resumable request session for one-off identity preparation."""

    def __init__(
        self,
        *,
        transport: Any,
        allow_network: bool,
        environment_network_enabled: bool,
        cache_dir: str | Path,
        parser_fingerprint: str,
        config_fingerprint: str,
        interval_seconds: dict[str, float] | None = None,
        monotonic=None,
        sleep=None,
    ):
        self.transport = transport
        self.allow_network = bool(allow_network)
        self.environment_network_enabled = bool(environment_network_enabled)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.cache_dir.chmod(0o700)
        except OSError:
            pass
        self.parser_fingerprint = str(parser_fingerprint or "").strip()
        self.config_fingerprint = str(config_fingerprint or "").strip()
        if not self.parser_fingerprint or not self.config_fingerprint:
            raise P0HorseIdentityBootstrapError(
                "parser/config fingerprint is required"
            )
        self.fingerprint = _sha256(
            {
                "parser_fingerprint": self.parser_fingerprint,
                "config_fingerprint": self.config_fingerprint,
            }
        )
        self.interval_seconds = {
            key: max(0.0, float(value))
            for key, value in (
                interval_seconds
                or {"jra": 8.0, "nar": 8.0, "netkeiba": 8.0}
            ).items()
        }
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._last_request_at: dict[str, float] = {}
        self._events: list[dict[str, Any]] = []
        self.state_path = self.cache_dir / "state.json"
        if self.state_path.exists():
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._fingerprint_drift = loaded.get("fingerprint") != self.fingerprint
            self._state = loaded
        else:
            self._fingerprint_drift = False
            self._state = {
                "schema_version": "identity-request-session.v1",
                "fingerprint": self.fingerprint,
                "parser_fingerprint": self.parser_fingerprint,
                "config_fingerprint": self.config_fingerprint,
                "provider_circuits": {},
                "budgets": {},
            }
            self._save_state()

    @staticmethod
    def _expected_provider(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme.casefold() != "https":
            return ""
        official = _official_provider(url)
        if official:
            return official
        host = str(parsed.hostname or "").lower()
        if host == "db.netkeiba.com":
            return "netkeiba"
        return ""

    def _save_state(self) -> None:
        _write_json(self.state_path, self._state)
        try:
            self.state_path.chmod(0o600)
        except OSError:
            pass

    def _cache_path(self, provider: str, url: str) -> Path:
        key = hashlib.sha256(f"{provider}\0{url}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"response-{key}.json"

    def _budget(self, candidate_key: str) -> dict[str, Any]:
        budgets = self._state.setdefault("budgets", {})
        return budgets.setdefault(
            candidate_key,
            {
                "unique_urls": [],
                "official_urls": [],
                "transfers": 0,
                "official_transfers": 0,
                "attempts_by_url": {},
            },
        )

    def _register_url(
        self,
        *,
        candidate_key: str,
        url: str,
        official_chain: bool,
    ) -> None:
        budget = self._budget(candidate_key)
        unique_urls = budget["unique_urls"]
        official_urls = budget["official_urls"]
        if url not in unique_urls:
            if len(unique_urls) >= TOTAL_UNIQUE_URL_BUDGET:
                raise P0HorseIdentityBootstrapError(
                    "REQUEST_BUDGET_EXHAUSTED: total unique URL budget"
                )
            if official_chain and len(official_urls) >= OFFICIAL_UNIQUE_URL_BUDGET:
                raise P0HorseIdentityBootstrapError(
                    "REQUEST_BUDGET_EXHAUSTED: official unique URL budget"
                )
            unique_urls.append(url)
        if official_chain and url not in official_urls:
            official_urls.append(url)
        self._save_state()

    def _register_transfer(
        self,
        *,
        candidate_key: str,
        url: str,
        official_chain: bool,
    ) -> None:
        budget = self._budget(candidate_key)
        attempts = budget["attempts_by_url"]
        current_attempts = int(attempts.get(url) or 0)
        if current_attempts >= PER_URL_ATTEMPT_BUDGET:
            raise P0HorseIdentityBootstrapError(
                "REQUEST_BUDGET_EXHAUSTED: per URL attempt budget"
            )
        if int(budget["transfers"]) >= TOTAL_TRANSFER_BUDGET:
            raise P0HorseIdentityBootstrapError(
                "REQUEST_BUDGET_EXHAUSTED: total transfer budget"
            )
        if (
            official_chain
            and int(budget["official_transfers"]) >= OFFICIAL_TRANSFER_BUDGET
        ):
            raise P0HorseIdentityBootstrapError(
                "REQUEST_BUDGET_EXHAUSTED: official transfer budget"
            )
        attempts[url] = current_attempts + 1
        budget["transfers"] = int(budget["transfers"]) + 1
        if official_chain:
            budget["official_transfers"] = int(budget["official_transfers"]) + 1
        self._save_state()

    def _rate_limit(self, provider: str) -> None:
        now = float(self._monotonic())
        if provider in self._last_request_at:
            remaining = (
                float(self.interval_seconds.get(provider, 0.0))
                - (now - self._last_request_at[provider])
            )
            if remaining > 0:
                self._sleep(remaining)
                now = float(self._monotonic())
        self._last_request_at[provider] = now

    def _open_circuit(self, provider: str, reason: str) -> None:
        self._state.setdefault("provider_circuits", {})[provider] = {
            "reason": reason,
            "opened_at": timezone.now().isoformat(),
        }
        self._save_state()

    def _cached_response(
        self,
        *,
        provider: str,
        url: str,
    ) -> Any | None:
        path = self._cache_path(provider, url)
        if not path.exists():
            return None
        cached = json.loads(path.read_text(encoding="utf-8"))
        if (
            cached.get("fingerprint") != self.fingerprint
            or cached.get("provider") != provider
            or cached.get("requested_url") != url
            or int(cached.get("status_code") or 0) != 200
        ):
            raise P0HorseIdentityBootstrapError(
                "cache parser/config fingerprint or metadata drift"
            )
        content = str(cached.get("body") or "")
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != cached.get(
            "content_sha256"
        ):
            raise P0HorseIdentityBootstrapError("cache content SHA drift")
        self._events.append(
            {
                "candidate_key": None,
                "provider": provider,
                "url": url,
                "final_url": cached.get("final_url") or url,
                "http_status": 200,
                "content_sha256": cached["content_sha256"],
                "cache_hit": True,
            }
        )
        return SimpleNamespace(
            text=content,
            url=str(cached.get("final_url") or url),
            status_code=200,
            headers=deepcopy(cached.get("headers") or {}),
        )

    def get(
        self,
        *,
        candidate_key: str,
        provider: str,
        url: str,
        official_chain: bool,
    ) -> Any:
        provider = str(provider or "").strip().lower()
        url = str(url or "").strip()
        candidate_key = str(candidate_key or "").strip()
        if (
            not candidate_key
            or provider not in {"jra", "nar", "netkeiba"}
            or self._expected_provider(url) != provider
        ):
            raise P0HorseIdentityBootstrapError(
                "SOURCE_ACCESS_DENIED: provider URL is not allowlisted"
            )
        if self._fingerprint_drift:
            raise P0HorseIdentityBootstrapError(
                "parser/config fingerprint drift"
            )
        cached = self._cached_response(provider=provider, url=url)
        if cached is not None:
            self._events[-1]["candidate_key"] = candidate_key
            return cached
        if not self.allow_network or not self.environment_network_enabled:
            raise P0HorseIdentityBootstrapError(
                "network requires --allow-network and enabled environment gate"
            )
        circuit = (self._state.get("provider_circuits") or {}).get(provider)
        if circuit:
            raise P0HorseIdentityBootstrapError(
                f"SOURCE_ACCESS_DENIED: provider circuit open ({circuit.get('reason')})"
            )

        current_url = url
        while True:
            self._register_url(
                candidate_key=candidate_key,
                url=current_url,
                official_chain=official_chain,
            )
            self._register_transfer(
                candidate_key=candidate_key,
                url=current_url,
                official_chain=official_chain,
            )
            self._rate_limit(provider)
            try:
                response = self.transport.get(
                    current_url,
                    allow_redirects=False,
                    timeout=(
                        SOURCE_CONNECT_TIMEOUT_SECONDS,
                        SOURCE_READ_TIMEOUT_SECONDS,
                    ),
                )
            except Exception as exc:
                attempts = int(
                    self._budget(candidate_key)["attempts_by_url"].get(current_url)
                    or 0
                )
                if attempts < PER_URL_ATTEMPT_BUDGET:
                    continue
                raise P0HorseIdentityBootstrapError(
                    f"SOURCE_ACCESS_DENIED: transport failed ({type(exc).__name__})"
                ) from exc
            status = int(getattr(response, "status_code", 0) or 0)
            final_url = str(getattr(response, "url", "") or current_url)
            text = str(getattr(response, "text", "") or "")
            headers = dict(getattr(response, "headers", {}) or {})
            content_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            self._events.append(
                {
                    "candidate_key": candidate_key,
                    "provider": provider,
                    "url": current_url,
                    "final_url": final_url,
                    "http_status": status,
                    "content_sha256": content_sha,
                    "cache_hit": False,
                }
            )
            if status in {301, 302, 303, 307, 308}:
                location = str(
                    headers.get("Location") or headers.get("location") or ""
                ).strip()
                redirect_url = urljoin(current_url, location)
                if (
                    not location
                    or self._expected_provider(redirect_url) != provider
                ):
                    self._open_circuit(provider, "redirect outside allowlist")
                    raise P0HorseIdentityBootstrapError(
                        "SOURCE_ACCESS_DENIED: redirect outside provider allowlist"
                    )
                current_url = redirect_url
                continue
            lowered = text.casefold()
            access_signal = any(
                marker in lowered
                for marker in (
                    "captcha",
                    "access denied",
                    "too many requests",
                    "異常なアクセス",
                    "ロボットではありません",
                )
            )
            if status in {401, 403, 429} or access_signal:
                self._open_circuit(provider, f"http={status or 'restriction-page'}")
                raise P0HorseIdentityBootstrapError(
                    "SOURCE_ACCESS_DENIED: source refused access"
                )
            if status >= 500:
                attempts = int(
                    self._budget(candidate_key)["attempts_by_url"].get(current_url)
                    or 0
                )
                if attempts < PER_URL_ATTEMPT_BUDGET:
                    continue
                raise P0HorseIdentityBootstrapError(
                    f"SOURCE_ACCESS_DENIED: source HTTP {status}"
                )
            if status != 200:
                raise P0HorseIdentityBootstrapError(
                    f"SOURCE_ACCESS_DENIED: source HTTP {status}"
                )
            if self._expected_provider(final_url) != provider:
                self._open_circuit(provider, "response outside allowlist")
                raise P0HorseIdentityBootstrapError(
                    "SOURCE_ACCESS_DENIED: final URL outside provider allowlist"
                )
            cache = {
                "schema_version": "identity-source-cache.v1",
                "fingerprint": self.fingerprint,
                "provider": provider,
                "requested_url": url,
                "final_url": final_url,
                "status_code": status,
                "headers": {
                    str(key): str(value)
                    for key, value in headers.items()
                    if str(key).casefold()
                    in {"content-type", "etag", "last-modified"}
                },
                "content_sha256": content_sha,
                "body": text,
                "fetched_at": timezone.now().isoformat(),
            }
            cache_path = self._cache_path(provider, url)
            _write_json(cache_path, cache)
            try:
                cache_path.chmod(0o600)
            except OSError:
                pass
            return SimpleNamespace(
                text=text,
                url=final_url,
                status_code=status,
                headers=headers,
            )

    def ledger(self) -> dict[str, Any]:
        return {
            "schema_version": "identity-request-ledger.v1",
            "fingerprint": self.fingerprint,
            "limits": {
                "total_unique_urls": TOTAL_UNIQUE_URL_BUDGET,
                "total_transfers": TOTAL_TRANSFER_BUDGET,
                "official_unique_urls": OFFICIAL_UNIQUE_URL_BUDGET,
                "official_transfers": OFFICIAL_TRANSFER_BUDGET,
                "per_url_attempts": PER_URL_ATTEMPT_BUDGET,
            },
            "budgets": deepcopy(self._state.get("budgets") or {}),
            "provider_circuits": deepcopy(
                self._state.get("provider_circuits") or {}
            ),
            "events": deepcopy(self._events),
        }


def _response_evidence(response: Any, *, provider: str) -> dict[str, Any]:
    body = str(getattr(response, "text", "") or "")
    return {
        "provider": provider,
        "source_url": str(getattr(response, "url", "") or ""),
        "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "parser_version": PARSER_VERSION,
        "fetched_at": timezone.now().isoformat(),
    }


def _provider_error(exc: Exception) -> dict[str, Any]:
    message = str(exc)
    if "REQUEST_BUDGET_EXHAUSTED" in message:
        reason = "REQUEST_BUDGET_EXHAUSTED"
    elif "SOURCE_ACCESS_DENIED" in message or "network requires" in message:
        reason = "SOURCE_ACCESS_DENIED"
    else:
        reason = "SOURCE_LAYOUT_CHANGED"
    return _source_blocker(reason, evidence={"error_type": type(exc).__name__})


def _table_label_values(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            label = _normalize_identity_name(cells[0].get_text(" ", strip=True))
            value = _text(cells[-1].get_text(" ", strip=True))
            if label and value:
                values[label] = value
    return values


def _identity_from_label_values(
    soup: BeautifulSoup,
    values: dict[str, str],
) -> dict[str, str]:
    heading = soup.select_one("h1")
    horse_name = _text(heading.get_text(" ", strip=True) if heading else "")
    birth_date = _iso_date(_field(values, "生年月日", "誕生日"))
    sire_name = _field(values, "父", "父馬")
    dam_name = _field(values, "母", "母馬")
    return {
        "horse_name": horse_name,
        "sire_name": sire_name,
        "dam_name": dam_name,
        "birth_date": birth_date,
        "birth_date_precision": "day" if birth_date else "unknown",
    }


def _identity_is_complete(identity: dict[str, Any]) -> bool:
    return all(
        str(identity.get(field) or "").strip()
        for field in ("horse_name", "sire_name", "dam_name", "birth_date")
    )


class NetkeibaHorseIdentityProvider:
    """Extract only the identity lock fields from a provider-bound horse ID."""

    provider_name = "netkeiba"

    def __init__(self, request_session: IdentityRequestSession):
        self.request_session = request_session

    def fetch(self, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_key = str(candidate.get("candidate_key") or "").strip()
        horse_id = str(candidate.get("netkeiba_id") or "").strip()
        if not candidate_key or not horse_id.isdigit():
            return _source_blocker("PROVIDER_BOUND_IDENTITY_REQUIRED")
        profile_url = f"https://db.netkeiba.com/horse/{horse_id}/"
        pedigree_url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
        try:
            profile_response = self.request_session.get(
                candidate_key=candidate_key,
                provider=self.provider_name,
                url=profile_url,
                official_chain=False,
            )
            pedigree_response = self.request_session.get(
                candidate_key=candidate_key,
                provider=self.provider_name,
                url=pedigree_url,
                official_chain=False,
            )
            profile_soup = BeautifulSoup(
                _netkeiba_page_text(profile_response), "html.parser"
            )
            pedigree_soup = BeautifulSoup(
                _netkeiba_page_text(pedigree_response), "html.parser"
            )
            heading = profile_soup.select_one(".horse_title h1")
            horse_name = re.sub(
                r"[（(][^）)]*[）)]",
                "",
                _text(heading.get_text(" ", strip=True) if heading else ""),
            ).strip()
            profile_values = _table_label_values(profile_soup)
            birth_date = _iso_date(_field(profile_values, "生年月日"))
            pedigree = _pedigree_from_roles(pedigree_soup)
            identity = {
                "horse_name": horse_name,
                "sire_name": pedigree.get("sire", ""),
                "dam_name": pedigree.get("dam", ""),
                "birth_date": birth_date,
                "birth_date_precision": "day" if birth_date else "unknown",
            }
            if not _identity_is_complete(identity):
                return _source_blocker("SOURCE_LAYOUT_CHANGED")
            return {
                "status": "source_pass",
                "provider": self.provider_name,
                "source_id_raw": horse_id,
                "url": str(profile_response.url or profile_url),
                "content_sha256": hashlib.sha256(
                    (
                        _netkeiba_page_text(profile_response)
                        + "\n"
                        + _netkeiba_page_text(pedigree_response)
                    ).encode("utf-8")
                ).hexdigest(),
                "identity": identity,
                "evidence": {
                    "profile": _response_evidence(
                        profile_response, provider=self.provider_name
                    ),
                    "pedigree": _response_evidence(
                        pedigree_response, provider=self.provider_name
                    ),
                },
            }
        except (P0HorseIdentityBootstrapError, P0HorseSourceBlocked) as exc:
            return _provider_error(exc)


class JraHorseIdentityProvider:
    """Parse JRA horse profiles using JRA-specific labels and identifiers."""

    provider_name = "jra"

    def __init__(self, request_session: IdentityRequestSession):
        self.request_session = request_session

    def fetch(
        self,
        candidate: dict[str, Any],
        anchor: dict[str, Any],
    ) -> dict[str, Any]:
        url = str(anchor.get("official_horse_url") or "").strip()
        if (
            anchor.get("provider") != self.provider_name
            or not _is_official_horse_url(self.provider_name, url)
        ):
            return _source_blocker("PROVIDER_BOUND_IDENTITY_REQUIRED")
        try:
            response = self.request_session.get(
                candidate_key=str(candidate.get("candidate_key") or ""),
                provider=self.provider_name,
                url=url,
                official_chain=True,
            )
            soup = BeautifulSoup(str(response.text or ""), "html.parser")
            values = _table_label_values(soup)
            identity = _identity_from_label_values(soup, values)
            trainer = _field(values, "調教師")
            affiliation = next(
                (value for value in ("美浦", "栗東") if value in trainer),
                "",
            )
            if not _identity_is_complete(identity) or not trainer or not affiliation:
                return _source_blocker("SOURCE_LAYOUT_CHANGED")
            qualification = anchor.get("qualification") or {}
            source_id = str(
                anchor.get("official_source_horse_id")
                or _official_source_horse_id(self.provider_name, url)
            )
            return {
                "status": "source_pass",
                "provider": self.provider_name,
                "source_id_raw": source_id,
                "url": str(response.url or url),
                "content_sha256": hashlib.sha256(
                    str(response.text or "").encode("utf-8")
                ).hexdigest(),
                "identity": identity,
                "qualification": deepcopy(qualification),
                "training_scope_status": "confirmed_japan",
                "training_evidence": [
                    {
                        "source": self.provider_name,
                        "source_id": source_id,
                        "source_url": str(response.url or url),
                        "race_date": qualification.get("race_date"),
                        "race_event_id": qualification.get("race_event_id"),
                        "trainer_name": trainer,
                        "affiliation": affiliation,
                        "reviewed": True,
                    }
                ],
                "evidence": _response_evidence(
                    response, provider=self.provider_name
                ),
            }
        except P0HorseIdentityBootstrapError as exc:
            return _provider_error(exc)


class NarHorseIdentityProvider:
    """Parse NAR horse profiles without sharing JRA page assumptions."""

    provider_name = "nar"

    def __init__(self, request_session: IdentityRequestSession):
        self.request_session = request_session

    def fetch(
        self,
        candidate: dict[str, Any],
        anchor: dict[str, Any],
    ) -> dict[str, Any]:
        url = str(anchor.get("official_horse_url") or "").strip()
        if (
            anchor.get("provider") != self.provider_name
            or not _is_official_horse_url(self.provider_name, url)
        ):
            return _source_blocker("PROVIDER_BOUND_IDENTITY_REQUIRED")
        try:
            response = self.request_session.get(
                candidate_key=str(candidate.get("candidate_key") or ""),
                provider=self.provider_name,
                url=url,
                official_chain=True,
            )
            soup = BeautifulSoup(str(response.text or ""), "html.parser")
            values = {
                _normalize_identity_name(label): value
                for label, value in _dl_values(soup).items()
            }
            identity = _identity_from_label_values(soup, values)
            trainer = _field(values, "調教師")
            affiliation = _field(values, "所属")
            if not _identity_is_complete(identity) or not trainer or not affiliation:
                return _source_blocker("SOURCE_LAYOUT_CHANGED")
            qualification = anchor.get("qualification") or {}
            source_id = str(
                anchor.get("official_source_horse_id")
                or _official_source_horse_id(self.provider_name, url)
            )
            return {
                "status": "source_pass",
                "provider": self.provider_name,
                "source_id_raw": source_id,
                "url": str(response.url or url),
                "content_sha256": hashlib.sha256(
                    str(response.text or "").encode("utf-8")
                ).hexdigest(),
                "identity": identity,
                "qualification": deepcopy(qualification),
                "training_scope_status": "confirmed_japan",
                "training_evidence": [
                    {
                        "source": self.provider_name,
                        "source_id": source_id,
                        "source_url": str(response.url or url),
                        "race_date": qualification.get("race_date"),
                        "race_event_id": qualification.get("race_event_id"),
                        "trainer_name": trainer,
                        "affiliation": affiliation,
                        "reviewed": True,
                    }
                ],
                "evidence": _response_evidence(
                    response, provider=self.provider_name
                ),
            }
        except P0HorseIdentityBootstrapError as exc:
            return _provider_error(exc)


def _normalized_horse_number(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return text.lstrip("0") or ("0" if text else "")


def _response_hop(response: Any, requested_url: str) -> tuple[str, dict[str, Any]]:
    text = str(getattr(response, "text", "") or "")
    final_url = str(getattr(response, "url", "") or requested_url)
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        raise P0HorseIdentityBootstrapError(
            f"official source returned HTTP {status_code}"
        )
    return text, {
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": status_code,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _participant_rows(
    soup: BeautifulSoup,
    *,
    page_url: str,
    provider: str,
    horse_number: str,
    horse_name: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"])
        number = _text(row.get("data-horse-number"))
        if not number:
            number_cell = row.select_one(".horse-number, .umaban, [data-role='horse-number']")
            number = _text(number_cell.get_text(" ", strip=True)) if number_cell else ""
        if not number and cells:
            number = _text(cells[0].get_text(" ", strip=True))
        links: list[str] = []
        names: list[str] = []
        for link in row.select("a[href]"):
            resolved = urljoin(page_url, _text(link.get("href")))
            if (
                _official_provider(resolved) == provider
                and _is_official_horse_url(provider, resolved)
            ):
                links.append(resolved)
                names.append(_text(link.get_text(" ", strip=True)))
        visible_name = next((name for name in names if name), "")
        if not visible_name:
            name_cell = row.select_one(".horse-name, [data-role='horse-name']")
            visible_name = (
                _text(name_cell.get_text(" ", strip=True)) if name_cell else ""
            )
        if (
            _normalized_horse_number(number) == _normalized_horse_number(horse_number)
            and _same_name(visible_name, horse_name)
        ):
            matches.append(
                {
                    "horse_number": number,
                    "horse_name": visible_name,
                    "official_horse_urls": sorted(set(links)),
                    "row_text": _text(row.get_text(" ", strip=True)),
                }
            )
    return matches


def _detail_links(
    soup: BeautifulSoup,
    *,
    page_url: str,
    provider: str,
    race_date: str,
    racecourse: str,
) -> list[str]:
    links: list[str] = []
    normalized_course = _normalize_identity_name(racecourse)
    for link in soup.select("a[href]"):
        resolved = urljoin(page_url, _text(link.get("href")))
        if (
            _official_provider(resolved) != provider
            or _is_official_horse_url(provider, resolved)
        ):
            continue
        link_date = _text(link.get("data-race-date"))
        link_course = _text(link.get("data-racecourse"))
        surrounding = _text(link.get_text(" ", strip=True))
        date_match = link_date == race_date or (race_date and race_date in surrounding)
        course_match = (
            _normalize_identity_name(link_course) == normalized_course
            or (racecourse and racecourse in surrounding)
        )
        if date_match and course_match and resolved not in links:
            links.append(resolved)
    return links


def resolve_official_horse_anchor(
    candidate: dict[str, Any],
    *,
    transport: Any | None = None,
    allow_network: bool = False,
    environment_network_enabled: bool = False,
    request_interval_seconds: float = 8.0,
    request_session: IdentityRequestSession | None = None,
) -> dict[str, Any]:
    qualifications = [
        row
        for row in candidate.get("qualification") or []
        if isinstance(row, dict) and row.get("official_provider") in {"jra", "nar"}
    ]
    if not qualifications:
        return _source_blocker("OFFICIAL_ANCHOR_MISSING")
    qualifications.sort(
        key=lambda row: (
            int(PHASE_ONE_GRADE_PRIORITY.get(str(row.get("grade") or ""), 99)),
            str(row.get("race_date") or ""),
            int(row.get("race_event_id") or 0),
        )
    )
    direct = [
        row
        for row in qualifications
        if row.get("official_horse_url")
        and _official_provider(str(row["official_horse_url"]))
        == row.get("official_provider")
        and _is_official_horse_url(
            str(row["official_provider"]), str(row["official_horse_url"])
        )
    ]
    if direct:
        row = direct[0]
        url = str(row["official_horse_url"])
        return {
            "status": "anchor_pass",
            "provider": row["official_provider"],
            "official_horse_url": url,
            "official_source_horse_id": (
                str(row.get("official_source_horse_id") or "")
                or _official_source_horse_id(str(row["official_provider"]), url)
            ),
            "qualification": deepcopy(row),
            "matched_row": {
                "horse_number": str(row.get("horse_number") or ""),
                "horse_name": str(row.get("horse_name") or ""),
            },
            "hops": [],
        }
    if any(row.get("official_horse_url") for row in qualifications):
        return _source_blocker("OFFICIAL_ANCHOR_MISSING")
    if request_session is None and (
        not allow_network or not environment_network_enabled
    ):
        raise P0HorseIdentityBootstrapError(
            "network requires --allow-network and enabled environment gate"
        )
    if request_session is None and transport is None:
        raise P0HorseIdentityBootstrapError("transport or request session is required")

    row = next(
        (
            item
            for item in qualifications
            if item.get("official_race_url")
            and item.get("race_date")
            and item.get("racecourse")
            and item.get("horse_number")
            and item.get("horse_name")
        ),
        None,
    )
    if row is None:
        return _source_blocker("OFFICIAL_CONTEXT_NOT_FOUND")
    provider = str(row["official_provider"])
    current_url = str(row["official_race_url"])
    if _official_provider(current_url) != provider:
        return _source_blocker("OFFICIAL_CONTEXT_NOT_FOUND")

    hops: list[dict[str, Any]] = []
    visited: set[str] = set()
    for step in range(2):
        if current_url in visited or len(visited) >= 3:
            return _source_blocker("REQUEST_BUDGET_EXHAUSTED", evidence={"hops": hops})
        visited.add(current_url)
        try:
            response = (
                request_session.get(
                    candidate_key=str(candidate.get("candidate_key") or ""),
                    provider=provider,
                    url=current_url,
                    official_chain=True,
                )
                if request_session is not None
                else transport.get(current_url)
            )
        except P0HorseIdentityBootstrapError as exc:
            return _provider_error(exc)
        try:
            text, hop = _response_hop(response, current_url)
        except P0HorseIdentityBootstrapError as exc:
            return _source_blocker("SOURCE_ACCESS_DENIED", evidence={"message": str(exc)})
        if _official_provider(hop["final_url"]) != provider:
            return _source_blocker("SOURCE_ACCESS_DENIED", evidence={"hops": hops + [hop]})
        hops.append(hop)
        soup = BeautifulSoup(text, "html.parser")
        matches = _participant_rows(
            soup,
            page_url=hop["final_url"],
            provider=provider,
            horse_number=str(row["horse_number"]),
            horse_name=str(row["horse_name"]),
        )
        if len(matches) > 1:
            return _source_blocker(
                "OFFICIAL_CONTEXT_AMBIGUOUS",
                evidence={"hops": hops, "matched_rows": matches},
            )
        if len(matches) == 1:
            urls = matches[0]["official_horse_urls"]
            if len(urls) != 1:
                reason = (
                    "OFFICIAL_CONTEXT_AMBIGUOUS"
                    if len(urls) > 1
                    else "OFFICIAL_CONTEXT_NOT_FOUND"
                )
                return _source_blocker(
                    reason, evidence={"hops": hops, "matched_rows": matches}
                )
            anchor = urls[0]
            return {
                "status": "anchor_pass",
                "provider": provider,
                "official_horse_url": anchor,
                "official_source_horse_id": _official_source_horse_id(
                    provider, anchor
                ),
                "qualification": deepcopy(row),
                "matched_row": {
                    "horse_number": matches[0]["horse_number"],
                    "horse_name": matches[0]["horse_name"],
                    "row_text": matches[0]["row_text"],
                },
                "hops": hops,
            }
        if step == 0:
            detail_urls = _detail_links(
                soup,
                page_url=hop["final_url"],
                provider=provider,
                race_date=str(row["race_date"]),
                racecourse=str(row["racecourse"]),
            )
            if len(detail_urls) > 1:
                return _source_blocker(
                    "OFFICIAL_CONTEXT_AMBIGUOUS",
                    evidence={"hops": hops, "detail_urls": detail_urls},
                )
            if len(detail_urls) == 1:
                current_url = detail_urls[0]
                continue
        return _source_blocker("OFFICIAL_CONTEXT_NOT_FOUND", evidence={"hops": hops})
    return _source_blocker("OFFICIAL_CONTEXT_NOT_FOUND", evidence={"hops": hops})


def _split_country_suffix(value: Any) -> tuple[str, str]:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    match = re.match(r"^(.*?)(?:\s*\(([A-Za-z]{2,4})\))?$", text)
    if not match:
        return _normalize_identity_name(text), ""
    return _normalize_identity_name(match.group(1)), str(match.group(2) or "").upper()


def _has_mixed_script_pair(left: Any, right: Any) -> bool:
    left_text = str(left or "")
    right_text = str(right or "")
    left_latin = bool(re.search(r"[A-Za-z]", left_text))
    right_latin = bool(re.search(r"[A-Za-z]", right_text))
    left_japanese = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", left_text))
    right_japanese = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", right_text))
    return (left_latin and right_japanese) or (right_latin and left_japanese)


def compare_identity_sources(
    *,
    netkeiba: dict[str, Any],
    official: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    official_rows = [deepcopy(row) for row in official]
    required = ("horse_name", "sire_name", "dam_name", "birth_date")
    if not official_rows or any(not netkeiba.get(field) for field in required):
        return _source_blocker("REQUIRED_FIELD_MISSING")
    partial = False
    providers: set[str] = set()
    for row in official_rows:
        if any(not row.get(field) for field in required):
            return _source_blocker("REQUIRED_FIELD_MISSING")
        provider = str(row.get("provider") or "")
        if provider not in {"jra", "nar"}:
            return _source_blocker("OFFICIAL_ANCHOR_MISSING")
        providers.add(provider)
        left_name, left_suffix = _split_country_suffix(netkeiba["horse_name"])
        right_name, right_suffix = _split_country_suffix(row["horse_name"])
        if (
            left_name != right_name
            or (left_suffix and right_suffix and left_suffix != right_suffix)
        ):
            return _source_blocker("NAME_MISMATCH")
        for field, reason in (
            ("sire_name", "SIRE_MISMATCH"),
            ("dam_name", "DAM_MISMATCH"),
        ):
            if _same_name(netkeiba[field], row[field]):
                continue
            if _has_mixed_script_pair(netkeiba[field], row[field]):
                return _source_blocker("SCRIPT_ALIAS_UNRESOLVED")
            return _source_blocker(reason)
        left_date = str(netkeiba["birth_date"])
        right_date = str(row["birth_date"])
        if left_date[:4] != right_date[:4]:
            return _source_blocker("BIRTH_YEAR_MISMATCH")
        right_precision = str(row.get("birth_date_precision") or "")
        if len(left_date) == 10 and len(right_date) == 10 and right_precision != "year":
            if left_date != right_date:
                return _source_blocker("BIRTH_DATE_MISMATCH")
        else:
            partial = True
    if partial:
        return {
            "status": "candidate_partial",
            "reason": "BIRTH_DATE_PRECISION_PARTIAL",
            "identity_evidence_grade": "C",
        }
    if providers == {"jra", "nar"}:
        mode = "NETKEIBA_JRA_NAR_CONSENSUS"
        grade = "A+"
    elif providers == {"jra"}:
        mode = "NETKEIBA_JRA_CONSENSUS"
        grade = "A"
    else:
        mode = "NETKEIBA_NAR_CONSENSUS"
        grade = "A"
    return {
        "status": "candidate_pass",
        "identity_mode": mode,
        "identity_evidence_grade": grade,
        "fields": {
            "sire_text": str(netkeiba["sire_name"]),
            "dam_text": str(netkeiba["dam_name"]),
            "birth_date": str(netkeiba["birth_date"]),
        },
    }


def _same_name(left: Any, right: Any) -> bool:
    return bool(_normalize_identity_name(left)) and (
        _normalize_identity_name(left) == _normalize_identity_name(right)
    )


def fetch_dual_source_identity(
    candidate: dict[str, Any],
    *,
    request_session: IdentityRequestSession,
) -> dict[str, Any]:
    required = {"profile_id", "candidate_key", "horse_name", "netkeiba_id"}
    if required - set(candidate) or not str(candidate.get("netkeiba_id") or "").isdigit():
        raise P0HorseIdentityBootstrapError("candidate identity input is incomplete")
    netkeiba_result = NetkeibaHorseIdentityProvider(request_session).fetch(candidate)
    if netkeiba_result.get("status") != "source_pass":
        return netkeiba_result
    net_identity = deepcopy(netkeiba_result["identity"])
    if not _same_name(candidate["horse_name"], net_identity["horse_name"]):
        return _source_blocker("NAME_MISMATCH")

    qualifications = [
        row
        for row in candidate.get("qualification") or []
        if isinstance(row, dict) and row.get("official_provider") in {"jra", "nar"}
    ]
    providers = sorted(
        {str(row["official_provider"]) for row in qualifications},
        key=("jra", "nar").index,
    )
    if not providers:
        return _source_blocker("OFFICIAL_ANCHOR_MISSING")

    official_results: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    provider_types = {
        "jra": JraHorseIdentityProvider,
        "nar": NarHorseIdentityProvider,
    }
    for provider in providers:
        scoped_candidate = {
            **candidate,
            "qualification": [
                row
                for row in qualifications
                if row.get("official_provider") == provider
            ],
        }
        anchor = resolve_official_horse_anchor(
            scoped_candidate,
            request_session=request_session,
        )
        if anchor.get("status") != "anchor_pass":
            return anchor
        source_result = provider_types[provider](request_session).fetch(
            candidate, anchor
        )
        if source_result.get("status") != "source_pass":
            return source_result
        anchors.append(anchor)
        official_results.append(source_result)

    comparison = compare_identity_sources(
        netkeiba=net_identity,
        official=[
            {
                **row["identity"],
                "provider": row["provider"],
                "source_id": row["source_id_raw"],
            }
            for row in official_results
        ],
    )
    if comparison.get("status") != "candidate_pass":
        return comparison
    return {
        **comparison,
        "profile_id": int(candidate["profile_id"]),
        "candidate_key": str(candidate["candidate_key"]),
        "horse_name": str(candidate["horse_name"]),
        "netkeiba_id": str(candidate["netkeiba_id"]),
        "official_providers": providers,
        "qualification": deepcopy(candidate.get("qualification") or []),
        "anchors": anchors,
        "evidence": {
            "netkeiba": netkeiba_result,
            "official": official_results,
        },
        "fetched_at": timezone.now().isoformat(),
    }


def _load_selected_manifest(value: dict[str, Any] | str | Path) -> dict[str, Any]:
    manifest = (
        deepcopy(value)
        if isinstance(value, dict)
        else json.loads(Path(value).read_text(encoding="utf-8"))
    )
    recomputed = _sha256(
        {key: item for key, item in manifest.items() if key != "input_sha256"}
    )
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "selected"
        or manifest.get("parser_version") != PARSER_VERSION
        or manifest.get("config_fingerprint") != _selection_config_fingerprint()
        or manifest.get("input_sha256") != recomputed
    ):
        raise P0HorseIdentityBootstrapError("selected manifest drift or schema mismatch")
    horses = list(manifest.get("horses") or [])
    if not 1 <= len(horses) <= MAX_BATCH_SIZE:
        raise P0HorseIdentityBootstrapError("selected manifest must contain 1-100 horses")
    return manifest


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    content = b"".join(_canonical_bytes(row) + b"\n" for row in rows)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
    return hashlib.sha256(content).hexdigest()


def _write_review_workbook(
    path: Path,
    *,
    candidates: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> str:
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise P0HorseIdentityBootstrapError(
            "openpyxl is required for the identity review workbook"
        ) from exc
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "身份审核"
    headers = [
        "profile_id",
        "horse_name",
        "status",
        "blocker_reason",
        "highest_grade",
        "qualification_count",
        "all_qualifications",
        "official_providers",
        "official_anchors",
        "identity_mode",
        "evidence_grade",
        "netkeiba_raw_identity",
        "official_raw_identity",
        "normalized_identity",
        "sire_text",
        "dam_text",
        "birth_date",
        "netkeiba_url",
        "official_urls",
        "人工决定",
        "审核备注",
    ]
    sheet.append(headers)
    for row in candidates:
        sheet.append(
            [
                row["profile_id"],
                row["horse_name"],
                row["status"],
                "",
                row.get("highest_grade", ""),
                len(row.get("qualification") or []),
                json.dumps(
                    row.get("qualification") or [],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                ",".join(row.get("official_providers") or []),
                json.dumps(
                    row.get("anchors") or [],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                row.get("identity_mode", ""),
                row.get("identity_evidence_grade", ""),
                json.dumps(
                    row.get("evidence", {})
                    .get("netkeiba", {})
                    .get("identity", {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(
                    [
                        item.get("identity") or {}
                        for item in row.get("evidence", {}).get("official", [])
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(
                    row.get("fields") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                row["fields"]["sire_text"],
                row["fields"]["dam_text"],
                row["fields"]["birth_date"],
                (
                    row.get("evidence", {})
                    .get("netkeiba", {})
                    .get("evidence", {})
                    .get("profile", {})
                    .get("source_url", "")
                ),
                "\n".join(
                    str(item.get("url") or "")
                    for item in row.get("evidence", {}).get("official", [])
                ),
                "",
                "",
            ]
        )
    for row in blockers:
        sheet.append(
            [
                row.get("profile_id"),
                row.get("horse_name"),
                "blocker",
                row.get("reason"),
                row.get("highest_grade", ""),
                len(row.get("qualification") or []),
                json.dumps(
                    row.get("qualification") or [],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "",
                json.dumps(
                    row.get("anchors") or [],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
    sheet.freeze_panes = "A2"
    workbook.save(path)
    return _file_sha256(path)


def prepare_identity_bootstrap_batch(
    selected_manifest: dict[str, Any] | str | Path,
    *,
    output_dir: str | Path,
    transport: Any,
    allow_network: bool,
    environment_network_enabled: bool,
    request_interval_seconds: float = 8.0,
) -> dict[str, Any]:
    manifest = _load_selected_manifest(selected_manifest)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    evidence_dir = root / "source_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    request_cache_dir = root / ".request_cache"
    fingerprint = _sha256(
        {
            "input_sha256": manifest["input_sha256"],
            "parser_version": PARSER_VERSION,
            "netkeiba_parser_version": NETKEIBA_PARSER_VERSION,
            "config_fingerprint": manifest["config_fingerprint"],
            "request_interval_seconds": float(request_interval_seconds),
            "total_unique_url_budget": TOTAL_UNIQUE_URL_BUDGET,
            "total_transfer_budget": TOTAL_TRANSFER_BUDGET,
            "official_unique_url_budget": OFFICIAL_UNIQUE_URL_BUDGET,
            "official_transfer_budget": OFFICIAL_TRANSFER_BUDGET,
            "per_url_attempt_budget": PER_URL_ATTEMPT_BUDGET,
        }
    )
    state_path = root / "state.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"fingerprint": fingerprint, "completed": {}}
    )
    if state.get("fingerprint") != fingerprint:
        raise P0HorseIdentityBootstrapError("checkpoint fingerprint drift")

    missing_cache = [
        row
        for row in manifest["horses"]
        if not (evidence_dir / f"{int(row['profile_id'])}.json").exists()
    ]
    if missing_cache and (not allow_network or not environment_network_enabled):
        raise P0HorseIdentityBootstrapError(
            "network gates are required before fetching uncached identity evidence"
        )

    request_session = IdentityRequestSession(
        transport=transport,
        allow_network=allow_network,
        environment_network_enabled=environment_network_enabled,
        cache_dir=request_cache_dir,
        parser_fingerprint=f"{PARSER_VERSION}:{NETKEIBA_PARSER_VERSION}",
        config_fingerprint=fingerprint,
        interval_seconds={
            "jra": request_interval_seconds,
            "nar": request_interval_seconds,
            "netkeiba": request_interval_seconds,
        },
    )
    candidates: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    evidence_entries: list[dict[str, Any]] = []
    qualification_rows: list[dict[str, Any]] = []
    for row in manifest["horses"]:
        profile_id = int(row["profile_id"])
        qualification = deepcopy(row.get("qualification") or [])
        qualification_sha = _sha256(qualification)
        if qualification_sha != row.get("qualification_sha256"):
            raise P0HorseIdentityBootstrapError(
                f"profile {profile_id} qualification SHA drift"
            )
        qualification_rows.append(
            {
                "profile_id": profile_id,
                "candidate_key": row["candidate_key"],
                "highest_grade": row.get("highest_grade"),
                "qualification": qualification,
                "qualification_sha256": qualification_sha,
            }
        )
        cache_path = evidence_dir / f"{profile_id}.json"
        if cache_path.exists():
            current_cache_sha = _file_sha256(cache_path)
            completed_state = (state.get("completed") or {}).get(str(profile_id))
            if (
                completed_state
                and completed_state.get("evidence_sha256") != current_cache_sha
            ):
                raise P0HorseIdentityBootstrapError(
                    f"checkpoint evidence hash drift for profile {profile_id}"
                )
            envelope = json.loads(cache_path.read_text(encoding="utf-8"))
            if envelope.get("fingerprint") != fingerprint:
                raise P0HorseIdentityBootstrapError(
                    f"source evidence fingerprint drift for profile {profile_id}"
                )
            result = envelope["result"]
        else:
            try:
                result = fetch_dual_source_identity(
                    row,
                    request_session=request_session,
                )
            except Exception as exc:  # isolate one candidate without silent omission
                result = _source_blocker(
                    "UNEXPECTED_ERROR",
                    evidence={"error_type": type(exc).__name__},
                )
            envelope = {
                "schema_version": SCHEMA_VERSION,
                "fingerprint": fingerprint,
                "profile_id": profile_id,
                "retrieval": "bounded_request_session",
                "result": result,
            }
            _write_json(cache_path, envelope)
        result = deepcopy(result)
        result.update(
            {
                "profile_id": profile_id,
                "candidate_key": row["candidate_key"],
                "horse_name": row["horse_name"],
                "netkeiba_id": row["netkeiba_id"],
                "highest_grade": row.get("highest_grade"),
                "highest_grade_priority": row.get("highest_grade_priority"),
                "has_official_identity_anchor": row.get(
                    "has_official_identity_anchor"
                ),
                "has_complete_official_context": row.get(
                    "has_complete_official_context"
                ),
                "training_scope_status": row.get("training_scope_status"),
                "training_evidence": deepcopy(row.get("training_evidence") or []),
                "qualification": qualification,
                "qualification_sha256": qualification_sha,
            }
        )
        if result.get("status") == "candidate_pass":
            result["profile_snapshot"] = deepcopy(row.get("profile_snapshot") or {})
            candidates.append(result)
        else:
            blockers.append(result)
        evidence_entries.append(
            {
                "profile_id": profile_id,
                "path": str(cache_path.relative_to(root)),
                "sha256": _file_sha256(cache_path),
                "retrieval": envelope.get("retrieval", "bounded_request_session"),
                "status": result.get("status"),
            }
        )
        state["completed"][str(profile_id)] = {
            "status": result.get("status"),
            "evidence_sha256": evidence_entries[-1]["sha256"],
        }
        _write_json(state_path, state)

    qualification_path = root / "qualification.jsonl"
    candidate_path = root / "candidates.jsonl"
    blocker_path = root / "blockers.jsonl"
    summary_path = root / "summary.json"
    evidence_manifest_path = root / "source_evidence_manifest.json"
    request_ledger_path = root / "request_ledger.json"
    workbook_path = root / "review.xlsx"
    qualification_sha = _write_jsonl(qualification_path, qualification_rows)
    candidate_sha = _write_jsonl(candidate_path, candidates)
    blocker_sha = _write_jsonl(blocker_path, blockers)
    evidence_manifest = {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "entries": evidence_entries,
    }
    evidence_manifest_sha = _write_json(evidence_manifest_path, evidence_manifest)
    previous_ledger = (
        json.loads(request_ledger_path.read_text(encoding="utf-8"))
        if request_ledger_path.exists()
        else {}
    )
    request_ledger = request_session.ledger()
    request_ledger["events"] = [
        *(previous_ledger.get("events") or []),
        *(request_ledger.get("events") or []),
    ]
    request_ledger_sha = _write_json(request_ledger_path, request_ledger)
    by_grade: dict[str, dict[str, int]] = {}
    by_provider: dict[str, dict[str, int]] = {}
    for row in [*candidates, *blockers]:
        status = str(row.get("status") or "unknown")
        grade = str(row.get("highest_grade") or "UNKNOWN")
        grade_counts = by_grade.setdefault(grade, {})
        grade_counts[status] = grade_counts.get(status, 0) + 1
        providers = row.get("official_providers") or ["unresolved"]
        for provider in providers:
            provider_counts = by_provider.setdefault(str(provider), {})
            provider_counts[status] = provider_counts.get(status, 0) + 1
    summary = {
        "total": len(manifest["horses"]),
        "candidate_pass": len(candidates),
        "blockers": len(blockers),
        "unknown_errors": sum(
            row.get("reason") == "UNEXPECTED_ERROR" for row in blockers
        ),
        "accounted": len(candidates) + len(blockers),
        "by_highest_grade": by_grade,
        "by_official_provider": by_provider,
    }
    summary_sha = _write_json(summary_path, summary)
    workbook_input_sha = _sha256({"candidates": candidates, "blockers": blockers})
    workbook_state_path = root / "review.xlsx.input.sha256"
    if (
        workbook_path.exists()
        and workbook_state_path.exists()
        and workbook_state_path.read_text(encoding="ascii").strip()
        == workbook_input_sha
    ):
        workbook_sha = _file_sha256(workbook_path)
    else:
        workbook_sha = _write_review_workbook(
            workbook_path, candidates=candidates, blockers=blockers
        )
        workbook_state_path.write_text(workbook_input_sha + "\n", encoding="ascii")
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "status": "prepared",
        "input_sha256": manifest["input_sha256"],
        "parser_version": PARSER_VERSION,
        "config_fingerprint": manifest["config_fingerprint"],
        "candidates": candidates,
        "blockers": blockers,
        "artifact_paths": {
            "qualification": qualification_path.name,
            "candidates": candidate_path.name,
            "blockers": blocker_path.name,
            "summary": summary_path.name,
            "source_evidence": evidence_manifest_path.name,
            "request_ledger": request_ledger_path.name,
            "workbook": workbook_path.name,
            "state": state_path.name,
        },
        "artifact_hashes": {
            "qualification": qualification_sha,
            "candidates": candidate_sha,
            "blockers": blocker_sha,
            "summary": summary_sha,
            "source_evidence": evidence_manifest_sha,
            "request_ledger": request_ledger_sha,
            "workbook": workbook_sha,
            "state": _file_sha256(state_path),
        },
    }
    artifact_path = root / "artifact.json"
    artifact_sha = _write_json(artifact_path, artifact)
    return {
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha,
        "summary": summary,
        "fingerprint": fingerprint,
    }


def approve_identity_bootstrap_artifact(
    artifact_path: str | Path,
    *,
    reviewer: str,
    approved_profile_ids: Iterable[int],
) -> dict[str, Any]:
    path = Path(artifact_path)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    reviewer_text = str(reviewer or "").strip()
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise P0HorseIdentityBootstrapError("artifact schema mismatch")
    if artifact.get("status") != "prepared":
        raise P0HorseIdentityBootstrapError("artifact is not prepared")
    if artifact.get("config_fingerprint") != _selection_config_fingerprint():
        raise P0HorseIdentityBootstrapError("artifact config fingerprint drift")
    if not reviewer_text:
        raise P0HorseIdentityBootstrapError("reviewer is required")
    artifact_paths = artifact.get("artifact_paths") or {}
    artifact_hashes = artifact.get("artifact_hashes") or {}
    required_artifacts = {
        "qualification",
        "candidates",
        "blockers",
        "summary",
        "source_evidence",
        "request_ledger",
        "workbook",
        "state",
    }
    verified_artifact_paths: dict[str, Path] = {}
    if set(artifact_paths) != required_artifacts or set(artifact_hashes) != required_artifacts:
        raise P0HorseIdentityBootstrapError("review package path/hash set is incomplete")
    for key in sorted(required_artifacts):
        relative = Path(str(artifact_paths[key]))
        if relative.is_absolute() or ".." in relative.parts:
            raise P0HorseIdentityBootstrapError("review package path escapes artifact directory")
        file_path = path.parent / relative
        if not file_path.is_file() or _file_sha256(file_path) != artifact_hashes[key]:
            raise P0HorseIdentityBootstrapError(
                f"review package artifact drift: {key}"
            )
        verified_artifact_paths[key] = file_path
    for key in ("candidates", "blockers"):
        embedded_rows = artifact.get(key) or []
        expected_content = b"".join(
            _canonical_bytes(row) + b"\n" for row in embedded_rows
        )
        if verified_artifact_paths[key].read_bytes() != expected_content:
            raise P0HorseIdentityBootstrapError(
                f"review package embedded {key} drift"
            )
    approved_ids = sorted({int(value) for value in approved_profile_ids})
    candidate_by_id = {
        int(row["profile_id"]): row for row in artifact.get("candidates") or []
    }
    if len(candidate_by_id) != len(artifact.get("candidates") or []):
        raise P0HorseIdentityBootstrapError("duplicate candidate profile IDs")
    if not approved_ids or any(value not in candidate_by_id for value in approved_ids):
        raise P0HorseIdentityBootstrapError("approved set must be a non-empty candidate subset")
    for profile_id in approved_ids:
        candidate = candidate_by_id[profile_id]
        if (
            candidate.get("status") != "candidate_pass"
            or candidate.get("identity_evidence_grade") not in {"A", "A+"}
            or candidate.get("identity_mode")
            not in {
                "NETKEIBA_JRA_CONSENSUS",
                "NETKEIBA_NAR_CONSENSUS",
                "NETKEIBA_JRA_NAR_CONSENSUS",
            }
        ):
            raise P0HorseIdentityBootstrapError(
                "only complete A/A+ candidate_pass rows may be approved"
            )
        qualification = candidate.get("qualification")
        if (
            not isinstance(qualification, list)
            or not qualification
            or candidate.get("qualification_sha256") != _sha256(qualification)
        ):
            raise P0HorseIdentityBootstrapError(
                f"profile {profile_id} qualification evidence is incomplete"
            )
        _validate_candidate_evidence(candidate)
    review_event = {
        "reviewer": reviewer_text,
        "approved_profile_ids": approved_ids,
        "approved_at": timezone.now().isoformat(),
        "prepared_artifact_sha256": _file_sha256(path),
    }
    review_event["event_sha256"] = _sha256(review_event)
    artifact["status"] = "approved"
    artifact["approved_candidates"] = [candidate_by_id[value] for value in approved_ids]
    artifact["approval"] = review_event
    artifact["approved_sha256"] = _sha256(
        {key: value for key, value in artifact.items() if key != "approved_sha256"}
    )
    _write_json(path, artifact)
    return artifact


def _load_approved(path: Path, approved_sha256: str) -> dict[str, Any]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    recomputed = _sha256(
        {key: value for key, value in artifact.items() if key != "approved_sha256"}
    )
    if (
        artifact.get("schema_version") != SCHEMA_VERSION
        or artifact.get("status") != "approved"
        or recomputed != artifact.get("approved_sha256")
        or recomputed != approved_sha256
    ):
        raise P0HorseIdentityBootstrapError("approved artifact SHA or state mismatch")
    if not (artifact.get("approval") or {}).get("reviewer"):
        raise P0HorseIdentityBootstrapError("approved artifact lacks reviewer")
    approval = artifact["approval"]
    event_sha = str(approval.get("event_sha256") or "")
    if not event_sha or event_sha != _sha256(
        {key: value for key, value in approval.items() if key != "event_sha256"}
    ):
        raise P0HorseIdentityBootstrapError("approved review event drift")
    return artifact


def _current_snapshot(profile: HorseProfile) -> dict[str, Any]:
    return {
        "sire_text": str(profile.sire_text or "").strip(),
        "dam_text": str(profile.dam_text or "").strip(),
        "birth_date": profile.birth_date.isoformat() if profile.birth_date else "",
        "manual_lock_flags": deepcopy(profile.manual_lock_flags or {}),
        "source_refs": deepcopy(profile.source_refs or {}),
        "p0_source_ids": list(
            profile.p0_sources.filter(status=HorseP0SourceStatus.ACTIVE)
            .order_by("id")
            .values_list("id", flat=True)
        ),
    }


def _validate_candidate_evidence(candidate: dict[str, Any]) -> None:
    profile_id = int(candidate.get("profile_id") or 0)
    evidence = candidate.get("evidence") or {}
    netkeiba = evidence.get("netkeiba")
    official = evidence.get("official")
    anchors = candidate.get("anchors")
    providers = candidate.get("official_providers")
    qualification = candidate.get("qualification") or []
    if (
        not isinstance(netkeiba, dict)
        or not netkeiba.get("url")
        or not netkeiba.get("content_sha256")
        or not isinstance(official, list)
        or not official
        or not isinstance(anchors, list)
        or len(anchors) != len(official)
        or not isinstance(providers, list)
        or sorted(set(providers)) != sorted(
            {str(row.get("provider") or "") for row in official}
        )
    ):
        raise P0HorseIdentityBootstrapError(
            f"profile {profile_id} dual-source evidence is incomplete"
        )
    anchors_by_provider: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        provider = str(anchor.get("provider") or "")
        url = str(anchor.get("official_horse_url") or "")
        anchor_qualification = anchor.get("qualification")
        if (
            provider not in {"jra", "nar"}
            or provider in anchors_by_provider
            or _official_provider(url) != provider
            or not _is_official_horse_url(provider, url)
            or anchor_qualification not in qualification
            or str(anchor.get("official_source_horse_id") or "")
            != _official_source_horse_id(provider, url)
        ):
            raise P0HorseIdentityBootstrapError(
                f"profile {profile_id} official anchor evidence drift"
            )
        anchors_by_provider[provider] = anchor
    for row in official:
        provider = str(row.get("provider") or "")
        anchor = anchors_by_provider.get(provider)
        if (
            not isinstance(row, dict)
            or anchor is None
            or row.get("status") not in {None, "source_pass"}
            or str(row.get("url") or "")
            != str(anchor.get("official_horse_url") or "")
            or not row.get("content_sha256")
            or str(row.get("source_id_raw") or row.get("source_id") or "")
            != str(anchor.get("official_source_horse_id") or "")
        ):
            raise P0HorseIdentityBootstrapError(
                f"profile {profile_id} official source evidence drift"
            )
    netkeiba_identity = netkeiba.get("identity")
    official_identities = [
        {
            **(row.get("identity") or {}),
            "provider": str(row.get("provider") or ""),
        }
        for row in official
    ]
    if not isinstance(netkeiba_identity, dict) or any(
        not isinstance(row.get("identity"), dict) for row in official
    ):
        raise P0HorseIdentityBootstrapError(
            f"profile {profile_id} consensus evidence is incomplete"
        )
    recomputed = compare_identity_sources(
        netkeiba=netkeiba_identity,
        official=official_identities,
    )
    frozen_consensus = {
        key: candidate.get(key)
        for key in (
            "status",
            "identity_mode",
            "identity_evidence_grade",
            "fields",
        )
    }
    recomputed_consensus = {
        key: recomputed.get(key)
        for key in (
            "status",
            "identity_mode",
            "identity_evidence_grade",
            "fields",
        )
    }
    if (
        recomputed.get("status") != "candidate_pass"
        or frozen_consensus != recomputed_consensus
    ):
        raise P0HorseIdentityBootstrapError(
            f"profile {profile_id} consensus evidence drift"
        )


def _validate_candidate_snapshot(
    profile: HorseProfile,
    candidate: dict[str, Any],
) -> None:
    _validate_candidate_evidence(candidate)
    if _current_snapshot(profile) != candidate.get("profile_snapshot"):
        raise P0HorseIdentityBootstrapError(
            f"profile {profile.pk} drifted after review"
        )
    sources = list(
        HorseP0Source.objects.filter(
            profile=profile,
            status=HorseP0SourceStatus.ACTIVE,
        )
        .select_related("race_event", "race_runner", "race_result")
        .order_by("id")
    )
    current = _build_selection_row(profile, sources)
    frozen_fields = (
        "netkeiba_id",
        "qualification",
        "qualification_sha256",
        "highest_grade",
        "highest_grade_priority",
        "has_official_identity_anchor",
        "has_complete_official_context",
        "training_scope_status",
        "training_evidence",
    )
    if current is None or any(
        current.get(field) != candidate.get(field) for field in frozen_fields
    ):
        raise P0HorseIdentityBootstrapError(
            f"profile {profile.pk} qualification or identity evidence drift"
        )


def _expected_evidence_summary(
    candidates: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    return {
        str(row["profile_id"]): {
            "netkeiba": row["evidence"]["netkeiba"].get("content_sha256"),
            "official": [
                {
                    "provider": item.get("provider"),
                    "content_sha256": item.get("content_sha256"),
                }
                for item in row["evidence"]["official"]
            ],
            "qualification_sha256": row["qualification_sha256"],
        }
        for row in candidates
    }


def _validate_replay(
    receipt: HorseIdentityEvidenceCommitReceipt,
    artifact: dict[str, Any],
    *,
    artifact_path: Path,
) -> dict[str, Any]:
    approved_ids = [int(row["profile_id"]) for row in artifact["approved_candidates"]]
    if approved_ids != [int(value) for value in receipt.approved_profile_ids]:
        raise P0HorseIdentityBootstrapError("receipt approved set drift")
    profiles = {
        profile.pk: profile
        for profile in HorseProfile.objects.filter(pk__in=approved_ids)
    }
    after_by_profile = receipt.before_after.get("after_by_profile") or {}
    for profile_id in approved_ids:
        profile = profiles.get(profile_id)
        expected = after_by_profile.get(str(profile_id))
        if profile is None or expected is None:
            raise P0HorseIdentityBootstrapError("receipt replay target missing")
        current = {
            "sire_text": str(profile.sire_text or "").strip(),
            "dam_text": str(profile.dam_text or "").strip(),
            "birth_date": profile.birth_date.isoformat() if profile.birth_date else "",
            "source_refs": deepcopy(profile.source_refs or {}),
        }
        if current != expected:
            raise P0HorseIdentityBootstrapError("receipt replay state drift")
    if receipt.artifact_sha256 != _file_sha256(artifact_path):
        raise P0HorseIdentityBootstrapError("receipt artifact SHA drift")
    if receipt.evidence_summary != _expected_evidence_summary(
        artifact["approved_candidates"]
    ):
        raise P0HorseIdentityBootstrapError("receipt evidence summary drift")
    result = deepcopy(receipt.result_payload)
    expected_result = {
        "approved_sha256": receipt.approved_sha256,
        "approved_profile_ids": approved_ids,
        "profiles_written": len(approved_ids),
        "replay": False,
    }
    if result != expected_result:
        raise P0HorseIdentityBootstrapError("receipt result payload drift")
    operation = receipt.operation_log
    if (
        operation is None
        or operation.action_type != "p0_horse_identity_evidence_commit"
        or operation.target_type != "approved_sha256"
        or operation.target_id != receipt.approved_sha256
        or operation.detail
        != json.dumps(result, ensure_ascii=False, sort_keys=True)
    ):
        raise P0HorseIdentityBootstrapError("receipt operation log drift")
    result.update({"profiles_written": 0, "replay": True})
    return result


def commit_identity_bootstrap_artifact(
    artifact_path: str | Path,
    *,
    approved_sha256: str,
    approved_by: str,
) -> dict[str, Any]:
    path = Path(artifact_path)
    artifact = _load_approved(path, approved_sha256)
    operator = str(approved_by or "").strip()
    if not operator:
        raise P0HorseIdentityBootstrapError("approved_by is required")
    if operator == str((artifact.get("approval") or {}).get("reviewer") or "").strip():
        raise P0HorseIdentityBootstrapError("committer must be independent from reviewer")
    existing = HorseIdentityEvidenceCommitReceipt.objects.filter(
        approved_sha256=approved_sha256
    ).select_related("operation_log").first()
    if existing is not None:
        return _validate_replay(existing, artifact, artifact_path=path)

    candidates = sorted(
        artifact["approved_candidates"], key=lambda row: int(row["profile_id"])
    )
    approved_ids = [int(row["profile_id"]) for row in candidates]
    try:
        with transaction.atomic():
            profiles = list(
                HorseProfile.objects.select_for_update()
                .filter(pk__in=approved_ids)
                .order_by("pk")
            )
            concurrent_receipt = HorseIdentityEvidenceCommitReceipt.objects.filter(
                approved_sha256=approved_sha256
            ).select_related("operation_log").first()
            if concurrent_receipt is not None:
                return _validate_replay(
                    concurrent_receipt, artifact, artifact_path=path
                )
            if [profile.pk for profile in profiles] != approved_ids:
                raise P0HorseIdentityBootstrapError("approved profile set drift")
            by_id = {int(row["profile_id"]): row for row in candidates}
            before_by_profile: dict[str, Any] = {}
            after_by_profile: dict[str, Any] = {}
            for profile in profiles:
                candidate = by_id[profile.pk]
                snapshot = _current_snapshot(profile)
                _validate_candidate_snapshot(profile, candidate)
                locks = snapshot["manual_lock_flags"]
                if any(locks.get(field) for field in ("sire_text", "dam_text", "birth_date")):
                    raise P0HorseIdentityBootstrapError(
                        f"profile {profile.pk} has a locked identity field"
                    )
                if snapshot["sire_text"] or snapshot["dam_text"] or snapshot["birth_date"]:
                    raise P0HorseIdentityBootstrapError(
                        f"profile {profile.pk} identity fields are not empty"
                    )
                fields = candidate["fields"]
                if not all(fields.get(field) for field in ("sire_text", "dam_text", "birth_date")):
                    raise P0HorseIdentityBootstrapError(
                        f"profile {profile.pk} candidate fields are incomplete"
                    )
                before_by_profile[str(profile.pk)] = snapshot
                refs = deepcopy(profile.source_refs or {})
                key = f"netkeiba:{candidate['netkeiba_id']}".casefold()
                verified = [str(value).casefold() for value in refs.get("horse_identity_verified_keys") or []]
                if key not in verified:
                    refs.setdefault("horse_identity_verified_keys", []).append(key)
                evidence_rows = list(refs.get("identity_evidence") or [])
                official_evidence = deepcopy(
                    (candidate.get("evidence") or {}).get("official") or []
                )
                if not official_evidence:
                    raise P0HorseIdentityBootstrapError(
                        f"profile {profile.pk} official evidence is missing"
                    )
                evidence_rows.append(
                    {
                        "kind": str(candidate["identity_mode"]).casefold(),
                        "identity_evidence_grade": candidate[
                            "identity_evidence_grade"
                        ],
                        "approved_sha256": approved_sha256,
                        "reviewer": artifact["approval"]["reviewer"],
                        "approved_by": operator,
                        "netkeiba": candidate["evidence"]["netkeiba"],
                        "official": official_evidence,
                        "qualification_sha256": candidate[
                            "qualification_sha256"
                        ],
                    }
                )
                refs["identity_evidence"] = evidence_rows
                profile.sire_text = fields["sire_text"]
                profile.dam_text = fields["dam_text"]
                profile.birth_date = date.fromisoformat(fields["birth_date"])
                profile.source_refs = refs
                profile.save(
                    update_fields=[
                        "sire_text",
                        "dam_text",
                        "birth_date",
                        "source_refs",
                        "updated_at",
                    ]
                )
                after_by_profile[str(profile.pk)] = {
                    "sire_text": profile.sire_text,
                    "dam_text": profile.dam_text,
                    "birth_date": profile.birth_date.isoformat(),
                    "source_refs": deepcopy(profile.source_refs),
                }
            result = {
                "approved_sha256": approved_sha256,
                "approved_profile_ids": approved_ids,
                "profiles_written": len(profiles),
                "replay": False,
            }
            operation = OperationLog.objects.create(
                action_type="p0_horse_identity_evidence_commit",
                target_type="approved_sha256",
                target_id=approved_sha256,
                detail=json.dumps(result, ensure_ascii=False, sort_keys=True),
            )
            HorseIdentityEvidenceCommitReceipt.objects.create(
                approved_sha256=approved_sha256,
                artifact_sha256=_file_sha256(path),
                approved_by=operator,
                approved_profile_ids=approved_ids,
                before_after={
                    "before_by_profile": before_by_profile,
                    "after_by_profile": after_by_profile,
                },
                evidence_summary=_expected_evidence_summary(candidates),
                result_payload=result,
                operation_log=operation,
            )
            return result
    except IntegrityError:
        receipt = HorseIdentityEvidenceCommitReceipt.objects.filter(
            approved_sha256=approved_sha256
        ).select_related("operation_log").first()
        if receipt is None:
            raise
        return _validate_replay(receipt, artifact, artifact_path=path)


def verify_identity_bootstrap_commit(
    artifact_path: str | Path,
    *,
    approved_sha256: str,
) -> dict[str, Any]:
    artifact = _load_approved(Path(artifact_path), approved_sha256)
    receipt = HorseIdentityEvidenceCommitReceipt.objects.filter(
        approved_sha256=approved_sha256
    ).select_related("operation_log").first()
    if receipt is None:
        raise P0HorseIdentityBootstrapError("commit receipt not found")
    result = _validate_replay(receipt, artifact, artifact_path=Path(artifact_path))
    result["verified"] = True
    return result
