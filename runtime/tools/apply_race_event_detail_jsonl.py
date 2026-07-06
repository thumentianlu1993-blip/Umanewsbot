from __future__ import annotations

import json
import os
from pathlib import Path

from stable.models import RaceEvent, RaceEventModule
from stable.services.race_events import apply_data_candidate, save_data_candidate


ALLOWED_MODULES = {RaceEventModule.RUNNERS, RaceEventModule.RESULTS, RaceEventModule.HISTORY_WINNERS}


def main() -> None:
    jsonl_path = Path(os.environ["DETAIL_JSONL_PATH"])
    should_apply = os.environ.get("DETAIL_APPLY", "").lower() in {"1", "true", "yes", "on"}
    confidence = int(os.environ.get("DETAIL_CONFIDENCE", "90"))
    records = []
    with jsonl_path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            year = int(record["year"])
            slug = str(record["slug"])
            event = RaceEvent.objects.get(year=year, slug=slug)
            modules = record.get("modules") or {}
            if not isinstance(modules, dict) or not modules:
                raise RuntimeError(f"line={line_number} modules must be a non-empty object")
            for module, payload in modules.items():
                if module not in ALLOWED_MODULES:
                    raise RuntimeError(f"line={line_number} unsupported module={module}")
                if isinstance(payload, list):
                    payload = {"items": payload}
                    modules[module] = payload
                if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                    raise RuntimeError(f"line={line_number} invalid payload for module={module}")
            records.append((event, record))

    counts = {"events": len(records), "candidates": 0, "applied": 0, "items": {}}
    for _event, record in records:
        for module, payload in record["modules"].items():
            counts["items"][module] = counts["items"].get(module, 0) + len(payload.get("items") or [])

    if not should_apply:
        print(json.dumps({"dry_run": True, **counts}, ensure_ascii=False, sort_keys=True))
        return

    for event, record in records:
        raw_payload = {
            "year": event.year,
            "slug": event.slug,
            "source_name": record.get("source_name") or "json",
            "source_url": record.get("source_url") or "",
            "modules": record["modules"],
        }
        for module, payload in record["modules"].items():
            candidate = save_data_candidate(
                event=event,
                module=module,
                source_name=record.get("source_name") or "json",
                source_url=record.get("source_url") or "",
                candidate_payload=payload,
                raw_payload=raw_payload,
                confidence=confidence,
            )
            counts["candidates"] += 1
            apply_data_candidate(candidate)
            counts["applied"] += 1

    print(json.dumps({"dry_run": False, **counts}, ensure_ascii=False, sort_keys=True))


main()
