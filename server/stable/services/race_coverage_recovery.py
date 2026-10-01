"""2026-10-02 七场受审参考赛果恢复；不是常驻自动发布入口。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.race_reference_parsers import sporting_life, zeturf
from stable.services.race_data_sync_control import disenroll
from stable.services.race_events import transfer_race_event_projection_owner
from stable.services.scheduled_race_result_review import (
    apply_reviewed_event_payloads,
    compute_event_baseline,
    compute_reviewed_row_digest,
)

EVENT_IDS = frozenset((772, 828, 830, 833, 970, 975, 976))
RECOVERY_KEY = "race_coverage_recovery_20261002"


class RecoveryBlocked(ValueError):
    pass


def _require(ok, reason):
    if not ok:
        raise RecoveryBlocked(reason)


def _name(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def _inventory(rows):
    return {(str(r["horse_number"]), _name(r["horse_name"])) for r in rows}


def verify_package(*, manifest_path, expected_sha256):
    """从固定本地证据重新解析；apply 不抓网络，不相信手改的结果表。"""
    path = Path(manifest_path).resolve()
    raw = path.read_bytes()
    _require(
        hashlib.sha256(raw).hexdigest() == expected_sha256, "manifest_sha256_drift"
    )
    package = json.loads(raw)
    _require(
        package.get("schema_version") == 1 and package.get("operation") == RECOVERY_KEY,
        "manifest_schema_invalid",
    )
    payloads = package["events"]
    _require(
        len(payloads) == 7 and {p["event_id"] for p in payloads} == EVENT_IDS,
        "scope_invalid",
    )
    for payload in payloads:
        proofs = payload["proofs"]
        _require(bool(proofs), "proof_missing")
        supported = {}
        source_inventory = None
        for proof in proofs:
            source_path = (path.parent / proof["file"]).resolve()
            _require(
                source_path.is_relative_to(path.parent) and source_path.is_file(),
                "proof_path_invalid",
            )
            body = source_path.read_bytes()
            _require(
                hashlib.sha256(body).hexdigest() == proof["sha256"],
                "proof_sha256_drift",
            )
            url = urlsplit(proof["url"])
            _require(
                url.scheme == "https"
                and not url.username
                and not url.password
                and not url.query,
                "proof_url_invalid",
            )
            html = body.decode("utf-8")
            if url.hostname == "www.sportinglife.com":
                _require(
                    url.path.startswith(
                        "/racing/results/" + payload["local_date"] + "/"
                    ),
                    "proof_date_drift",
                )
                runners, results, meta = sporting_life.parse_legacy_page(
                    html, source_url=proof["url"]
                )
                _require(meta.get("race_stage") == "WEIGHEDIN", "source_not_final")
            elif url.hostname == "www.zeturf.fr":
                runners, results, meta = zeturf.parse_legacy_page(
                    html, source_url=proof["url"]
                )
                _require(meta.get("date") == payload["local_date"], "proof_date_drift")
                # ZEturf 到着表可能截断；只接受明确出现的非完赛标记，绝不把缺行推定为退赛。
                text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
                for number in payload.get("fallen_numbers", []):
                    _require(
                        re.search(
                            r"Tombé\(s\)\s*:\s*" + re.escape(number) + r"(?!\d)", text
                        ),
                        "nonfinish_proof_missing",
                    )
                    rider = next(
                        (r for r in runners if r["horse_number"] == number), None
                    )
                    _require(rider is not None, "nonfinish_runner_missing")
                    supported[number] = (None, _name(rider["horse_name"]), "fell")
            else:
                raise RecoveryBlocked("proof_provider_not_allowed")
            inventory = _inventory(runners)
            _require(len(inventory) == len(runners), "proof_duplicate_runner")
            if source_inventory is None:
                source_inventory = inventory
            _require(inventory == source_inventory, "proof_runner_disagreement")
            for row in results:
                number = row["horse_number"]
                evidence = (
                    row["finish_position"],
                    _name(row["horse_name"]),
                    "declared",
                )
                _require(
                    number not in supported or supported[number] == evidence,
                    "proof_result_disagreement",
                )
                supported[number] = evidence
        _require(
            _inventory(payload["results"]) == source_inventory,
            "proof_inventory_incomplete",
        )
        for row in payload["results"]:
            expected = (
                None if row["running_status"] == "fell" else row["finish_position"],
                _name(row["horse_name"]),
                row["running_status"],
            )
            _require(
                supported.get(row["horse_number"]) == expected, "proof_result_drift"
            )
        _require(
            compute_reviewed_row_digest(payload["results"])
            == payload["reviewed_row_digest"],
            "reviewed_digest_drift",
        )
    return payloads


def _preflight(payload, manifest_sha256, now, lock):
    event_id = payload["event_id"]

    # 与实时控制链一致：lifecycle -> event -> owner -> tracking -> enrollment -> results。
    def query(model):
        qs = model.objects.all()
        return qs.select_for_update() if lock else qs

    lifecycle = (
        query(models.RaceEventLifecycleControl).filter(event_id=event_id).first()
    )
    event = query(models.RaceEvent).get(pk=event_id)
    owner = query(models.RaceEventProjectionControl).get(event_id=event_id)
    tracking = query(models.RaceEventLiveTracking).get(event_id=event_id)
    enrollment = query(models.RaceDataSyncEnrollment).get(event_id=event_id)
    results = list(
        query(models.RaceEventResult)
        .filter(event_id=event_id)
        .order_by("finish_position", "id")
    )
    rows = payload["results"]
    _require(
        compute_reviewed_row_digest(rows) == payload["reviewed_row_digest"],
        "reviewed_digest_drift",
    )
    _require(
        event.visibility_status == "published"
        and event.status == "finished"
        and event.local_date
        and event.local_date < now.date(),
        "event_not_past_finished",
    )
    _require(
        not models.RaceEventProductCanonicalLink.objects.filter(
            duplicate_event_id=event_id, is_active=True
        ).exists(),
        "event_merged",
    )
    _require(
        not any((event.manual_lock_flags or {}).values())
        and not (lifecycle and lifecycle.manual_pause_reason),
        "manual_pause",
    )
    _require(
        not tracking.active_attempt_token
        or (tracking.claim_expires_at and tracking.claim_expires_at <= now),
        "active_claim_exists",
    )
    _require(
        not lifecycle
        or not lifecycle.claim_token
        or (lifecycle.claim_expires_at and lifecycle.claim_expires_at <= now),
        "active_lifecycle_claim_exists",
    )
    if (
        owner.write_owner == "historical"
        and owner.owner_manifest_sha256 == manifest_sha256
    ):
        stored = [
            dict(
                finish_position=r.finish_position,
                horse_number=r.horse_number,
                horse_name=r.horse_name,
                running_status=r.running_status,
            )
            for r in results
        ]
        _require(
            compute_reviewed_row_digest(stored) == payload["reviewed_row_digest"]
            and bool(results)
            and all(
                r.is_confirmed
                and r.official_finish_position is None
                and r.source_refs.get(RECOVERY_KEY) == manifest_sha256
                for r in results
            )
            and event.result_confirmed_at is not None
            and enrollment.state == "retired"
            and not tracking.tracking_enabled,
            "applied_result_drift",
        )
        _require(
            models.RaceResultReviewApproval.objects.filter(
                event_id=event_id,
                bundle_sha256=manifest_sha256,
                reviewed_row_digest=payload["reviewed_row_digest"],
            ).exists(),
            "recovery_receipt_missing",
        )
        return "already_applied"
    _require(
        not event.result_confirmed_at
        and not any(r.is_confirmed for r in results)
        and owner.current_result_revision_id is None,
        "confirmed_result_exists",
    )
    _require(
        compute_event_baseline(event, result_rows=results)
        == payload["baseline_sha256"],
        "database_baseline_drift",
    )
    _require(
        owner.write_owner == "data_sync"
        and owner.owner_generation == payload["owner_generation"]
        and owner.owner_manifest_sha256 == payload["owner_manifest_sha256"]
        and enrollment.state == "enrolled"
        and enrollment.manifest_sha256 == payload["owner_manifest_sha256"]
        and enrollment.projection_owner_generation == payload["owner_generation"],
        "owner_cas_stale",
    )
    runners = list(
        query(models.RaceEventRunner)
        .filter(event_id=event_id)
        .values("horse_number", "horse_name")
    )
    _require(
        bool(rows)
        and len(rows) == len(runners)
        and len(_inventory(rows)) == len(rows)
        and _inventory(rows) == _inventory(runners),
        "runner_inventory_incomplete",
    )
    _require(
        [r["finish_position"] for r in rows] == list(range(1, len(rows) + 1)),
        "result_order_invalid",
    )
    _require(
        all(r["running_status"] in ("declared", "fell") for r in rows),
        "running_status_invalid",
    )
    return "ready"


def recover_events(*, payloads, manifest_sha256, now, apply=False):
    _require(not timezone.is_naive(now), "now_not_aware")
    _require(re.fullmatch(r"[0-9a-f]{64}", manifest_sha256), "manifest_invalid")
    _require(
        len(payloads) == 7 and {p["event_id"] for p in payloads} == EVENT_IDS,
        "scope_invalid",
    )
    payloads = sorted(payloads, key=lambda p: p["event_id"])
    with transaction.atomic():
        states = [_preflight(p, manifest_sha256, now, apply) for p in payloads]
        _require(len(set(states)) == 1, "partial_batch_state")
        if states[0] == "already_applied" or not apply:
            return dict(
                status=states[0],
                event_ids=sorted(EVENT_IDS),
                manifest_sha256=manifest_sha256,
            )
        for p in payloads:
            release = disenroll(
                event_id=p["event_id"],
                expected_manifest_sha256=p["owner_manifest_sha256"],
                expected_owner_generation=p["owner_generation"],
                now=now,
            )
            _require(release.action == "released", "disenroll_" + release.reason_code)
            transfer_race_event_projection_owner(
                event_id=p["event_id"],
                expected_owner="unmanaged",
                expected_generation=release.generation,
                new_owner="historical",
                manifest_sha256=manifest_sha256,
            )
        # 复用受审参考赛果事务和不可变 approval。authority 是既有分类值；审计明确记录实际执行者为 Codex。
        approved = [
            dict(
                p,
                authority="human_reviewed_reference",
                source_authority="third_party_high_access",
                result_order_complete=True,
            )
            for p in payloads
        ]
        result = apply_reviewed_event_payloads(
            bundle_sha256=manifest_sha256,
            approved_event_ids=sorted(EVENT_IDS),
            reviewer="codex:user-authorized-recovery:20261002",
            event_payloads=approved,
            confirmed_at=now,
        )
        _require(
            len(result.get("events", [])) == 7
            and all(r["status"] == "applied" for r in result["events"]),
            "reviewed_writer_failed",
        )
        for p in payloads:
            source_rows = {r["horse_number"]: r for r in p["results"]}
            for row in models.RaceEventResult.objects.filter(event_id=p["event_id"]):
                incoming = source_rows[row.horse_number]
                row.reported_finish_position = (
                    None if row.running_status == "fell" else row.finish_position
                )
                row.source_refs = {
                    **row.source_refs,
                    RECOVERY_KEY: manifest_sha256,
                    "public_label": "参考赛果（完整性已核验）",
                    "review_method": "codex_source_and_full_runner_verification",
                    "evidence": p["proofs"],
                }
                for field in (
                    "jockey_name",
                    "trainer_name",
                    "finish_time",
                    "margin",
                    "carried_weight",
                    "odds_value",
                    "barrier",
                ):
                    if incoming.get(field):
                        setattr(row, field, incoming[field])
                row.save()
            models.OperationLog.objects.create(
                action_type="race_coverage_recovery",
                target_type="RaceEvent",
                target_id=str(p["event_id"]),
                detail=json.dumps(
                    dict(
                        manifest_sha256=manifest_sha256,
                        previous_owner="data_sync",
                        new_owner="historical",
                        proofs=p["proofs"],
                        review_method="codex_source_and_full_runner_verification",
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        return dict(
            status="applied",
            event_ids=sorted(EVENT_IDS),
            manifest_sha256=manifest_sha256,
        )
