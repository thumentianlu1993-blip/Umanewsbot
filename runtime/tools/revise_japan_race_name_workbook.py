#!/usr/bin/env python3
"""Create the authorized Japan workbook revision by editing one shared string."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


EXPECTED_SOURCE_SHA256 = (
    "57a40984e2723251db554f6a6c7c7a9b2661991fee16ad89b69ed3e902c81fad"
)
SHARED_STRINGS_MEMBER = "xl/sharedStrings.xml"
WORKSHEET_MEMBER_PREFIX = "xl/worksheets/"
EXPECTED_BEFORE = "京成杯秋季让赛".encode("utf-8")
EXPECTED_AFTER = "京成杯秋季赛".encode("utf-8")
AUTHORIZED_CELL_REF = "C68"


def _shared_string_reference_cells(
    archive: "ZipFile", shared_strings: bytes, needle: bytes
) -> list[tuple[str, str]]:
    """Return (member, cell) pairs referencing the si that contains needle.

    OOXML shared strings are deduplicated: multiple cells may reference the
    same <si> index. Replacing the text of that <si> would silently rewrite
    every referencing cell, so the authorized single-cell revision requires
    the index to be referenced exactly once, at 翻译清单!C68.
    """
    si_index = shared_strings[: shared_strings.index(needle)].count(b"<si>") - 1
    references: list[tuple[str, str]] = []
    cell_pattern = re.compile(rb"<c\b[^>]*?(?:/>|>.*?</c>)", re.DOTALL)
    ref_pattern = re.compile(rb'\br="([A-Z]+[0-9]+)"')
    type_pattern = re.compile(rb'\bt="s"')
    value_pattern = re.compile(rb"<v>(\d+)</v>")
    for member in archive.namelist():
        if not member.startswith(WORKSHEET_MEMBER_PREFIX):
            continue
        if not member.endswith(".xml"):
            continue
        sheet_xml = archive.read(member)
        for cell_match in cell_pattern.finditer(sheet_xml):
            cell_xml = cell_match.group(0)
            if not type_pattern.search(cell_xml):
                continue
            value_match = value_pattern.search(cell_xml)
            if value_match is None or int(value_match.group(1)) != si_index:
                continue
            ref_match = ref_pattern.search(cell_xml)
            references.append(
                (member, ref_match.group(1).decode("ascii") if ref_match else "")
            )
    return references


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def revise(source: Path, destination: Path) -> dict[str, object]:
    actual_source_sha256 = sha256_file(source)
    if actual_source_sha256 != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "Japan baseline SHA mismatch: "
            f"expected={EXPECTED_SOURCE_SHA256}, actual={actual_source_sha256}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".incomplete",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(source, "r") as before_archive, ZipFile(
            temporary_path,
            "w",
            compression=ZIP_DEFLATED,
        ) as after_archive:
            for member in before_archive.infolist():
                payload = before_archive.read(member.filename)
                if member.filename == SHARED_STRINGS_MEMBER:
                    if payload.count(EXPECTED_BEFORE) != 1:
                        raise ValueError(
                            "authorized Japan source text must occur exactly once"
                        )
                    if EXPECTED_AFTER in payload:
                        raise ValueError("authorized Japan destination text already exists")
                    references = _shared_string_reference_cells(
                        before_archive, payload, EXPECTED_BEFORE
                    )
                    if len(references) != 1 or references[0][1] != AUTHORIZED_CELL_REF:
                        raise ValueError(
                            "authorized Japan shared string must be referenced "
                            f"exactly once at {AUTHORIZED_CELL_REF}: {references}"
                        )
                    payload = payload.replace(EXPECTED_BEFORE, EXPECTED_AFTER)
                after_archive.writestr(member, payload)
        with ZipFile(source, "r") as before_archive, ZipFile(
            temporary_path,
            "r",
        ) as after_archive:
            if before_archive.namelist() != after_archive.namelist():
                raise ValueError("XLSX archive member order changed")
            changed_members = [
                member
                for member in before_archive.namelist()
                if before_archive.read(member) != after_archive.read(member)
            ]
            if changed_members != [SHARED_STRINGS_MEMBER]:
                raise ValueError(
                    f"unexpected XLSX members changed: {changed_members}"
                )
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {
        "sourceSha256": actual_source_sha256,
        "destinationSha256": sha256_file(destination),
        "changedMembers": [SHARED_STRINGS_MEMBER],
        "authorizedCell": "翻译清单!C68",
        "before": EXPECTED_BEFORE.decode("utf-8"),
        "after": EXPECTED_AFTER.decode("utf-8"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    print(revise(args.source.resolve(), args.destination.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
