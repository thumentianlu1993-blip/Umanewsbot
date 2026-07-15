#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse


SCHEMA_VERSION = "1.0"
OUTPUT_FILES = (
    "coverage_ledger.jsonl",
    "historical_hard_selection.jsonl",
    "historical_best_effort_selection.jsonl",
    "new_formal_selection.jsonl",
    "priority_shards.json",
    "gap_review_ledger.jsonl",
    "summary.json",
)
HEX64 = re.compile(r"[0-9a-f]{64}")


class CoveragePolicyError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identity(path: Path, root: Path | None = None) -> dict[str, Any]:
    shown = str(path.relative_to(root)) if root is not None else str(path)
    return {"path": shown, "sha256": _sha256(path), "size": path.stat().st_size}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoveragePolicyError(f"JSON is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CoveragePolicyError(f"JSON object is required: {path}")
    return value


def _resolve_inside(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise CoveragePolicyError(f"artifact path escapes root: {raw_path}") from exc
    return candidate


def _check_identity(root: Path, claimed: dict[str, Any], *, label: str) -> Path:
    if not isinstance(claimed, dict):
        raise CoveragePolicyError(f"{label} identity is missing")
    path = _resolve_inside(root, str(claimed.get("path") or ""))
    if not path.is_file():
        raise CoveragePolicyError(f"{label} identity path is missing")
    if path.stat().st_size != int(claimed.get("size", -1)) or _sha256(path) != claimed.get("sha256"):
        raise CoveragePolicyError(f"{label} identity mismatch")
    return path


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CoveragePolicyError(f"invalid JSONL at {path}:{line_no}") from exc
            if not isinstance(row, dict):
                raise CoveragePolicyError(f"JSONL object required at {path}:{line_no}")
            yield row


class _StreamingJson:
    def __init__(self, path: Path) -> None:
        self.handle = path.open(encoding="utf-8")
        self.buffer = ""
        self.pos = 0
        self.decoder = json.JSONDecoder()

    def close(self) -> None:
        self.handle.close()

    def _compact(self) -> None:
        if self.pos > 1024 * 1024:
            self.buffer = self.buffer[self.pos :]
            self.pos = 0

    def _fill(self) -> bool:
        self._compact()
        chunk = self.handle.read(1024 * 1024)
        if not chunk:
            return False
        self.buffer += chunk
        return True

    def _skip(self) -> None:
        while True:
            while self.pos < len(self.buffer) and self.buffer[self.pos].isspace():
                self.pos += 1
            if self.pos < len(self.buffer) or not self._fill():
                return

    def char(self, expected: str) -> None:
        self._skip()
        if self.pos >= len(self.buffer) and not self._fill():
            raise CoveragePolicyError("unexpected end of package JSON")
        if self.buffer[self.pos] != expected:
            raise CoveragePolicyError(f"expected {expected!r} in package JSON")
        self.pos += 1

    def value(self) -> Any:
        while True:
            self._skip()
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.pos)
            except json.JSONDecodeError:
                if not self._fill():
                    raise CoveragePolicyError("invalid package JSON")
                continue
            self.pos = end
            return value

    def array(self) -> Iterator[Any]:
        self.char("[")
        self._skip()
        if self.pos < len(self.buffer) and self.buffer[self.pos] == "]":
            self.pos += 1
            return
        while True:
            yield self.value()
            self._skip()
            if self.pos >= len(self.buffer) and not self._fill():
                raise CoveragePolicyError("unterminated package array")
            token = self.buffer[self.pos]
            self.pos += 1
            if token == "]":
                return
            if token != ",":
                raise CoveragePolicyError("invalid package array separator")


def _stream_package(path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    reader = _StreamingJson(path)
    try:
        reader.char("{")
        first = True
        while True:
            reader._skip()
            if reader.pos < len(reader.buffer) and reader.buffer[reader.pos] == "}":
                reader.pos += 1
                break
            if not first:
                reader.char(",")
            key = reader.value()
            if not isinstance(key, str):
                raise CoveragePolicyError("package key must be text")
            reader.char(":")
            if key in {"records", "gaps"}:
                for item in reader.array():
                    if not isinstance(item, dict):
                        raise CoveragePolicyError(f"package {key} item must be an object")
                    yield key[:-1] if key.endswith("s") else key, item
            else:
                value = reader.value()
                if key in {"record_count", "gap_count", "accounted_count", "target_count", "scope_count"}:
                    yield "scalar", {key: value}
            first = False
    finally:
        reader.close()


def _load_v9(v9_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_path = v9_root / "manifest.json"
    manifest = _read_json(manifest_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CoveragePolicyError("v9 manifest artifacts are invalid")
    master_path = _check_identity(v9_root, artifacts.get("master_selection.json"), label="v9 master_selection")
    master = _read_json(master_path)
    remaining_from_manifest = artifacts.get("remaining_targets.jsonl")
    remaining_from_master = master.get("remaining_targets")
    if remaining_from_manifest != remaining_from_master:
        raise CoveragePolicyError("v9 remaining target identity disagrees between manifest and master selection")
    remaining_path = _check_identity(v9_root, remaining_from_master, label="v9 remaining targets")
    inventory_sha = str(master.get("inventory_manifest_sha256") or "")
    if not HEX64.fullmatch(inventory_sha):
        raise CoveragePolicyError("v9 inventory SHA is invalid")
    targets: list[dict[str, Any]] = []
    identities: dict[int, str] = {}
    for row in _iter_jsonl(remaining_path):
        try:
            target_id = int(row["target_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CoveragePolicyError("v9 target identity is invalid") from exc
        target_sha = str(row.get("target_sha256") or "")
        if target_id <= 0 or not HEX64.fullmatch(target_sha):
            raise CoveragePolicyError("v9 target identity is invalid")
        if target_id in identities:
            raise CoveragePolicyError("duplicate target_id in v9 remaining targets")
        if row.get("inventory_artifact_sha256") != inventory_sha:
            raise CoveragePolicyError("v9 inventory SHA cross-check failed")
        identities[target_id] = target_sha
        targets.append(row)
    expected_count = int(manifest.get("target_count", -1))
    if expected_count != len(targets) or int(master.get("unresolved_target_count", -1)) != len(targets):
        raise CoveragePolicyError("v9 remaining target count identity mismatch")
    return targets, {
        "manifest": _identity(manifest_path),
        "master_selection": _identity(master_path),
        "remaining_targets": _identity(remaining_path),
        "inventory_manifest_sha256": inventory_sha,
        "upstream_inventory_identity_status": "unverified",
        "upstream_inventory_identity_reason": "v9 does not contain the upstream inventory path, size, or target count",
    }


def _load_v6(v6_root: Path) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    manifest_path = v6_root / "manifest.json"
    manifest = _read_json(manifest_path)
    report_path = _check_identity(v6_root, manifest.get("execution_report_identity"), label="v6 execution report")
    report = _read_json(report_path)
    main = report.get("main_descriptors")
    smoke = report.get("smoke")
    if smoke is None:
        smoke = report.get("smoke_descriptors")
    if not isinstance(main, list) or len(main) != int(manifest.get("descriptor_count", -1)):
        raise CoveragePolicyError("v6 main descriptor count identity mismatch")
    if not isinstance(smoke, list) or len(smoke) != int(manifest.get("smoke_descriptor_count", -1)):
        raise CoveragePolicyError("v6 smoke descriptor count identity mismatch")
    manifest_artifacts = {
        (str(item.get("path")), str(item.get("sha256")), int(item.get("size", -1)))
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict)
    }
    statuses: dict[int, dict[str, Any]] = {}
    package_identities: list[dict[str, Any]] = []
    main_shard_ids = {str(item.get("shard_id") or "") for item in main}
    smoke_shard_ids = {str(item.get("shard_id") or "") for item in smoke}
    if "" in main_shard_ids or "" in smoke_shard_ids or main_shard_ids & smoke_shard_ids:
        raise CoveragePolicyError("v6 main/smoke descriptor identity conflict")
    main_package_paths = {str(item.get("package_identity", {}).get("path") or "") for item in main}
    for descriptor in smoke:
        claimed = descriptor.get("package_identity")
        smoke_path = _check_identity(v6_root, claimed, label="v6 smoke package")
        if str(claimed.get("path") or "") in main_package_paths:
            raise CoveragePolicyError("v6 main/smoke package identity conflict")
        smoke_tuple = (
            str(smoke_path.relative_to(v6_root)),
            str(claimed.get("sha256")),
            int(claimed.get("size", -1)),
        )
        if smoke_tuple not in manifest_artifacts:
            raise CoveragePolicyError("v6 smoke package identity is absent from manifest artifacts")
    for descriptor in main:
        claimed = descriptor.get("package_identity")
        package_path = _check_identity(v6_root, claimed, label="v6 main package")
        relative = str(package_path.relative_to(v6_root))
        identity_tuple = (relative, str(claimed.get("sha256")), int(claimed.get("size", -1)))
        if identity_tuple not in manifest_artifacts:
            raise CoveragePolicyError("v6 main package identity is absent from manifest artifacts")
        package_counts: Counter[str] = Counter()
        package_scalars: dict[str, int] = {}
        for kind, item in _stream_package(package_path):
            if kind == "scalar":
                for key, value in item.items():
                    try:
                        package_scalars[key] = int(value)
                    except (TypeError, ValueError) as exc:
                        raise CoveragePolicyError("v6 package scalar count is invalid") from exc
                continue
            package_counts[kind] += 1
            try:
                target_id = int(item["target_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CoveragePolicyError("v6 package target identity is invalid") from exc
            target_sha = str(item.get("target_sha256") or "")
            if not HEX64.fullmatch(target_sha):
                raise CoveragePolicyError("v6 package target SHA is invalid")
            previous = statuses.get(target_id)
            if previous is not None:
                if previous["target_sha256"] != target_sha:
                    raise CoveragePolicyError("v6 target id/SHA drift")
                if previous["package_status"] != kind:
                    raise CoveragePolicyError("v6 record/gap conflict")
                raise CoveragePolicyError("duplicate target_id in v6 main packages")
            compact: dict[str, Any]
            if kind == "record":
                compact = {
                    "record_facts": _compact_record(item),
                    "gap_reason": "",
                }
            else:
                compact = {
                    "hard_blockers": [str(item.get("reason_code") or "detail_gap")],
                    "barrier_evidence_status": "unknown",
                    "gap_reason": str(item.get("reason_code") or "detail_gap"),
                }
            statuses[target_id] = {
                "target_id": target_id,
                "target_sha256": target_sha,
                "package_status": kind,
                "shard_id": descriptor.get("shard_id"),
                **compact,
            }
        declared = {
            "record": int(descriptor.get("records", -1)),
            "gap": int(descriptor.get("gaps", -1)),
        }
        if package_counts != Counter(declared) or int(descriptor.get("target_count", -1)) != sum(package_counts.values()):
            raise CoveragePolicyError("v6 package count identity mismatch")
        target_scalar = package_scalars.get("target_count", package_scalars.get("scope_count", -1))
        if (
            package_scalars.get("record_count") != package_counts["record"]
            or package_scalars.get("gap_count") != package_counts["gap"]
            or package_scalars.get("accounted_count") != sum(package_counts.values())
            or target_scalar != sum(package_counts.values())
            or (
                "target_count" in package_scalars
                and "scope_count" in package_scalars
                and package_scalars["target_count"] != package_scalars["scope_count"]
            )
        ):
            raise CoveragePolicyError("v6 package scalar count identity mismatch")
        package_identities.append(
            {
                "shard_id": descriptor.get("shard_id"),
                **_identity(package_path, v6_root),
                "counts": {
                    "record_count": package_counts["record"],
                    "gap_count": package_counts["gap"],
                    "accounted_count": sum(package_counts.values()),
                    "target_count": target_scalar,
                },
            }
        )
    return statuses, {
        "manifest": _identity(manifest_path),
        "execution_report": _identity(report_path),
        "main_descriptor_count": len(main),
        "smoke_descriptor_count": len(smoke),
        "smoke_packages_excluded": True,
        "main_packages": package_identities,
    }


def _grade_number(value: Any) -> int | None:
    text = str(value or "").strip().upper().replace("GROUP", "G").replace("GRADE", "G")
    match = re.search(r"(?:^|\b)G\s*([123])(?:\b|$)", text)
    return int(match.group(1)) if match else None


def _classify(target: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    region = str(target.get("country_region") or "")
    year = int(target.get("year", 0))
    if region not in config["regions"] or year <= 0:
        raise CoveragePolicyError("target region/year classification is invalid")
    whitelist = next(
        (
            rule
            for rule in config.get("whitelist_rules", [])
            if rule.get("country_region") == region and rule.get("series_key") == target.get("series_key")
        ),
        None,
    )
    if year >= int(config["new_year_start"]):
        return {"coverage_period": "new", "coverage_tier": "new_formal", "classification_reason": "new_formal_from_2025", "whitelist_rule_id": whitelist.get("rule_id") if whitelist else ""}
    if year > int(config["historical_year_end"]):
        raise CoveragePolicyError("coverage year boundary is inconsistent")
    if region in config["historical_all_hard_regions"]:
        return {"coverage_period": "historical", "coverage_tier": "historical_hard", "classification_reason": "region_existing_official_scope", "whitelist_rule_id": whitelist.get("rule_id") if whitelist else ""}
    if whitelist:
        return {"coverage_period": "historical", "coverage_tier": "historical_hard", "classification_reason": "explicit_whitelist", "whitelist_rule_id": whitelist["rule_id"]}
    grade = _grade_number(target.get("grade_text"))
    if grade == 1:
        reason = "historical_g1"
        tier = "historical_hard"
    elif grade in {2, 3}:
        reason = "historical_g2_g3_best_effort"
        tier = "historical_best_effort"
    else:
        reason = "unknown_grade_fail_closed"
        tier = "historical_hard"
    return {"coverage_period": "historical", "coverage_tier": tier, "classification_reason": reason, "whitelist_rule_id": ""}


def _valid_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalized_host(value: Any) -> str:
    return str(urlparse(str(value or "")).hostname or "").casefold().rstrip(".")


def _trusted_evidence(
    evidence: Any,
    *,
    target: dict[str, Any],
    config: dict[str, Any],
    allowed_roles: set[str],
    require_target_binding: bool = True,
) -> bool:
    if not isinstance(evidence, dict) or not _valid_url(evidence.get("url")):
        return False
    identity = str(evidence.get("source_identity") or "")
    source = config.get("trusted_sources", {}).get(identity)
    if not isinstance(source, dict) or source.get("role") not in allowed_roles:
        return False
    if target.get("country_region") not in source.get("regions", []):
        return False
    hosts = {_normalized_host(f"https://{host}") for host in source.get("hosts", [])}
    if not hosts or _normalized_host(evidence.get("url")) not in hosts:
        return False
    if require_target_binding and not all(
        evidence.get(key) == target.get(key)
        for key in ("target_id", "target_sha256", "series_key", "year")
    ):
        return False
    return True


def _strict_absence_evidence(target: dict[str, Any], kind: str, config: dict[str, Any]) -> bool:
    evidence = target.get("absence_evidence")
    if not isinstance(evidence, dict) or evidence.get("assertion_kind") != kind:
        return False
    if not _trusted_evidence(
        evidence,
        target=target,
        config=config,
        allowed_roles={"official", "authority"},
    ):
        return False
    if not HEX64.fullmatch(str(evidence.get("snapshot_sha256") or "")):
        return False
    source = config["trusted_sources"][evidence["source_identity"]]
    if evidence.get("source_authority") and evidence.get("source_authority") != source.get("role"):
        return False
    if not (evidence.get("captured_at") or evidence.get("checked_at")):
        return False
    return True


def _strict_permanent_evidence(target: dict[str, Any], config: dict[str, Any]) -> bool:
    evidence = target.get("permanent_unavailable_evidence")
    if not isinstance(evidence, dict):
        return False
    if not all(evidence.get(key) == target.get(key) for key in ("target_id", "target_sha256", "series_key", "year")):
        return False
    identities: list[str] = []
    for label, roles in (
        ("official_archive", {"official", "authority"}),
        ("independent_source", {"authority", "professional"}),
    ):
        item = evidence.get(label)
        if not _trusted_evidence(
            item,
            target=target,
            config=config,
            allowed_roles=roles,
            require_target_binding=False,
        ):
            return False
        if not all(str(item.get(k) or "").strip() for k in ("checked_at", "query_scope", "snapshot_sha256")):
            return False
        if not HEX64.fullmatch(str(item.get("snapshot_sha256") or "")):
            return False
        if item.get("query_scope") != f"{target.get('series_key')}:{target.get('year')}":
            return False
        identities.append(str(item.get("source_identity") or ""))
    return bool(identities[0]) and identities[0] != identities[1]


def _normalize_grade(value: Any) -> str | None:
    text = re.sub(r"[\s._-]+", "", str(value or "").casefold())
    match = re.fullmatch(r"(?:g|group|grade)([123])", text)
    return f"G{match.group(1)}" if match else None


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    modules = record.get("modules") if isinstance(record.get("modules"), dict) else {}
    runners_module = modules.get("runners") if isinstance(modules.get("runners"), dict) else {}
    results_module = modules.get("results") if isinstance(modules.get("results"), dict) else {}
    runners = runners_module.get("items") if isinstance(runners_module.get("items"), list) else []
    results = results_module.get("items") if isinstance(results_module.get("items"), list) else []
    first = next((row for row in results if row.get("finish_position") == 1), None)
    winner = record.get("winner") if isinstance(record.get("winner"), dict) else {}
    return {
        "basic_field_evidence": record.get("basic_field_evidence"),
        "distance_text": record.get("distance_text"),
        "distance_provenance": record.get("distance_provenance"),
        "runners_complete": bool(runners_module.get("is_complete")) and bool(runners),
        "results_complete": bool(results_module.get("is_complete")) and bool(results),
        "runners_have_barriers": bool(runners) and all(str(row.get("barrier") or "").strip() for row in runners),
        "winner_identity": (str(winner.get("horse_number")), str(winner.get("horse_name"))),
        "first_identity": (
            (str(first.get("horse_number")), str(first.get("horse_name")))
            if isinstance(first, dict)
            else None
        ),
        "source_evidence": record.get("source_evidence"),
        "barrier_evidence_status": record.get("barrier_evidence_status"),
        "barrier_evidence": record.get("barrier_evidence"),
    }


def _record_acceptance(
    facts: dict[str, Any],
    *,
    target: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[str], str]:
    blockers: list[str] = []
    basic = facts.get("basic_field_evidence")
    if not isinstance(basic, dict):
        blockers.append("basic_field_evidence")
    else:
        for field in ("grade", "surface", "race_type"):
            evidence = basic.get(field)
            if (
                not _trusted_evidence(
                    evidence,
                    target=target,
                    config=config,
                    allowed_roles={"official", "authority", "professional"},
                )
                or not HEX64.fullmatch(str((evidence or {}).get("snapshot_sha256") or ""))
            ):
                blockers.append(f"{field}_evidence")
            elif not str(evidence.get("value") or "").strip():
                blockers.append(f"{field}_evidence")
        grade_evidence = basic.get("grade")
        if isinstance(grade_evidence, dict) and str(grade_evidence.get("value") or "").strip():
            target_grade = _normalize_grade(target.get("grade_text"))
            evidence_grade = _normalize_grade(grade_evidence.get("value"))
            if target_grade is None or evidence_grade is None:
                blockers.append("grade_evidence_invalid")
            elif target_grade != evidence_grade:
                blockers.append("grade_evidence_conflict")
    distance = facts.get("distance_provenance")
    if not facts.get("distance_text") or not isinstance(distance, dict) or not _valid_url(distance.get("source_url")):
        blockers.append("distance_evidence")
    if not facts.get("runners_complete"):
        blockers.append("complete_runners")
    if not facts.get("results_complete"):
        blockers.append("complete_results")
    if not facts.get("first_identity") or facts.get("first_identity") != facts.get("winner_identity"):
        blockers.append("winner_consistency")
    source = facts.get("source_evidence")
    if (
        not _trusted_evidence(
            source,
            target=target,
            config=config,
            allowed_roles={"official", "authority", "professional"},
            require_target_binding=False,
        )
        or not source.get("captured_at")
        or not source.get("source_type")
        or not HEX64.fullmatch(str(source.get("snapshot_sha256") or ""))
    ):
        blockers.append("source_traceability")
    barrier_status = str(facts.get("barrier_evidence_status") or "unknown")
    if barrier_status == "complete":
        if not facts.get("runners_have_barriers"):
            barrier_status = "unknown"
    elif barrier_status == "not_applicable_with_evidence":
        evidence = facts.get("barrier_evidence")
        race_type = basic.get("race_type") if isinstance(basic, dict) else None
        allowed_types = {str(value).casefold() for value in config.get("barrier_not_applicable_race_types", [])}
        race_type_value = str((race_type or {}).get("value") or "").strip().casefold()
        same_evidence = all(
            isinstance(evidence, dict)
            and evidence.get(key) == race_type.get(key)
            for key in ("source_identity", "url", "snapshot_sha256", "target_id", "target_sha256", "series_key", "year")
        ) if isinstance(race_type, dict) else False
        if (
            not isinstance(evidence, dict)
            or evidence.get("assertion_kind") != "barrier_not_applicable"
            or evidence.get("race_type_value", "").casefold() != race_type_value
            or race_type_value not in allowed_types
            or not same_evidence
            or not evidence.get("reason")
            or not _trusted_evidence(
                evidence,
                target=target,
                config=config,
                allowed_roles={"official", "authority", "professional"},
            )
        ):
            barrier_status = "unknown"
    else:
        barrier_status = "unknown"
    if barrier_status == "unknown":
        blockers.append("barrier_evidence_unknown")
    return sorted(set(blockers)), barrier_status


def _coverage_row(target: dict[str, Any], package: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any]:
    classification = _classify(target, config)
    detail_status = "pending"
    acceptance = "blocked"
    blockers: list[str] = []
    barrier_status = "unknown"
    package_shard = ""
    gap_reason = ""
    expectation = str(target.get("expectation_status") or "")
    resolution = str(target.get("resolution_status") or "")
    if expectation in {"cancelled", "not_held"}:
        if _strict_absence_evidence(target, expectation, config):
            detail_status, acceptance, barrier_status = "not_applicable", "satisfied", "not_applicable_with_evidence"
        else:
            detail_status, gap_reason = "gap", f"invalid_{expectation}_evidence"
            blockers.append(gap_reason)
    elif resolution == "permanently_unavailable":
        if _strict_permanent_evidence(target, config):
            detail_status, acceptance, barrier_status = "not_applicable", "satisfied", "not_applicable_with_evidence"
        else:
            detail_status, gap_reason = "gap", "invalid_permanently_unavailable_evidence"
            blockers.append(gap_reason)
    elif package is None:
        blockers.append("detail_pending")
    elif package["target_sha256"] != target.get("target_sha256"):
        raise CoveragePolicyError("v6 target id/SHA does not match v9")
    else:
        package_shard = str(package.get("shard_id") or "")
        if package["package_status"] == "gap":
            detail_status = "gap"
            gap_reason = str(package.get("gap_reason") or "detail_gap")
            blockers.append(gap_reason)
        else:
            detail_status = "complete"
            blockers, barrier_status = _record_acceptance(
                package.get("record_facts") or {},
                target=target,
                config=config,
            )
            acceptance = "satisfied" if not blockers else "blocked"
    return {
        **target,
        **classification,
        "policy_version": config["policy_id"],
        "detail_package_status": detail_status,
        "detail_status": detail_status,
        "accounting_status": acceptance,
        "policy_acceptance_status": acceptance,
        "barrier_evidence_status": barrier_status,
        "hard_blockers": blockers,
        "gap_reason": gap_reason,
        "detail_shard_id": package_shard,
    }


def _write_jsonl(path: Path, rows: Iterator[dict[str, Any]] | list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _canonical_existing_path(value: Path | str, *, label: str, directory: bool) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CoveragePolicyError(f"{label} path is missing or cannot be resolved") from exc
    if directory and not path.is_dir():
        raise CoveragePolicyError(f"{label} path must be a directory")
    if not directory and not path.is_file():
        raise CoveragePolicyError(f"{label} path must be a file")
    return path


def _canonical_output_path(value: Path | str) -> Path:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise CoveragePolicyError("output root path cannot be resolved") from exc


def build_coverage(*, v9_root: Path | str, v6_root: Path | str, policy_doc: Path | str, config_path: Path | str, output_root: Path | str) -> dict[str, Any]:
    v9_root = _canonical_existing_path(v9_root, label="v9 root", directory=True)
    v6_root = _canonical_existing_path(v6_root, label="v6 root", directory=True)
    policy_doc = _canonical_existing_path(policy_doc, label="policy document", directory=False)
    config_path = _canonical_existing_path(config_path, label="policy config", directory=False)
    output_root = _canonical_output_path(output_root)
    config = _read_json(config_path)
    required_config = {
        "policy_id",
        "historical_year_end",
        "new_year_start",
        "regions",
        "historical_all_hard_regions",
        "historical_graded_regions",
        "barrier_not_applicable_race_types",
        "trusted_sources",
        "whitelist_rules",
    }
    if config.get("schema_version") != SCHEMA_VERSION or not required_config.issubset(config):
        raise CoveragePolicyError("coverage policy config is invalid")
    if int(config["historical_year_end"]) + 1 != int(config["new_year_start"]):
        raise CoveragePolicyError("coverage policy year boundary is invalid")
    trusted_sources = config["trusted_sources"]
    covered_regions: set[str] = set()
    claimed_hosts: dict[str, str] = {}
    if not isinstance(trusted_sources, dict) or not trusted_sources:
        raise CoveragePolicyError("coverage trusted source registry is invalid")
    for source_identity, source in trusted_sources.items():
        if (
            not source_identity
            or not isinstance(source, dict)
            or source.get("role") not in {"official", "authority", "professional"}
            or not isinstance(source.get("hosts"), list)
            or not isinstance(source.get("regions"), list)
        ):
            raise CoveragePolicyError("coverage trusted source registry is invalid")
        regions = set(source["regions"])
        if not regions or not regions.issubset(set(config["regions"])):
            raise CoveragePolicyError("coverage trusted source region is invalid")
        covered_regions.update(regions)
        for raw_host in source["hosts"]:
            host = _normalized_host(f"https://{raw_host}")
            if not host or (host in claimed_hosts and claimed_hosts[host] != source_identity):
                raise CoveragePolicyError("coverage trusted source host identity is invalid")
            claimed_hosts[host] = source_identity
    if covered_regions != set(config["regions"]):
        raise CoveragePolicyError("coverage trusted source registry does not cover all regions")
    seen_rules: set[str] = set()
    seen_series: set[tuple[str, str]] = set()
    for rule in config["whitelist_rules"]:
        identity = (str(rule.get("country_region") or ""), str(rule.get("series_key") or ""))
        if not rule.get("rule_id") or rule["rule_id"] in seen_rules or identity in seen_series or not rule.get("reason"):
            raise CoveragePolicyError("coverage whitelist rule identity is invalid")
        seen_rules.add(rule["rule_id"])
        seen_series.add(identity)
    targets, v9_identity = _load_v9(v9_root)
    packages, v6_identity = _load_v6(v6_root)
    target_ids = {int(row["target_id"]) for row in targets}
    unexpected = sorted(set(packages) - target_ids)
    if unexpected:
        raise CoveragePolicyError("v6 contains target outside v9 remaining selection")
    rows = [_coverage_row(target, packages.get(int(target["target_id"])), config) for target in targets]
    if [(row["target_id"], row["target_sha256"]) for row in rows] != [(row["target_id"], row["target_sha256"]) for row in targets]:
        raise CoveragePolicyError("target id/SHA conservation failed")
    if output_root.exists():
        raise CoveragePolicyError("output root already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent))
    try:
        _write_jsonl(staging / "coverage_ledger.jsonl", rows)
        tier_files = {
            "historical_hard": "historical_hard_selection.jsonl",
            "historical_best_effort": "historical_best_effort_selection.jsonl",
            "new_formal": "new_formal_selection.jsonl",
        }
        for tier, name in tier_files.items():
            _write_jsonl(
                staging / name,
                (
                    {**target, "coverage_tier": tier}
                    for target, row in zip(targets, rows)
                    if row["coverage_tier"] == tier
                ),
            )
        gap_rows = [
            {
                "target_id": row["target_id"],
                "target_sha256": row["target_sha256"],
                "country_region": row["country_region"],
                "series_key": row["series_key"],
                "year": row["year"],
                "coverage_tier": row["coverage_tier"],
                "detail_status": row["detail_status"],
                "detail_package_status": row["detail_package_status"],
                "accounting_status": row["accounting_status"],
                "gap_reason": row["gap_reason"],
                "hard_blockers": row["hard_blockers"],
            }
            for row in rows
            if row["accounting_status"] == "blocked"
        ]
        _write_jsonl(staging / "gap_review_ledger.jsonl", gap_rows)
        shards: dict[tuple[str, int, str], list[int]] = defaultdict(list)
        for row in rows:
            shards[(row["country_region"], int(row["year"]), row["coverage_tier"])].append(int(row["target_id"]))
        priority = {
            "schema_version": SCHEMA_VERSION,
            "policy_id": config["policy_id"],
            "shards": [
                {"shard_id": f"{region}-{year}-{tier}", "country_region": region, "year": year, "coverage_tier": tier, "target_count": len(ids), "target_ids": ids}
                for (region, year, tier), ids in sorted(shards.items(), key=lambda item: ({"historical_hard": 0, "new_formal": 1, "historical_best_effort": 2}[item[0][2]], item[0][0], item[0][1]))
            ],
        }
        (staging / "priority_shards.json").write_text(json.dumps(priority, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary = {
            "schema_version": SCHEMA_VERSION,
            "policy_id": config["policy_id"],
            "scope": "remaining_targets_only",
            "full_history_baseline_available": False,
            "target_count": len(rows),
            "coverage_tier_counts": dict(sorted(Counter(row["coverage_tier"] for row in rows).items())),
            "detail_status_counts": dict(sorted(Counter(row["detail_status"] for row in rows).items())),
            "detail_package_status_counts": dict(sorted(Counter(row["detail_package_status"] for row in rows).items())),
            "accounting_status_counts": dict(sorted(Counter(row["accounting_status"] for row in rows).items())),
            "acceptance_status_counts": dict(sorted(Counter(row["accounting_status"] for row in rows).items())),
            "barrier_evidence_status_counts": dict(sorted(Counter(row["barrier_evidence_status"] for row in rows).items())),
            "selection_counts": {
                tier: sum(row["coverage_tier"] == tier for row in rows)
                for tier in tier_files
            },
            "region_counts": dict(sorted(Counter(row["country_region"] for row in rows).items())),
            "complete_runners_count": sum("complete_runners" not in row["hard_blockers"] and row["detail_package_status"] == "complete" for row in rows),
            "complete_results_count": sum("complete_results" not in row["hard_blockers"] and row["detail_package_status"] == "complete" for row in rows),
            "winner_only_count": 0,
            "cancelled_satisfied_count": sum(row.get("expectation_status") == "cancelled" and row["accounting_status"] == "satisfied" for row in rows),
            "not_held_satisfied_count": sum(row.get("expectation_status") == "not_held" and row["accounting_status"] == "satisfied" for row in rows),
            "permanently_unavailable_satisfied_count": sum(row.get("resolution_status") == "permanently_unavailable" and row["accounting_status"] == "satisfied" for row in rows),
            "manual_review_count": len(gap_rows),
            "upstream_inventory_identity_status": v9_identity["upstream_inventory_identity_status"],
        }
        (staging / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        artifacts = {name: _identity(staging / name, staging) for name in OUTPUT_FILES}
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": "historical_race_coverage_policy",
            "scope": "remaining_targets_only",
            "full_history_baseline_available": False,
            "policy_id": config["policy_id"],
            "target_count": len(rows),
            "policy_document_identity": _identity(policy_doc),
            "policy_config_identity": _identity(config_path),
            "v9_identity": v9_identity,
            "v6_identity": v6_identity,
            "artifacts": artifacts,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(staging, output_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "output_root": str(output_root),
        "target_count": len(rows),
        "historical_hard_count": sum(row["coverage_tier"] == "historical_hard" for row in rows),
        "historical_best_effort_count": sum(row["coverage_tier"] == "historical_best_effort" for row in rows),
        "new_formal_count": sum(row["coverage_tier"] == "new_formal" for row in rows),
        "upstream_inventory_identity_status": "unverified",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build immutable historical race coverage-policy artifacts.")
    parser.add_argument("--v9-root", required=True, type=Path)
    parser.add_argument("--v6-root", required=True, type=Path)
    parser.add_argument("--policy-doc", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = build_coverage(v9_root=args.v9_root, v6_root=args.v6_root, policy_doc=args.policy_doc, config_path=args.config, output_root=args.output_root)
    except CoveragePolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
