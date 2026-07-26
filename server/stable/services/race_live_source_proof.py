from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import stat
import tempfile
import time
from typing import Any, Callable
from urllib.parse import urlsplit


_HOST = "api.theracingapi.com"
_PROOF_ENDPOINTS = (
    ("regions", "/v1/courses/regions"),
    ("racecards_today", "/v1/racecards/free?day=today&limit=500&skip=0"),
    ("results_today", "/v1/results/today/free?limit=50&skip=0"),
)
_SYNC_ENDPOINTS = (
    (
        "racecards_sync_today",
        "/v1/racecards/free?day=today&region_codes=gb&limit=500&skip=0",
    ),
    (
        "racecards_sync_tomorrow",
        "/v1/racecards/free?day=tomorrow&region_codes=gb&limit=500&skip=0",
    ),
)
_ENDPOINTS = _PROOF_ENDPOINTS + _SYNC_ENDPOINTS
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REGION_CODES = {
    "united_kingdom": "gb",
    "france": "fr",
    "hong_kong": "hk",
    "japan": "jpn",
    "united_states": "usa",
}
_ROUTE_CONTRACTS = {
    "racecards_free": {
        "path": "/v1/racecards/free",
        "day": ["today", "tomorrow"],
        "limit": [500],
        "skip": [0],
    },
    "results_today_free": {
        "path": "/v1/results/today/free",
        "limit": [50],
        "skip": list(range(0, 500, 50)),
    },
}


@dataclass(frozen=True)
class RaceLiveProofHttpResponse:
    status_code: int
    content_type: str
    body: bytes
    elapsed_ms: int
    redirect_url: str | None = None


@dataclass(frozen=True)
class RaceLiveSourceProofResult:
    completed: bool
    request_count: int
    output_dir: Path


def _read_secret(path_value: str | os.PathLike[str]) -> tuple[str, str]:
    path = Path(path_value)
    if not path.is_absolute():
        raise ValueError("secret env file must be absolute")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("secret env file must be a regular file")
        if file_stat.st_uid != os.getuid():
            raise PermissionError("secret env file must be owned by the current user")
        if stat.S_IMODE(file_stat.st_mode) & 0o077:
            raise PermissionError("secret env file must not grant group/other access")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            secret_text = handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    values: dict[str, str] = {}
    for raw_line in secret_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid secret env syntax")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        elif value.startswith(('"', "'")) or value.endswith(('"', "'")):
            raise ValueError("invalid secret env quoting")
        if key in values:
            raise ValueError("duplicate secret env key")
        values[key] = value

    allowed = {"THE_RACING_API_USERNAME", "THE_RACING_API_PASSWORD"}
    if set(values) != allowed or not all(values.values()):
        raise ValueError("secret env must contain exactly the required non-empty keys")
    return values["THE_RACING_API_USERNAME"], values["THE_RACING_API_PASSWORD"]


def _read_registry_contract(
    path_value: str | os.PathLike[str],
    *,
    expected_sha256: str,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    path = Path(path_value)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if (
        len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256.lower())
        or not hmac.compare_digest(digest, expected_sha256.lower())
    ):
        raise PermissionError("source registry digest mismatch")
    try:
        registry = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("source registry must be valid JSON") from exc
    if not isinstance(registry, dict):
        raise ValueError("source registry must be an object")
    required_v1 = {
        "schema_version",
        "source_key",
        "host",
        "terms_status",
        "proof_network_allowed",
        "automation_allowed",
        "valid_until",
        "max_requests",
        "evidence",
        "endpoints",
    }
    required_v2 = (
        required_v1
        - {"endpoints"}
        | {"allowed_region_codes", "route_contracts"}
    )
    schema_version = registry.get("schema_version")
    if (
        schema_version == 1
        and set(registry) != required_v1
    ) or (
        schema_version == 2
        and set(registry) != required_v2
    ) or schema_version not in {1, 2}:
        raise ValueError("source registry keys do not match the proof contract")
    if registry["source_key"] != "the_racing_api" or registry["host"] != _HOST:
        raise PermissionError("source registry identity is not approved")
    if registry["terms_status"] != "approved":
        raise PermissionError("source terms status is not approved")
    if not isinstance(registry["proof_network_allowed"], bool):
        raise ValueError("network proof permission must be an explicit boolean")
    if not isinstance(registry["automation_allowed"], bool):
        raise ValueError("source automation permission must be an explicit boolean")
    try:
        valid_until = datetime.fromisoformat(registry["valid_until"])
    except (TypeError, ValueError) as exc:
        raise ValueError("source registry expiry is invalid") from exc
    if valid_until.tzinfo is None or now.tzinfo is None:
        raise ValueError("source registry times must be timezone-aware")
    if now >= valid_until:
        raise PermissionError("source registry permission has expired")
    evidence = registry["evidence"]
    expected_evidence_keys = {
        "documentation_url",
        "terms_url",
        "verified_at",
        "authorization_basis",
    }
    if not isinstance(evidence, dict) or set(evidence) != expected_evidence_keys:
        raise ValueError("source registry evidence does not match the proof contract")
    if (
        evidence["documentation_url"]
        != "https://api.theracingapi.com/documentation"
        or evidence["terms_url"]
        != "https://www.theracingapi.com/terms-of-service"
        or evidence["authorization_basis"]
        != "user_confirmed_automation_permission"
    ):
        raise PermissionError("source registry evidence is not approved")
    try:
        evidence_verified_at = datetime.fromisoformat(evidence["verified_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError("source registry evidence timestamp is invalid") from exc
    if evidence_verified_at.tzinfo is None:
        raise ValueError("source registry evidence timestamp must be timezone-aware")
    if evidence_verified_at > now:
        raise PermissionError("source registry evidence timestamp is in the future")
    if now - evidence_verified_at > timedelta(days=31):
        raise PermissionError("source registry evidence is stale")
    registry_budget = registry["max_requests"]
    if (
        isinstance(registry_budget, bool)
        or not isinstance(registry_budget, int)
        or registry_budget < 1
        or registry_budget > len(_PROOF_ENDPOINTS)
    ):
        raise ValueError("source registry max_requests must be between 1 and 3")
    if schema_version == 1:
        expected_endpoints = [
            {"name": name, "path": path} for name, path in _ENDPOINTS
        ]
        if registry["endpoints"] != expected_endpoints:
            raise PermissionError(
                "source registry endpoints do not match the allowlist"
            )
    else:
        if registry["allowed_region_codes"] != _REGION_CODES:
            raise PermissionError(
                "source registry region codes do not match the allowlist"
            )
        if registry["route_contracts"] != _ROUTE_CONTRACTS:
            raise PermissionError(
                "source registry route contracts do not match the allowlist"
            )
    return registry, digest


def build_the_racing_api_route_url(
    *,
    registry: dict[str, Any],
    route_name: str,
    region: str,
    limit: int,
    skip: int,
    day: str | None = None,
) -> str:
    """Build one canonical URL from the reviewed registry v2 contract."""
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != 2
        or registry.get("source_key") != "the_racing_api"
        or registry.get("host") != _HOST
        or registry.get("allowed_region_codes") != _REGION_CODES
        or registry.get("route_contracts") != _ROUTE_CONTRACTS
    ):
        raise PermissionError("source registry v2 contract is invalid")
    region_code = _REGION_CODES.get(region)
    contract = _ROUTE_CONTRACTS.get(route_name)
    if region_code is None or contract is None:
        raise ValueError("region or route is not allowed")
    if (
        isinstance(limit, bool)
        or limit not in contract["limit"]
        or isinstance(skip, bool)
        or skip not in contract["skip"]
    ):
        raise ValueError("route pagination is outside the contract")
    if route_name == "racecards_free":
        if day not in contract["day"]:
            raise ValueError("racecard day is outside the contract")
        query = (
            f"day={day}&region_codes={region_code}"
            f"&limit={limit}&skip={skip}"
        )
    else:
        if day is not None:
            raise ValueError("results route does not accept day")
        query = f"limit={limit}&skip={skip}"
    return f"https://{_HOST}{contract['path']}?{query}"


def _read_registry(
    path_value: str | os.PathLike[str],
    *,
    expected_sha256: str,
    now: datetime,
    max_requests: int,
) -> tuple[dict[str, Any], str]:
    registry, digest = _read_registry_contract(
        path_value,
        expected_sha256=expected_sha256,
        now=now,
    )
    if registry["proof_network_allowed"] is not True:
        raise PermissionError("network proof is not permitted")
    if (
        isinstance(max_requests, bool)
        or not isinstance(max_requests, int)
        or max_requests < 1
        or max_requests > len(_PROOF_ENDPOINTS)
    ):
        raise ValueError("max_requests must be between 1 and 3")
    if max_requests > registry["max_requests"]:
        raise PermissionError("requested proof exceeds the approved request budget")
    return registry, digest


def read_the_racing_api_automation_registry(
    *,
    registry_file: str | os.PathLike[str],
    expected_registry_sha256: str,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    """Read the fixed TRA registry under the long-term automation permission."""
    registry, digest = _read_registry_contract(
        registry_file,
        expected_sha256=expected_registry_sha256,
        now=now,
    )
    if registry["automation_allowed"] is not True:
        raise PermissionError("source automation is not permitted")
    return registry, digest


def _collection_metadata(endpoint_name: str, payload: Any) -> dict[str, Any]:
    if endpoint_name == "regions":
        if not isinstance(payload, list):
            raise ValueError("regions response must be a list")
        rows = payload
        top_level_fields: list[str] = []
        top_level_type = "list"
    else:
        collection_key = (
            "racecards"
            if endpoint_name
            in {
                "racecards_today",
                "racecards_sync_today",
                "racecards_sync_tomorrow",
            }
            else "results"
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get(collection_key), list
        ):
            raise ValueError(f"{collection_key} response collection must be a list")
        rows = payload[collection_key]
        top_level_fields = sorted(str(key) for key in payload)
        top_level_type = "object"
    row_fields: set[str] = set()
    runner_fields: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_fields.update(str(key) for key in row)
        runners = row.get("runners", [])
        if isinstance(runners, list):
            for runner in runners:
                if isinstance(runner, dict):
                    runner_fields.update(str(key) for key in runner)
    return {
        "collection_count": len(rows),
        "top_level_type": top_level_type,
        "top_level_fields": top_level_fields,
        "row_fields": sorted(row_fields),
        "runner_fields": sorted(runner_fields),
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_artifacts(
    output_dir: Path,
    *,
    registry_sha256: str,
    started_at: datetime,
    finished_at: datetime,
    request_budget: int,
    endpoints: list[str],
    terms_status: str,
    evidence_verified_at: str,
    completed: bool,
    requests: list[dict[str, Any]],
) -> None:
    manifest = {
        "schema_version": 1,
        "runner_version": "race-live-proof-v1",
        "source_key": "the_racing_api",
        "registry_sha256": registry_sha256,
        "started_at": started_at.isoformat(),
        "request_budget": request_budget,
        "endpoints": endpoints,
        "terms_status": terms_status,
        "evidence_verified_at": evidence_verified_at,
        "artifact_files": ["manifest.json", "requests.jsonl", "summary.json"],
    }
    summary = {
        "schema_version": 1,
        "source_key": "the_racing_api",
        "registry_sha256": registry_sha256,
        "completed": completed,
        "request_count": len(requests),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "terms_status": terms_status,
        "evidence_verified_at": evidence_verified_at,
    }
    _atomic_json(output_dir / "manifest.json", manifest)
    requests_path = output_dir / "requests.jsonl"
    temporary = requests_path.with_name(".requests.jsonl.tmp")
    with temporary.open("xb") as handle:
        for row in requests:
            handle.write(
                (
                    json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                ).encode("utf-8")
            )
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, requests_path)
    _atomic_json(output_dir / "summary.json", summary)


def run_the_racing_api_free_proof(
    *,
    secret_env_file: str | os.PathLike[str],
    registry_file: str | os.PathLike[str],
    expected_registry_sha256: str,
    output_dir: str | os.PathLike[str],
    now: datetime,
    transport: Callable[..., RaceLiveProofHttpResponse],
    sleep: Callable[[float], Any],
    max_requests: int,
    region: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> RaceLiveSourceProofResult:
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"output directory already exists: {output.name}")
    username, password = _read_secret(secret_env_file)
    registry, registry_digest = _read_registry(
        registry_file,
        expected_sha256=expected_registry_sha256,
        now=now,
        max_requests=max_requests,
    )
    request_rows: list[dict[str, Any]] = []
    completed = True
    schema_version = registry["schema_version"]
    if schema_version == 1:
        endpoints = [
            {
                "name": endpoint["name"],
                "url": f"https://{_HOST}{endpoint['path']}",
                "path": endpoint["path"],
            }
            for endpoint in registry["endpoints"][:max_requests]
        ]
    else:
        endpoints = []
        route_specs = (
            ("racecards_sync_today", "racecards_free", "today", 500),
            ("racecards_sync_tomorrow", "racecards_free", "tomorrow", 500),
            ("results_today", "results_today_free", None, 50),
        )
        for endpoint_name, route_name, day, limit in route_specs[:max_requests]:
            endpoints.append(
                {
                    "name": endpoint_name,
                    "url": build_the_racing_api_route_url(
                        registry=registry,
                        route_name=route_name,
                        region=region,
                        day=day,
                        limit=limit,
                        skip=0,
                    ),
                }
            )
        for endpoint in endpoints:
            parsed_url = urlsplit(endpoint["url"])
            endpoint["path"] = parsed_url.path + (
                f"?{parsed_url.query}" if parsed_url.query else ""
            )
    requested_paths: list[str] = []
    for index, endpoint in enumerate(endpoints):
        if index:
            sleep(1.05)
        row: dict[str, Any] = {
            "endpoint_name": endpoint["name"],
            "request_number": index + 1,
        }
        try:
            requested_paths.append(endpoint["path"])
            response = transport(
                endpoint_name=endpoint["name"],
                url=endpoint["url"],
                username=username,
                password=password,
                timeout_seconds=15,
                max_response_bytes=_MAX_RESPONSE_BYTES,
                allow_redirects=False,
            )
            row.update(
                {
                    "status": response.status_code,
                    "elapsed_ms": response.elapsed_ms,
                    "bytes": len(response.body),
                    "content_type": response.content_type,
                    "response_sha256": hashlib.sha256(response.body).hexdigest(),
                }
            )
            if response.redirect_url is not None or 300 <= response.status_code < 400:
                row["error"] = "redirect_rejected"
                completed = False
            elif response.status_code != 200:
                row["error"] = "http_status_error"
                completed = False
            elif len(response.body) > _MAX_RESPONSE_BYTES:
                row["error"] = "response_too_large"
                completed = False
            elif response.content_type.split(";", 1)[0].strip().lower() not in {
                "application/json",
                "application/problem+json",
            }:
                row["error"] = "non_json_content_type"
                completed = False
            else:
                try:
                    payload = json.loads(response.body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    row["error"] = "invalid_json"
                    completed = False
                else:
                    try:
                        row.update(_collection_metadata(endpoint["name"], payload))
                    except ValueError:
                        row["error"] = "schema_contract_error"
                        completed = False
        except Exception:
            row["status"] = "transport_error"
            row["error"] = "transport_error: [REDACTED]"
            completed = False
        request_rows.append(row)
        if not completed:
            break

    finished_at = (
        clock() if clock is not None else datetime.now(tz=dt_timezone.utc)
    )
    if not isinstance(finished_at, datetime):
        raise ValueError("proof completion clock must return a datetime")
    if finished_at.tzinfo is None:
        raise ValueError("proof completion clock must be timezone-aware")
    if finished_at < now:
        raise ValueError("proof completion time cannot precede its start time")

    parent = output.parent
    if not parent.is_dir():
        raise ValueError("output parent directory must already exist")
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", suffix=".tmp", dir=parent)
    )
    try:
        _write_artifacts(
            temporary,
            registry_sha256=registry_digest,
            started_at=now,
            finished_at=finished_at,
            request_budget=max_requests,
            endpoints=(
                [endpoint["path"] for endpoint in registry["endpoints"]]
                if schema_version == 1
                else requested_paths
            ),
            terms_status=registry["terms_status"],
            evidence_verified_at=registry["evidence"]["verified_at"],
            completed=completed,
            requests=request_rows,
        )
        directory_fd = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if output.exists():
            raise FileExistsError(f"output directory already exists: {output.name}")
        temporary.rename(output)
        parent_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return RaceLiveSourceProofResult(
        completed=completed,
        request_count=len(request_rows),
        output_dir=output,
    )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        address: str,
        *,
        timeout: float,
    ) -> None:
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._address, self.port or 443),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _resolve_public_addresses(host: str) -> list[str]:
    addresses: list[str] = []
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        address = info[4][0]
        parsed = ipaddress.ip_address(address)
        if not parsed.is_global:
            raise PermissionError("source host resolved to a non-public address")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise OSError("source host did not resolve")
    return addresses


def the_racing_api_transport(
    *,
    endpoint_name: str,
    url: str,
    username: str,
    password: str,
    timeout_seconds: int,
    max_response_bytes: int,
    allow_redirects: bool,
) -> RaceLiveProofHttpResponse:
    parsed = urlsplit(url)
    request_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    allowed_requests = set(_ENDPOINTS)
    for region_code in _REGION_CODES.values():
        for day in ("today", "tomorrow"):
            allowed_requests.add(
                (
                    f"racecards_sync_{day}",
                    (
                        "/v1/racecards/free"
                        f"?day={day}&region_codes={region_code}"
                        "&limit=500&skip=0"
                    ),
                )
            )
    for skip in range(0, 500, 50):
        allowed_requests.add(
            (
                "results_today",
                f"/v1/results/today/free?limit=50&skip={skip}",
            )
        )
    if (
        (endpoint_name, request_path) not in allowed_requests
        or parsed.scheme != "https"
        or parsed.hostname != _HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or allow_redirects is not False
    ):
        raise PermissionError("transport target is outside the fixed allowlist")
    addresses = _resolve_public_addresses(_HOST)
    credential = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
        "ascii"
    )
    started = time.monotonic()
    connection = _PinnedHTTPSConnection(
        _HOST,
        addresses[0],
        timeout=timeout_seconds,
    )
    try:
        connection.request(
            "GET",
            request_path,
            headers={
                "Authorization": f"Basic {credential}",
                "Accept": "application/json",
                "User-Agent": "UmaFans-RaceLive-Proof/1.0",
            },
        )
        response = connection.getresponse()
        body = response.read(max_response_bytes + 1)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return RaceLiveProofHttpResponse(
            status_code=response.status,
            content_type=response.getheader("Content-Type", ""),
            body=body,
            elapsed_ms=elapsed_ms,
            redirect_url=response.getheader("Location"),
        )
    finally:
        connection.close()
