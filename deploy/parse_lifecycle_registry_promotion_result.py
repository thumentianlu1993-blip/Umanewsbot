#!/usr/bin/env python3
"""Fail-closed parser for the registry promotion command's stdout contract."""

from __future__ import annotations

import argparse
import re
import sys


LINE = re.compile(
    r"^outcome=(partial|applied|replay) "
    r"batch_members=([0-9]+) total=([1-9][0-9]*) remaining=([0-9]+)$"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-total", type=int, required=True)
    parser.add_argument("--previous-remaining", type=int, required=True)
    args = parser.parse_args()
    if args.expected_total <= 0 or not 0 <= args.previous_remaining <= args.expected_total:
        return 2

    raw = sys.stdin.read()
    lines = raw.splitlines()
    if len(lines) != 1 or not lines[0]:
        return 2
    match = LINE.fullmatch(lines[0])
    if match is None:
        return 2
    outcome = match.group(1)
    batch, total, remaining = map(int, match.groups()[1:])
    if total != args.expected_total or remaining > total:
        return 2

    if outcome == "partial":
        if not 1 <= batch <= 100 or remaining <= 0:
            return 2
        if args.previous_remaining == 0:
            if batch + remaining > total:
                return 2
        elif remaining != args.previous_remaining - batch:
            return 2
    elif outcome == "applied":
        if not 1 <= batch <= 100 or remaining != 0:
            return 2
        if args.previous_remaining and batch != args.previous_remaining:
            return 2
    else:  # replay is only valid for an already complete registry.
        if batch != total or remaining != 0:
            return 2

    print(f"{outcome} {remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
