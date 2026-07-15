#!/usr/bin/env python3
"""Write a plan-eng-review ledger entry.

Inputs are environment variables so Codex can bind review state without
rewriting JSON-handling code during every review.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _loads(name: str, default: str) -> Any:
    return json.loads(os.environ.get(name, default))


def _session(entry: dict[str, Any]) -> int:
    raw = entry.get("session", 0)
    return raw if isinstance(raw, int) else 0


def main() -> int:
    change_dir = Path(os.environ["CHANGE_DIR"])
    current_round = int(os.environ["CURRENT_ROUND"])
    now = os.environ["NOW_ISO8601"]
    artifacts_modified = _loads("ARTIFACTS_MODIFIED_JSON", "[]")
    findings = _loads("FINDINGS_JSON", "[]")
    new_findings = _loads("NEW_FINDINGS_JSON", "[]")
    resolved_count = int(os.environ["RESOLVED_COUNT"])

    sidecar_dir = change_dir / ".sidecar"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = sidecar_dir / "ledger.json"

    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        if not isinstance(raw.get("entries"), list):
            raise ValueError("entries must be a list")
        ledger = raw
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        if ledger_path.exists():
            backup = ledger_path.with_suffix(f".json.bak.{time.time_ns()}")
            os.replace(ledger_path, backup)
            print(
                f"plan-eng-review: malformed ledger backed up to {backup.name}",
                file=sys.stderr,
            )
        ledger = {"schema_version": "1.0", "entries": []}

    entries = ledger["entries"]
    if current_round == 1:
        current_session = max((_session(entry) for entry in entries), default=0) + 1
    else:
        candidates = [
            _session(entry)
            for entry in entries
            if entry.get("source") == "plan-eng-review"
        ]
        if not candidates:
            print(
                "plan-eng-review: round > 1 requested with no existing review entry",
                file=sys.stderr,
            )
            return 1
        current_session = max(candidates)

    entry = next((item for item in entries if _session(item) == current_session), None)
    if entry is None:
        entry = {
            "source": "plan-eng-review",
            "session": current_session,
            "round": current_round,
            "timestamp": now,
            "last_updated": now,
            "mode": "full" if current_round == 1 else "delta",
            "artifacts_modified": list(artifacts_modified),
            "rounds_total_for_session": current_round,
            "issues_resolved": resolved_count,
            "findings": list(findings),
        }
        entries.append(entry)
        action = "appended"
    else:
        entry["round"] = current_round
        entry["mode"] = "delta"
        entry["last_updated"] = now
        entry["artifacts_modified"] = sorted(
            set(entry.get("artifacts_modified", [])) | set(artifacts_modified)
        )
        entry["rounds_total_for_session"] = current_round
        entry["issues_resolved"] = resolved_count
        entry.setdefault("findings", []).extend(new_findings)
        action = "updated"

    ledger_path.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"plan-eng-review: ledger.json {action} "
        f"(session {current_session}, round {current_round})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
