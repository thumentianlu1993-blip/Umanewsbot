"""BASIC-tier publish gate and first-publish channels for P0 horse profiles.

The gate decides whether a profile may be publicly shown. Identity trust
comes only from ``source_refs.horse_identity_verified_keys`` — keys written
by the fail-closed identity enrichment commit or by a human-reviewed batch
commit. Flat ``horse_identity_keys`` attributed by source sync (name
matching) never satisfy the gate.

Three publish paths share the same gate and the same audited writer
(``transition_review_status``): manual admin publish, batch-commit auto
first publish, and the approved stock publish command.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from django.db import transaction
from django.db.models import QuerySet

from stable.models import HorseProfile, HorseProfileStatus
from stable.services.horse_profiles import transition_review_status
from stable.services.p0_horse_profiles import P0_REGIONS

PUBLISH_SCHEMA_VERSION = "p0-horse-publish.v1"
PUBLISH_COMMIT_CHUNK_SIZE = 500

# Only keys from these namespaces may satisfy the identity branch; unmapped
# namespaces are neutral evidence, not publish-grade trust.
BASIC_GATE_IDENTITY_NAMESPACES = ("netkeiba", "nar", "hkjc", "sporting_life")

AUTO_PUBLISH_LOCK_KEY = "auto_publish_blocked"


class P0HorsePublishError(Exception):
    """Raised when a publish operation must fail closed."""


@dataclass(frozen=True)
class PublishGateResult:
    eligible: bool
    blocking_reasons: tuple[str, ...] = field(default_factory=tuple)


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


def _verified_namespaces(profile: HorseProfile) -> set[str]:
    refs = profile.source_refs if isinstance(profile.source_refs, dict) else {}
    namespaces = set()
    for key in refs.get("horse_identity_verified_keys") or []:
        parts = str(key).split(":", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            namespaces.add(parts[0].strip().casefold())
    return namespaces


def evaluate_basic_publish_gate(profile: HorseProfile) -> PublishGateResult:
    """Evaluate the BASIC-tier horse-profile publication contract."""
    reasons: list[str] = []
    if not str(profile.display_name or "").strip():
        reasons.append("gate.name")
    if profile.racing_region not in P0_REGIONS:
        reasons.append("gate.region")
    has_verified_identity = bool(
        _verified_namespaces(profile) & set(BASIC_GATE_IDENTITY_NAMESPACES)
    )
    has_three_fields = bool(
        str(profile.sire_text or "").strip()
        and str(profile.dam_text or "").strip()
        and profile.birth_date
    )
    if not (has_verified_identity or has_three_fields):
        reasons.append("gate.identity")
    if profile.review_status == HorseProfileStatus.HIDDEN or profile.hidden_at is not None:
        reasons.append("state.hidden")
    if (profile.manual_lock_flags or {}).get(AUTO_PUBLISH_LOCK_KEY):
        reasons.append("state.locked")
    return PublishGateResult(eligible=not reasons, blocking_reasons=tuple(reasons))


def auto_publish_profiles(
    profiles: Iterable[HorseProfile | int],
    *,
    user: Any,
    note: str,
) -> dict[str, Any]:
    """Publish gate-passing profiles via the audited transition channel.

    Per-profile isolation: one failure never aborts the loop; already
    published profiles are counted as skipped; gate-blocked profiles are
    counted with their reasons.
    """
    report: dict[str, Any] = {
        "published": 0,
        "skipped_already_published": 0,
        "blocked": 0,
        "blocked_reasons": {},
        "published_profile_ids": [],
        "errors": [],
    }
    if isinstance(profiles, QuerySet) and profiles.query.select_for_update:
        raise P0HorsePublishError(
            "auto publish accepts IDs or a non-locking queryset only"
        )
    profile_ids = [
        int(profile.pk if isinstance(profile, HorseProfile) else profile)
        for profile in profiles
    ]
    for profile_id in profile_ids:
        try:
            outcome: tuple[str, Any]
            # PostgreSQL requires the locking read to be evaluated inside the
            # transaction. Re-read and re-check the gate under that row lock.
            with transaction.atomic():
                profile = HorseProfile.objects.select_for_update().get(
                    pk=profile_id
                )
                if profile.review_status == HorseProfileStatus.PUBLISHED:
                    outcome = ("skipped", None)
                else:
                    gate = evaluate_basic_publish_gate(profile)
                    if not gate.eligible:
                        outcome = ("blocked", gate.blocking_reasons)
                    else:
                        transition_review_status(
                            profile,
                            HorseProfileStatus.PUBLISHED,
                            user=user,
                            note=note,
                        )
                        outcome = ("published", profile.pk)
            if outcome[0] == "skipped":
                report["skipped_already_published"] += 1
            elif outcome[0] == "blocked":
                report["blocked"] += 1
                for reason in outcome[1]:
                    report["blocked_reasons"][reason] = (
                        report["blocked_reasons"].get(reason, 0) + 1
                    )
            else:
                report["published"] += 1
                report["published_profile_ids"].append(outcome[1])
        except Exception as exc:  # noqa: BLE001 - per-profile isolation
            report["errors"].append(
                {"profile_id": profile_id, "error": str(exc)}
            )
    return report


def build_publish_dry_run_artifact(
    *,
    regions: Iterable[str],
    profile_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    region_list = list(regions)
    profiles = list(
        HorseProfile.objects.filter(
            racing_region__in=region_list,
            review_status__in=(HorseProfileStatus.DRAFT, HorseProfileStatus.READY),
        )
        .select_related("primary_term")
        .order_by("racing_region", "id")
    )
    if profile_ids is not None:
        wanted = {int(value) for value in profile_ids}
        profiles = [profile for profile in profiles if profile.pk in wanted]

    candidates: list[dict[str, Any]] = []
    blocked_histogram: dict[str, int] = {}
    for profile in profiles:
        gate = evaluate_basic_publish_gate(profile)
        if gate.eligible:
            candidates.append(
                {
                    "profile_id": profile.pk,
                    "horse_name": profile.original_name,
                    "region": profile.racing_region,
                }
            )
        else:
            for reason in gate.blocking_reasons:
                blocked_histogram[reason] = blocked_histogram.get(reason, 0) + 1

    stats = {
        "profiles_evaluated": len(profiles),
        "candidates": len(candidates),
        "blocked": len(profiles) - len(candidates),
        "blocked_reasons": blocked_histogram,
        "by_region": {
            region: {
                "profiles": sum(1 for p in profiles if p.racing_region == region),
                "candidates": sum(1 for c in candidates if c["region"] == region),
            }
            for region in region_list
        },
    }
    return {
        "schema_version": PUBLISH_SCHEMA_VERSION,
        "generated_at": _utcnow_iso(),
        "regions": region_list,
        "candidates": candidates,
        "stats": stats,
        "metrics_before": _publish_metrics(region_list),
    }


def _publish_metrics(regions: Iterable[str]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for region in regions:
        base = HorseProfile.objects.filter(racing_region=region)
        published = base.filter(review_status=HorseProfileStatus.PUBLISHED).count()
        total = base.filter(
            review_status__in=(
                HorseProfileStatus.DRAFT,
                HorseProfileStatus.READY,
                HorseProfileStatus.PUBLISHED,
            )
        ).count()
        metrics[region] = {
            "profiles_total": total,
            "published": published,
        }
    return {
        "schema_version": f"{PUBLISH_SCHEMA_VERSION}-metrics",
        "generated_at": _utcnow_iso(),
        "regions": metrics,
    }


def write_publish_manifest(
    artifact: dict[str, Any],
    *,
    output_dir: str | Path,
) -> Path:
    out = Path(output_dir)
    artifact_sha = _write_json(out / "publish_artifact.json", artifact)
    manifest = {
        "schema_version": f"{PUBLISH_SCHEMA_VERSION}-manifest",
        "status": "pending",
        "created_at": _utcnow_iso(),
        "regions": artifact["regions"],
        "artifact_path": str(out / "publish_artifact.json"),
        "artifact_sha256": artifact_sha,
        "stats": artifact["stats"],
        "approval": None,
    }
    _write_json(out / "publish_manifest.json", manifest)
    return out / "publish_manifest.json"


def approve_publish_manifest(
    manifest_path: str | Path,
    *,
    reviewer: str,
) -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    schema = str(manifest.get("schema_version") or "")
    if not schema.startswith(PUBLISH_SCHEMA_VERSION):
        raise P0HorsePublishError(f"manifest schema mismatch: {schema or 'unknown'}")
    reviewer_text = str(reviewer or "").strip()
    if not reviewer_text:
        raise P0HorsePublishError("approval requires a reviewer")
    if manifest.get("status") != "pending":
        raise P0HorsePublishError("manifest is not pending")
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
) -> dict[str, Any]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    schema = str(manifest.get("schema_version") or "")
    if not schema.startswith(PUBLISH_SCHEMA_VERSION):
        raise P0HorsePublishError(f"manifest schema mismatch: {schema or 'unknown'}")
    if manifest.get("status") != "approved" or not (manifest.get("approval") or {}).get(
        "reviewer"
    ):
        raise P0HorsePublishError("manifest is not approved")
    recomputed = _sha256(
        {key: value for key, value in manifest.items() if key != "approved_sha256"}
    )
    if manifest.get("approved_sha256") != recomputed:
        raise P0HorsePublishError("manifest drifted after approval")
    if manifest.get("approved_sha256") != approved_sha256:
        raise P0HorsePublishError("approved SHA-256 mismatch")
    artifact_path = Path(manifest["artifact_path"])
    artifact_bytes = artifact_path.read_bytes()
    actual_sha = hashlib.sha256(artifact_bytes).hexdigest()
    if actual_sha != manifest["artifact_sha256"]:
        raise P0HorsePublishError("artifact SHA-256 drift")
    return json.loads(artifact_bytes)


def commit_approved_publish_manifest(
    manifest_path: str | Path,
    *,
    approved_sha256: str,
    reviewer: Any,
) -> dict[str, Any]:
    artifact = _load_approved_artifact(manifest_path, approved_sha256=approved_sha256)
    if reviewer is None or not (
        getattr(reviewer, "is_active", False) and getattr(reviewer, "is_superuser", False)
    ):
        raise P0HorsePublishError(
            "publish commit requires an active superuser reviewer"
        )
    candidates = artifact["candidates"]
    note = f"stock first publish (manifest sha256 {approved_sha256})"
    report: dict[str, Any] = {"regions": {}}
    for region in artifact["regions"]:
        region_candidates = [c for c in candidates if c["region"] == region]
        published = skipped = blocked = 0
        errors: list[dict[str, Any]] = []
        for start in range(0, len(region_candidates), PUBLISH_COMMIT_CHUNK_SIZE):
            chunk = region_candidates[start : start + PUBLISH_COMMIT_CHUNK_SIZE]
            chunk_report = auto_publish_profiles(
                [c["profile_id"] for c in chunk],
                user=reviewer,
                note=note,
            )
            published += chunk_report["published"]
            skipped += chunk_report["skipped_already_published"]
            blocked += chunk_report["blocked"]
            errors.extend(chunk_report["errors"])
        report["regions"][region] = {
            "published": published,
            "skipped_already_published": skipped,
            "blocked": blocked,
            "errors": errors,
        }
    report["metrics_after"] = _publish_metrics(artifact["regions"])
    return report
