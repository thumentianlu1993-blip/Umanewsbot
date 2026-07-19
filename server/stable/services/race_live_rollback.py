from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from datetime import datetime
from typing import Any
import uuid

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from stable import models


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_ARTIFACT_BYTES = 1024 * 1024
_POLICY_FIELDS = {
    "mode",
    "version",
    "registry_digest",
    "coverage_proof_digest",
    "valid_until",
}
_MANIFEST_KEYS = {
    "schema_version",
    "event_id",
    "reviewed_release_image_id",
    "filtered_env_sha256",
    "approved_commit",
    "generated_at",
    "expected_current_revision_id",
    "expected_provisional_revision_id",
    "expected_allowlist_version",
    "expected_publication_id",
    "expected_tracking_lock_version",
    "planned_policy_snapshot",
    "baseline_policies",
    "expected_tracking_state",
    "maintenance_confirmation",
}
_TRACKING_KEYS = {
    "tracking_enabled",
    "next_poll_at",
    "active_attempt_token",
    "claim_expires_at",
    "lock_version",
}
_FORBIDDEN_KEY_PARTS = (
    "password",
    "passwd",
    "credential",
    "secret",
    "api_key",
    "apikey",
    "smtp",
    "notification",
)
_PUBLICATION_MODE_RANK = {
    mode: rank
    for rank, mode in enumerate(
        (
            models.RaceLivePublicationMode.OFF,
            models.RaceLivePublicationMode.SHADOW,
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
            models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
        )
    )
}


def _canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValueError(f"{label} must be an aware datetime")
    return value


def _parse_aware(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO datetime") from exc
    return _aware(parsed, label)


def _background_tasks_are_off() -> bool:
    return (
        getattr(settings, "RACE_LIVE_SCHEDULER_ENABLED", False) is False
        and getattr(settings, "RACE_LIVE_MONITOR_ENABLED", False) is False
        and tuple(getattr(settings, "RACE_LIVE_ENABLED_REGIONS", ())) == ()
    )


def _policy_payload(policy: models.RaceLivePublicationPolicy) -> dict[str, Any]:
    return {
        "mode": policy.mode,
        "version": policy.version,
        "registry_digest": policy.registry_digest,
        "coverage_proof_digest": policy.coverage_proof_digest,
        "valid_until": (
            policy.valid_until.isoformat()
            if policy.valid_until is not None
            else None
        ),
    }


def _tracking_payload(
    tracking: models.RaceEventLiveTracking,
) -> dict[str, Any]:
    return {
        "tracking_enabled": tracking.tracking_enabled,
        "next_poll_at": (
            tracking.next_poll_at.isoformat()
            if tracking.next_poll_at is not None
            else None
        ),
        "active_attempt_token": tracking.active_attempt_token,
        "claim_expires_at": (
            tracking.claim_expires_at.isoformat()
            if tracking.claim_expires_at is not None
            else None
        ),
        "lock_version": tracking.lock_version,
    }


def _expected_scopes(
    *,
    event: models.RaceEvent,
    source: models.RaceResultSourceIdentity,
) -> tuple[tuple[str, str], ...]:
    return (
        (models.RaceLivePublicationScopeType.GLOBAL, "global"),
        (
            models.RaceLivePublicationScopeType.REGION,
            event.country_region,
        ),
        (
            models.RaceLivePublicationScopeType.SOURCE,
            source.source_key,
        ),
        (
            models.RaceLivePublicationScopeType.EVENT,
            str(event.pk),
        ),
    )


def _validate_tracking_is_fully_off(
    tracking: models.RaceEventLiveTracking,
) -> None:
    if _tracking_payload(tracking) != {
        "tracking_enabled": False,
        "next_poll_at": None,
        "active_attempt_token": "",
        "claim_expires_at": None,
        "lock_version": tracking.lock_version,
    }:
        raise PermissionError("target tracking is not fully disabled")


def _load_provisional_baseline(
    *,
    event_id: int,
    now: datetime,
    lock: bool,
    require_public_policy: bool = True,
) -> dict[str, Any]:
    if (
        isinstance(event_id, bool)
        or not isinstance(event_id, int)
        or event_id <= 0
    ):
        raise ValueError("event_id must be a positive integer")
    _aware(now, "now")
    if not _background_tasks_are_off():
        raise PermissionError("race-live background gates must be fully off")

    event_query = models.RaceEvent.objects
    control_query = models.RaceEventProjectionControl.objects
    tracking_query = models.RaceEventLiveTracking.objects
    if lock:
        event_query = event_query.select_for_update()
        control_query = control_query.select_for_update()
        tracking_query = tracking_query.select_for_update()
    event = event_query.filter(pk=event_id).first()
    control = control_query.filter(event_id=event_id).first()
    tracking = tracking_query.filter(event_id=event_id).first()
    if event is None or control is None or tracking is None:
        raise ValueError("race-live rollback baseline is incomplete")
    if event.visibility_status != models.RaceEventVisibility.PUBLISHED:
        raise PermissionError("rollback target is not publicly visible")
    _validate_tracking_is_fully_off(tracking)

    if models.RaceEventLiveTracking.objects.filter(
        Q(active_attempt_token__gt="")
        | Q(claim_expires_at__isnull=False)
    ).exists():
        raise PermissionError("active race-live claims exist")

    provisional_id = control.last_provisional_result_revision_id
    if (
        provisional_id is None
        or control.current_result_revision_id != provisional_id
    ):
        raise PermissionError("current result is not the provisional pointer")
    revision_query = models.RaceEventRevision.objects
    if lock:
        revision_query = revision_query.select_for_update()
    revision = revision_query.filter(
        pk=provisional_id,
        event_id=event_id,
        kind=models.RaceEventRevisionKind.RESULT,
        phase=models.RaceResultPhase.PROVISIONAL,
    ).first()
    if (
        revision is None
        or revision.published_at is None
        or revision.primary_observation_id is None
        or revision.source_authority
        != models.RaceResultSourceAuthority.SUPPLEMENTAL
    ):
        raise PermissionError("provisional revision is not publishable")

    observation_query = models.RaceResultObservation.objects
    source_query = models.RaceResultSourceIdentity.objects
    publication_query = models.RaceEventRevisionPublication.objects
    allowlist_query = models.RaceLiveEventPublicationAllowlist.objects
    policy_query = models.RaceLivePublicationPolicy.objects
    if lock:
        observation_query = observation_query.select_for_update()
        source_query = source_query.select_for_update()
        publication_query = publication_query.select_for_update()
        allowlist_query = allowlist_query.select_for_update()
        policy_query = policy_query.select_for_update()
    observation = observation_query.filter(
        pk=revision.primary_observation_id,
        result_phase=models.RaceResultPhase.PROVISIONAL,
    ).first()
    source = source_query.filter(
        pk=(
            observation.source_identity_id
            if observation is not None
            else None
        ),
        event_id=event_id,
        source_key="the_racing_api",
        review_status=models.RaceLiveReviewStatus.APPROVED,
        terms_status=models.RaceSourceTermsStatus.APPROVED,
        automation_allowed=True,
        result_authority=(
            models.RaceResultSourceAuthority.SUPPLEMENTAL
        ),
    ).first()
    publication = publication_query.filter(
        revision_id=revision.pk,
        authorization_kind="provisional_policy",
        official_authorization_version=0,
    ).first()
    allowlist = allowlist_query.filter(
        event_id=event_id,
        source_key="the_racing_api",
        enabled=True,
    ).first()
    if (
        observation is None
        or source is None
        or publication is None
        or allowlist is None
        or source.valid_until is None
        or source.valid_until <= now
        or publication.published_at != revision.published_at
        or publication.registry_digest != source.registry_digest
        or publication.coverage_proof_digest
        != allowlist.coverage_proof_digest
        or publication.allowlist_version != allowlist.version
        or _PUBLICATION_MODE_RANK.get(allowlist.max_mode, -1)
        < _PUBLICATION_MODE_RANK[
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
        ]
    ):
        raise PermissionError("provisional audit baseline is invalid")

    scopes = _expected_scopes(event=event, source=source)
    scope_filter = Q()
    for scope_type, scope_key in scopes:
        scope_filter |= Q(scope_type=scope_type, scope_key=scope_key)
    policies = list(policy_query.filter(scope_filter))
    by_key = {
        f"{policy.scope_type}:{policy.scope_key}": policy
        for policy in policies
    }
    expected_keys = {
        f"{scope_type}:{scope_key}" for scope_type, scope_key in scopes
    }
    if set(by_key) != expected_keys:
        raise PermissionError("publication policy scopes are incomplete")
    for key, policy in by_key.items():
        if (
            policy.valid_until is None
            or policy.valid_until <= now
            or policy.registry_digest != source.registry_digest
            or policy.coverage_proof_digest
            != allowlist.coverage_proof_digest
            or (
                require_public_policy
                and _PUBLICATION_MODE_RANK.get(policy.mode, -1)
                < _PUBLICATION_MODE_RANK[
                    models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                ]
            )
            or policy.version > (2**63 - 3)
        ):
            raise PermissionError(f"publication policy is unusable: {key}")
    source_key = (
        f"{models.RaceLivePublicationScopeType.SOURCE}:"
        f"{source.source_key}"
    )
    if require_public_policy and (
        by_key[source_key].mode
        != models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
    ):
        raise PermissionError("source restore mode must be provisional_public")
    return {
        "event": event,
        "control": control,
        "tracking": tracking,
        "revision": revision,
        "source": source,
        "publication": publication,
        "allowlist": allowlist,
        "policies": by_key,
    }


def build_race_live_rollback_bundle(
    *,
    event_id: int,
    reviewed_release_image_id: str,
    filtered_env_sha256: str,
    approved_commit: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic, read-only rollback manifest from one baseline."""
    if _IMAGE_ID_RE.fullmatch(reviewed_release_image_id or "") is None:
        raise ValueError("reviewed_release_image_id is invalid")
    if _SHA256_RE.fullmatch(filtered_env_sha256 or "") is None:
        raise ValueError("filtered_env_sha256 is invalid")
    if _COMMIT_RE.fullmatch(approved_commit or "") is None:
        raise ValueError("approved_commit is invalid")
    generated_at = _aware(
        generated_at or timezone.now(),
        "generated_at",
    )
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL TRANSACTION READ ONLY")
        baseline = _load_provisional_baseline(
            event_id=event_id,
            now=generated_at,
            lock=False,
        )
        # Import lazily because race_events owns the public-read admission
        # resolver and imports this rollback service for its maintenance API.
        from stable.services.race_events import resolve_race_live_public_read

        public_read = resolve_race_live_public_read(
            event_id=event_id,
            now=generated_at,
        )
        if (
            public_read.visible is not True
            or public_read.revision_id != baseline["revision"].pk
            or public_read.phase != models.RaceResultPhase.PROVISIONAL
        ):
            raise PermissionError(
                "rollback target does not pass public-read admission: "
                f"{public_read.reason}"
            )
        baseline_policies = {
            key: _policy_payload(policy)
            for key, policy in sorted(baseline["policies"].items())
        }
        planned_policy_snapshot = {}
        for key, current in baseline_policies.items():
            maintenance = {
                **current,
                "mode": models.RaceLivePublicationMode.OFF,
                "version": current["version"] + 1,
            }
            restore = {
                **current,
                "version": current["version"] + 2,
            }
            planned_policy_snapshot[key] = {
                "maintenance": maintenance,
                "restore": restore,
            }
        control = baseline["control"]
        tracking = baseline["tracking"]
        revision = baseline["revision"]
        publication = baseline["publication"]
        allowlist = baseline["allowlist"]
        manifest = {
            "schema_version": 1,
            "event_id": event_id,
            "reviewed_release_image_id": reviewed_release_image_id,
            "filtered_env_sha256": filtered_env_sha256,
            "approved_commit": approved_commit,
            "generated_at": generated_at.isoformat(),
            "expected_current_revision_id": (
                control.current_result_revision_id
            ),
            "expected_provisional_revision_id": revision.pk,
            "expected_allowlist_version": allowlist.version,
            "expected_publication_id": publication.pk,
            "expected_tracking_lock_version": tracking.lock_version,
            "planned_policy_snapshot": planned_policy_snapshot,
            "baseline_policies": baseline_policies,
            "expected_tracking_state": _tracking_payload(tracking),
            "maintenance_confirmation": (
                f"ENTER_RACE_LIVE_ROLLBACK_MAINTENANCE_{event_id}"
            ),
        }
        report = {
            "schema_version": 1,
            "event_id": event_id,
            "generated_at": generated_at.isoformat(),
            "status": "rollback_bundle_ready",
            "policy_scope_count": len(planned_policy_snapshot),
            "tracking_fully_disabled": True,
            "active_claim_count": 0,
        }
    _validate_manifest(manifest)
    return {"manifest": manifest, "report": report}


def _validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise ValueError("rollback manifest schema is invalid")
    if manifest["schema_version"] != 1:
        raise ValueError("rollback manifest version is invalid")
    if (
        isinstance(manifest["event_id"], bool)
        or not isinstance(manifest["event_id"], int)
        or manifest["event_id"] <= 0
        or not isinstance(manifest["reviewed_release_image_id"], str)
        or _IMAGE_ID_RE.fullmatch(
            manifest["reviewed_release_image_id"]
        ) is None
        or not isinstance(manifest["filtered_env_sha256"], str)
        or _SHA256_RE.fullmatch(manifest["filtered_env_sha256"]) is None
        or not isinstance(manifest["approved_commit"], str)
        or _COMMIT_RE.fullmatch(manifest["approved_commit"]) is None
    ):
        raise ValueError("rollback manifest identity is invalid")
    _parse_aware(manifest["generated_at"], "generated_at")
    positive_ids = (
        "expected_current_revision_id",
        "expected_provisional_revision_id",
        "expected_allowlist_version",
        "expected_publication_id",
    )
    if any(
        isinstance(manifest[field], bool)
        or not isinstance(manifest[field], int)
        or manifest[field] <= 0
        for field in positive_ids
    ):
        raise ValueError("rollback manifest pointers are invalid")
    if (
        isinstance(manifest["expected_tracking_lock_version"], bool)
        or not isinstance(manifest["expected_tracking_lock_version"], int)
        or manifest["expected_tracking_lock_version"] < 0
        or manifest["expected_current_revision_id"]
        != manifest["expected_provisional_revision_id"]
    ):
        raise ValueError("rollback manifest tracking/revision is invalid")
    tracking = manifest["expected_tracking_state"]
    if (
        not isinstance(tracking, dict)
        or set(tracking) != _TRACKING_KEYS
        or tracking
        != {
            "tracking_enabled": False,
            "next_poll_at": None,
            "active_attempt_token": "",
            "claim_expires_at": None,
            "lock_version": manifest[
                "expected_tracking_lock_version"
            ],
        }
    ):
        raise ValueError("rollback tracking snapshot is invalid")
    if manifest["maintenance_confirmation"] != (
        "ENTER_RACE_LIVE_ROLLBACK_MAINTENANCE_"
        f"{manifest['event_id']}"
    ):
        raise ValueError("rollback confirmation is invalid")
    baseline = manifest["baseline_policies"]
    planned = manifest["planned_policy_snapshot"]
    if (
        not isinstance(baseline, dict)
        or not isinstance(planned, dict)
        or len(baseline) != 4
        or set(baseline) != set(planned)
    ):
        raise ValueError("rollback policy scopes are invalid")
    scope_prefixes = {
        key.split(":", 1)[0]
        for key in baseline
        if isinstance(key, str) and ":" in key
    }
    expected_event_key = (
        f"{models.RaceLivePublicationScopeType.EVENT}:"
        f"{manifest['event_id']}"
    )
    if (
        scope_prefixes
        != {
            models.RaceLivePublicationScopeType.GLOBAL,
            models.RaceLivePublicationScopeType.REGION,
            models.RaceLivePublicationScopeType.SOURCE,
            models.RaceLivePublicationScopeType.EVENT,
        }
        or (
            f"{models.RaceLivePublicationScopeType.GLOBAL}:global"
            not in baseline
        )
        or (
            f"{models.RaceLivePublicationScopeType.SOURCE}:"
            "the_racing_api"
            not in baseline
        )
        or expected_event_key not in baseline
    ):
        raise ValueError("rollback policy scope identity is invalid")
    region_keys = [
        key
        for key in baseline
        if key.startswith(
            f"{models.RaceLivePublicationScopeType.REGION}:"
        )
    ]
    if (
        len(region_keys) != 1
        or region_keys[0].split(":", 1)[1]
        not in models.RacingRegion.values
    ):
        raise ValueError("rollback policy region is invalid")
    source_modes = []
    registry_digests = set()
    coverage_digests = set()
    generated_at = _parse_aware(manifest["generated_at"], "generated_at")
    for key in sorted(baseline):
        current = baseline[key]
        snapshots = planned[key]
        if (
            not isinstance(key, str)
            or not isinstance(current, dict)
            or set(current) != _POLICY_FIELDS
            or not isinstance(snapshots, dict)
            or set(snapshots) != {"maintenance", "restore"}
        ):
            raise ValueError("rollback policy schema is invalid")
        maintenance = snapshots["maintenance"]
        restore = snapshots["restore"]
        if (
            not isinstance(maintenance, dict)
            or not isinstance(restore, dict)
            or set(maintenance) != _POLICY_FIELDS
            or set(restore) != _POLICY_FIELDS
            or isinstance(current["version"], bool)
            or not isinstance(current["version"], int)
            or current["version"] < 1
            or maintenance["mode"]
            != models.RaceLivePublicationMode.OFF
            or maintenance["version"] != current["version"] + 1
            or restore["version"] != current["version"] + 2
            or restore["mode"] != current["mode"]
            or current["mode"]
            not in {
                models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
            }
        ):
            raise ValueError("rollback policy transition is invalid")
        for field in (
            "registry_digest",
            "coverage_proof_digest",
            "valid_until",
        ):
            if (
                maintenance[field] != current[field]
                or restore[field] != current[field]
            ):
                raise ValueError("rollback policy evidence drift")
        if (
            not isinstance(current["registry_digest"], str)
            or _SHA256_RE.fullmatch(current["registry_digest"]) is None
            or not isinstance(current["coverage_proof_digest"], str)
            or _SHA256_RE.fullmatch(
                current["coverage_proof_digest"]
            ) is None
        ):
            raise ValueError("rollback policy digest is invalid")
        if (
            _parse_aware(
                current["valid_until"],
                "policy.valid_until",
            )
            <= generated_at
        ):
            raise ValueError("rollback policy validity is expired")
        registry_digests.add(current["registry_digest"])
        coverage_digests.add(current["coverage_proof_digest"])
        if key.startswith(
            f"{models.RaceLivePublicationScopeType.SOURCE}:"
        ):
            source_modes.append(restore["mode"])
    if source_modes != [models.RaceLivePublicationMode.PROVISIONAL_PUBLIC]:
        raise ValueError("rollback source policy is invalid")
    if len(registry_digests) != 1 or len(coverage_digests) != 1:
        raise ValueError("rollback policy evidence is inconsistent")
    return manifest


def _strict_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _read_regular_file(path: Path) -> bytes:
    if os.geteuid() != 0:
        raise PermissionError("rollback manifest loading requires root EUID")
    current = path.parent
    checked_parent = False
    while current != current.parent:
        current_stat = current.lstat()
        if stat.S_ISLNK(current_stat.st_mode):
            raise PermissionError("rollback manifest ancestors cannot be symlinks")
        if not checked_parent:
            if (
                not stat.S_ISDIR(current_stat.st_mode)
                or stat.S_IMODE(current_stat.st_mode) != 0o700
                or (current_stat.st_uid, current_stat.st_gid) != (0, 0)
            ):
                raise PermissionError(
                    "rollback manifest directory ownership is invalid"
                )
            checked_parent = True
        current = current.parent
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size > _MAX_ARTIFACT_BYTES
        or stat.S_IMODE(before.st_mode) != 0o600
        or (before.st_uid, before.st_gid) != (0, 0)
    ):
        raise PermissionError("rollback manifest is not a bounded regular file")
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino)
            != (after.st_dev, after.st_ino)
            or not stat.S_ISREG(after.st_mode)
            or after.st_size > _MAX_ARTIFACT_BYTES
        ):
            raise PermissionError("rollback manifest identity changed")
        chunks = []
        remaining = _MAX_ARTIFACT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise ValueError("rollback manifest is too large")
        return payload
    finally:
        os.close(descriptor)


def load_race_live_rollback_manifest(
    *,
    manifest_path: str | os.PathLike[str],
    expected_manifest_sha256: str,
    expected_approved_commit: str,
) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.is_absolute():
        raise ValueError("rollback manifest path must be absolute")
    if _SHA256_RE.fullmatch(expected_manifest_sha256 or "") is None:
        raise ValueError("expected manifest SHA-256 is invalid")
    if _COMMIT_RE.fullmatch(expected_approved_commit or "") is None:
        raise ValueError("expected approved commit is invalid")
    payload_bytes = _read_regular_file(path)
    if hashlib.sha256(payload_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError("rollback manifest SHA-256 drift")
    payload = json.loads(
        payload_bytes,
        object_pairs_hook=_strict_json_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant: {value}")
        ),
    )
    manifest = _validate_manifest(payload)
    if manifest["approved_commit"] != expected_approved_commit:
        raise PermissionError("rollback approved commit drift")
    return manifest


def _scan_secret_free(payload: Any) -> None:
    serialized = _canonical_json(payload).decode("utf-8")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).casefold()
                if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                    raise PermissionError("rollback artifact contains secret key")
                if (
                    "token" in lowered
                    and item is not None
                    and item != ""
                ):
                    raise PermissionError(
                        "rollback artifact contains nonempty token"
                    )
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(payload)
    for env_key, env_value in os.environ.items():
        if (
            env_value
            and len(env_value) >= 8
            and env_value.casefold()
            not in {
                "true",
                "false",
                "disabled",
                "localhost",
            }
            and any(
                marker in env_key.upper()
                for marker in (
                    "PASSWORD",
                    "SECRET",
                    "API_KEY",
                    "SMTP",
                    "DATABASE_URL",
                    "THE_RACING_API",
                )
            )
            and env_value in serialized
        ):
            raise PermissionError("rollback artifact contains environment secret")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(
    path: str | Path,
    payload: bytes,
    *,
    dir_fd: int | None = None,
) -> None:
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise ValueError("rollback artifact file is too large")
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=dir_fd,
    )
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or stat.S_IMODE(file_stat.st_mode) != 0o600
            or (file_stat.st_uid, file_stat.st_gid) != (0, 0)
        ):
            raise PermissionError("rollback artifact file ownership is invalid")
    finally:
        os.close(descriptor)


def _rename_no_replace_at(
    source_dir_fd: int,
    source_name: str,
    destination_dir_fd: int,
    destination_name: str,
) -> None:
    source_bytes = os.fsencode(source_name)
    destination_bytes = os.fsencode(destination_name)
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(
            source_dir_fd,
            ctypes.c_char_p(source_bytes),
            destination_dir_fd,
            ctypes.c_char_p(destination_bytes),
            1,
        )
    elif sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        result = libc.renameatx_np(
            source_dir_fd,
            ctypes.c_char_p(source_bytes),
            destination_dir_fd,
            ctypes.c_char_p(destination_bytes),
            0x00000004,
        )
    else:
        try:
            os.stat(
                destination_name,
                dir_fd=destination_dir_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(destination_name)
        os.rename(
            source_name,
            destination_name,
            src_dir_fd=source_dir_fd,
            dst_dir_fd=destination_dir_fd,
        )
        return
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(destination_name)
        raise OSError(error, os.strerror(error), destination_name)


def _remove_owned_directory_at(
    root_fd: int,
    name: str,
    identity: tuple[int, int] | None,
) -> None:
    if identity is None:
        return
    try:
        current = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (
        not stat.S_ISDIR(current.st_mode)
        or (current.st_dev, current.st_ino) != identity
    ):
        return
    try:
        directory_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
    except OSError:
        return
    for filename in ("manifest.json", "report.json", "sha256s.json"):
        try:
            child_stat = os.stat(
                filename,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        if stat.S_ISREG(child_stat.st_mode) and not stat.S_ISLNK(
            child_stat.st_mode
        ):
            os.unlink(filename, dir_fd=directory_fd)
    os.close(directory_fd)
    try:
        os.rmdir(name, dir_fd=root_fd)
    except OSError:
        pass


def _validate_artifact_root(root: Path) -> None:
    if not root.is_absolute():
        raise ValueError("artifact root must be absolute")
    root_stat = root.lstat()
    if (
        not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_ISLNK(root_stat.st_mode)
        or stat.S_IMODE(root_stat.st_mode) != 0o700
        or (root_stat.st_uid, root_stat.st_gid) != (0, 0)
    ):
        raise PermissionError("artifact root must be root-owned mode 0700")
    current = root
    while current != current.parent:
        current_stat = current.lstat()
        if stat.S_ISLNK(current_stat.st_mode):
            raise PermissionError("artifact ancestors cannot be symlinks")
        current = current.parent


def prepare_race_live_rollback_bundle(
    *,
    event_id: int,
    reviewed_release_image_id: str,
    filtered_env_sha256: str,
    approved_commit: str,
    run_id: str,
    output_root: str | os.PathLike[str],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise PermissionError("rollback artifacts require root EUID")
    if (
        not isinstance(run_id, str)
        or _RUN_ID_RE.fullmatch(run_id) is None
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
    ):
        raise ValueError("run_id is invalid")
    root = Path(output_root)
    _validate_artifact_root(root)
    final = root / run_id
    bundle = build_race_live_rollback_bundle(
        event_id=event_id,
        reviewed_release_image_id=reviewed_release_image_id,
        filtered_env_sha256=filtered_env_sha256,
        approved_commit=approved_commit,
        generated_at=generated_at,
    )
    _scan_secret_free(bundle)
    manifest_bytes = _canonical_json(bundle["manifest"])
    report_bytes = _canonical_json(bundle["report"])
    sha_payload = {
        "manifest.json": hashlib.sha256(manifest_bytes).hexdigest(),
        "report.json": hashlib.sha256(report_bytes).hexdigest(),
    }
    sha_bytes = _canonical_json(sha_payload)
    staging = root / f".staging-{run_id}-{uuid.uuid4().hex}"
    staging_identity = None
    final_identity = None
    root_fd = os.open(
        root,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        root_stat = os.fstat(root_fd)
        if (
            stat.S_IMODE(root_stat.st_mode) != 0o700
            or (root_stat.st_uid, root_stat.st_gid) != (0, 0)
        ):
            raise PermissionError("artifact root identity is invalid")
        try:
            os.stat(run_id, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(final)
        os.mkdir(staging.name, mode=0o700, dir_fd=root_fd)
        staging_stat = os.stat(
            staging.name,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        staging_identity = (staging_stat.st_dev, staging_stat.st_ino)
        if (
            stat.S_IMODE(staging_stat.st_mode) != 0o700
            or (staging_stat.st_uid, staging_stat.st_gid) != (0, 0)
        ):
            raise PermissionError("rollback staging ownership is invalid")
        staging_fd = os.open(
            staging.name,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        try:
            _write_exclusive(
                "manifest.json",
                manifest_bytes,
                dir_fd=staging_fd,
            )
            _write_exclusive(
                "report.json",
                report_bytes,
                dir_fd=staging_fd,
            )
            _write_exclusive(
                "sha256s.json",
                sha_bytes,
                dir_fd=staging_fd,
            )
            os.fsync(staging_fd)
            _rename_no_replace_at(
                root_fd,
                staging.name,
                root_fd,
                run_id,
            )
            final_identity = staging_identity
            staging_identity = None
        finally:
            os.close(staging_fd)
        final_stat = os.stat(
            run_id,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        final_identity = (final_stat.st_dev, final_stat.st_ino)
        final_fd = os.open(
            run_id,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        try:
            os.fsync(final_fd)
            os.fsync(root_fd)
            if set(os.listdir(final_fd)) != {
                "manifest.json",
                "report.json",
                "sha256s.json",
            }:
                raise PermissionError("rollback artifact file set drifted")
            for filename in os.listdir(final_fd):
                file_stat = os.stat(
                    filename,
                    dir_fd=final_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(file_stat.st_mode)
                    or stat.S_IMODE(file_stat.st_mode) != 0o600
                    or (file_stat.st_uid, file_stat.st_gid) != (0, 0)
                    or file_stat.st_size > _MAX_ARTIFACT_BYTES
                ):
                    raise PermissionError(
                        "rollback artifact verification failed"
                    )
        finally:
            os.close(final_fd)
        current_root = root.lstat()
        if (
            current_root.st_dev,
            current_root.st_ino,
        ) != (root_stat.st_dev, root_stat.st_ino):
            raise PermissionError("artifact root path identity changed")
        return {
            "output_dir": str(final),
            "manifest_path": str(final / "manifest.json"),
            "manifest_sha256": sha_payload["manifest.json"],
            "report_sha256": sha_payload["report.json"],
        }
    except Exception:
        _remove_owned_directory_at(
            root_fd,
            staging.name,
            staging_identity,
        )
        _remove_owned_directory_at(root_fd, run_id, final_identity)
        try:
            os.fsync(root_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(root_fd)


def transition_race_live_rollback_maintenance(
    *,
    manifest: dict[str, Any],
    expected_manifest_sha256: str,
    expected_approved_commit: str,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        _validate_manifest(manifest)
        now = _aware(now or timezone.now(), "now")
        if (
            not isinstance(apply, bool)
            or _SHA256_RE.fullmatch(expected_manifest_sha256 or "") is None
            or _digest(manifest) != expected_manifest_sha256
            or manifest["approved_commit"] != expected_approved_commit
            or _COMMIT_RE.fullmatch(expected_approved_commit or "") is None
            or not _background_tasks_are_off()
        ):
            raise PermissionError("rollback maintenance input is invalid")
    except (TypeError, ValueError, PermissionError) as exc:
        return {
            "ok": False,
            "reason": "maintenance_input_invalid",
            "detail": str(exc),
        }

    event_id = manifest["event_id"]
    with transaction.atomic():
        list(
            models.RaceEventProjectionControl.objects.select_for_update()
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        tracking_rows = list(
            models.RaceEventLiveTracking.objects.select_for_update().order_by(
                "pk"
            )
        )
        if any(
            row.active_attempt_token or row.claim_expires_at is not None
            for row in tracking_rows
        ):
            return {"ok": False, "reason": "active_claims_exist"}
        try:
            baseline = _load_provisional_baseline(
                event_id=event_id,
                now=now,
                lock=True,
                require_public_policy=False,
            )
        except (TypeError, ValueError, PermissionError) as exc:
            return {
                "ok": False,
                "reason": "maintenance_baseline_invalid",
                "detail": str(exc),
            }
        if (
            _tracking_payload(baseline["tracking"])
            != manifest["expected_tracking_state"]
        ):
            return {"ok": False, "reason": "tracking_state_drift"}
        if (
            baseline["control"].current_result_revision_id
            != manifest["expected_current_revision_id"]
            or baseline["revision"].pk
            != manifest["expected_provisional_revision_id"]
            or baseline["publication"].pk
            != manifest["expected_publication_id"]
            or baseline["allowlist"].version
            != manifest["expected_allowlist_version"]
        ):
            return {"ok": False, "reason": "audit_pointer_drift"}
        actual = {
            key: _policy_payload(policy)
            for key, policy in baseline["policies"].items()
        }
        baseline_states = manifest["baseline_policies"]
        maintenance_states = {
            key: snapshots["maintenance"]
            for key, snapshots in manifest[
                "planned_policy_snapshot"
            ].items()
        }
        if actual == maintenance_states:
            return {
                "ok": True,
                "mode": "apply" if apply else "dry_run",
                "reason": "already_maintenance",
                "manifest_sha256": expected_manifest_sha256,
                "policy_transitions": maintenance_states,
            }
        if actual != baseline_states:
            return {"ok": False, "reason": "policy_baseline_drift"}
        transitions = {
            key: {
                "from": baseline_states[key],
                "to": maintenance_states[key],
            }
            for key in sorted(actual)
        }
        if not apply:
            return {
                "ok": True,
                "mode": "dry_run",
                "reason": "maintenance_ready",
                "manifest_sha256": expected_manifest_sha256,
                "policy_transitions": transitions,
            }
        for key, policy in baseline["policies"].items():
            target = maintenance_states[key]
            policy.mode = target["mode"]
            policy.version = target["version"]
            policy.registry_digest = target["registry_digest"]
            policy.coverage_proof_digest = target[
                "coverage_proof_digest"
            ]
            policy.valid_until = _parse_aware(
                target["valid_until"],
                "policy.valid_until",
            )
            policy.save(
                update_fields=(
                    "mode",
                    "version",
                    "registry_digest",
                    "coverage_proof_digest",
                    "valid_until",
                    "updated_at",
                )
            )
        from stable.services.race_events import resolve_race_live_public_read

        if resolve_race_live_public_read(
            event_id=event_id,
            now=now,
        ).visible:
            raise PermissionError("maintenance read gate remained visible")
        models.OperationLog.objects.create(
            action_type="race_live_rollback_maintenance",
            target_type="race_event",
            target_id=str(event_id),
            detail=json.dumps(
                {
                    "event_id": event_id,
                    "manifest_sha256": expected_manifest_sha256,
                    "changed_scopes": sorted(actual),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        return {
            "ok": True,
            "mode": "apply",
            "reason": "maintenance_applied",
            "manifest_sha256": expected_manifest_sha256,
            "policy_transitions": transitions,
        }
