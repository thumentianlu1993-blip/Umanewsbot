from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from stable import models


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DISALLOWED_RECEIPT_KEYS = {
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "page_html",
    "raw_html",
    "raw_page",
    "token",
}


class RecoveryOfficialReceiptError(ValueError):
    def __init__(self, reason_code: str, message: str = ""):
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class RecoveryParticipantIdentityError(ValueError):
    def __init__(self, reason_code: str, message: str = ""):
        self.reason_code = reason_code
        super().__init__(message or reason_code)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _aware_datetime(value: Any, *, reason_code: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RecoveryOfficialReceiptError(reason_code) from exc
    else:
        raise RecoveryOfficialReceiptError(reason_code)
    if timezone.is_naive(parsed):
        raise RecoveryOfficialReceiptError(reason_code)
    return parsed


def _route_from_registry(
    route_registry: Mapping[str, Any], route_key: str
) -> Mapping[str, Any]:
    routes = route_registry.get("routes")
    if isinstance(routes, Mapping):
        route = routes.get(route_key)
    elif route_registry.get("route") == route_key:
        route = route_registry
    else:
        raise RecoveryOfficialReceiptError("route_registry_invalid")
    if not isinstance(route, Mapping):
        raise RecoveryOfficialReceiptError("route_not_approved")
    return route


def _validate_url(source_url: str, route: Mapping[str, Any]) -> None:
    try:
        parsed = urlsplit(source_url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise RecoveryOfficialReceiptError("route_url_invalid") from exc
    hosts = route.get("allowed_hosts")
    if not isinstance(hosts, list):
        hosts = [route.get("host")]
    allowed_hosts = {
        str(value or "").casefold() for value in hosts if str(value or "")
    }
    prefixes = route.get("allowed_path_prefixes")
    if not isinstance(prefixes, list):
        prefixes = [route.get("path_prefix")]
    path_prefixes = [
        str(value or "") for value in prefixes if str(value or "")
    ]
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in allowed_hosts
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not path_prefixes
        or not any(parsed.path.startswith(prefix) for prefix in path_prefixes)
    ):
        raise RecoveryOfficialReceiptError("route_url_outside_allowlist")


def _validate_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise RecoveryOfficialReceiptError("official_rows_missing")
    normalized: list[dict[str, Any]] = []
    seen_orders: set[int] = set()
    valid_statuses = set(models.RaceEventRevisionItemStatus.values)
    for row in rows:
        if not isinstance(row, Mapping):
            raise RecoveryOfficialReceiptError("official_row_invalid")
        order = row.get("internal_order")
        if (
            isinstance(order, bool)
            or not isinstance(order, int)
            or order <= 0
            or order in seen_orders
        ):
            raise RecoveryOfficialReceiptError("internal_order_invalid")
        seen_orders.add(order)
        official_position = row.get("official_finish_position")
        if (
            official_position is not None
            and (
                isinstance(official_position, bool)
                or not isinstance(official_position, int)
                or official_position <= 0
            )
        ):
            raise RecoveryOfficialReceiptError("official_position_invalid")
        status = str(row.get("status") or "")
        if status not in valid_statuses:
            raise RecoveryOfficialReceiptError("result_status_invalid")
        provenance = row.get("field_provenance")
        if not isinstance(provenance, Mapping) or not provenance:
            raise RecoveryOfficialReceiptError("field_provenance_missing")
        normalized.append(
            {
                "external_runner_id": str(
                    row.get("external_runner_id") or ""
                ).strip(),
                "official_name": str(row.get("official_name") or "").strip(),
                "horse_number": str(row.get("horse_number") or "").strip(),
                "internal_order": order,
                "official_finish_position": official_position,
                "status": status,
                "raw_status": str(row.get("raw_status") or "").strip(),
                "jockey_name": str(row.get("jockey_name") or "").strip(),
                "trainer_name": str(row.get("trainer_name") or "").strip(),
                "finish_time": str(row.get("finish_time") or "").strip(),
                "margin": str(row.get("margin") or "").strip(),
                "field_provenance": dict(provenance),
            }
        )
    normalized.sort(key=lambda item: item["internal_order"])
    if [row["internal_order"] for row in normalized] != list(
        range(1, len(normalized) + 1)
    ):
        raise RecoveryOfficialReceiptError("internal_order_not_contiguous")
    return normalized


def validate_recovery_official_receipt(
    *,
    receipt: Mapping[str, Any],
    route_registry: Mapping[str, Any],
    expected_event_id: int,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise RecoveryOfficialReceiptError("receipt_invalid")
    if _DISALLOWED_RECEIPT_KEYS & set(receipt):
        raise RecoveryOfficialReceiptError("restricted_page_material_forbidden")
    if receipt.get("schema_version") != 1:
        raise RecoveryOfficialReceiptError("receipt_schema_invalid")
    if int(receipt.get("event_id") or 0) != int(expected_event_id):
        raise RecoveryOfficialReceiptError("event_identity_drift")
    if not isinstance(now, datetime) or timezone.is_naive(now):
        raise RecoveryOfficialReceiptError("now_invalid")

    route_key = str(receipt.get("route_key") or "")
    route = _route_from_registry(route_registry, route_key)
    if route.get("access_mode") != "manual_browser_only":
        raise RecoveryOfficialReceiptError("route_access_mode_invalid")
    route_region = str(
        route.get("region") or route.get("country_region") or ""
    )
    if str(receipt.get("region") or "") != route_region:
        raise RecoveryOfficialReceiptError("route_region_drift")
    route_markers = route.get("allowed_marker_types")
    if not isinstance(route_markers, list):
        route_markers = [route.get("marker")]
    if str(receipt.get("marker") or "") not in {
        str(value or "") for value in route_markers
    }:
        raise RecoveryOfficialReceiptError("route_marker_drift")
    route_source_key = str(route.get("source_key") or "")
    if route_source_key and str(receipt.get("source_key") or "") != route_source_key:
        raise RecoveryOfficialReceiptError("route_source_drift")
    if (
        str(receipt.get("route_contract_digest") or "")
        != str(route.get("contract_digest") or "")
        or _SHA256_RE.fullmatch(
            str(receipt.get("route_contract_digest") or "")
        )
        is None
    ):
        raise RecoveryOfficialReceiptError("route_digest_drift")
    route_terms_digest = str(
        route.get("terms_digest")
        or (
            route.get("terms_evidence", {}).get("sha256")
            if isinstance(route.get("terms_evidence"), Mapping)
            else ""
        )
        or ""
    )
    if (
        str(receipt.get("terms_digest") or "")
        != route_terms_digest
        or _SHA256_RE.fullmatch(str(receipt.get("terms_digest") or "")) is None
    ):
        raise RecoveryOfficialReceiptError("terms_digest_drift")

    route_valid_until = _aware_datetime(
        route.get("valid_until") or route_registry.get("valid_until"),
        reason_code="route_validity_invalid",
    )
    receipt_valid_until = _aware_datetime(
        receipt.get("valid_until"), reason_code="route_validity_invalid"
    )
    if now > route_valid_until or now > receipt_valid_until:
        raise RecoveryOfficialReceiptError("route_expired")
    observed_at = _aware_datetime(
        receipt.get("observed_at"), reason_code="observed_at_invalid"
    )
    if observed_at > now:
        raise RecoveryOfficialReceiptError("observed_at_in_future")

    source_url = str(receipt.get("source_url") or "").strip()
    _validate_url(source_url, route)
    registry_digest = _sha256(route_registry)
    supplied_registry_digest = str(
        receipt.get("route_registry_digest") or ""
    )
    if supplied_registry_digest and supplied_registry_digest != registry_digest:
        raise RecoveryOfficialReceiptError("route_registry_digest_drift")
    rows = _validate_rows(receipt.get("rows"))
    evidence_sha = str(receipt.get("evidence_sha256") or "")
    if _SHA256_RE.fullmatch(evidence_sha) is None or evidence_sha != _sha256(
        receipt.get("rows")
    ):
        raise RecoveryOfficialReceiptError("evidence_digest_mismatch")

    normalized = {
        "schema_version": 1,
        "event_id": int(expected_event_id),
        "region": str(receipt["region"]),
        "route_key": route_key,
        "source_key": str(receipt.get("source_key") or "").strip(),
        "source_url": source_url,
        "marker": str(receipt["marker"]),
        "observed_at": observed_at.isoformat(),
        "valid_until": min(route_valid_until, receipt_valid_until).isoformat(),
        "route_contract_digest": str(receipt["route_contract_digest"]),
        "terms_digest": str(receipt["terms_digest"]),
        "route_registry_digest": registry_digest,
        "evidence_sha256": evidence_sha,
        "authority": "official",
        "rows": rows,
    }
    normalized["receipt_sha256"] = _sha256(normalized)
    return normalized


def validate_recovery_official_receipt_batch(
    *,
    receipts: list[Mapping[str, Any]],
    route_registry: Mapping[str, Any],
    expected_event_ids: list[int] | tuple[int, ...],
    now: datetime,
) -> dict[str, Any]:
    ids = [int(value) for value in expected_event_ids]
    if not ids or len(ids) != len(set(ids)):
        raise RecoveryOfficialReceiptError("batch_event_scope_invalid")
    if not isinstance(receipts, list):
        raise RecoveryOfficialReceiptError("batch_receipts_invalid")
    by_event: dict[int, Mapping[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise RecoveryOfficialReceiptError("batch_receipts_invalid")
        event_id = int(receipt.get("event_id") or 0)
        if event_id in by_event:
            raise RecoveryOfficialReceiptError("batch_event_duplicate")
        by_event[event_id] = receipt
    if set(by_event) != set(ids):
        raise RecoveryOfficialReceiptError("batch_event_scope_drift")
    validated = [
        validate_recovery_official_receipt(
            receipt=by_event[event_id],
            route_registry=route_registry,
            expected_event_id=event_id,
            now=now,
        )
        for event_id in ids
    ]
    payload = {
        "schema_version": 1,
        "artifact_kind": "race_result_recovery_official_receipt_batch",
        "event_ids": ids,
        "route_registry_digest": _sha256(route_registry),
        "receipts": validated,
    }
    payload["batch_sha256"] = _sha256(payload)
    return payload


def write_immutable_receipt_batch(
    batch: Mapping[str, Any], output_path: str | Path
) -> dict[str, Any]:
    supplied = dict(batch)
    batch_sha = str(supplied.pop("batch_sha256", ""))
    if _SHA256_RE.fullmatch(batch_sha) is None or batch_sha != _sha256(
        supplied
    ):
        raise RecoveryOfficialReceiptError("batch_sha256_mismatch")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RecoveryOfficialReceiptError("batch_artifact_exists")
    body = json.dumps(
        batch, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o444)
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return {
        "path": str(path.resolve()),
        "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "batch_sha256": batch_sha,
    }


@transaction.atomic
def bind_recovery_participants(
    *,
    event: models.RaceEvent,
    source_identity: models.RaceResultSourceIdentity,
    rows: list[Mapping[str, Any]],
    manifest_sha256: str,
) -> list[dict[str, Any]]:
    if _SHA256_RE.fullmatch(str(manifest_sha256 or "")) is None:
        raise RecoveryParticipantIdentityError("manifest_sha256_invalid")
    if source_identity.event_id != event.pk:
        raise RecoveryParticipantIdentityError("source_event_mismatch")
    if (
        source_identity.review_status != models.RaceLiveReviewStatus.APPROVED
        or source_identity.result_authority
        != models.RaceResultSourceAuthority.OFFICIAL
    ):
        raise RecoveryParticipantIdentityError("source_identity_not_official")

    bindings: list[dict[str, Any]] = []
    used_participants: set[int] = set()
    for row in sorted(rows, key=lambda value: int(value["internal_order"])):
        runner_id = str(row.get("external_runner_id") or "").strip()
        official_name = str(row.get("official_name") or "").strip()
        if not official_name:
            raise RecoveryParticipantIdentityError("official_name_missing")
        participant = None
        identity = None
        if runner_id:
            identities = list(
                models.RaceEventParticipantSourceIdentity.objects.select_related(
                    "participant"
                ).filter(
                    source_identity=source_identity,
                    external_runner_id=runner_id,
                )
            )
            if len(identities) > 1:
                raise RecoveryParticipantIdentityError(
                    "participant_ambiguous"
                )
            if identities:
                identity = identities[0]
                participant = identity.participant

        if participant is None:
            exact = list(
                models.RaceEventParticipant.objects.filter(
                    event=event,
                    canonical_name=official_name,
                ).order_by("pk")
            )
            if len(exact) > 1:
                raise RecoveryParticipantIdentityError(
                    "participant_ambiguous"
                )
            if exact:
                participant = exact[0]
            else:
                stable_digest = hashlib.sha256(
                    _canonical_bytes(
                        {
                            "source_key": source_identity.source_key,
                            "runner_id": runner_id,
                            "official_name": official_name,
                            "horse_number": str(
                                row.get("horse_number") or ""
                            ).strip(),
                            "manifest_sha256": manifest_sha256,
                        }
                    )
                ).hexdigest()
                participant = models.RaceEventParticipant.objects.create(
                    event=event,
                    stable_key=f"recovery:{stable_digest[:96]}",
                    canonical_name=official_name,
                    country_region=event.country_region,
                    review_status=models.RaceLiveReviewStatus.APPROVED,
                )
            if identity is None:
                identity, _created = (
                    models.RaceEventParticipantSourceIdentity.objects.get_or_create(
                        participant=participant,
                        source_identity=source_identity,
                        defaults={"external_runner_id": runner_id},
                    )
                )
                if (
                    identity.external_runner_id
                    and identity.external_runner_id != runner_id
                ):
                    raise RecoveryParticipantIdentityError(
                        "participant_identity_drift"
                    )
        if participant.event_id != event.pk:
            raise RecoveryParticipantIdentityError("participant_event_mismatch")
        if participant.canonical_name != official_name:
            raise RecoveryParticipantIdentityError(
                "participant_name_drift"
            )
        if participant.pk in used_participants:
            raise RecoveryParticipantIdentityError(
                "participant_duplicate_binding"
            )
        used_participants.add(participant.pk)
        bindings.append(
            {
                "internal_order": int(row["internal_order"]),
                "participant_id": participant.pk,
                "source_identity_id": identity.pk if identity else None,
                "external_runner_id": runner_id,
            }
        )
    return bindings
