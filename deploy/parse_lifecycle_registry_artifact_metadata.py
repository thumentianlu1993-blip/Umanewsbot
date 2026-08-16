#!/usr/bin/env python3
"""Read the bounded promotion metadata needed by the host wrapper."""

from __future__ import annotations

import json
import re
import sys


def main() -> int:
    raw = sys.stdin.buffer.read()
    def pairs_hook(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    def canonicalize(item, *, numeric_event_keys=False):
        if isinstance(item, dict):
            keys = list(item)
            keys.sort(key=(lambda key: int(key)) if numeric_event_keys else None)
            return {
                key: canonicalize(
                    item[key],
                    numeric_event_keys=(not numeric_event_keys and key == "events"),
                )
                for key in keys
            }
        if isinstance(item, list):
            return [canonicalize(value) for value in item]
        return item

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs_hook)
        canonical = (
            json.dumps(
                canonicalize(value),
                ensure_ascii=False,
                sort_keys=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
        return 2
    if raw != canonical:
        return 2
    if not isinstance(value, dict) or "predecessor_root_sha256" not in value:
        return 2
    count = value.get("member_count")
    predecessor = value.get("predecessor_root_sha256")
    if type(count) is not int or count <= 0 or not isinstance(predecessor, str):
        return 2
    if predecessor == "":
        print(f"{count} first")
        return 0
    if re.fullmatch(r"[0-9a-f]{64}", predecessor) is None:
        return 2
    print(f"{count} successor {predecessor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
