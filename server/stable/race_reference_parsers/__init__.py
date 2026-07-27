"""Side-effect-free parsers for private post-race reference observations."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


def decode_html(raw_bytes: bytes) -> str:
    if not isinstance(raw_bytes, bytes):
        raise RuntimeError("raw_bytes must be bytes")
    return raw_bytes.decode("utf-8", errors="replace")


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def runner_key(row: Mapping[str, Any], *, index: int) -> str:
    refs = row.get("source_refs")
    if isinstance(refs, dict):
        for key in ("horse_id", "horse_url"):
            if refs.get(key):
                return f"{key}:{text(refs[key])}"
    number = text(row.get("horse_number"))
    name = text(row.get("horse_name"))
    return f"runner:{number or index}:{name}"


def legacy_hash(runners: list[dict], results: list[dict], metadata: dict) -> str:
    body = json.dumps(
        {"runners": runners, "results": results, "metadata": metadata},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def reference_runners(
    runners: list[dict],
    results: list[dict],
) -> list[dict[str, str]]:
    results_by_number = {
        text(row.get("horse_number")): row
        for row in results
        if text(row.get("horse_number"))
    }
    output: list[dict[str, str]] = []
    for index, row in enumerate(runners, start=1):
        result = results_by_number.get(text(row.get("horse_number")), {})
        refs = result.get("source_refs")
        if not isinstance(refs, dict):
            refs = {}
        reported_position = refs.get("official_finish_position")
        if reported_position in (None, ""):
            reported_position = result.get("finish_position", "")
        output.append(
            {
                "source_runner_key": runner_key(row, index=index),
                "horse_number": text(row.get("horse_number")),
                "draw": text(row.get("barrier")),
                "horse_name": text(row.get("horse_name")),
                "jockey_name": text(row.get("jockey_name")),
                "trainer_name": text(row.get("trainer_name")),
                "carried_weight": text(row.get("carried_weight")),
                "odds_value": text(row.get("odds_value")),
                "running_status": text(row.get("running_status")),
                "source_reported_finish_position": text(reported_position),
                "margin": text(result.get("margin")),
            }
        )
    return output
