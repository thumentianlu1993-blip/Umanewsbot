from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.utils import timezone

from stable.models import (
    RaceEventLiveTracking,
    RaceEventProjectionControl,
    RaceEventProjectionWriteOwner,
    RaceResultSourceIdentity,
)
from stable.services.race_events import (
    admit_race_live_publication,
    apply_race_result_observation_revision,
    calculate_race_live_next_poll_at,
    complete_race_event_live_checkpoint,
    record_race_result_observation,
    record_race_live_host_outcome,
    reserve_race_live_host_request,
    resolve_race_source_network_permission,
)
from stable.services.race_live_fixtures import (
    parse_the_racing_api_live_results_payload,
    parse_the_racing_api_offline_fixture,
)
from stable.services.race_live_source_proof import (
    _read_secret,
    read_the_racing_api_automation_registry,
)


_SOURCE_KEY = "the_racing_api"
_HOST = "api.theracingapi.com"
_RESULTS_URL = (
    "https://api.theracingapi.com/v1/results/today/free?limit=50&skip=0"
)
_SAFE_EXTERNAL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_FIXTURE_BYTES = 2 * 1024 * 1024


def _checkpoint_result(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now,
    success: bool,
    next_poll_at,
    checkpoint_payload: dict[str, Any],
    observation_sha256: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    checkpoint = complete_race_event_live_checkpoint(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        success=success,
        next_poll_at=next_poll_at,
        checkpoint_payload=checkpoint_payload,
        observation_sha256=observation_sha256,
    )
    if not checkpoint.applied:
        return {
            "processed": False,
            "reason": f"checkpoint_{checkpoint.reason}",
            "event_id": event_id,
        }
    return result


def _failure(
    *,
    reason: str,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now,
) -> dict[str, Any]:
    return _checkpoint_result(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        success=False,
        next_poll_at=now + timedelta(minutes=5),
        checkpoint_payload={"status": "failed", "reason": reason},
        observation_sha256="",
        result={"processed": False, "reason": reason, "event_id": event_id},
    )


def _safe_fixture_path(fixture_root: str, external_race_id: str) -> Path | None:
    if (
        not isinstance(fixture_root, str)
        or not fixture_root
        or not isinstance(external_race_id, str)
        or external_race_id in {".", ".."}
        or _SAFE_EXTERNAL_ID_RE.fullmatch(external_race_id) is None
        or Path(external_race_id).name != external_race_id
    ):
        return None
    configured_root = Path(fixture_root)
    if not configured_root.is_absolute():
        return None
    root = configured_root.resolve(strict=False)
    candidate = (root / _SOURCE_KEY / f"{external_race_id}.json").resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _normalized_result_payload(race: dict[str, Any]) -> dict[str, Any]:
    participants = []
    for participant in race["participants"]:
        status = participant["status"]
        participants.append(
            {
                "external_runner_id": participant["external_runner_id"],
                "status": status,
                "official_finish_position": participant["official_finish_position"],
                "raw_status": str(participant["position_raw"]),
                "finish_time": "",
                "margin": "",
                "number": participant["number"],
                "barrier": "",
                "jockey_name": "",
                "trainer_name": "",
                "carried_weight": "",
                "field_provenance": {"result": _SOURCE_KEY},
            }
        )
    return {
        "external_race_id": race["external_race_id"],
        "off_time": race["off_time"],
        "region": race["region"],
        "course": race["course"],
        "race_name": race["race_name"],
        "race_status": race["race_status"],
        "participants": participants,
    }


def run_race_live_offline_fixture(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    fixture_root: str,
    configured_mode: str,
) -> dict[str, Any]:
    """Run one claimed event from a bounded local fixture; this function never uses HTTP."""
    now = timezone.now()
    if configured_mode != "offline_fixture":
        return _failure(
            reason="runner_mode_invalid",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key=_SOURCE_KEY,
    ).first()
    if source is None:
        return _failure(
            reason="source_identity_missing",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    fixture_path = _safe_fixture_path(fixture_root, source.external_race_id)
    if fixture_path is None:
        return _failure(
            reason="unsafe_fixture_identity",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    try:
        with fixture_path.open("rb") as fixture_file:
            raw_fixture = fixture_file.read(_MAX_FIXTURE_BYTES + 1)
    except FileNotFoundError:
        return _failure(
            reason="fixture_missing",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    except OSError:
        return _failure(
            reason="fixture_unreadable",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    if len(raw_fixture) > _MAX_FIXTURE_BYTES:
        return _failure(
            reason="fixture_too_large",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    try:
        fixture = json.loads(raw_fixture.decode("utf-8"))
        if not isinstance(fixture, dict):
            raise ValueError("fixture container must be an object")
        snapshot = parse_the_racing_api_offline_fixture(fixture)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ):
        return _failure(
            reason="fixture_invalid",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    matching = [
        race
        for race in snapshot.races
        if race["external_race_id"] == source.external_race_id
    ]
    if len(matching) != 1 or snapshot.phase != "provisional":
        return _failure(
            reason="fixture_race_not_found" if not matching else "fixture_phase_unsupported",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    normalized_payload = _normalized_result_payload(matching[0])
    observation_decision = record_race_result_observation(
        source_identity_id=source.pk,
        observed_at=now,
        source_updated_at=None,
        parser_version="the_racing_api_fixture_v1",
        raw_sha256=hashlib.sha256(raw_fixture).hexdigest(),
        result_phase=snapshot.phase,
        normalized_payload=normalized_payload,
        field_provenance={"source": _SOURCE_KEY},
        parse_warnings=[],
        permission_classification="offline_fixture",
    )
    if not observation_decision.recorded or observation_decision.observation is None:
        return _failure(
            reason=f"observation_{observation_decision.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    apply_decision = apply_race_result_observation_revision(
        observation_id=observation_decision.observation.pk,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        source_authority=source.result_authority,
        official_marker=False,
        identity_valid=True,
        payload_complete=True,
        manual_lock_conflict=False,
        project_current=False,
    )
    successful = apply_decision.applied or apply_decision.action == "replay"
    revision_id = apply_decision.revision.pk if apply_decision.revision else None
    result = {
        "processed": successful,
        "reason": "offline_fixture_applied" if successful else f"apply_{apply_decision.reason}",
        "event_id": event_id,
        "action": apply_decision.action,
        "revision_id": revision_id,
    }
    next_poll_at = now + timedelta(minutes=5)
    if successful:
        tracking_state = RaceEventLiveTracking.objects.filter(
            event_id=event_id
        ).values_list("state", flat=True).first()
        off_time = datetime.fromisoformat(
            matching[0]["off_time"].replace("Z", "+00:00")
        )
        calculated_next_poll_at = calculate_race_live_next_poll_at(
            off_time=off_time,
            now=now,
            state=tracking_state,
        )
        next_poll_at = calculated_next_poll_at
    return _checkpoint_result(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
        success=successful,
        next_poll_at=next_poll_at,
        checkpoint_payload={
            "status": "succeeded" if successful else "failed",
            "reason": result["reason"],
            "fixture_payload_sha256": snapshot.payload_sha256,
            "action": apply_decision.action,
            "revision_id": revision_id,
        },
        observation_sha256=(
            observation_decision.observation.normalized_sha256 if successful else ""
        ),
        result=result,
    )


def _current_claim_rejection_reason(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    now: datetime,
) -> str:
    control = RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    if control is None:
        return "control_missing"
    if (
        control.write_owner != RaceEventProjectionWriteOwner.LIVE
        or control.owner_generation != expected_owner_generation
    ):
        return "owner_mismatch"
    tracking = RaceEventLiveTracking.objects.filter(event_id=event_id).first()
    if tracking is None:
        return "tracking_missing"
    if (
        tracking.claim_generation != expected_claim_generation
        or tracking.active_attempt_token != attempt_token
    ):
        return "claim_mismatch"
    if tracking.claim_expires_at is None:
        return "claim_missing_expiry"
    if tracking.claim_expires_at <= now:
        return "claim_expired"
    return ""


def run_race_live_the_racing_api_free(
    *,
    event_id: int,
    expected_owner_generation: int,
    expected_claim_generation: int,
    attempt_token: str,
    secret_env_file: str,
    registry_file: str,
    expected_registry_sha256: str,
    now: datetime,
    transport,
    clock=None,
) -> dict[str, Any]:
    """Fetch and publish one claimed event from the fixed TRA Free results endpoint."""
    if not isinstance(now, datetime) or timezone.is_naive(now):
        return {
            "processed": False,
            "reason": "invalid_start_time",
            "event_id": event_id,
        }
    try:
        _, registry_digest = read_the_racing_api_automation_registry(
            registry_file=registry_file,
            expected_registry_sha256=expected_registry_sha256,
            now=now,
        )
    except Exception:
        return _failure(
            reason="source_registry_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    source = RaceResultSourceIdentity.objects.filter(
        event_id=event_id,
        source_key=_SOURCE_KEY,
    ).first()
    if source is None:
        return _failure(
            reason="source_identity_missing",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    if source.host != _HOST:
        return _failure(
            reason="source_host_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    control = RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    historical_handoff_complete = bool(
        control
        and control.write_owner == RaceEventProjectionWriteOwner.LIVE
        and control.owner_generation == expected_owner_generation
    )
    network_permission = resolve_race_source_network_permission(
        mode="production",
        terms_status=source.terms_status,
        automation_allowed=source.automation_allowed,
        proof_network_allowed=source.proof_network_allowed,
        valid_until=source.valid_until,
        evidence_sha256=source.evidence_sha256,
        registry_digest=source.registry_digest,
        expected_registry_digest=registry_digest,
        manifest_approved=True,
        request_budget=1,
        historical_handoff_complete=historical_handoff_complete,
        now=now,
    )
    if not network_permission.allowed:
        return _failure(
            reason=f"source_permission_{network_permission.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )
    claim_rejection = _current_claim_rejection_reason(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=now,
    )
    if claim_rejection:
        return _failure(
            reason=claim_rejection,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    try:
        username, password = _read_secret(secret_env_file)
    except Exception:
        return _failure(
            reason="source_secret_rejected",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    reservation = reserve_race_live_host_request(host=_HOST, now=now)
    if not reservation.reserved:
        return _failure(
            reason=f"host_reservation_{reservation.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=now,
        )

    response = None
    failure_reason = ""
    try:
        response = transport(
            endpoint_name="results_today",
            url=_RESULTS_URL,
            username=username,
            password=password,
            timeout_seconds=15,
            max_response_bytes=_MAX_FIXTURE_BYTES,
            allow_redirects=False,
        )
    except Exception:
        failure_reason = "the_racing_api_transport_error"

    try:
        clock_fn = timezone.now if clock is None else clock
        fresh_now = clock_fn()
    except Exception:
        return {
            "processed": False,
            "reason": "fresh_clock_error",
            "event_id": event_id,
        }
    if not isinstance(fresh_now, datetime) or timezone.is_naive(fresh_now):
        return {
            "processed": False,
            "reason": "fresh_clock_invalid",
            "event_id": event_id,
        }
    if fresh_now < now:
        if clock is not None:
            return {
                "processed": False,
                "reason": "fresh_clock_before_start",
                "event_id": event_id,
            }
        fresh_now = now

    snapshot = None
    if not failure_reason:
        try:
            if response.redirect_url is not None or (
                isinstance(response.status_code, int)
                and 300 <= response.status_code < 400
            ):
                failure_reason = "the_racing_api_redirect_rejected"
            elif response.status_code != 200:
                failure_reason = "the_racing_api_http_error"
            elif (
                not isinstance(response.body, bytes)
                or len(response.body) > _MAX_FIXTURE_BYTES
            ):
                failure_reason = "the_racing_api_response_too_large"
            elif (
                not isinstance(response.content_type, str)
                or response.content_type.split(";", 1)[0].strip().lower()
                not in {"application/json", "application/problem+json"}
            ):
                failure_reason = "the_racing_api_content_type_rejected"
            else:
                payload = json.loads(response.body)
                snapshot = parse_the_racing_api_live_results_payload(payload)
        except (
            AttributeError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            failure_reason = "the_racing_api_payload_invalid"

    matching = []
    if snapshot is not None:
        matching = [
            race
            for race in snapshot.races
            if race["external_race_id"] == source.external_race_id
        ]
        if len(matching) > 1:
            failure_reason = "the_racing_api_result_ambiguous"

    outcome = record_race_live_host_outcome(
        host=_HOST,
        now=fresh_now,
        success=not failure_reason,
        error_code=failure_reason,
        circuit_threshold=3,
        circuit_seconds=300,
        expected_reservation_version=reservation.reservation_version,
    )
    if not outcome.recorded:
        return _failure(
            reason=f"host_outcome_{outcome.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )
    if failure_reason:
        return _failure(
            reason=failure_reason,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )

    claim_rejection = _current_claim_rejection_reason(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
    )
    if claim_rejection:
        return _failure(
            reason=claim_rejection,
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )

    if not matching:
        return _checkpoint_result(
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
            success=True,
            next_poll_at=fresh_now + timedelta(minutes=3),
            checkpoint_payload={
                "status": "result_not_found",
                "reason": "the_racing_api_result_not_found",
                "response_sha256": snapshot.payload_sha256,
            },
            observation_sha256=snapshot.payload_sha256,
            result={
                "processed": False,
                "reason": "the_racing_api_result_not_found",
                "event_id": event_id,
            },
        )

    raw_sha256 = hashlib.sha256(response.body).hexdigest()
    normalized_payload = _normalized_result_payload(matching[0])
    observation_decision = record_race_result_observation(
        source_identity_id=source.pk,
        observed_at=fresh_now,
        source_updated_at=None,
        parser_version="the_racing_api_free_v1",
        raw_sha256=raw_sha256,
        result_phase="provisional",
        normalized_payload=normalized_payload,
        field_provenance={"source": _SOURCE_KEY},
        parse_warnings=[],
        permission_classification="licensed_api_automation",
    )
    if not observation_decision.recorded or observation_decision.observation is None:
        return _failure(
            reason=f"observation_{observation_decision.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )

    apply_decision = apply_race_result_observation_revision(
        observation_id=observation_decision.observation.pk,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
        source_authority=source.result_authority,
        official_marker=False,
        identity_valid=True,
        payload_complete=True,
        manual_lock_conflict=False,
        project_current=False,
    )
    if not apply_decision.applied and apply_decision.action != "replay":
        return _failure(
            reason=f"apply_{apply_decision.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )

    admission = admit_race_live_publication(
        observation_id=observation_decision.observation.pk,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
    )
    if not admission.applied and admission.action != "replay":
        if admission.reason == "shadow_only":
            tracking_state = (
                RaceEventLiveTracking.objects.filter(event_id=event_id)
                .values_list("state", flat=True)
                .first()
            )
            next_poll_at = calculate_race_live_next_poll_at(
                off_time=datetime.fromisoformat(
                    matching[0]["off_time"].replace("Z", "+00:00")
                ),
                now=fresh_now,
                state=tracking_state,
            )
            revision = admission.revision or apply_decision.revision
            return _checkpoint_result(
                event_id=event_id,
                expected_owner_generation=expected_owner_generation,
                expected_claim_generation=expected_claim_generation,
                attempt_token=attempt_token,
                now=fresh_now,
                success=True,
                next_poll_at=next_poll_at,
                checkpoint_payload={
                    "status": "shadow_applied",
                    "reason": "the_racing_api_shadow_applied",
                    "response_sha256": snapshot.payload_sha256,
                    "revision_id": (
                        revision.pk if revision is not None else None
                    ),
                },
                observation_sha256=(
                    observation_decision.observation.normalized_sha256
                ),
                result={
                    "processed": True,
                    "reason": "the_racing_api_shadow_applied",
                    "event_id": event_id,
                    "action": admission.action,
                    "revision_id": (
                        revision.pk if revision is not None else None
                    ),
                },
            )
        return _failure(
            reason=f"admission_{admission.reason}",
            event_id=event_id,
            expected_owner_generation=expected_owner_generation,
            expected_claim_generation=expected_claim_generation,
            attempt_token=attempt_token,
            now=fresh_now,
        )

    next_poll_at = calculate_race_live_next_poll_at(
        off_time=datetime.fromisoformat(
            matching[0]["off_time"].replace("Z", "+00:00")
        ),
        now=fresh_now,
        state="provisional_result",
    )
    revision = admission.revision or apply_decision.revision
    return _checkpoint_result(
        event_id=event_id,
        expected_owner_generation=expected_owner_generation,
        expected_claim_generation=expected_claim_generation,
        attempt_token=attempt_token,
        now=fresh_now,
        success=True,
        next_poll_at=next_poll_at,
        checkpoint_payload={
            "status": "provisional_published",
            "reason": "the_racing_api_provisional_published",
            "response_sha256": snapshot.payload_sha256,
            "revision_id": revision.pk if revision is not None else None,
        },
        observation_sha256=observation_decision.observation.normalized_sha256,
        result={
            "processed": True,
            "reason": "the_racing_api_provisional_published",
            "event_id": event_id,
            "action": admission.action,
            "revision_id": revision.pk if revision is not None else None,
        },
    )
