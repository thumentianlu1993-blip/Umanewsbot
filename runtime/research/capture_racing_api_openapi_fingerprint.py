#!/usr/bin/env python3
"""从已下载的 TRA OpenAPI 生成可复核、无网络的精确指纹。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = "racing-api-openapi-fingerprint-capture.v1"
SOURCE_URL = "https://api.theracingapi.com/openapi.json"
SELECTED_PATHS = (
    "/v1/horses/search",
    "/v1/horses/{horse_id}/pro",
    "/v1/horses/{horse_id}/results",
    "/v1/horses/{horse_id}/standard",
    "/v1/results",
)
SELECTED_SCHEMAS = (
    "Horse",
    "HorsePro",
    "ResultsStandardPage",
    "RunnerStandard",
)
EXPECTED_OPERATION_PLANS = {
    "/v1/horses/search": {"Standard Plan", "Pro Plan"},
    "/v1/horses/{horse_id}/pro": {"Pro Plan"},
    "/v1/horses/{horse_id}/results": {"Pro Plan"},
    "/v1/horses/{horse_id}/standard": {"Standard Plan", "Pro Plan"},
    "/v1/results": {"Standard Plan", "Pro Plan"},
}
SHA256_RE = re.compile(r"[0-9a-f]{64}$")


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _regular_input(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError("OpenAPI input must be a regular non-symlink file")
    return resolved


def _operation(path: str, paths: Mapping[str, object]) -> dict:
    value = paths.get(path)
    if not isinstance(value, Mapping) or set(value) != {"get"}:
        raise ValueError(f"selected OpenAPI path contract drift: {path}")
    operation = value.get("get")
    if not isinstance(operation, Mapping):
        raise ValueError(f"selected OpenAPI operation is invalid: {path}")
    tags = operation.get("tags")
    description = operation.get("description")
    if (
        not isinstance(tags, list)
        or not EXPECTED_OPERATION_PLANS[path].issubset(set(tags))
        or not isinstance(description, str)
        or "5 requests per second" not in description
    ):
        raise ValueError(f"selected OpenAPI entitlement/rate contract drift: {path}")
    return dict(value)


def build_fingerprint(
    *, raw_openapi_path: Path, generated_at: datetime
) -> tuple[dict, dict]:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    resolved = _regular_input(raw_openapi_path)
    raw = resolved.read_bytes()
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("OpenAPI input size is invalid")
    try:
        document = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("OpenAPI input is invalid JSON") from exc
    if not isinstance(document, Mapping):
        raise ValueError("OpenAPI root must be an object")
    info = document.get("info")
    paths = document.get("paths")
    components = document.get("components")
    schemas = components.get("schemas") if isinstance(components, Mapping) else None
    if (
        document.get("openapi") != "3.1.0"
        or not isinstance(info, Mapping)
        or info.get("title") != "The Racing API"
        or not isinstance(info.get("version"), str)
        or not isinstance(paths, Mapping)
        or not isinstance(schemas, Mapping)
    ):
        raise ValueError("OpenAPI root contract drift")
    selected_paths = {path: _operation(path, paths) for path in SELECTED_PATHS}
    selected_schemas = {}
    for name in SELECTED_SCHEMAS:
        schema = schemas.get(name)
        if not isinstance(schema, Mapping):
            raise ValueError(f"selected OpenAPI schema is missing: {name}")
        selected_schemas[name] = dict(schema)
    selected_contract_sha256 = sha256_bytes(
        canonical_json(selected_paths).encode("utf-8")
    )
    selected_schema_sha256 = sha256_bytes(
        canonical_json(selected_schemas).encode("utf-8")
    )
    fingerprint = {
        "fingerprint_generated_at": generated_at.isoformat(),
        "full_openapi_sha256": sha256_bytes(raw),
        "openapi_version": info["version"],
        "selected_contract": {
            "paths": list(SELECTED_PATHS),
            "sha256": selected_contract_sha256,
        },
        "selected_schema": {
            "names": list(SELECTED_SCHEMAS),
            "sha256": selected_schema_sha256,
        },
        "source_url": SOURCE_URL,
    }
    review = {
        "schema_version": SCHEMA_VERSION,
        "network_requests": 0,
        "database_writes": 0,
        "raw_openapi": {
            "path": str(resolved),
            "sha256": sha256_bytes(raw),
            "size": len(raw),
        },
        "fingerprint": fingerprint,
        "selected_operations": [
            {
                "path": path,
                "operation_id": selected_paths[path]["get"].get("operationId"),
                "plans": sorted(
                    tag
                    for tag in selected_paths[path]["get"]["tags"]
                    if tag.endswith(" Plan")
                ),
                "rate_limit_requests_per_second": 5,
            }
            for path in SELECTED_PATHS
        ],
        "historical_bulk_add_on_declared": (
            "historical results add-on"
            in selected_paths["/v1/results"]["get"]["description"].casefold()
        ),
    }
    return fingerprint, review


def capture(
    *,
    raw_openapi_path: Path,
    generated_at: datetime,
    output_path: Path,
    review_path: Path,
) -> dict:
    if output_path.resolve() == review_path.resolve():
        raise ValueError("fingerprint and review outputs must differ")
    if output_path.exists() or review_path.exists():
        raise ValueError("fingerprint outputs must not already exist")
    fingerprint, review = build_fingerprint(
        raw_openapi_path=raw_openapi_path,
        generated_at=generated_at,
    )
    _atomic_write(
        output_path,
        (json.dumps(fingerprint, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    review["fingerprint_file"] = {
        "path": str(output_path.resolve(strict=True)),
        "sha256": sha256_bytes(output_path.read_bytes()),
        "size": output_path.stat().st_size,
    }
    _atomic_write(
        review_path,
        (json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return review


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-openapi", required=True, type=Path)
    parser.add_argument("--generated-at", required=True, type=datetime.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--review-output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    review = capture(
        raw_openapi_path=args.raw_openapi,
        generated_at=args.generated_at,
        output_path=args.output,
        review_path=args.review_output,
    )
    print(
        json.dumps(
            {
                "fingerprint_sha256": review["fingerprint_file"]["sha256"],
                "full_openapi_sha256": review["fingerprint"]["full_openapi_sha256"],
                "selected_contract_sha256": review["fingerprint"]["selected_contract"]["sha256"],
                "selected_schema_sha256": review["fingerprint"]["selected_schema"]["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
