from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from stable.services.race_events import build_race_live_canonical_sha256


_SOURCE_KEY = "the_racing_api"
_ENDPOINTS = {
    "/v1/racecards/free": ("racecards", "racecard"),
    "/v1/results/today/free": ("results", "provisional"),
}
_ACQUISITION_METHODS = {
    "synthetic_from_public_docs",
    "licensed_snapshot",
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RACES = 500
_MAX_RUNNERS_PER_RACE = 100


@dataclass(frozen=True)
class TheRacingApiFixtureSnapshot:
    source_key: str
    endpoint: str
    phase: str
    payload_sha256: str
    races: tuple[dict[str, Any], ...]


def _required_nonempty_string(
    container: dict[str, Any],
    key: str,
    *,
    max_length: int | None = None,
) -> str:
    value = container.get(key)
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or (max_length is not None and len(value) > max_length)
    ):
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string(
    container: dict[str, Any],
    key: str,
    *,
    max_length: int | None = None,
) -> str:
    value = container.get(key, "")
    if (
        not isinstance(value, str)
        or value != value.strip()
        or "\x00" in value
        or (max_length is not None and len(value) > max_length)
    ):
        raise ValueError(f"{key} must be a string")
    return value


def _aware_iso_datetime(container: dict[str, Any], key: str) -> str:
    value = _required_nonempty_string(container, key, max_length=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{key} must include a timezone offset")
    return value


def _normalize_racecard_runner(runner: Any) -> dict[str, Any]:
    if not isinstance(runner, dict):
        raise ValueError("racecard runner must be an object")
    return {
        "external_runner_id": _required_nonempty_string(
            runner, "horse_id", max_length=128
        ),
        "horse_name": _required_nonempty_string(
            runner, "horse", max_length=255
        ),
        "number": _required_nonempty_string(
            runner, "number", max_length=32
        ),
        "draw": _optional_string(runner, "draw", max_length=32),
        "jockey_name": _optional_string(
            runner, "jockey", max_length=255
        ),
        "jockey_id": _optional_string(
            runner, "jockey_id", max_length=128
        ),
        "status": "declared",
    }


def _positive_finish_position(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        position = int(value)
        return position if position > 0 else None
    return None


def _normalize_result_runner(runner: Any) -> dict[str, Any]:
    if not isinstance(runner, dict):
        raise ValueError("result runner must be an object")
    if "position" not in runner:
        raise ValueError("position is required")
    position_raw = runner["position"]
    if not isinstance(position_raw, (str, int)) or isinstance(position_raw, bool):
        raise ValueError("position must be a string or integer")
    finish_position = _positive_finish_position(position_raw)
    status = "finished"
    if finish_position is None:
        normalized_position = str(position_raw).strip().upper()
        status = {
            "PU": "pulled_up",
            "F": "fell",
            "UR": "unseated_rider",
            "NR": "non_runner",
            "DSQ": "disqualified",
            "REF": "refused",
        }.get(normalized_position, "unknown")
    return {
        "external_runner_id": _required_nonempty_string(
            runner, "horse_id", max_length=128
        ),
        "horse_name": _required_nonempty_string(
            runner, "horse", max_length=255
        ),
        "number": _required_nonempty_string(
            runner, "number", max_length=32
        ),
        "position_raw": position_raw,
        "official_finish_position": finish_position,
        "status": status,
    }


def _normalize_race(race: Any, *, phase: str) -> dict[str, Any]:
    if not isinstance(race, dict):
        raise ValueError("race must be an object")
    runners = race.get("runners")
    if not isinstance(runners, list):
        raise ValueError("runners must be a list")
    if not runners:
        raise ValueError("race must contain at least one runner")
    if len(runners) > _MAX_RUNNERS_PER_RACE:
        raise ValueError("race exceeds runner limit")

    normalize_runner = (
        _normalize_racecard_runner if phase == "racecard" else _normalize_result_runner
    )
    return {
        "external_race_id": _required_nonempty_string(
            race, "race_id", max_length=128
        ),
        "off_time": _aware_iso_datetime(race, "off_dt"),
        "region": _required_nonempty_string(
            race, "region", max_length=32
        ),
        "course": _required_nonempty_string(
            race, "course", max_length=255
        ),
        "race_name": _required_nonempty_string(
            race, "race_name", max_length=255
        ),
        "race_status": _optional_string(
            race, "race_status", max_length=64
        ),
        "participants": tuple(normalize_runner(runner) for runner in runners),
    }


def parse_the_racing_api_offline_fixture(
    fixture: Any,
) -> TheRacingApiFixtureSnapshot:
    """Validate and normalize a redistributable, offline The Racing API fixture."""
    if not isinstance(fixture, dict):
        raise ValueError("fixture must be an object")
    metadata = fixture.get("metadata")
    payload = fixture.get("payload")
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    schema_version = metadata.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        raise ValueError("schema_version must be integer 1")
    if metadata.get("source_key") != _SOURCE_KEY:
        raise ValueError("source_key is invalid")

    endpoint = metadata.get("endpoint")
    if not isinstance(endpoint, str) or endpoint not in _ENDPOINTS:
        raise ValueError("endpoint is not allowed")
    wrapper_key, phase = _ENDPOINTS[endpoint]
    _aware_iso_datetime(metadata, "created_at")
    acquisition = metadata.get("acquisition")
    if not isinstance(acquisition, str) or acquisition not in _ACQUISITION_METHODS:
        raise ValueError("acquisition is not allowed")
    if metadata.get("redistribution_allowed") is not True:
        raise ValueError("redistribution is not allowed")

    payload_sha256 = metadata.get("payload_sha256")
    if not isinstance(payload_sha256, str) or not _SHA256_RE.fullmatch(
        payload_sha256
    ):
        raise ValueError("payload_sha256 is invalid")
    try:
        actual_sha256 = build_race_live_canonical_sha256(normalized_payload=payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload is not strict JSON") from exc
    if payload_sha256 != actual_sha256:
        raise ValueError("payload_sha256 does not match payload")

    races = payload.get(wrapper_key)
    if not isinstance(races, list):
        raise ValueError(f"{wrapper_key} must be a list")
    if not races:
        raise ValueError(f"empty {wrapper_key}")
    if len(races) > _MAX_RACES:
        raise ValueError("fixture exceeds race limit")

    return TheRacingApiFixtureSnapshot(
        source_key=_SOURCE_KEY,
        endpoint=endpoint,
        phase=phase,
        payload_sha256=payload_sha256,
        races=tuple(_normalize_race(race, phase=phase) for race in races),
    )


def parse_the_racing_api_live_results_payload(
    payload: Any,
) -> TheRacingApiFixtureSnapshot:
    """Validate and normalize one live TRA Free results response."""
    if not isinstance(payload, dict):
        raise ValueError("results payload must be an object")
    races = payload.get("results")
    if not isinstance(races, list):
        raise ValueError("results must be a list")
    if len(races) > _MAX_RACES:
        raise ValueError("results payload exceeds race limit")
    try:
        payload_sha256 = build_race_live_canonical_sha256(
            normalized_payload=payload
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("payload is not strict JSON") from exc
    return TheRacingApiFixtureSnapshot(
        source_key=_SOURCE_KEY,
        endpoint="/v1/results/today/free",
        phase="provisional",
        payload_sha256=payload_sha256,
        races=tuple(
            _normalize_race(race, phase="provisional") for race in races
        ),
    )


def parse_the_racing_api_live_racecards_payload(
    payload: Any,
) -> TheRacingApiFixtureSnapshot:
    """Validate and normalize one live TRA Free racecards response."""
    if not isinstance(payload, dict):
        raise ValueError("racecards payload must be an object")
    races = payload.get("racecards")
    if not isinstance(races, list):
        raise ValueError("racecards must be a list")
    if len(races) > _MAX_RACES:
        raise ValueError("racecards payload exceeds race limit")
    try:
        payload_sha256 = build_race_live_canonical_sha256(
            normalized_payload=payload
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("payload is not strict JSON") from exc

    normalized_races: list[dict[str, Any]] = []
    race_ids: set[str] = set()
    for race in races:
        normalized = _normalize_race(race, phase="racecard")
        external_race_id = normalized["external_race_id"]
        if external_race_id in race_ids:
            raise ValueError("duplicate race_id")
        race_ids.add(external_race_id)
        runner_ids: set[str] = set()
        runner_numbers: set[str] = set()
        for participant in normalized["participants"]:
            external_runner_id = participant["external_runner_id"]
            number = participant["number"]
            if external_runner_id in runner_ids:
                raise ValueError("duplicate horse_id")
            if number in runner_numbers:
                raise ValueError("duplicate runner number")
            runner_ids.add(external_runner_id)
            runner_numbers.add(number)
        normalized_races.append(normalized)

    return TheRacingApiFixtureSnapshot(
        source_key=_SOURCE_KEY,
        endpoint="/v1/racecards/free",
        phase="racecard",
        payload_sha256=payload_sha256,
        races=tuple(normalized_races),
    )
