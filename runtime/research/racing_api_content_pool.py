#!/usr/bin/env python3
"""TRA batch 的内容寻址对象池与紧凑单马导出格式。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping


POOL_SCHEMA_VERSION = "racing-api-content-pool.v1"
REF_SCHEMA_VERSION = "racing-api-content-ref.v1"
COMPACT_SCHEMA_VERSION = "targeted-horse-pooled-export.v1"
KIND_RE = re.compile(r"[a-z][a-z0-9_]{0,31}$")
SHA256_RE = re.compile(r"[0-9a-f]{64}$")
HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
RACE_ID_RE = re.compile(r"rac_[A-Za-z0-9_]+$")
MAX_INDEX_BYTES = 64 * 1024 * 1024


class ContentPoolError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _strict_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise ContentPoolError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _load_json(raw: bytes, *, label: str) -> dict:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ContentPoolError(f"invalid JSON constant: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContentPoolError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContentPoolError(f"{label} must be a JSON object")
    return value


def _private_regular(path: Path, *, label: str, allow_missing: bool = False):
    if path.is_symlink():
        raise ContentPoolError(f"{label} must not be a symlink")
    try:
        metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise ContentPoolError(f"{label} is missing") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise ContentPoolError(f"{label} must be a regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ContentPoolError(f"{label} must be private")
    return metadata


class ContentAddressedPool:
    def __init__(self, root: Path):
        supplied = Path(root)
        if supplied.is_symlink():
            raise ContentPoolError("content pool root must not be a symlink")
        supplied.mkdir(mode=0o700, parents=True, exist_ok=True)
        if supplied.is_symlink() or not supplied.is_dir():
            raise ContentPoolError("content pool root must be a directory")
        if stat.S_IMODE(supplied.stat(follow_symlinks=False).st_mode) & 0o077:
            raise ContentPoolError("content pool root must be private")
        self.root = supplied.resolve(strict=True)
        self.object_root = self.root / "sha256"
        self.object_root.mkdir(mode=0o700, exist_ok=True)
        if self.object_root.is_symlink():
            raise ContentPoolError("content object root must not be a symlink")
        self.index_path = self.root / "object-index.json"
        self.lock_path = self.root / ".pool.lock"
        with self._locked():
            if self.index_path.exists() or self.index_path.is_symlink():
                self._validate_index(self._read_index_unlocked())
            else:
                self._write_index_unlocked(
                    {"schema_version": POOL_SCHEMA_VERSION, "entries": {}}
                )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self.lock_path.is_symlink():
            raise ContentPoolError("content pool lock must not be a symlink")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ContentPoolError("content pool lock cannot be opened") from exc
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or stat.S_IMODE(opened.st_mode) & 0o077:
                raise ContentPoolError("content pool lock must be a private regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if self.lock_path.is_symlink():
                raise ContentPoolError("content pool lock must not be a symlink")
            current = self.lock_path.stat(follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ContentPoolError("content pool lock identity changed")
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    @staticmethod
    def _validate_identity(kind: str, identity: str) -> None:
        if not KIND_RE.fullmatch(str(kind or "")):
            raise ContentPoolError("content object kind is invalid")
        if (
            not isinstance(identity, str)
            or not identity
            or len(identity) > 512
            or identity.strip() != identity
            or "\0" in identity
        ):
            raise ContentPoolError("content object identity is invalid")

    def _validate_index(self, index: dict) -> None:
        if index.get("schema_version") != POOL_SCHEMA_VERSION:
            raise ContentPoolError("content pool index schema drift")
        entries = index.get("entries")
        if not isinstance(entries, dict):
            raise ContentPoolError("content pool index entries are invalid")
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                raise ContentPoolError("content pool index entry is invalid")
            kind = entry.get("kind")
            identity = entry.get("identity")
            self._validate_identity(kind, identity)
            if key != f"{kind}\0{identity}":
                raise ContentPoolError("content pool index key drift")
            singleton = entry.get("singleton_identity")
            hashes = entry.get("hashes")
            if not isinstance(singleton, bool) or not isinstance(hashes, list) or not hashes:
                raise ContentPoolError("content pool index hash set is invalid")
            if hashes != sorted(set(hashes)) or any(
                not SHA256_RE.fullmatch(str(value or "")) for value in hashes
            ):
                raise ContentPoolError("content pool index hash set is invalid")
            if singleton and len(hashes) != 1:
                raise ContentPoolError("singleton content identity has multiple hashes")

    def _read_index_unlocked(self) -> dict:
        metadata = _private_regular(self.index_path, label="content pool index")
        if metadata is None or metadata.st_size > MAX_INDEX_BYTES:
            raise ContentPoolError("content pool index is too large")
        raw = self.index_path.read_bytes()
        if len(raw) != metadata.st_size:
            raise ContentPoolError("content pool index changed while reading")
        return _load_json(raw, label="content pool index")

    def _atomic_write(self, path: Path, raw: bytes, *, prefix: str) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink() or path.is_symlink():
            raise ContentPoolError("content pool path must not contain symlinks")
        descriptor, temporary_name = tempfile.mkstemp(prefix=prefix, dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _write_index_unlocked(self, index: dict) -> None:
        self._validate_index(index)
        self._atomic_write(
            self.index_path,
            canonical_bytes(index),
            prefix=".index-",
        )

    def _object_path(self, sha256: str) -> Path:
        return self.object_root / sha256[:2] / sha256

    def put_bytes(
        self,
        *,
        kind: str,
        identity: str,
        raw: bytes,
        singleton_identity: bool,
    ) -> dict:
        self._validate_identity(kind, identity)
        if not isinstance(raw, bytes) or not raw:
            raise ContentPoolError("content object body must be non-empty bytes")
        if not isinstance(singleton_identity, bool):
            raise ContentPoolError("content singleton flag is invalid")
        sha256 = hashlib.sha256(raw).hexdigest()
        key = f"{kind}\0{identity}"
        with self._locked():
            index = self._read_index_unlocked()
            self._validate_index(index)
            existing = index["entries"].get(key)
            if existing is not None:
                if existing["singleton_identity"] != singleton_identity:
                    raise ContentPoolError("content identity mode drift")
                if singleton_identity and sha256 not in existing["hashes"]:
                    raise ContentPoolError(
                        f"content identity conflict: {kind}:{identity}"
                    )
            object_path = self._object_path(sha256)
            if object_path.exists() or object_path.is_symlink():
                metadata = _private_regular(object_path, label="content object")
                if metadata is None or metadata.st_size != len(raw):
                    raise ContentPoolError("content object identity changed")
                existing_raw = object_path.read_bytes()
                if existing_raw != raw or hashlib.sha256(existing_raw).hexdigest() != sha256:
                    raise ContentPoolError("content object hash collision or corruption")
            else:
                self._atomic_write(
                    object_path,
                    raw,
                    prefix=".object-",
                )
            hashes = sorted(set((existing or {}).get("hashes", [])) | {sha256})
            index["entries"][key] = {
                "kind": kind,
                "identity": identity,
                "singleton_identity": singleton_identity,
                "hashes": hashes,
            }
            self._write_index_unlocked(index)
        return {
            "schema_version": REF_SCHEMA_VERSION,
            "kind": kind,
            "identity": identity,
            "sha256": sha256,
            "size": len(raw),
            "path": object_path.relative_to(self.root).as_posix(),
        }

    def put_json(
        self,
        *,
        kind: str,
        identity: str,
        payload: object,
        singleton_identity: bool,
    ) -> dict:
        return self.put_bytes(
            kind=kind,
            identity=identity,
            raw=canonical_bytes(payload),
            singleton_identity=singleton_identity,
        )

    def read_json(self, reference: Mapping[str, object]) -> dict:
        if reference.get("schema_version") != REF_SCHEMA_VERSION:
            raise ContentPoolError("content reference schema drift")
        sha256 = str(reference.get("sha256") or "")
        if not SHA256_RE.fullmatch(sha256):
            raise ContentPoolError("content reference hash is invalid")
        path = self.root / str(reference.get("path") or "")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise ContentPoolError("content reference path escapes pool") from exc
        if resolved != self._object_path(sha256) or path.is_symlink():
            raise ContentPoolError("content reference path identity drift")
        metadata = _private_regular(resolved, label="content object")
        raw = resolved.read_bytes()
        if (
            metadata is None
            or metadata.st_size != reference.get("size")
            or hashlib.sha256(raw).hexdigest() != sha256
        ):
            raise ContentPoolError("content reference object changed")
        return _load_json(raw, label="content object")

    def snapshot(self) -> dict:
        with self._locked():
            index = self._read_index_unlocked()
            self._validate_index(index)
            hashes = sorted(
                {
                    sha256
                    for entry in index["entries"].values()
                    for sha256 in entry["hashes"]
                }
            )
            objects = []
            for sha256 in hashes:
                path = self._object_path(sha256)
                metadata = _private_regular(path, label="content object")
                raw = path.read_bytes()
                if metadata is None or hashlib.sha256(raw).hexdigest() != sha256:
                    raise ContentPoolError("content pool object verification failed")
                objects.append(
                    {
                        "sha256": sha256,
                        "size": metadata.st_size,
                        "path": path.relative_to(self.root).as_posix(),
                    }
                )
            return {
                "schema_version": POOL_SCHEMA_VERSION,
                "entry_count": len(index["entries"]),
                "object_count": len(objects),
                "objects": objects,
                "entries": index["entries"],
            }


def _profile_reference(profile: Mapping[str, object], *, pool: ContentAddressedPool) -> dict:
    horse_id = str(profile.get("horse_id") or "")
    if not HORSE_ID_RE.fullmatch(horse_id):
        raise ContentPoolError("profile horse identity is invalid")
    return pool.put_json(
        kind="horse_profile",
        identity=horse_id,
        payload=dict(profile),
        singleton_identity=False,
    )


def compact_targeted_export(
    result: Mapping[str, object], *, pool: ContentAddressedPool
) -> dict:
    if (
        result.get("schema_version") != "targeted-horse-export.v1"
        or result.get("database_writes") != 0
    ):
        raise ContentPoolError("targeted export schema drift")
    horse_id = str(result.get("horse_id") or "")
    if not HORSE_ID_RE.fullmatch(horse_id):
        raise ContentPoolError("target horse identity is invalid")
    profile = result.get("profile")
    parents = result.get("parent_profiles")
    career = result.get("career")
    target_race = result.get("target_race")
    page_field_matrix = result.get("page_field_matrix")
    if (
        not isinstance(profile, Mapping)
        or not isinstance(parents, list)
        or not isinstance(career, Mapping)
        or not isinstance(page_field_matrix, Mapping)
    ):
        raise ContentPoolError("targeted export objects are incomplete")
    profile_only = result.get("identity_mode") == "external_anchor_profile_only"
    if profile_only:
        if target_race is not None:
            raise ContentPoolError("profile-only export must not contain provider target race")
    elif not isinstance(target_race, Mapping):
        raise ContentPoolError("targeted export target race is incomplete")
    profile_ref = _profile_reference(profile, pool=pool)
    if (
        page_field_matrix.get("schema_version") != "horse-page-field-matrix.v1"
        or page_field_matrix.get("horse_id") != horse_id
        or page_field_matrix.get("database_writes") != 0
    ):
        raise ContentPoolError("page field matrix contract drift")
    page_field_matrix_ref = pool.put_json(
        kind="horse_page_field_matrix",
        identity=horse_id,
        payload=dict(page_field_matrix),
        singleton_identity=False,
    )
    parent_refs = []
    for parent in parents:
        if not isinstance(parent, Mapping):
            raise ContentPoolError("parent profile must be an object")
        parent_refs.append(_profile_reference(parent, pool=pool))
    races = career.get("races")
    if (
        not isinstance(races, list)
        or career.get("unique_race_count") != len(races)
    ):
        raise ContentPoolError("targeted career race count drift")
    records = []
    race_refs: dict[str, dict] = {}
    for race in races:
        if not isinstance(race, Mapping):
            raise ContentPoolError("career race must be an object")
        race_id = str(race.get("race_id") or "")
        if not RACE_ID_RE.fullmatch(race_id):
            raise ContentPoolError("career race identity is invalid")
        runners = race.get("runners")
        if not isinstance(runners, list):
            raise ContentPoolError("career race runners are invalid")
        target_rows = [
            dict(runner)
            for runner in runners
            if isinstance(runner, Mapping) and runner.get("horse_id") == horse_id
        ]
        if len(target_rows) != 1:
            raise ContentPoolError("target horse occurrence count drift")
        race_ref = pool.put_json(
            kind="race",
            identity=race_id,
            payload=dict(race),
            singleton_identity=True,
        )
        race_refs[race_id] = race_ref
        records.append(
            {
                "race_id": race_id,
                "race_ref": race_ref,
                "target_runner": target_rows[0],
            }
        )
    target_race_id = None if profile_only else str(target_race.get("race_id") or "")
    if not profile_only and target_race_id not in race_refs:
        raise ContentPoolError("target race is absent from provider career")
    scope_target_races = result.get("scope_target_races", [] if profile_only else [target_race])
    if not isinstance(scope_target_races, list) or (not profile_only and not scope_target_races):
        raise ContentPoolError("targeted scope races are missing")
    if profile_only and scope_target_races:
        raise ContentPoolError("profile-only export cannot claim provider scope races")
    scope_target_race_ids = []
    for scoped_race in scope_target_races:
        if not isinstance(scoped_race, Mapping):
            raise ContentPoolError("targeted scope race must be an object")
        scoped_race_id = str(scoped_race.get("race_id") or "")
        if scoped_race_id not in race_refs:
            raise ContentPoolError("targeted scope race is absent from provider career")
        if scoped_race_id in scope_target_race_ids:
            raise ContentPoolError("targeted scope race identity is duplicated")
        scope_target_race_ids.append(scoped_race_id)
    return {
        "schema_version": COMPACT_SCHEMA_VERSION,
        "database_writes": 0,
        "seed_id": result.get("seed_id"),
        "horse_id": horse_id,
        "identity_mode": result.get("identity_mode"),
        "profile_ref": profile_ref,
        "page_field_matrix_ref": page_field_matrix_ref,
        "parent_profile_refs": parent_refs,
        "career": {
            "provider_row_count": career.get("provider_row_count"),
            "unique_race_count": career.get("unique_race_count"),
            "page_count": career.get("page_count"),
            "records": records,
        },
        "career_authority": result.get("career_authority"),
        "target_occurrence": result.get("target_occurrence"),
        "target_race_id": target_race_id,
        "target_race_ref": race_refs[target_race_id] if target_race_id else None,
        "scope_target_race_ids": scope_target_race_ids,
        "scope_target_race_refs": [race_refs[race_id] for race_id in scope_target_race_ids],
    }
