from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from stable.models import (
    HistoricalRaceEventTarget,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RacingRegion,
)
from stable.services.historical_race_batches import target_identity
from stable.services.historical_race_date_discovery import validate_direct_source_urls
from stable.services.historical_race_inventory import (
    InventoryValidationError,
    canonical_json,
    file_identity,
)


DETAIL_SOURCE_ARTIFACT_SCHEMA_VERSION = "1.0"
SOURCE_NAME_TO_PROVIDER = {
    "jra_official_result_page": "jra",
    "keiba_go_jp": "nar",
    "netkeiba": "netkeiba",
    "hkjc_results_all_zh_hk": "hkjc",
    "sporting_life": "uk_sportinglife",
    "irishracing_uk": "uk_irishracing",
    "irishracing_france": "france_irishracing",
    "horse_racing_nation": "us_hrn",
    "equibase_pdf_chart": "equibase",
    "equibase_yearbook": "equibase",
    "nsa_official_result_pdf": "nsa",
    "zeturf": "zeturf",
    "zone_turf": "zone_turf",
}
PROVIDER_AUTHORITIES = {
    "jra": "official",
    "nar": "official",
    "netkeiba": "third_party_high_access",
    "hkjc": "official",
    "uk_sportinglife": "third_party_high_access",
    "uk_irishracing": "third_party_high_access",
    "france_irishracing": "third_party_high_access",
    "us_hrn": "third_party_high_access",
    "equibase": "third_party",
    "nsa": "official",
    "zeturf": "third_party_high_access",
    "zone_turf": "third_party_database",
}
PROVIDER_REGIONS = {
    "jra": RacingRegion.JAPAN,
    "nar": RacingRegion.JAPAN,
    "netkeiba": RacingRegion.JAPAN,
    "hkjc": RacingRegion.HONG_KONG,
    "uk_sportinglife": RacingRegion.UNITED_KINGDOM,
    "uk_irishracing": RacingRegion.UNITED_KINGDOM,
    "france_irishracing": RacingRegion.FRANCE,
    "us_hrn": RacingRegion.UNITED_STATES,
    "equibase": RacingRegion.UNITED_STATES,
    "nsa": RacingRegion.UNITED_STATES,
    "zeturf": RacingRegion.FRANCE,
    "zone_turf": RacingRegion.FRANCE,
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InventoryValidationError(f"detail source row is invalid JSON: {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise InventoryValidationError(f"detail source row must be an object: {path}:{line_number}")
            rows.append(row)
    return rows


def _artifact_path(root: Path, relative: Any, *, label: str) -> Path:
    text = str(relative or "").strip()
    path = (root / text).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise InventoryValidationError(f"{label} is outside artifact directory: {text}") from exc
    return path


def _source_cache_by_url(manifest_paths: Iterable[Path]) -> dict[str, tuple[dict[str, Any], Path]]:
    by_url: dict[str, tuple[dict[str, Any], Path]] = {}
    for manifest_path in manifest_paths:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InventoryValidationError(f"source cache manifest is unreadable: {manifest_path}") from exc
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0" or not isinstance(files, dict):
            raise InventoryValidationError(f"source cache manifest is invalid: {manifest_path}")
        root = manifest_path.parent.resolve()
        for identity in files.values():
            if not isinstance(identity, dict):
                raise InventoryValidationError(f"source cache identity is invalid: {manifest_path}")
            source = (root / str(identity.get("path") or "")).resolve()
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise InventoryValidationError(f"source cache path escapes manifest directory: {source}") from exc
            if not source.is_file():
                raise InventoryValidationError(f"source cache file is missing: {source}")
            body = source.read_bytes()
            if len(body) != int(identity.get("size") or -1) or hashlib.sha256(body).hexdigest() != identity.get(
                "sha256"
            ):
                raise InventoryValidationError(f"source cache identity changed: {source}")
            url = str(identity.get("source_url") or "").strip()
            if not url:
                raise InventoryValidationError(f"source cache URL is missing: {source}")
            existing = by_url.get(url)
            if existing is None or str(identity.get("cached_at") or "") > str(existing[0].get("cached_at") or ""):
                by_url[url] = (identity, source)
            elif str(identity.get("cached_at") or "") == str(existing[0].get("cached_at") or "") and identity != existing[0]:
                raise InventoryValidationError(f"source URL has ambiguous cache identities: {url}")
    return by_url


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_detail_source_artifact(
    *,
    candidate_jsonl_paths: Iterable[str | Path],
    source_cache_manifest_paths: Iterable[str | Path],
    output_dir: str | Path,
) -> dict[str, Any]:
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise InventoryValidationError(f"detail source artifact directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    candidates = []
    for path in candidate_jsonl_paths:
        candidates.extend(_read_jsonl(Path(path)))
    if not candidates:
        raise InventoryValidationError("detail source artifact has no candidates")
    cache_by_url = _source_cache_by_url(Path(path) for path in source_cache_manifest_paths)

    keys = [(int(row.get("year") or 0), str(row.get("slug") or "")) for row in candidates]
    if len(keys) != len(set(keys)):
        raise InventoryValidationError("detail source artifact has duplicate event candidates")
    event_query = Q()
    for year, slug in keys:
        event_query |= Q(event__year=year, event__slug=slug)
    targets = HistoricalRaceEventTarget.objects.select_related("race_series", "event").filter(event_query)
    targets_by_key = {(target.event.year, target.event.slug): target for target in targets}
    if set(keys) != set(targets_by_key):
        missing = sorted(set(keys) - set(targets_by_key))
        raise InventoryValidationError(f"detail source candidate is outside materialized targets: {missing[0]}")

    source_dir = root / "sources"
    source_dir.mkdir()
    rows = []
    review_rows = []
    for candidate in candidates:
        key = (int(candidate["year"]), str(candidate["slug"]))
        target = targets_by_key[key]
        if target.resolution_status != HistoricalRaceResolutionStatus.READY or not target.event_id:
            raise InventoryValidationError(f"detail source target must be ready and materialized: {target.pk}")
        modules = candidate.get("modules") if isinstance(candidate.get("modules"), dict) else {}
        if set(modules) != {"runners", "results"} or any(
            not isinstance(modules[name], dict) or not isinstance(modules[name].get("items"), list) or not modules[name]["items"]
            for name in ("runners", "results")
        ):
            raise InventoryValidationError(f"detail source candidate modules are incomplete: {target.pk}")
        source_name = str(candidate.get("source_name") or "").strip()
        provider = SOURCE_NAME_TO_PROVIDER.get(source_name)
        if not provider:
            raise InventoryValidationError(f"unsupported detail source name: {source_name}")
        if PROVIDER_REGIONS[provider] != target.country_region:
            raise InventoryValidationError(
                f"detail source provider region mismatch: {provider} != {target.country_region}"
            )
        source_url = str(candidate.get("source_url") or "").strip()
        authority = PROVIDER_AUTHORITIES[provider]
        normalized = validate_direct_source_urls(
            provider,
            {
                "result_url": {
                    "url": source_url,
                    "source_provider": provider,
                    "source_authority": authority,
                    "redirect_chain": [],
                }
            },
        )["result_url"]
        cached = cache_by_url.get(source_url)
        if cached is None:
            raise InventoryValidationError(f"detail source URL has no verified cache identity: {source_url}")
        original_identity, source = cached
        suffix = source.suffix if source.suffix else ".bin"
        copied = source_dir / f"target-{target.pk}{suffix}"
        body = source.read_bytes()
        copied.write_bytes(body)
        copied_identity = {
            "path": str(copied.relative_to(root)),
            "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "source_url": source_url,
            "cached_at": original_identity.get("cached_at") or "",
            "protected_by": [],
        }
        identity = target_identity(target)
        row = {
            "target_id": target.pk,
            "expected_target_sha256": identity["target_sha256"],
            "inventory_artifact_sha256": target.artifact_sha256,
            "year": target.year,
            "slug": target.event.slug,
            "source_name": source_name,
            "source_url": source_url,
            "source_provider": provider,
            "source_authority": authority,
            "redirect_chain": normalized.get("redirect_chain") or [],
            "source_cache_identity": copied_identity,
        }
        rows.append(row)
        review_rows.append(
            {
                "target_id": target.pk,
                "year": target.year,
                "slug": target.event.slug,
                "source_provider": provider,
                "source_url": source_url,
                "source_sha256": copied_identity["sha256"],
                "operator_decision": "",
                "operator_notes": "",
            }
        )

    rows.sort(key=lambda row: row["target_id"])
    candidates_path = root / "detail_source_candidates.jsonl"
    candidates_path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")
    review_path = root / "detail_source_review.csv"
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)
    artifact_files = {
        "detail_source_candidates": file_identity(candidates_path, relative_to=root).as_dict(),
        "detail_source_review": file_identity(review_path, relative_to=root).as_dict(),
        "sources": [file_identity(root / row["source_cache_identity"]["path"], relative_to=root).as_dict() for row in rows],
    }
    manifest = {
        "schema_version": DETAIL_SOURCE_ARTIFACT_SCHEMA_VERSION,
        "candidate_count": len(rows),
        "artifacts": artifact_files,
    }
    _write_json(root / "manifest.json", manifest)
    _write_json(
        root / "approval.json",
        {
            "status": "pending",
            "manifest_identity": file_identity(root / "manifest.json", relative_to=root).as_dict(),
            "approved_by": "",
            "approved_at": "",
            "approved_target_ids": [],
        },
    )
    return {
        "output_dir": str(root),
        "candidate_count": len(rows),
        "manifest": str(root / "manifest.json"),
        "approval": str(root / "approval.json"),
    }


def validate_detail_source_artifact(
    artifact_dir: str | Path,
    approval_path: str | Path,
    *,
    require_approved: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    root = Path(artifact_dir)
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        approval = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryValidationError("detail source artifact is unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != DETAIL_SOURCE_ARTIFACT_SCHEMA_VERSION:
        raise InventoryValidationError("detail source artifact schema is unsupported")
    if not isinstance(approval, dict):
        raise InventoryValidationError("detail source approval is invalid")
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    required = {"detail_source_candidates", "detail_source_review", "sources"}
    if set(artifacts) != required or not isinstance(artifacts["sources"], list):
        raise InventoryValidationError("detail source artifact manifest is incomplete")
    identities = [artifacts["detail_source_candidates"], artifacts["detail_source_review"], *artifacts["sources"]]
    for identity in identities:
        if not isinstance(identity, dict):
            raise InventoryValidationError("detail source artifact identity is invalid")
        path = _artifact_path(root, identity.get("path"), label="detail source artifact file")
        if not path.is_file() or file_identity(path, relative_to=root).as_dict() != identity:
            raise InventoryValidationError(f"detail source artifact changed after manifest: {identity.get('path')}")
    if approval.get("manifest_identity") != file_identity(manifest_path, relative_to=root).as_dict():
        raise InventoryValidationError("detail source approval does not match manifest")
    rows = _read_jsonl(_artifact_path(root, artifacts["detail_source_candidates"]["path"], label="detail source candidates"))
    if len(rows) != int(manifest.get("candidate_count") or -1):
        raise InventoryValidationError("detail source candidate count is inconsistent")
    source_identities = {identity["path"]: identity for identity in artifacts["sources"]}
    for row in rows:
        cache_identity = row.get("source_cache_identity") if isinstance(row.get("source_cache_identity"), dict) else {}
        artifact_identity = source_identities.get(cache_identity.get("path"))
        if artifact_identity is None or any(
            cache_identity.get(key) != artifact_identity.get(key) for key in ("path", "size", "sha256")
        ):
            raise InventoryValidationError(f"detail source cache identity is not in manifest: {row.get('target_id')}")
        validate_direct_source_urls(
            str(row.get("source_provider") or ""),
            {
                "result_url": {
                    "url": row.get("source_url"),
                    "source_provider": row.get("source_provider"),
                    "source_authority": row.get("source_authority"),
                    "redirect_chain": row.get("redirect_chain") or [],
                }
            },
        )
    if require_approved:
        if approval.get("status") != "approved" or not str(approval.get("approved_by") or "").strip() or not str(
            approval.get("approved_at") or ""
        ).strip():
            raise InventoryValidationError("detail source artifact is not approved")
        approved_ids = approval.get("approved_target_ids")
        candidate_ids = {int(row["target_id"]) for row in rows}
        if (
            not isinstance(approved_ids, list)
            or not approved_ids
            or not all(isinstance(value, int) and not isinstance(value, bool) for value in approved_ids)
            or len(approved_ids) != len(set(approved_ids))
        ):
            raise InventoryValidationError("detail source approved target ids are invalid")
        if not set(approved_ids).issubset(candidate_ids):
            raise InventoryValidationError("detail source approval includes unknown targets")
        rows = [row for row in rows if int(row["target_id"]) in set(approved_ids)]
    return manifest, approval, rows


def _locked_targets(target_ids: Iterable[int]):
    return HistoricalRaceEventTarget.objects.select_for_update().select_related("race_series").filter(pk__in=target_ids)


def _locked_events(event_ids: Iterable[int]):
    return RaceEvent.objects.select_for_update().filter(pk__in=event_ids)


def _validate_current_targets(rows: list[dict[str, Any]], targets: dict[int, HistoricalRaceEventTarget]) -> None:
    target_ids = {int(row["target_id"]) for row in rows}
    if set(targets) != target_ids:
        raise InventoryValidationError("detail source target disappeared after approval")
    for row in rows:
        target = targets[int(row["target_id"])]
        if target_identity(target)["target_sha256"] != row["expected_target_sha256"]:
            raise InventoryValidationError(f"detail source target changed after approval: {target.pk}")
        if target.artifact_sha256 != row["inventory_artifact_sha256"]:
            raise InventoryValidationError(f"detail source inventory changed after approval: {target.pk}")
        if target.resolution_status != HistoricalRaceResolutionStatus.READY or not target.event_id:
            raise InventoryValidationError(f"detail source target is no longer ready/materialized: {target.pk}")


def check_detail_source_artifact(*, artifact_dir: str | Path, approval_path: str | Path) -> dict[str, Any]:
    root = Path(artifact_dir)
    _manifest, approval, rows = validate_detail_source_artifact(root, approval_path)
    if not get_user_model().objects.filter(username=str(approval["approved_by"])).exists():
        raise InventoryValidationError("detail source approval operator does not exist")
    target_ids = {int(row["target_id"]) for row in rows}
    targets = {
        target.pk: target
        for target in HistoricalRaceEventTarget.objects.select_related("race_series", "event").filter(pk__in=target_ids)
    }
    _validate_current_targets(rows, targets)
    return {
        "manifest_sha256": file_identity(root / "manifest.json", relative_to=root).sha256,
        "checked_count": len(rows),
    }


def apply_detail_source_artifact(*, artifact_dir: str | Path, approval_path: str | Path) -> dict[str, Any]:
    if not getattr(settings, "HISTORICAL_RACE_BACKFILL_ENABLED", False):
        raise InventoryValidationError("historical race backfill is disabled")
    root = Path(artifact_dir)
    manifest, approval, rows = validate_detail_source_artifact(root, approval_path)
    actor = get_user_model().objects.filter(username=str(approval["approved_by"])).first()
    if actor is None:
        raise InventoryValidationError("detail source approval operator does not exist")
    target_ids = {int(row["target_id"]) for row in rows}
    manifest_sha = file_identity(root / "manifest.json", relative_to=root).sha256
    changes = []
    with transaction.atomic():
        targets = {target.pk: target for target in _locked_targets(target_ids)}
        _validate_current_targets(rows, targets)
        event_ids = {target.event_id for target in targets.values()}
        events = {event.pk: event for event in _locked_events(event_ids)}
        if set(events) != event_ids:
            raise InventoryValidationError("detail source event disappeared after approval")
        for row in rows:
            target = targets[int(row["target_id"])]
            before = target_identity(target)["target_sha256"]
            refs = dict(target.source_refs or {})
            discovery = dict(refs.get("detail_discovery") or {})
            approved_sources = list(discovery.get("approved_detail_sources") or [])
            evidence = {
                "url": row["source_url"],
                "source_provider": row["source_provider"],
                "source_authority": row["source_authority"],
                "redirect_chain": row.get("redirect_chain") or [],
                "source_cache_identity": row["source_cache_identity"],
                "artifact_manifest_sha256": manifest_sha,
                "approved_by": approval["approved_by"],
                "approved_at": approval["approved_at"],
            }
            approved_sources = [item for item in approved_sources if item.get("url") != row["source_url"]]
            approved_sources.append(evidence)
            discovery["approved_detail_sources"] = approved_sources
            refs["detail_discovery"] = discovery

            event = events[target.event_id]
            event_refs = dict(event.source_refs or {})
            event_discovery = dict(event_refs.get("detail_discovery") or {})
            event_sources = list(event_discovery.get("approved_detail_sources") or [])
            event_sources = [item for item in event_sources if item.get("url") != row["source_url"]]
            event_sources.append(dict(evidence))
            event_discovery["approved_detail_sources"] = event_sources
            event_refs["detail_discovery"] = event_discovery
            event.source_refs = event_refs
            event.save(update_fields={"source_refs"})

            target.source_refs = refs
            target.save(update_fields={"source_refs"})
            target.refresh_from_db()
            changes.append(
                {
                    "target_id": target.pk,
                    "before": before,
                    "after": target_identity(target)["target_sha256"],
                }
            )
        OperationLog.objects.create(
            admin=actor,
            action_type="historical_detail_sources_applied",
            target_type="detail_source_artifact",
            target_id=manifest_sha,
            detail=canonical_json(
                {
                    "manifest_sha256": manifest_sha,
                    "target_sha256_changes": changes,
                }
            ),
        )
    return {
        "manifest_sha256": manifest_sha,
        "applied_count": len(changes),
        "target_sha256_changes": changes,
    }
