#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class ControlledHTTPError(RuntimeError):
    pass


def _validate_policy(policy: object) -> dict:
    if not isinstance(policy, dict):
        raise ControlledHTTPError("request policy must be an object")
    normalized = dict(policy)
    max_requests = normalized.get("max_requests")
    host_max = normalized.get("max_requests_per_host", max_requests)
    interval = normalized.get("minimum_interval_seconds")
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests <= 0:
        raise ControlledHTTPError("per-shard request budget must be positive")
    if isinstance(host_max, bool) or not isinstance(host_max, int) or host_max <= 0:
        raise ControlledHTTPError("per-host request budget must be positive")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < 0:
        raise ControlledHTTPError("minimum request interval is invalid")
    allowed = normalized.get("allowed_hosts")
    redirects = normalized.get("redirect_hosts")
    patterns = normalized.get("url_patterns")
    if (
        not isinstance(allowed, list)
        or not allowed
        or len(allowed) != len(set(allowed))
        or not isinstance(redirects, list)
        or not set(redirects) <= set(allowed)
        or not isinstance(patterns, dict)
        or set(patterns) != set(allowed)
    ):
        raise ControlledHTTPError("request host policy is invalid")
    for host in allowed:
        if not isinstance(host, str) or host != host.casefold() or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise ControlledHTTPError("request host is invalid")
        host_patterns = patterns.get(host)
        if not isinstance(host_patterns, list) or not host_patterns:
            raise ControlledHTTPError(f"request URL patterns are missing for {host}")
        for pattern in host_patterns:
            if not isinstance(pattern, str):
                raise ControlledHTTPError("request URL regex is invalid")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ControlledHTTPError("request URL regex is invalid") from exc
    query_patterns = normalized.get("query_patterns")
    if query_patterns is not None:
        if not isinstance(query_patterns, dict) or not set(query_patterns) <= set(allowed):
            raise ControlledHTTPError("request query host policy is invalid")
        for host, query_policy in query_patterns.items():
            if not isinstance(query_policy, dict) or set(query_policy) != {
                "parameters",
                "required_keys",
            }:
                raise ControlledHTTPError("request query policy is invalid")
            parameters = query_policy["parameters"]
            required = query_policy["required_keys"]
            if (
                not isinstance(parameters, dict)
                or not parameters
                or not isinstance(required, list)
                or len(required) != len(set(required))
                or not set(required) <= set(parameters)
            ):
                raise ControlledHTTPError("request query parameter policy is invalid")
            for key, pattern in parameters.items():
                if (
                    not isinstance(key, str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key)
                    or not isinstance(pattern, str)
                    or not pattern
                    or ".*" in pattern
                    or ".+" in pattern
                ):
                    raise ControlledHTTPError("request query parameter regex is invalid")
                try:
                    compiled = re.compile(pattern)
                except re.error as exc:
                    raise ControlledHTTPError("request query parameter regex is invalid") from exc
                if compiled.fullmatch("") is not None:
                    raise ControlledHTTPError("request query parameter regex cannot match empty values")
    normalized["max_requests_per_host"] = host_max
    return normalized


def _validate_query(
    query: str,
    *,
    host: str,
    query_patterns: Mapping[str, dict],
    url: str,
) -> None:
    query_policy = query_patterns.get(host)
    if not query:
        if query_policy and query_policy["required_keys"]:
            raise ControlledHTTPError(f"request URL is missing required query parameters: {url}")
        return
    if query_policy is None:
        raise ControlledHTTPError(f"request URL query is not approved: {url}")
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ControlledHTTPError(f"request URL query is malformed: {url}") from exc
    parameters = query_policy["parameters"]
    seen: set[str] = set()
    for key, value in pairs:
        if (
            not key
            or key in seen
            or key not in parameters
            or not value
            or re.fullmatch(parameters[key], value) is None
        ):
            raise ControlledHTTPError(f"request URL query is not approved: {url}")
        seen.add(key)
    if not set(query_policy["required_keys"]) <= seen:
        raise ControlledHTTPError(f"request URL is missing required query parameters: {url}")


def _validated_url(
    url: str,
    *,
    hosts: set[str],
    patterns: Mapping[str, list[str]],
    query_patterns: Mapping[str, dict],
) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ControlledHTTPError(f"request URL is malformed: {url}") from exc
    if (
        parsed.scheme != "https"
        or not host
        or host not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise ControlledHTTPError(f"request URL is outside the approved boundary: {url}")
    if not any(re.fullmatch(pattern, parsed.path) for pattern in patterns.get(host, [])):
        raise ControlledHTTPError(f"request URL path is not approved: {url}")
    _validate_query(
        parsed.query,
        host=host,
        query_patterns=query_patterns,
        url=url,
    )
    return url, host


def _safe_artifact_path(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise ControlledHTTPError(f"request state path is unsafe: {path}")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ControlledHTTPError(f"symlink request state path is forbidden: {current}")
        if not current.exists():
            break
    return path


def _read_state(path: Path, *, kind: str) -> dict:
    if not path.exists():
        return {"schema_version": "2.0", "request_count": 0, "requests": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlledHTTPError(f"{kind} request state is corrupt: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("request_count"), int):
        raise ControlledHTTPError(f"{kind} request state is invalid: {path}")
    return value


def _atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class ControlledRequestSession:
    def __init__(
        self,
        *,
        policy: dict,
        shard_id: str,
        shard_state_path: str | Path,
        host_state_root: str | Path,
    ) -> None:
        if not isinstance(shard_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", shard_id):
            raise ControlledHTTPError("request shard identity is invalid")
        self.policy = _validate_policy(policy)
        self.shard_id = shard_id
        self.shard_state_path = _safe_artifact_path(Path(shard_state_path))
        self.host_state_root = _safe_artifact_path(Path(host_state_root))
        self.shard_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.host_state_root.mkdir(parents=True, exist_ok=True)
        _safe_artifact_path(self.shard_state_path.parent)
        _safe_artifact_path(self.host_state_root)
        self.reserved_urls: list[str] = []

    def reserve_initial(self, url: str) -> dict:
        validated, host = _validated_url(
            url,
            hosts=set(self.policy["allowed_hosts"]),
            patterns=self.policy["url_patterns"],
            query_patterns=self.policy.get("query_patterns") or {},
        )
        return self._reserve(validated, host=host, request_kind="initial")

    def reserve_redirect(self, url: str) -> dict:
        validated, host = _validated_url(
            url,
            hosts=set(self.policy["redirect_hosts"]),
            patterns=self.policy["url_patterns"],
            query_patterns=self.policy.get("query_patterns") or {},
        )
        return self._reserve(validated, host=host, request_kind="redirect")

    def validate_final_url(self, url: str) -> None:
        validated, _host = _validated_url(
            url,
            hosts=set(self.policy["allowed_hosts"]),
            patterns=self.policy["url_patterns"],
            query_patterns=self.policy.get("query_patterns") or {},
        )
        if validated not in self.reserved_urls:
            raise ControlledHTTPError(f"unreserved redirect response is forbidden: {url}")

    def _reserve(self, url: str, *, host: str, request_kind: str) -> dict:
        host_state = _safe_artifact_path(self.host_state_root / f"{host}.last-start.json")
        host_log = _safe_artifact_path(self.host_state_root / f"{host}.requests.jsonl")
        lock_paths = sorted(
            {
                self.shard_state_path.with_suffix(self.shard_state_path.suffix + ".lock"),
                host_state.with_suffix(host_state.suffix + ".lock"),
            },
            key=str,
        )
        with ExitStack() as stack:
            handles = []
            for lock_path in lock_paths:
                _safe_artifact_path(lock_path)
                handle = stack.enter_context(lock_path.open("a+b"))
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                handles.append(handle)
            shard = _read_state(self.shard_state_path, kind="shard")
            shared = _read_state(host_state, kind="host")
            shard_count = shard["request_count"]
            host_count = shared["request_count"]
            shard_requests = shard.get("requests")
            if (
                not isinstance(shard_requests, list)
                or len(shard_requests) != shard_count
                or any(not isinstance(row, dict) for row in shard_requests)
            ):
                raise ControlledHTTPError(
                    f"shard request state is invalid: {self.shard_state_path}"
                )
            shard_host_count = sum(
                1 for row in shard_requests if row.get("host") == host
            )
            if shard_count >= self.policy["max_requests"]:
                raise ControlledHTTPError("per-shard request budget is exhausted")
            if shard_host_count >= self.policy["max_requests_per_host"]:
                raise ControlledHTTPError("per-host request budget is exhausted")
            previous = float(shared.get("last_start_epoch") or 0.0)
            remaining = float(self.policy["minimum_interval_seconds"]) - (time.time() - previous)
            if remaining > 0:
                time.sleep(remaining)
            started_epoch = time.time()
            row = {
                "sequence": shard_count + 1,
                "host_sequence": host_count + 1,
                "host": host,
                "shard_id": self.shard_id,
                "request_kind": request_kind,
                "url": url,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "started_at_epoch": started_epoch,
            }
            shard_requests = list(shard_requests)
            shard_requests.append(row)
            shard.update(
                {
                    "schema_version": "2.0",
                    "shard_id": self.shard_id,
                    "max_requests": self.policy["max_requests"],
                    "request_count": shard_count + 1,
                    "requests": shard_requests,
                }
            )
            shared.update(
                {
                    "schema_version": "2.0",
                    "host": host,
                    "request_count": host_count + 1,
                    "last_start_epoch": started_epoch,
                    "last_shard_id": self.shard_id,
                }
            )
            _atomic_write(self.shard_state_path, shard)
            _atomic_write(host_state, shared)
            with host_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        self.reserved_urls.append(url)
        return row


class _ControlledRedirectHandler(HTTPRedirectHandler):
    def __init__(
        self,
        session: ControlledRequestSession,
        *,
        before_request: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.session = session
        self.before_request = before_request

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.session.reserve_redirect(newurl)
        if self.before_request is not None:
            self.before_request(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def controlled_http_get(
    url: str,
    *,
    policy: dict,
    shard_id: str,
    shard_state_path: str | Path,
    host_state_root: str | Path,
    timeout: int,
    headers: Mapping[str, str] | None = None,
    before_request: Callable[[str], None] | None = None,
) -> bytes:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ControlledHTTPError("request timeout must be a positive integer")
    session = ControlledRequestSession(
        policy=policy,
        shard_id=shard_id,
        shard_state_path=shard_state_path,
        host_state_root=host_state_root,
    )
    session.reserve_initial(url)
    if before_request is not None:
        before_request(url)
    opener = build_opener(
        _ControlledRedirectHandler(
            session,
            before_request=before_request,
        )
    )
    request = Request(url, headers=dict(headers or {}), method="GET")
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        session.validate_final_url(final_url)
        return response.read()
