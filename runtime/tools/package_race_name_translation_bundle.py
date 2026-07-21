#!/usr/bin/env python3
"""Create and verify a deterministic tracked archive from an approved bundle."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
import tempfile
from pathlib import Path


MEMBERS = (
    "apply_race_name_translation_manifest.py",
    "verify_race_name_translation_manifest.py",
    "input-lock.json",
    "normalized-input.json",
    "manifest.json",
    "production-before.json",
    "dry-run.json",
    "rollback-before.json",
    "execution-metadata.json",
    "execution-plan.json",
    "artifact-index.json",
    "bundle-index.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_source(source: Path, expected_index_sha256: str) -> dict:
    index_path = source / "bundle-index.json"
    if sha256_file(index_path) != expected_index_sha256:
        raise RuntimeError("bundle-index raw SHA mismatch")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schemaVersion") != "race-name-translation-bundle-index.v1":
        raise RuntimeError("unsupported bundle index schema")
    content = dict(index)
    expected_content_sha256 = content.pop("contentSha256", None)
    if (
        not isinstance(expected_content_sha256, str)
        or len(expected_content_sha256) != 64
        or expected_content_sha256 != sha256_json(content)
    ):
        raise RuntimeError("bundle index content sha mismatch")
    rows_list = index["files"]
    if not isinstance(rows_list, list) or len(rows_list) != len(MEMBERS) - 1:
        raise RuntimeError("bundle index files row count mismatch")
    rows = {row["file"]: row for row in rows_list}
    if set(rows) != set(MEMBERS[:-1]):
        raise RuntimeError("bundle member set mismatch")
    for name in MEMBERS[:-1]:
        path = source / name
        row = rows[name]
        if path.stat().st_size != row["sizeBytes"] or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"bundle member mismatch: {name}")
    return index


def build_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for name in MEMBERS:
                    data = (source / name).read_bytes()
                    info = tarfile.TarInfo(name=name)
                    info.size = len(data)
                    info.mtime = 0
                    info.mode = 0o600
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    archive.addfile(info, io.BytesIO(data))


def verify_archive(archive_path: Path, expected_index_sha256: str) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary)
        with tarfile.open(archive_path, mode="r:gz") as archive:
            names = archive.getnames()
            if names != list(MEMBERS):
                raise RuntimeError(f"archive member order/set mismatch: {names}")
            for member in archive.getmembers():
                if not member.isfile() or "/" in member.name or member.name.startswith("."):
                    raise RuntimeError(f"unsafe archive member: {member.name}")
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"cannot read archive member: {member.name}")
                (target / member.name).write_bytes(source.read())
        verify_source(target, expected_index_sha256)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-bundle-index-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    receipt_path = Path(args.receipt).resolve()
    index = verify_source(source, args.expected_bundle_index_sha256)
    build_archive(source, output)
    verify_archive(output, args.expected_bundle_index_sha256)
    receipt = {
        "schemaVersion": "race-name-translation-bundle-receipt.v1",
        "archive": output.name,
        "archiveSizeBytes": output.stat().st_size,
        "archiveSha256": sha256_file(output),
        "bundleIndexSha256": args.expected_bundle_index_sha256,
        "bundleContentSha256": index["contentSha256"],
        "memberCount": len(MEMBERS),
        "members": list(MEMBERS),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
