from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Callable
import unicodedata
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from stable import models
from stable.services.race_events import (
    calculate_race_live_next_poll_at,
    record_race_live_host_outcome,
    reserve_race_live_host_request,
)
from stable.services.race_live_fixtures import (
    parse_the_racing_api_live_racecards_payload,
)
from stable.services.race_live_source_proof import (
    RaceLiveProofHttpResponse,
    _read_secret,
    read_the_racing_api_automation_registry,
)


_HOST = "api.theracingapi.com"
_MIN_INTERVAL_MS = 1050
_MAX_WAIT_SECONDS = 2.0
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SAFE_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_SYNC_ENDPOINTS = (
    (
        "racecards_sync_today",
        "/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
    ),
    (
        "racecards_sync_tomorrow",
        "/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
    ),
)


@dataclass(frozen=True)
class RaceLiveRacecardPrepareResult:
    completed: bool
    request_count: int
    output_dir: Path
    blocker_codes: tuple[str, ...]


def normalize_identity_text(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("identity text must be a non-empty trimmed string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        char if char.isalnum() else " " for char in normalized
    )
    result = " ".join(normalized.split())
    if not result:
        raise ValueError("identity text normalizes to empty")
    return result


def _contains_han_text(value: str) -> bool:
    return any(
        "\u3400" <= char <= "\u4dbf"
        or "\u4e00" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in value
    )


def _validate_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _validate_aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValueError(f"{label} must be an aware datetime")
    return value


def _validate_root(root_value: str | os.PathLike[str]) -> Path:
    root = Path(root_value)
    if not root.is_absolute():
        raise ValueError("artifact root must be absolute")
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise ValueError("artifact root must already exist") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise PermissionError("artifact root must be a real directory")
    if stat.S_IMODE(root_stat.st_mode) & 0o077:
        raise PermissionError("artifact root must not grant group/other access")
    current = root.parent
    while current != current.parent:
        current_stat = current.lstat()
        if stat.S_ISLNK(current_stat.st_mode):
            macos_var_alias = (
                current == Path("/var")
                and current.resolve(strict=True) == Path("/private/var")
            )
            if not macos_var_alias:
                raise PermissionError(
                    "artifact root ancestors cannot be symlinks"
                )
        current = current.parent
    return root


def _validate_run_id(run_id: str) -> str:
    if (
        not isinstance(run_id, str)
        or _SAFE_RUN_ID_RE.fullmatch(run_id) is None
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
    ):
        raise ValueError("run-id must be a safe basename")
    return run_id


def _bootstrap_host_budget() -> None:
    with transaction.atomic():
        budget, _ = models.RaceLiveHostBudget.objects.select_for_update().get_or_create(
            host=_HOST,
            defaults={"min_interval_ms": _MIN_INTERVAL_MS},
        )
        if budget.min_interval_ms != _MIN_INTERVAL_MS:
            raise PermissionError("host budget configuration mismatch")


def _reserve_with_bounded_wait(
    *,
    clock: Callable[[], datetime],
    sleep: Callable[[float], Any],
) -> tuple[int | None, str]:
    current = _validate_aware(clock(), "clock")
    decision = reserve_race_live_host_request(host=_HOST, now=current)
    if decision.reserved:
        return decision.reservation_version, ""
    if decision.reason not in {"rate_limited", "circuit_open"}:
        return None, f"host_budget_{decision.reason}"
    if decision.next_allowed_at is None:
        return None, f"host_budget_{decision.reason}"
    wait_seconds = (decision.next_allowed_at - current).total_seconds()
    if wait_seconds <= 0 or wait_seconds > _MAX_WAIT_SECONDS:
        return None, "host_budget_wait_exceeded"
    sleep(wait_seconds)
    retry_now = max(
        _validate_aware(clock(), "clock"),
        decision.next_allowed_at,
    )
    retry = reserve_race_live_host_request(host=_HOST, now=retry_now)
    if not retry.reserved:
        return None, (
            "host_budget_wait_exceeded"
            if retry.reason in {"rate_limited", "circuit_open"}
            else f"host_budget_{retry.reason}"
        )
    return retry.reservation_version, ""


def _validate_response(
    response: RaceLiveProofHttpResponse,
) -> tuple[Any | None, str]:
    if response.redirect_url is not None or (
        isinstance(response.status_code, int)
        and 300 <= response.status_code < 400
    ):
        return None, "redirect_rejected"
    if response.status_code != 200:
        return None, f"http_{response.status_code}"
    if not isinstance(response.body, bytes) or len(response.body) > _MAX_RESPONSE_BYTES:
        return None, "response_too_large"
    if (
        not isinstance(response.content_type, str)
        or response.content_type.split(";", 1)[0].strip().lower()
        not in {"application/json", "application/problem+json"}
    ):
        return None, "non_json_content_type"
    try:
        def strict_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate JSON key")
                value[key] = item
            return value

        payload = json.loads(
            response.body,
            object_pairs_hook=strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid JSON constant: {value}")
            ),
        )
        return parse_the_racing_api_live_racecards_payload(payload), ""
    except (
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        return None, "racecard_schema_invalid"


def _occupied_event_ids(event_ids: list[int]) -> set[int]:
    occupied: set[int] = set()
    for model in (
        models.RaceEventProjectionControl,
        models.RaceEventLiveTracking,
        models.RaceResultSourceIdentity,
        models.RaceLiveEventPublicationAllowlist,
        models.RaceEventParticipant,
        models.RaceEventRevision,
        models.RaceEventResult,
    ):
        occupied.update(
            model.objects.filter(event_id__in=event_ids).values_list(
                "event_id",
                flat=True,
            )
        )
    occupied.update(
        models.RaceResultObservation.objects.filter(
            source_identity__event_id__in=event_ids
        ).values_list("source_identity__event_id", flat=True)
    )
    return occupied


def _event_names(event: models.RaceEvent) -> set[str]:
    names = {normalize_identity_text(event.original_name)}
    chinese_languages = {
        models.SourceLanguage.CHINESE,
        models.SourceLanguage.CHINESE_TRADITIONAL,
    }
    for alias in event.aliases.filter(is_active=True).exclude(
        source_language__in=chinese_languages
    ).only("text"):
        if not _contains_han_text(alias.text):
            names.add(normalize_identity_text(alias.text))
    if event.race_series_id:
        series = event.race_series
        names.add(normalize_identity_text(series.canonical_name_original))
        valid_names = series.names.filter(is_active=True).exclude(
            source_language__in=chinese_languages
        ).filter(
            Q(valid_from_year=0) | Q(valid_from_year__lte=event.year),
            Q(valid_to_year=0) | Q(valid_to_year__gte=event.year),
        )
        for series_name in valid_names.only("text"):
            if not _contains_han_text(series_name.text):
                names.add(normalize_identity_text(series_name.text))
    major = event.major_race_event
    if major is not None and major.is_active and major.year == event.year:
        for value in (major.name, major.normalized_name):
            if value and not _contains_han_text(value):
                names.add(normalize_identity_text(value))
        if isinstance(major.aliases, list):
            for alias in major.aliases:
                if (
                    isinstance(alias, str)
                    and alias.strip() == alias
                    and alias
                    and not _contains_han_text(alias)
                ):
                    names.add(normalize_identity_text(alias))
    return names


def _load_target_events(
    event_ids: list[int],
    *,
    generated_at: datetime,
) -> tuple[list[models.RaceEvent], list[str]]:
    if (
        not isinstance(event_ids, list)
        or not event_ids
        or len(event_ids) > 500
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in event_ids
        )
        or len(set(event_ids)) != len(event_ids)
    ):
        raise ValueError("event_ids must be unique positive integers")
    events = list(
        models.RaceEvent.objects.filter(pk__in=event_ids)
        .select_related("race_series", "major_race_event")
        .prefetch_related("aliases", "race_series__names")
    )
    by_id = {event.pk: event for event in events}
    occupied_event_ids = _occupied_event_ids(event_ids)
    blockers: list[str] = []
    london_today = generated_at.astimezone(
        ZoneInfo("Europe/London")
    ).date()
    for event_id in event_ids:
        event = by_id.get(event_id)
        if event is None:
            blockers.append("event_not_found")
            continue
        locks = event.manual_lock_flags
        invalid = (
            event.country_region != models.RacingRegion.UNITED_KINGDOM
            or event.status != models.RaceEventStatus.SCHEDULED
            or event.local_date is None
            or event.local_date < london_today
            or event.local_date > london_today + timedelta(days=1)
            or event.timezone_name != "Europe/London"
            or not isinstance(locks, dict)
            or locks.get(models.RaceEventModule.RUNNERS)
            or locks.get(models.RaceEventModule.RESULTS)
            or event.pk in occupied_event_ids
        )
        if invalid:
            blockers.append("event_baseline_rejected")
    return [by_id[event_id] for event_id in event_ids if event_id in by_id], blockers


def _match_events(
    *,
    events: list[models.RaceEvent],
    candidate_rows: list[tuple[dict[str, Any], str]],
    generated_at: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    london = ZoneInfo("Europe/London")
    manifest_events: list[dict[str, Any]] = []
    blockers: list[str] = []
    used_external_ids: set[str] = set()
    for event in events:
        approved_names = _event_names(event)
        normalized_course = normalize_identity_text(event.racecourse)
        matches: list[tuple[dict[str, Any], str, datetime]] = []
        for race, response_sha in candidate_rows:
            try:
                off_time = datetime.fromisoformat(
                    race["off_time"].replace("Z", "+00:00")
                )
                local = off_time.astimezone(london)
                matching = (
                    race["region"].upper() == "GB"
                    and local.date() == event.local_date
                    and normalize_identity_text(race["course"]) == normalized_course
                    and normalize_identity_text(race["race_name"]) in approved_names
                )
            except (KeyError, TypeError, ValueError):
                matching = False
            if matching:
                matches.append((race, response_sha, off_time))
        if not matches:
            blockers.append("racecard_not_found")
            continue
        if len(matches) != 1:
            blockers.append("racecard_ambiguous")
            continue
        race, response_sha, off_time = matches[0]
        external_race_id = race["external_race_id"]
        if external_race_id in used_external_ids:
            blockers.append("external_race_reused")
            continue
        used_external_ids.add(external_race_id)
        local = off_time.astimezone(london)
        if (
            event.race_datetime is not None
            and event.race_datetime != off_time
        ) or (
            event.local_start_time is not None
            and event.local_start_time
            != local.time().replace(tzinfo=None)
        ):
            blockers.append("event_time_conflict")
            continue
        tracking_state = (
            models.RaceEventLiveState.RACECARD_READY
            if generated_at < off_time
            else models.RaceEventLiveState.AWAITING_RESULT
        )
        next_poll_at = (
            calculate_race_live_next_poll_at(
                off_time=off_time,
                now=generated_at,
                state=tracking_state,
            )
            if generated_at < off_time
            else generated_at
        )
        participants = []
        for runner in race["participants"]:
            runner_id = runner["external_runner_id"]
            participants.append(
                {
                    "stable_key": "tra:"
                    + hashlib.sha256(runner_id.encode("utf-8")).hexdigest(),
                    "canonical_name": runner["horse_name"],
                    "country_region": "",
                    "external_runner_id": runner_id,
                    "horse_number": runner["number"],
                    "status": models.RaceEventRevisionItemStatus.DECLARED,
                    "barrier": runner["draw"],
                    "jockey_name": runner["jockey_name"],
                    "jockey_id": runner["jockey_id"],
                }
            )
        manifest_events.append(
            {
                "event_id": event.pk,
                "expected_event_updated_at": event.updated_at.isoformat(),
                "year": event.year,
                "slug": event.slug,
                "original_name": event.original_name,
                "country_region": event.country_region,
                "racecourse": event.racecourse,
                "grade_text": event.grade_text,
                "race_datetime": race["off_time"],
                "external_race_id": external_race_id,
                "tracking_state": tracking_state,
                "next_poll_at": next_poll_at.isoformat(),
                "expected_race_datetime_before": (
                    event.race_datetime.isoformat()
                    if event.race_datetime is not None
                    else None
                ),
                "expected_local_start_time_before": (
                    event.local_start_time.isoformat()
                    if event.local_start_time is not None
                    else None
                ),
                "expected_status": models.RaceEventStatus.SCHEDULED,
                "expected_local_date": event.local_date.isoformat(),
                "expected_timezone_name": "Europe/London",
                "local_date": local.date().isoformat(),
                "source_off_dt": race["off_time"],
                "source_response_sha256": response_sha,
                "participants": participants,
            }
        )
    return manifest_events, blockers


def _encode_json(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_file(path: Path, payload: bytes) -> None:
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise ValueError("artifact file exceeds the 2 MiB limit")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_artifact(
    *,
    root: Path,
    run_id: str,
    requests: list[dict[str, Any]],
    report: dict[str, Any],
    manifest_base: dict[str, Any] | None,
) -> Path:
    final = root / run_id
    lock_path = root / ".artifact-publish.lock"
    lock_descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT,
        0o600,
    )
    try:
        try:
            fcntl.flock(
                lock_descriptor,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as exc:
            raise FileExistsError(
                "run-id publication is already in progress"
            ) from exc
        if final.exists():
            raise FileExistsError("run-id already exists")
        temporary = root / f".{run_id}.{os.getpid()}.tmp"
        os.mkdir(temporary, 0o700)
        temporary_stat = temporary.lstat()
        published_identity: tuple[int, int] | None = None
        try:
            requests_bytes = b"".join(_encode_json(row) for row in requests)
            report_bytes = _encode_json(report)
            _write_file(temporary / "requests.jsonl", requests_bytes)
            _write_file(temporary / "report.json", report_bytes)
            if manifest_base is not None:
                manifest = {
                    **manifest_base,
                    "requests_sha256": hashlib.sha256(requests_bytes).hexdigest(),
                    "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
                }
                _write_file(temporary / "manifest.json", _encode_json(manifest))
            directory_fd = os.open(temporary, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            temporary.rename(final)
            published_identity = (
                temporary_stat.st_dev,
                temporary_stat.st_ino,
            )
            root_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
        except Exception:
            if published_identity is not None:
                try:
                    final_stat = final.lstat()
                except OSError:
                    final_stat = None
                if (
                    final_stat is not None
                    and stat.S_ISDIR(final_stat.st_mode)
                    and (final_stat.st_dev, final_stat.st_ino)
                    == published_identity
                ):
                    shutil.rmtree(final, ignore_errors=True)
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    finally:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(lock_descriptor)
    return final


def prepare_race_live_racecards(
    *,
    event_ids: list[int],
    run_id: str,
    artifact_root: str | os.PathLike[str],
    secret_env_file: str | os.PathLike[str],
    registry_file: str | os.PathLike[str],
    expected_registry_sha256: str,
    approved_commit: str,
    coverage_proof_digest: str,
    terms_evidence_sha256: str,
    policy_valid_until: datetime,
    official_verification_route: str,
    official_verification_route_version: str,
    official_verification_evidence_sha256: str,
    official_verification_valid_until: datetime,
    now: datetime,
    transport: Callable[..., RaceLiveProofHttpResponse],
    sleep: Callable[[float], Any],
    clock: Callable[[], datetime],
    confirm_real_network: bool,
) -> RaceLiveRacecardPrepareResult:
    if confirm_real_network is not True:
        raise PermissionError("real network confirmation is required")
    generated_at = _validate_aware(now, "now")
    root = _validate_root(artifact_root)
    safe_run_id = _validate_run_id(run_id)
    if not isinstance(approved_commit, str) or _COMMIT_RE.fullmatch(
        approved_commit
    ) is None:
        raise ValueError("approved_commit must be a lowercase commit OID")
    for value, label in (
        (coverage_proof_digest, "coverage_proof_digest"),
        (terms_evidence_sha256, "terms_evidence_sha256"),
        (
            official_verification_evidence_sha256,
            "official_verification_evidence_sha256",
        ),
    ):
        _validate_digest(value, label)
    policy_valid_until = _validate_aware(
        policy_valid_until, "policy_valid_until"
    )
    official_verification_valid_until = _validate_aware(
        official_verification_valid_until,
        "official_verification_valid_until",
    )
    if (
        policy_valid_until <= generated_at
        or official_verification_valid_until <= generated_at
    ):
        raise PermissionError("policy/official route evidence has expired")
    if (
        not isinstance(official_verification_route, str)
        or not official_verification_route
        or official_verification_route != official_verification_route.strip()
        or len(official_verification_route) > 255
        or not isinstance(official_verification_route_version, str)
        or not official_verification_route_version
        or official_verification_route_version
        != official_verification_route_version.strip()
        or len(official_verification_route_version) > 64
    ):
        raise ValueError("official verification route is invalid")
    registry, registry_digest = read_the_racing_api_automation_registry(
        registry_file=registry_file,
        expected_registry_sha256=expected_registry_sha256,
        now=generated_at,
    )
    registry_valid_until = datetime.fromisoformat(registry["valid_until"])
    if policy_valid_until > registry_valid_until:
        raise PermissionError("policy outlives source registry")
    endpoints_by_name = {
        endpoint["name"]: endpoint["path"] for endpoint in registry["endpoints"]
    }
    if any(endpoints_by_name.get(name) != path for name, path in _SYNC_ENDPOINTS):
        raise PermissionError("sync routes do not match the registry")
    username, password = _read_secret(secret_env_file)
    events, baseline_blockers = _load_target_events(
        event_ids,
        generated_at=generated_at,
    )

    request_rows: list[dict[str, Any]] = []
    candidates: list[tuple[dict[str, Any], str]] = []
    blockers = list(baseline_blockers)
    if not blockers:
        _bootstrap_host_budget()
        for request_number, (endpoint_name, endpoint_path) in enumerate(
            _SYNC_ENDPOINTS,
            start=1,
        ):
            reservation_version, reservation_blocker = _reserve_with_bounded_wait(
                clock=clock,
                sleep=sleep,
            )
            if reservation_blocker:
                blockers.append(reservation_blocker)
                break
            row: dict[str, Any] = {
                "endpoint_name": endpoint_name,
                "request_number": request_number,
                "request_path": endpoint_path,
            }
            response = None
            failure = ""
            try:
                response = transport(
                    endpoint_name=endpoint_name,
                    url=f"https://{_HOST}{endpoint_path}",
                    username=username,
                    password=password,
                    timeout_seconds=15,
                    max_response_bytes=_MAX_RESPONSE_BYTES,
                    allow_redirects=False,
                )
                snapshot, failure = _validate_response(response)
            except Exception:
                response = None
                snapshot = None
                failure = "transport_error"
            outcome_now = _validate_aware(clock(), "clock")
            outcome = record_race_live_host_outcome(
                host=_HOST,
                now=outcome_now,
                success=not failure,
                error_code=failure,
                circuit_threshold=3,
                circuit_seconds=300,
                expected_reservation_version=reservation_version or 0,
            )
            if not outcome.recorded:
                failure = f"host_outcome_{outcome.reason}"
            if response is not None:
                row.update(
                    {
                        "status": response.status_code,
                        "elapsed_ms": response.elapsed_ms,
                        "bytes": len(response.body),
                        "content_type": response.content_type,
                        "response_sha256": hashlib.sha256(response.body).hexdigest(),
                    }
                )
            else:
                row["status"] = "transport_error"
            if failure:
                row["error"] = failure
            request_rows.append(row)
            if failure:
                blockers.append(failure)
                break
            assert snapshot is not None
            candidates.extend(
                (race, snapshot.payload_sha256) for race in snapshot.races
            )

    manifest_events: list[dict[str, Any]] = []
    if not blockers:
        manifest_events, match_blockers = _match_events(
            events=events,
            candidate_rows=candidates,
            generated_at=generated_at,
        )
        blockers.extend(match_blockers)
    blocker_codes = tuple(sorted(set(blockers)))
    report = {
        "schema_version": 1,
        "source_key": "the_racing_api",
        "generated_at": generated_at.isoformat(),
        "requested_event_count": len(event_ids),
        "matched_event_count": len(manifest_events),
        "request_count": len(request_rows),
        "key_event_count": sum(event.is_key_race for event in events),
        "ordinary_event_count": sum(not event.is_key_race for event in events),
        "blockers": list(blocker_codes),
    }
    manifest_base = None
    if not blocker_codes and len(manifest_events) == len(event_ids):
        manifest_base = {
            "schema_version": 2,
            "approved_commit": approved_commit,
            "generated_at": generated_at.isoformat(),
            "registry_digest": registry_digest,
            "registry_valid_until": registry_valid_until.isoformat(),
            "coverage_proof_digest": coverage_proof_digest,
            "terms_evidence_sha256": terms_evidence_sha256,
            "source_key": "the_racing_api",
            "host": _HOST,
            "policy_valid_until": policy_valid_until.isoformat(),
            "official_verification_route": official_verification_route,
            "official_verification_route_version": (
                official_verification_route_version
            ),
            "official_verification_evidence_sha256": (
                official_verification_evidence_sha256
            ),
            "official_verification_valid_until": (
                official_verification_valid_until.isoformat()
            ),
            "events": manifest_events,
        }
    output_dir = _write_artifact(
        root=root,
        run_id=safe_run_id,
        requests=request_rows,
        report=report,
        manifest_base=manifest_base,
    )
    return RaceLiveRacecardPrepareResult(
        completed=manifest_base is not None,
        request_count=len(request_rows),
        output_dir=output_dir,
        blocker_codes=blocker_codes,
    )
