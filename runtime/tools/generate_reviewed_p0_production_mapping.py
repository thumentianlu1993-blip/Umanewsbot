#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
sys.path.insert(0, str(Path.cwd()))

import django

django.setup()

from stable.models import HorseProfile
from stable.services.p0_horse_production_apply import (
    build_profile_mapping_snapshot,
    build_profile_snapshot,
    deterministic_identity_key,
)


BIND_EXISTING_PROFILE_IDS = {
    "Aventure": 3857,
    "First Look": 8338,
    "Horizon Dore": 8582,
    "EAGLE WAY": 11250,
    "SOUTHERN LEGEND": 12330,
    "BEAUTY GENERATION": 1368,
    "TIME WARP": 12535,
    "EXULTANT": 11320,
    "SEASONS BLOOM": 12236,
    "BEAUTY ONLY": 20430,
    "PAKISTAN STAR": 20320,
    "アスクナイスショー": 19804,
    "オニャンコポン": 13770,
    "オーロラエックス": 4023,
    "カラマティアノス": 4330,
    "クリスマスパレード": 19797,
    "コントラポスト": 12967,
    "サヴォーナ": 10129,
    "ショウナンマグマ": 19819,
    "センツブラッド": 19826,
    "Brando": 10211,
    "Art Power": 7669,
    "Regal Reality": 16546,
    "Stradivarius": 19439,
    "Fort George": 8367,
}

REJECTED_PROFILE_IDS = {"Stradivarius": [21276]}
ACTIVE_CUTOFF = date(2025, 7, 20)
APPROVED_AT = "2026-07-20T06:35:00+08:00"
DECISION_REFERENCE = "codex-task:p0-horse-50-production-apply-20260720"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def review_metadata(*, reason: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "reviewed_by": "project_owner",
        "approved_at": APPROVED_AT,
        "decision_source_reference": DECISION_REFERENCE,
    }
    if reason:
        payload["reason"] = reason
    return payload


def latest_race_date(horse: dict[str, object]) -> date:
    records = horse["career"]["records"]
    dates = [
        date.fromisoformat(record["race_date"])
        for record in records
        if record.get("race_date")
    ]
    if not dates:
        raise ValueError(f"{horse['identity']['horse_name']} has no dated race record")
    return max(dates)


def make_row(horse: dict[str, object]) -> dict[str, object]:
    identity = horse["identity"]
    horse_name = identity["horse_name"]
    snapshot = build_profile_mapping_snapshot(identity)
    latest_date = latest_race_date(horse)
    profile_id = BIND_EXISTING_PROFILE_IDS.get(horse_name)
    decision = "bind_existing" if profile_id is not None else "create_new"
    row: dict[str, object] = {
        "identity": identity,
        "decision": decision,
        "decision_evidence": review_metadata(
            reason="explicitly reviewed 50-horse production identity mapping"
        ),
        "module_reviews": {
            module: {
                "status": "approved",
                "confidence": 100,
                **review_metadata(),
            }
            for module in ("profile", "pedigree", "race_record", "major_wins")
        },
        "completion_decision": {
            "racing_career_status": (
                "active" if latest_date >= ACTIVE_CUTOFF else "retired"
            ),
            "records_synced_through": latest_date.isoformat(),
            **review_metadata(),
        },
        "database_mapping_snapshot": snapshot,
    }
    if profile_id is None:
        return row

    profile = HorseProfile.objects.get(pk=profile_id)
    rejected_ids = REJECTED_PROFILE_IDS.get(horse_name, [])
    row.update(
        {
            "profile_id": profile_id,
            "profile_snapshot": build_profile_snapshot(profile),
            "name_evidence": horse_name,
            "rejected_profile_ids": rejected_ids,
            "rejection_reason": (
                "selected official HKJC overseas term profile 19439; "
                "rejected community wpstud Japanese term profile 21276"
                if horse_name == "Stradivarius"
                else ""
            ),
        }
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-v3", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    research_path = Path(args.research_v3)
    research_bytes = research_path.read_bytes()
    research = json.loads(research_bytes)
    rows = [make_row(horse) for horse in research["horses"]]
    if len(rows) != 50:
        raise ValueError(f"expected 50 horses, got {len(rows)}")
    if sum(row["decision"] == "bind_existing" for row in rows) != 25:
        raise ValueError("expected exactly 25 bind_existing decisions")

    snapshot_payload = [
        {
            "identity_key": deterministic_identity_key(row["identity"]),
            "database_mapping_snapshot": row["database_mapping_snapshot"],
        }
        for row in sorted(
            rows,
            key=lambda item: deterministic_identity_key(item["identity"]),
        )
    ]
    mapping = {
        "schema_version": "p0-horse-profile-mapping-decisions.v1",
        "review_status": "approved",
        "reviewed_by": "project_owner",
        "reviewer_id": 1,
        "approved_at": APPROVED_AT,
        "decision_source_reference": DECISION_REFERENCE,
        "research_v3_sha256": hashlib.sha256(research_bytes).hexdigest(),
        "production_snapshot_sha256": hashlib.sha256(
            canonical_bytes(snapshot_payload)
        ).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_bytes(mapping))
    print(
        json.dumps(
            {
                "output": str(output_path),
                "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
                "horse_count": len(rows),
                "bind_existing_count": 25,
                "create_new_count": 25,
                "production_snapshot_sha256": mapping[
                    "production_snapshot_sha256"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
