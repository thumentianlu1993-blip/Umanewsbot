#!/usr/bin/env python3
"""The Racing API 马匹历史导出的纯离线合同与规范化函数。

联网 runner 会在这些 fail-closed 纯函数稳定后接入；本模块本身不读取凭据、不访问网络、
不导入 Django，也不写数据库。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

try:  # Package import for unittest/Django callers.
    from .racing_api_account_budget import (
        FileAccountBudget,
        load_exclusive_account_proof,
    )
    from .racing_api_content_pool import ContentAddressedPool, compact_targeted_export
except ImportError:  # Standalone script execution from runtime/research.
    from racing_api_account_budget import (
        FileAccountBudget,
        load_exclusive_account_proof,
    )
    from racing_api_content_pool import ContentAddressedPool, compact_targeted_export


HORSE_ID_RE = re.compile(r"hrs_[A-Za-z0-9]+$")
PARENT_ID_RE = re.compile(r"(?:sir|dam|dsi)_[A-Za-z0-9]+$")
COUNTRY_SUFFIX_RE = re.compile(r"^(.*?)\s*\(([A-Z]{2,3})\)\s*$")
FINISHED_POSITION_RE = re.compile(r"\d+(?:DH)?$", re.I)
STARTED_NON_FINISH = frozenset({"BD", "DNF", "F", "PU", "REF", "RO", "RR", "SU", "UR", "VOID"})
DISQUALIFIED = frozenset({"DSQ", "DQ"})
NON_RUNNER = frozenset({"NR", "NON-RUNNER", "NON RUNNER", "SCR", "SCRATCHED", "WD", "WDR", "WITHDRAWN"})
PROFILE_ONLY_EXTERNAL_ANCHOR_AUTHORITIES = frozenset(
    {
        "grading_authority",
        "human_reviewed_reference",
        "official_operator_archived_result",
        "official_or_reviewed_industry_result",
        "organizer_official",
        "regulator_official",
        "reviewed_human_and_organizer_official",
    }
)
REGION_CODES = {
    "united_kingdom": "GB",
    "ireland": "IRE",
    "france": "FR",
    "united_states": "USA",
}
API_ORIGIN = "https://api.theracingapi.com"
CLIENT_USER_AGENT = "UmanewsDataExporter/1.0 (https://umafans.run)"
OPENAPI_SOURCE_URL = f"{API_ORIGIN}/openapi.json"
EXPECTED_OPENAPI_VERSION = "1.4.4"
EXPECTED_OPENAPI_FULL_SHA256 = "0033643fcca4301889098fe6dcda021beb840207880f848a25b6153208a87df7"
EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256 = "910e5ccc1592bc3f50c5219bac6a195f9d1f7063bd5b7e7ef3b31b716d1514ba"
EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256 = "cc7fc55ebd1bd3a0c6120c698a7bd4e03a99ba83bfe839f7fa69d8badfef9173"
EXPECTED_OPENAPI_SELECTED_PATHS = (
    "/v1/horses/search",
    "/v1/horses/{horse_id}/pro",
    "/v1/horses/{horse_id}/results",
    "/v1/horses/{horse_id}/standard",
    "/v1/results",
)
EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES = (
    "Horse",
    "HorsePro",
    "ResultsStandardPage",
    "RunnerStandard",
)
MAX_OPENAPI_FINGERPRINT_BYTES = 64 * 1024
SAFE_STOP_EXIT_CODE = 75
ALLOWED_ENDPOINT_PATH_RE = re.compile(
    r"/v1/(?:horses/search|horses/hrs_[A-Za-z0-9]+/(?:pro|standard|results)|results)$"
)


class RacingApiError(RuntimeError):
    pass


class RacingApiHttpError(RacingApiError):
    pass


class RacingApiAuthError(RacingApiHttpError):
    pass


class RacingApiSchemaError(RacingApiError):
    pass


class RacingApiSemanticGap(ValueError):
    """A reviewed seed could not be resolved without guessing identity."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str


def classify_auth_failure(response: HttpResponse) -> str:
    """把 401/403 响应压缩成不包含服务端原文的可审计类别。"""

    if response.status == 401:
        return "credentials_rejected"
    if response.status != 403:
        raise ValueError("auth failure classification requires 401 or 403")
    content_type = str(response.headers.get("content-type", "")).casefold()
    message = ""
    if content_type.startswith("application/json") and len(response.body) <= 16 * 1024:
        try:
            payload = json.loads(
                response.body,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_non_finite_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            payload = None
        if isinstance(payload, Mapping):
            message = " ".join(
                normalize_space(payload.get(key))
                for key in (
                    "detail",
                    "message",
                    "error",
                    "error_category",
                    "error_name",
                )
                if isinstance(payload.get(key), str)
            ).casefold()
    edge_markers = (
        "browser's signature",
        "browser signature",
        "cloudflare",
        "edge_security",
    )
    credential_markers = (
        "credential",
        "incorrect username",
        "invalid username",
        "invalid password",
        "username or password",
        "authentication failed",
    )
    entitlement_markers = (
        "plan",
        "subscription",
        "subscribe",
        "upgrade",
        "permission",
        "not entitled",
    )
    if any(marker in message for marker in edge_markers):
        return "edge_client_blocked"
    if any(marker in message for marker in credential_markers):
        return "credentials_rejected"
    if any(marker in message for marker in entitlement_markers):
        return "endpoint_not_entitled"
    return "forbidden_unclassified"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_fetcher(*, url: str, headers: Mapping[str, str], timeout_seconds: float, max_body_bytes: int) -> HttpResponse:
    request = Request(url, method="GET", headers=dict(headers))
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(max_body_bytes + 1)
            return HttpResponse(
                status=response.status,
                headers={key.casefold(): value for key, value in response.headers.items()},
                body=body,
                final_url=response.geturl(),
            )
    except HTTPError as exc:
        return HttpResponse(
            status=exc.code,
            headers={key.casefold(): value for key, value in exc.headers.items()},
            body=exc.read(max_body_bytes + 1),
            final_url=exc.geturl(),
        )
    except URLError as exc:
        raise RacingApiHttpError(f"transport error: {exc.reason}") from exc


def _positive_page_value(name: str, value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"invalid {name}")
    return value


def build_endpoint(kind: str, **values: object) -> str:
    if kind == "horse_search":
        name = normalize_space(values.get("name"))
        if not name or len(name) > 200:
            raise ValueError("invalid horse search name")
        return f"{API_ORIGIN}/v1/horses/search?{urlencode({'name': name})}"
    if kind in {"horse_pro", "horse_standard", "horse_results"}:
        horse_id = normalize_space(values.get("horse_id"))
        if not HORSE_ID_RE.fullmatch(horse_id):
            raise ValueError("invalid horse id")
        suffix = {"horse_pro": "pro", "horse_standard": "standard", "horse_results": "results"}[kind]
        url = f"{API_ORIGIN}/v1/horses/{horse_id}/{suffix}"
        if kind == "horse_results":
            limit = _positive_page_value("limit", values.get("limit", 100), minimum=1, maximum=100)
            skip = _positive_page_value("skip", values.get("skip", 0), minimum=0, maximum=20000)
            url = f"{url}?{urlencode({'limit': limit, 'skip': skip})}"
        return url
    if kind == "bulk_results":
        start_date = normalize_space(values.get("start_date"))
        end_date = normalize_space(values.get("end_date"))
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError as exc:
            raise ValueError("invalid results date") from exc
        if start > end or (end - start).days > 364:
            raise ValueError("invalid results date range")
        # Race payloads use IFHA-style upper-case region codes, while the
        # /v1/results filter contract expects The Racing API's lower-case
        # course region codes (for example ``fr`` rather than ``FR``).
        region = normalize_space(values.get("region")).lower()
        if region not in {value.lower() for value in REGION_CODES.values()}:
            raise ValueError("invalid results region")
        limit = _positive_page_value("limit", values.get("limit", 100), minimum=1, maximum=100)
        skip = _positive_page_value("skip", values.get("skip", 0), minimum=0, maximum=20000)
        query = urlencode(
            {"start_date": start_date, "end_date": end_date, "region": region, "limit": limit, "skip": skip}
        )
        return f"{API_ORIGIN}/v1/results?{query}"
    raise ValueError(f"unknown endpoint kind: {kind}")


def validate_endpoint_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.theracingapi.com":
        raise ValueError("endpoint host is not allowlisted")
    if parsed.username or parsed.password or parsed.port is not None or parsed.fragment:
        raise ValueError("endpoint authority is invalid")
    if not ALLOWED_ENDPOINT_PATH_RE.fullmatch(parsed.path):
        raise ValueError("endpoint path is not allowlisted")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("endpoint query parameters cannot repeat")
    if parsed.path == "/v1/horses/search":
        if set(query) != {"name"} or not normalize_space(query["name"][0]):
            raise ValueError("horse search query is invalid")
        return
    if parsed.path.endswith(("/pro", "/standard")):
        if query:
            raise ValueError("profile endpoint query is forbidden")
        return
    if parsed.path.endswith("/results") and parsed.path != "/v1/results":
        if set(query) != {"limit", "skip"}:
            raise ValueError("horse results query is invalid")
        try:
            _positive_page_value("limit", int(query["limit"][0]), minimum=1, maximum=100)
            _positive_page_value("skip", int(query["skip"][0]), minimum=0, maximum=20000)
        except (TypeError, ValueError) as exc:
            raise ValueError("horse results query is invalid") from exc
        return
    if parsed.path == "/v1/results":
        if set(query) != {"start_date", "end_date", "region", "limit", "skip"}:
            raise ValueError("bulk results query is invalid")
        try:
            start = date.fromisoformat(query["start_date"][0])
            end = date.fromisoformat(query["end_date"][0])
            _positive_page_value("limit", int(query["limit"][0]), minimum=1, maximum=100)
            _positive_page_value("skip", int(query["skip"][0]), minimum=0, maximum=20000)
        except (TypeError, ValueError) as exc:
            raise ValueError("bulk results query is invalid") from exc
        if (
            start > end
            or (end - start).days > 364
            or query["region"][0]
            not in {value.lower() for value in REGION_CODES.values()}
        ):
            raise ValueError("bulk results query is invalid")
        return
    raise ValueError("endpoint query validation is missing")


class RacingApiClient:
    def __init__(
        self,
        *,
        username: str,
        password: str,
        request_ceiling: int,
        fetcher: Callable[..., HttpResponse] = _default_fetcher,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        timeout_seconds: float = 30.0,
        max_body_bytes: int = 16 * 1024 * 1024,
        min_interval_seconds: float = 0.25,
        max_attempts: int = 3,
        account_budget: object | None = None,
    ):
        if not username or not password:
            raise ValueError("Racing API credentials are required")
        if request_ceiling < 1 or max_body_bytes < 2 or min_interval_seconds < 0 or max_attempts < 1:
            raise ValueError("invalid client limits")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self._authorization = f"Basic {token}"
        self._fetcher = fetcher
        self._sleep = sleep
        self._monotonic = monotonic
        self.timeout_seconds = timeout_seconds
        self.max_body_bytes = max_body_bytes
        self.min_interval_seconds = min_interval_seconds
        self.max_attempts = max_attempts
        self.request_ceiling = request_ceiling
        self.request_count = 0
        self.request_ledger: list[dict] = []
        self._last_request_started: float | None = None
        self.account_budget = account_budget

    def _rate_limit(self) -> tuple[float, object | None]:
        reservation = None
        if self.account_budget is not None:
            reservation = self.account_budget.reserve()
        now = self._monotonic()
        if self._last_request_started is not None:
            remaining = self.min_interval_seconds - (now - self._last_request_started)
            if remaining > 0:
                self._sleep(remaining)
                now += remaining
        self._last_request_started = now
        return now, reservation

    @staticmethod
    def _reservation_fields(reservation: object | None) -> dict:
        if reservation is None:
            return {}
        return {
            "account_request_number": getattr(reservation, "request_number", None),
            "account_generation": getattr(reservation, "generation", None),
        }

    def _record(
        self,
        *,
        url: str,
        response: HttpResponse,
        started: float,
        attempt: int,
        reservation: object | None,
    ) -> None:
        self.request_ledger.append(
            {
                "url": url,
                "status": response.status,
                "attempt": attempt,
                "response_bytes": len(response.body),
                "response_sha256": hashlib.sha256(response.body).hexdigest(),
                "elapsed_seconds": max(0.0, self._monotonic() - started),
                **self._reservation_fields(reservation),
            }
        )

    def _record_error(
        self,
        *,
        url: str,
        error: Exception,
        started: float,
        attempt: int,
        reservation: object | None,
    ) -> None:
        self.request_ledger.append(
            {
                "url": url,
                "status": None,
                "attempt": attempt,
                "response_bytes": 0,
                "response_sha256": "",
                "elapsed_seconds": max(0.0, self._monotonic() - started),
                "error": type(error).__name__,
                **self._reservation_fields(reservation),
            }
        )

    def request_json(self, url: str, *, allow_not_found: bool = False) -> dict | None:
        validate_endpoint_url(url)
        for attempt in range(1, self.max_attempts + 1):
            if self.request_count >= self.request_ceiling:
                raise RacingApiHttpError("request ceiling exhausted")
            started, reservation = self._rate_limit()
            self.request_count += 1
            try:
                response = self._fetcher(
                    url=url,
                    headers={
                        "Accept": "application/json",
                        "Authorization": self._authorization,
                        "User-Agent": CLIENT_USER_AGENT,
                    },
                    timeout_seconds=self.timeout_seconds,
                    max_body_bytes=self.max_body_bytes,
                )
            except Exception as exc:
                self._record_error(
                    url=url,
                    error=exc,
                    started=started,
                    attempt=attempt,
                    reservation=reservation,
                )
                raise
            self._record(
                url=url,
                response=response,
                started=started,
                attempt=attempt,
                reservation=reservation,
            )
            headers = {str(key).casefold(): str(value) for key, value in response.headers.items()}
            if response.final_url != url:
                raise RacingApiHttpError("response URL drift")
            if 300 <= response.status < 400:
                raise RacingApiHttpError("redirect response is forbidden")
            if response.status in {401, 403}:
                category = classify_auth_failure(response)
                self.request_ledger[-1]["auth_failure_category"] = category
                raise RacingApiAuthError(
                    f"authentication failed with status {response.status} ({category})"
                )
            if response.status == 404 and allow_not_found:
                return None
            if response.status == 429 or 500 <= response.status <= 599:
                if attempt >= self.max_attempts:
                    raise RacingApiHttpError(f"retryable HTTP status exhausted: {response.status}")
                retry_after = headers.get("retry-after", "")
                try:
                    backoff = float(retry_after) if retry_after else float(2 ** (attempt - 1))
                except ValueError:
                    backoff = float(2 ** (attempt - 1))
                if self.account_budget is not None:
                    self.account_budget.defer(
                        max(0.0, backoff), reason=f"http_{response.status}"
                    )
                self._sleep(max(0.0, backoff))
                continue
            if response.status != 200:
                raise RacingApiHttpError(f"unexpected HTTP status: {response.status}")
            if len(response.body) > self.max_body_bytes:
                raise RacingApiSchemaError("response body too large")
            if not headers.get("content-type", "").casefold().startswith("application/json"):
                raise RacingApiSchemaError("unexpected content-type")
            try:
                payload = json.loads(
                    response.body,
                    object_pairs_hook=_reject_duplicate_json_keys,
                    parse_constant=_reject_non_finite_json_constant,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise RacingApiSchemaError("invalid JSON response") from exc
            if not isinstance(payload, dict):
                raise RacingApiSchemaError("JSON response root must be an object")
            return payload
        raise AssertionError("unreachable")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_space(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def split_country_suffix(value: object) -> tuple[str, str]:
    raw = normalize_space(value)
    match = COUNTRY_SUFFIX_RE.fullmatch(raw)
    if not match:
        return raw, ""
    return match.group(1).strip(), match.group(2)


def normalize_identity_text(value: object) -> str:
    name, _country = split_country_suffix(value)
    decomposed = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", decomposed.casefold()))


def parent_profile_id(value: object) -> str:
    raw = normalize_space(value)
    if not PARENT_ID_RE.fullmatch(raw):
        raise ValueError(f"invalid parent id: {raw!r}")
    return f"hrs_{raw.split('_', 1)[1]}"


def normalize_profile(
    payload: Mapping[str, object],
    *,
    profile_kind: str,
    allow_missing_pro_dob: bool = False,
) -> dict:
    if profile_kind not in {"pro", "standard"}:
        raise ValueError("profile_kind must be pro or standard")
    horse_id = normalize_space(payload.get("id"))
    if not HORSE_ID_RE.fullmatch(horse_id):
        raise ValueError("invalid horse id")
    raw_name = normalize_space(payload.get("name"))
    if not raw_name:
        raise ValueError("horse name is required")
    name, country_suffix = split_country_suffix(raw_name)
    parents = []
    for field in ("sire_id", "dam_id", "damsire_id"):
        value = normalize_space(payload.get(field))
        if value:
            parents.append(parent_profile_id(value))
    if profile_kind == "pro":
        dob = normalize_space(payload.get("dob"))
        if dob:
            try:
                date.fromisoformat(dob)
            except ValueError as exc:
                raise ValueError("invalid pro profile dob") from exc
        elif not allow_missing_pro_dob:
            raise ValueError("invalid pro profile dob")
    else:
        dob = ""
    return {
        "provider": "the_racing_api",
        "profile_kind": profile_kind,
        "horse_id": horse_id,
        "raw_name": raw_name,
        "name": name,
        "country_suffix": country_suffix,
        "dob": dob,
        "sex": normalize_space(payload.get("sex")),
        "sex_code": normalize_space(payload.get("sex_code")).upper(),
        "colour": normalize_space(payload.get("colour")),
        "colour_code": normalize_space(payload.get("colour_code")).upper(),
        "breeder": normalize_space(payload.get("breeder")),
        "sire": normalize_space(payload.get("sire")),
        "sire_id": normalize_space(payload.get("sire_id")),
        "dam": normalize_space(payload.get("dam")),
        "dam_id": normalize_space(payload.get("dam_id")),
        "damsire": normalize_space(payload.get("damsire")),
        "damsire_id": normalize_space(payload.get("damsire_id")),
        "parent_profile_ids": parents,
        "payload_sha256": payload_sha256(payload),
    }


def _seed_has_strong_identity(seed: Mapping[str, object]) -> bool:
    return all(normalize_space(seed.get(field)) for field in ("name", "country_suffix", "dob", "sex_code", "sire", "dam"))


def select_search_candidate(
    seed: Mapping[str, object],
    search_payload: Mapping[str, object],
    profiles_by_id: Mapping[str, Mapping[str, object]],
) -> str:
    if not _seed_has_strong_identity(seed):
        raise ValueError("strong identity requires name, country, dob, sex, sire and dam")
    search_rows = search_payload.get("search_results")
    if not isinstance(search_rows, list):
        raise ValueError("search_results must be a list")
    expected_name = normalize_identity_text(seed["name"])
    expected_country = normalize_space(seed["country_suffix"]).upper()
    expected_dob = normalize_space(seed["dob"])
    expected_sex = normalize_space(seed["sex_code"]).upper()
    expected_sire = normalize_identity_text(seed["sire"])
    expected_dam = normalize_identity_text(seed["dam"])
    matches = []
    for search_row in search_rows:
        if not isinstance(search_row, Mapping):
            raise ValueError("search result must be an object")
        horse_id = normalize_space(search_row.get("id"))
        if not HORSE_ID_RE.fullmatch(horse_id):
            raise ValueError("search result has invalid horse id")
        result_name, result_country = split_country_suffix(search_row.get("name"))
        if normalize_identity_text(result_name) != expected_name or result_country != expected_country:
            continue
        profile_payload = profiles_by_id.get(horse_id)
        if profile_payload is None:
            continue
        profile = normalize_profile(profile_payload, profile_kind="pro")
        if (
            profile["dob"] == expected_dob
            and profile["sex_code"] == expected_sex
            and normalize_identity_text(profile["sire"]) == expected_sire
            and normalize_identity_text(profile["dam"]) == expected_dam
        ):
            matches.append(horse_id)
    if len(matches) != 1:
        raise ValueError(f"strong identity candidate count must be 1, got {len(matches)}")
    return matches[0]


def target_occurrence_candidate_ids(
    seed: Mapping[str, object],
    search_payload: Mapping[str, object],
    results_by_id: Mapping[str, Iterable[Mapping[str, object]]],
) -> list[str]:
    """用受审赛事 occurrence 证明解析仅有姓名的外部 anchor。

    这不是名称单键：候选必须以同一 provider horse ID 出现在唯一目标赛事中，并满足外部来源
    声明的完赛名次（例如“1999 凯旋门冠军”中的冠军关系）。
    """

    source_url = normalize_space(seed.get("source_url"))
    parsed_source = urlsplit(source_url)
    if parsed_source.scheme != "https" or not parsed_source.hostname or parsed_source.username or parsed_source.password:
        raise ValueError("target occurrence seed requires a safe HTTPS source URL")
    source_sha = normalize_space(seed.get("source_payload_sha256")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise ValueError("target occurrence seed requires source payload SHA-256")
    if not normalize_space(seed.get("source_authority")):
        raise ValueError("target occurrence seed requires source authority")
    target = seed.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("target occurrence seed requires target object")
    expected_position = normalize_space(seed.get("expected_finish_position")).upper()
    if not FINISHED_POSITION_RE.fullmatch(expected_position):
        raise ValueError("target occurrence seed requires numeric expected finish position")
    search_rows = search_payload.get("search_results")
    if not isinstance(search_rows, list):
        raise ValueError("search_results must be a list")
    expected_name = normalize_identity_text(seed.get("name"))
    if not expected_name:
        raise ValueError("target occurrence seed requires horse name")
    expected_country = normalize_space(seed.get("country_suffix")).upper()
    qualified = []
    for search_row in search_rows:
        if not isinstance(search_row, Mapping):
            raise ValueError("search result must be an object")
        horse_id = normalize_space(search_row.get("id"))
        if not HORSE_ID_RE.fullmatch(horse_id):
            raise ValueError("search result has invalid horse id")
        result_name, result_country = split_country_suffix(search_row.get("name"))
        if normalize_identity_text(result_name) != expected_name:
            continue
        if expected_country and result_country != expected_country:
            continue
        candidate_races = list(results_by_id.get(horse_id, []))
        matching_races = [race for race in candidate_races if _race_matches_target(target, race)]
        if len(matching_races) != 1:
            continue
        race = matching_races[0]
        _validate_race(race)
        horse_rows = [runner for runner in race["runners"] if normalize_space(runner.get("horse_id")) == horse_id]
        if len(horse_rows) != 1:
            continue
        position = normalize_space(horse_rows[0].get("position")).upper()
        if position == expected_position and runner_disposition(position) == "finished":
            qualified.append(horse_id)
    return sorted(set(qualified))


def select_candidate_by_target_occurrence(
    seed: Mapping[str, object],
    search_payload: Mapping[str, object],
    results_by_id: Mapping[str, Iterable[Mapping[str, object]]],
) -> str:
    qualified = target_occurrence_candidate_ids(seed, search_payload, results_by_id)
    if len(qualified) != 1:
        raise ValueError(f"target occurrence candidate count must be 1, got {len(qualified)}")
    return qualified[0]


def _profile_only_external_anchor_allowed(seed: Mapping[str, object]) -> bool:
    """Validate the explicit, review-only escape hatch for provider omissions.

    This never treats the external occurrence as a TRA result.  It only permits
    exporting a unique exact-name provider candidate for later identity review.
    """

    if seed.get("allow_profile_only_if_target_missing") is not True:
        return False
    authority = normalize_space(seed.get("source_authority"))
    if authority not in PROFILE_ONLY_EXTERNAL_ANCHOR_AUTHORITIES:
        raise ValueError("profile-only external anchor authority is not trusted")
    source_url = normalize_space(seed.get("source_url"))
    parsed_source = urlsplit(source_url)
    if (
        parsed_source.scheme != "https"
        or not parsed_source.hostname
        or parsed_source.username
        or parsed_source.password
    ):
        raise ValueError("profile-only external anchor requires a safe HTTPS source URL")
    if not re.fullmatch(
        r"[0-9a-f]{64}",
        normalize_space(seed.get("source_payload_sha256")).lower(),
    ):
        raise ValueError("profile-only external anchor requires source payload SHA-256")
    if normalize_space(seed.get("expected_finish_position")) != "1":
        raise ValueError("profile-only external anchor must be a reviewed winner")
    target = seed.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("profile-only external anchor requires target object")
    required_target_fields = (
        "year",
        "country_region",
        "canonical_name_original",
        "racecourse",
        "grade_text",
        "discipline",
    )
    if any(not normalize_space(target.get(field)) for field in required_target_fields):
        raise ValueError("profile-only external anchor target is incomplete")
    try:
        target_year = int(str(target.get("year")))
    except (TypeError, ValueError) as exc:
        raise ValueError("profile-only external anchor target year is invalid") from exc
    target_date_text = normalize_space(target.get("local_date"))
    if target_date_text:
        try:
            target_date = date.fromisoformat(target_date_text)
        except ValueError as exc:
            raise ValueError("profile-only external anchor target date is invalid") from exc
        if target_date.year != target_year:
            raise ValueError("profile-only external anchor target year/date mismatch")
    elif seed.get("schema_version") == "targeted-horse-seed.v2":
        try:
            edition_year = int(str(target.get("edition_year")))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "profile-only external anchor edition year is invalid"
            ) from exc
        if edition_year != target_year:
            raise ValueError("profile-only external anchor edition year drift")
    else:
        raise ValueError("profile-only external anchor target date is required")
    if normalize_space(target.get("country_region")) not in REGION_CODES:
        raise ValueError("profile-only external anchor target region is unsupported")
    if normalize_space(target.get("grade_text")).upper() not in {"G1", "G2", "G3"}:
        raise ValueError("profile-only external anchor target grade is unsupported")
    if normalize_space(target.get("discipline")).lower() not in {"flat", "jumps"}:
        raise ValueError("profile-only external anchor target discipline is unsupported")
    return True


def _validate_result_page(page: Mapping[str, object], *, expected_skip: int, expected_total: int | None) -> tuple[list, int]:
    required = ("results", "total", "limit", "skip", "query")
    missing = [field for field in required if field not in page]
    if missing:
        raise ValueError(f"result page missing fields: {missing}")
    results = page["results"]
    total = page["total"]
    limit = page["limit"]
    skip = page["skip"]
    if not isinstance(results, list) or not isinstance(total, int) or not isinstance(limit, int) or not isinstance(skip, int):
        raise ValueError("result page field type drift")
    if not isinstance(page["query"], list):
        raise ValueError("result page query must be a list")
    if total < 0 or not 1 <= limit <= 100 or skip != expected_skip:
        raise ValueError("result page pagination drift")
    if expected_total is not None and total != expected_total:
        raise ValueError("result page total drift")
    if not results and skip < total:
        raise ValueError("empty page before total")
    if skip + len(results) > total:
        raise ValueError("result page exceeds total")
    return results, total


def _validate_race(race: Mapping[str, object]) -> None:
    for field in ("race_id", "date", "region", "course", "course_id", "race_name", "type", "pattern", "runners"):
        if field not in race:
            raise ValueError(f"race missing {field}")
    if not re.fullmatch(r"rac_[A-Za-z0-9_]+", normalize_space(race["race_id"])):
        raise ValueError("invalid race id")
    if not isinstance(race["runners"], list):
        raise ValueError("race runners must be a list")


def combine_result_pages(pages: Iterable[Mapping[str, object]]) -> dict:
    expected_skip = 0
    expected_total: int | None = None
    seen_page_hashes: set[str] = set()
    races_by_id: dict[str, dict] = {}
    provider_row_count = 0
    page_count = 0
    for page in pages:
        rows, total = _validate_result_page(page, expected_skip=expected_skip, expected_total=expected_total)
        expected_total = total
        page_hash = payload_sha256(page)
        if page_hash in seen_page_hashes:
            raise ValueError("pagination stalled on repeated page")
        seen_page_hashes.add(page_hash)
        for race in rows:
            if not isinstance(race, Mapping):
                raise ValueError("race result must be an object")
            _validate_race(race)
            race_id = normalize_space(race["race_id"])
            normalized = dict(race)
            existing = races_by_id.get(race_id)
            if existing is None:
                races_by_id[race_id] = normalized
            elif payload_sha256(existing) != payload_sha256(normalized):
                raise ValueError(f"race payload conflict: {race_id}")
        returned_count = len(rows)
        provider_row_count += returned_count
        expected_skip += returned_count
        page_count += 1
    if expected_total is None:
        raise ValueError("at least one result page is required")
    if provider_row_count != expected_total:
        raise ValueError(f"incomplete pagination: {provider_row_count}!={expected_total}")
    return {
        "provider_row_count": provider_row_count,
        "unique_race_count": len(races_by_id),
        "page_count": page_count,
        "races": [races_by_id[key] for key in sorted(races_by_id)],
    }


def fetch_all_horse_results(client: object, *, horse_id: str, max_pages: int = 5) -> dict:
    if not HORSE_ID_RE.fullmatch(horse_id):
        raise ValueError("invalid horse id")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    pages = []
    skip = 0
    total: int | None = None
    while total is None or skip < total:
        if len(pages) >= max_pages:
            raise ValueError(f"horse results page ceiling exceeded: {max_pages}")
        url = build_endpoint("horse_results", horse_id=horse_id, limit=100, skip=skip)
        payload = client.request_json(url)
        if not isinstance(payload, Mapping):
            raise RacingApiSchemaError("horse results response must be an object")
        rows, observed_total = _validate_result_page(payload, expected_skip=skip, expected_total=total)
        pages.append(dict(payload))
        total = observed_total
        skip += len(rows)
        if not rows:
            break
    return combine_result_pages(pages)


def exact_search_candidates(
    seed: Mapping[str, object],
    search_payload: Mapping[str, object],
    *,
    maximum: int,
) -> list[str]:
    rows = search_payload.get("search_results")
    if not isinstance(rows, list):
        raise RacingApiSchemaError("search_results must be a list")
    expected_name = normalize_identity_text(seed.get("name"))
    expected_country = normalize_space(seed.get("country_suffix")).upper()
    candidates = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise RacingApiSchemaError("search result must be an object")
        horse_id = normalize_space(row.get("id"))
        if not HORSE_ID_RE.fullmatch(horse_id):
            raise RacingApiSchemaError("search result has invalid horse id")
        name, country = split_country_suffix(row.get("name"))
        if normalize_identity_text(name) != expected_name:
            continue
        if expected_country and country != expected_country:
            continue
        candidates.append(horse_id)
    candidates = sorted(set(candidates))
    if not candidates:
        raise ValueError("search returned no exact-name candidates")
    if len(candidates) > maximum:
        raise ValueError(f"exact-name candidate ceiling exceeded: {len(candidates)}>{maximum}")
    return candidates


def fetch_profile_with_fallback(
    client: object,
    *,
    horse_id: str,
    allow_missing_pro_dob: bool = False,
) -> dict:
    if not HORSE_ID_RE.fullmatch(horse_id):
        raise ValueError("invalid horse id")
    payload = client.request_json(
        build_endpoint("horse_pro", horse_id=horse_id),
        allow_not_found=True,
    )
    profile_kind = "pro"
    if payload is None:
        payload = client.request_json(build_endpoint("horse_standard", horse_id=horse_id))
        profile_kind = "standard"
    if not isinstance(payload, Mapping):
        raise RacingApiSchemaError("horse profile response must be an object")
    normalized = normalize_profile(
        payload,
        profile_kind=profile_kind,
        allow_missing_pro_dob=allow_missing_pro_dob,
    )
    if normalized["horse_id"] != horse_id:
        raise RacingApiSchemaError("horse profile identity drift")
    return normalized


def fetch_parent_profiles(
    client: object,
    *,
    profile: Mapping[str, object],
    max_parent_profiles: int,
) -> list[dict]:
    if not 0 <= max_parent_profiles <= 2:
        raise ValueError("max_parent_profiles must be between 0 and 2")
    if max_parent_profiles == 0:
        return []
    parent_ids = []
    for field in ("sire_id", "dam_id"):
        raw = normalize_space(profile.get(field))
        if raw:
            parent_ids.append(parent_profile_id(raw))
    unique_parent_ids = list(dict.fromkeys(parent_ids))
    if len(unique_parent_ids) > max_parent_profiles:
        raise ValueError(
            f"parent profile ceiling exceeded: {len(unique_parent_ids)}>{max_parent_profiles}"
        )
    return [
        fetch_profile_with_fallback(
            client,
            horse_id=horse_id,
            allow_missing_pro_dob=True,
        )
        for horse_id in unique_parent_ids
    ]


def _page_field(value: object, *, source: str, status: str | None = None, **extra: object) -> dict:
    normalized = normalize_space(value)
    return {
        "value": normalized,
        "status": status or ("available" if normalized else "unknown"),
        "source": source,
        **extra,
    }


def _normalized_parent_name(value: object) -> str:
    return split_country_suffix(value)[0]


def build_horse_page_field_matrix(
    *,
    horse_id: str,
    profile: Mapping[str, object],
    parent_profiles: list[Mapping[str, object]],
    career: Mapping[str, object],
    provider_career_complete: bool | None = None,
    provider_career_complete_basis: str | None = None,
) -> dict:
    """Build a provider candidate for every hard field on the public horse page.

    This is an artifact-only projection.  It records unknown/conflict/local-review
    states and does not imply that any value is approved for ``HorseProfile``.
    """

    if not HORSE_ID_RE.fullmatch(horse_id) or profile.get("horse_id") != horse_id:
        raise ValueError("page field matrix horse identity drift")
    races = career.get("races")
    if (
        not isinstance(races, list)
        or career.get("unique_race_count") != len(races)
        or career.get("provider_row_count") is None
    ):
        raise ValueError("page field matrix career contract drift")
    parents_by_id: dict[str, Mapping[str, object]] = {}
    for parent in parent_profiles:
        if not isinstance(parent, Mapping):
            raise ValueError("page field matrix parent must be an object")
        parent_id = normalize_space(parent.get("horse_id"))
        if not HORSE_ID_RE.fullmatch(parent_id) or parent_id in parents_by_id:
            raise ValueError("page field matrix parent identity is invalid or duplicated")
        parents_by_id[parent_id] = parent

    sire_id = parent_profile_id(profile["sire_id"]) if normalize_space(profile.get("sire_id")) else ""
    dam_id = parent_profile_id(profile["dam_id"]) if normalize_space(profile.get("dam_id")) else ""
    sire_profile = parents_by_id.get(sire_id)
    dam_profile = parents_by_id.get(dam_id)
    profile_damsire = normalize_space(profile.get("damsire"))
    dam_profile_sire = normalize_space(dam_profile.get("sire")) if dam_profile else ""
    dam_sire_conflict = bool(
        profile_damsire
        and dam_profile_sire
        and normalize_identity_text(_normalized_parent_name(profile_damsire))
        != normalize_identity_text(_normalized_parent_name(dam_profile_sire))
    )

    fields = {
        "display_name_zh": _page_field(
            "", source="local_review", status="local_review_required"
        ),
        "original_name": _page_field(
            "", source="local_or_official_identity", status="local_review_required"
        ),
        "english_name": _page_field(profile.get("name"), source="the_racing_api.profile"),
        "japanese_name": _page_field(
            "", source="jra_or_jbis", status="official_crosswalk_required"
        ),
        "racing_region": _page_field(
            "", source="local_identity", status="local_review_required"
        ),
        "country": _page_field(profile.get("country_suffix"), source="the_racing_api.name_suffix"),
        "birth_date": _page_field(profile.get("dob"), source="the_racing_api.profile"),
        "sex": _page_field(profile.get("sex"), source="the_racing_api.profile"),
        "color": _page_field(profile.get("colour"), source="the_racing_api.profile"),
        "breeder_name": _page_field(profile.get("breeder"), source="the_racing_api.profile"),
        "sire_text": _page_field(profile.get("sire"), source="the_racing_api.profile"),
        "dam_text": _page_field(profile.get("dam"), source="the_racing_api.profile"),
        "sire_sire_text": _page_field(
            sire_profile.get("sire") if sire_profile else "",
            source="the_racing_api.sire_profile",
        ),
        "sire_dam_text": _page_field(
            sire_profile.get("dam") if sire_profile else "",
            source="the_racing_api.sire_profile",
        ),
        "dam_sire_text": _page_field(
            dam_profile_sire or profile_damsire,
            source=(
                "the_racing_api.dam_profile+profile"
                if dam_profile_sire and profile_damsire
                else "the_racing_api.dam_profile_or_profile"
            ),
            status="conflict" if dam_sire_conflict else None,
            candidate_values=list(
                dict.fromkeys(value for value in (profile_damsire, dam_profile_sire) if value)
            ),
        ),
        "dam_dam_text": _page_field(
            dam_profile.get("dam") if dam_profile else "",
            source="the_racing_api.dam_profile",
        ),
        "intro": _page_field("", source="local_editorial", status="optional_unknown"),
    }

    records = []
    relationship_observations: dict[str, list[dict]] = {"trainer_name": [], "owner_name": []}
    stats = {"starts": 0, "wins": 0, "seconds": 0, "thirds": 0}
    major_wins = []
    for race in races:
        if not isinstance(race, Mapping):
            raise ValueError("page field matrix race must be an object")
        _validate_race(race)
        target_rows = [
            runner
            for runner in race["runners"]
            if isinstance(runner, Mapping)
            and normalize_space(runner.get("horse_id")) == horse_id
        ]
        if len(target_rows) != 1:
            raise ValueError("page field matrix target runner occurrence drift")
        runner = target_rows[0]
        disposition = runner_disposition(runner.get("position"))
        if disposition == "unresolved":
            raise ValueError("page field matrix has unresolved runner status")
        race_date = normalize_space(race.get("date"))
        try:
            date.fromisoformat(race_date)
        except ValueError as exc:
            raise ValueError("page field matrix race date is invalid") from exc
        for field_name, runner_fields in {
            "trainer_name": ("trainer", "trainer_name"),
            "owner_name": ("owner", "owner_name"),
        }.items():
            value = next(
                (
                    normalize_space(runner.get(runner_field))
                    for runner_field in runner_fields
                    if normalize_space(runner.get(runner_field))
                ),
                "",
            )
            if value:
                relationship_observations[field_name].append(
                    {"value": value, "as_of": race_date, "race_id": race["race_id"]}
                )
        record = {
            "race_id": race["race_id"],
            "race_date": race_date,
            "race_name": normalize_space(race.get("race_name")),
            "region": normalize_space(race.get("region")),
            "racecourse": normalize_space(race.get("course")),
            "grade_text": normalize_space(race.get("pattern")),
            "discipline": normalize_space(race.get("type")),
            "distance_text": normalize_space(race.get("dist")),
            "distance_meters": (
                int(normalize_space(race.get("dist_m")))
                if normalize_space(race.get("dist_m")).isdigit()
                else None
            ),
            "surface": normalize_space(race.get("surface")),
            "going_text": normalize_space(race.get("going")),
            "eligibility_text": " ".join(
                dict.fromkeys(
                    value
                    for value in (
                        normalize_space(race.get("age_band")),
                        normalize_space(race.get("sex_rest")),
                    )
                    if value
                )
            ),
            "position": normalize_space(runner.get("position")),
            "participant_status": disposition,
            "horse_number": normalize_space(runner.get("number")),
            "barrier": normalize_space(runner.get("draw")),
            "jockey_name": normalize_space(runner.get("jockey")),
            "carried_weight": normalize_space(
                runner.get("weight")
                or runner.get("weight_lbs")
                or runner.get("lbs")
            ),
            "finish_time": normalize_space(runner.get("time")),
            "prize": normalize_space(runner.get("prize")),
        }
        records.append(record)
        if disposition != "non_runner":
            stats["starts"] += 1
            position = record["position"].upper()
            if position in {"1", "1DH"}:
                stats["wins"] += 1
                if record["grade_text"].upper().replace("GROUP ", "G") in {
                    "G1",
                    "G2",
                    "G3",
                }:
                    major_wins.append(record)
            elif position in {"2", "2DH"}:
                stats["seconds"] += 1
            elif position in {"3", "3DH"}:
                stats["thirds"] += 1

    for field_name, observations in relationship_observations.items():
        if not observations:
            fields[field_name] = _page_field(
                "", source="the_racing_api.runner_observation", status="unknown"
            )
            continue
        latest_date = max(row["as_of"] for row in observations)
        latest = [row for row in observations if row["as_of"] == latest_date]
        values = list(dict.fromkeys(row["value"] for row in latest))
        fields[field_name] = _page_field(
            values[0] if len(values) == 1 else "",
            source="the_racing_api.runner_observation",
            status="available" if len(values) == 1 else "conflict",
            as_of=latest_date,
            candidate_values=values,
        )

    required_provider_profile_fields = (
        "english_name",
        "birth_date",
        "sex",
        "color",
        "breeder_name",
        "sire_text",
        "dam_text",
    )
    required_page_profile_fields = (
        *required_provider_profile_fields,
        "country",
        "sire_sire_text",
        "sire_dam_text",
        "dam_sire_text",
        "dam_dam_text",
    )
    calculated_provider_career_complete = career.get("unique_race_count") == len(records)
    if provider_career_complete is None:
        provider_career_complete = calculated_provider_career_complete
        provider_career_complete_basis = "pagination_reconciled_to_unique_race_count"
    elif not isinstance(provider_career_complete, bool):
        raise ValueError("provider career completeness override must be boolean")
    elif not normalize_space(provider_career_complete_basis):
        raise ValueError("provider career completeness override requires a basis")
    return {
        "schema_version": "horse-page-field-matrix.v1",
        "database_writes": 0,
        "horse_id": horse_id,
        "profile_kind": profile.get("profile_kind"),
        "fields": fields,
        "career": {
            "provider_row_count": career.get("provider_row_count"),
            "unique_race_count": career.get("unique_race_count"),
            "page_count": career.get("page_count"),
            "records": sorted(records, key=lambda row: (row["race_date"], row["race_id"])),
            "stats": {
                **stats,
                "win_rate_percent": round(
                    (stats["wins"] / stats["starts"] * 100) if stats["starts"] else 0,
                    2,
                ),
            },
            "major_wins": sorted(
                major_wins, key=lambda row: (row["race_date"], row["race_id"])
            ),
        },
        "completeness": {
            "provider_profile_complete": all(
                fields[field]["status"] == "available"
                for field in required_provider_profile_fields
            ),
            "page_profile_complete": all(
                fields[field]["status"] == "available"
                for field in required_page_profile_fields
            ),
            # Pagination completeness is proved before this projection. A known
            # externally verified target missing from provider results overrides
            # this to false without inventing a career row.
            "provider_career_complete": provider_career_complete,
            "provider_career_complete_basis": provider_career_complete_basis,
            "local_identity_complete": False,
            "missing_or_conflicting_page_fields": [
                field
                for field in required_page_profile_fields
                if fields[field]["status"] != "available"
            ],
        },
        "source_refs": {
            "profile_payload_sha256": profile.get("payload_sha256"),
            "parent_profile_payload_sha256": {
                parent_id: parent.get("payload_sha256")
                for parent_id, parent in sorted(parents_by_id.items())
            },
        },
    }


def run_targeted_seed(
    seed: Mapping[str, object],
    *,
    client: object,
    max_search_candidates: int = 10,
    max_results_pages_per_horse: int = 5,
    max_parent_profiles: int = 0,
) -> dict:
    schema_version = seed.get("schema_version")
    if schema_version not in {
        "targeted-horse-seed.v1",
        "targeted-horse-seed.v2",
        "targeted-runner-stable-id-seed.v1",
        "targeted-runner-stable-id-seed.v2",
    }:
        raise ValueError("targeted seed schema drift")
    if max_search_candidates < 1 or max_results_pages_per_horse < 1:
        raise ValueError("candidate and results page ceilings must be positive")
    if schema_version in {
        "targeted-runner-stable-id-seed.v1",
        "targeted-runner-stable-id-seed.v2",
    }:
        return run_stable_id_seed(
            seed,
            client=client,
            max_results_pages_per_horse=max_results_pages_per_horse,
            max_parent_profiles=max_parent_profiles,
        )
    if schema_version == "targeted-horse-seed.v2":
        target = seed.get("target")
        if not isinstance(target, Mapping):
            raise ValueError("v2 targeted seed requires target object")
        required = (
            "year",
            "edition_year",
            "country_region",
            "canonical_name_original",
            "racecourse",
            "grade_text",
            "discipline",
        )
        if any(not normalize_space(target.get(field)) for field in required):
            raise ValueError("v2 targeted seed structured race identity is incomplete")
        try:
            target_year = int(str(target["year"]))
            edition_year = int(str(target["edition_year"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("v2 targeted seed year identity is invalid") from exc
        if (
            not 1900 <= target_year <= 2100
            or not 1900 <= edition_year <= 2100
            or abs(target_year - edition_year) > 1
            or normalize_space(target.get("country_region")) not in REGION_CODES
            or _normalized_pattern_grade(target.get("grade_text")) not in {"G1", "G2", "G3"}
            or normalize_space(target.get("discipline")).lower() not in {"flat", "jumps"}
        ):
            raise ValueError("v2 targeted seed structured race identity is invalid")
        target_date = normalize_space(target.get("local_date"))
        if target_date:
            try:
                parsed_target_date = date.fromisoformat(target_date)
            except ValueError as exc:
                raise ValueError("v2 targeted seed local date is invalid") from exc
            if parsed_target_date.year != target_year:
                raise ValueError("v2 targeted seed local date/year mismatch")
    name = normalize_space(seed.get("name"))
    search_payload = client.request_json(build_endpoint("horse_search", name=name))
    if not isinstance(search_payload, Mapping):
        raise RacingApiSchemaError("horse search response must be an object")
    candidates = exact_search_candidates(seed, search_payload, maximum=max_search_candidates)

    selected_id: str
    selected_profile_payload: Mapping[str, object] | None = None
    career_by_id: dict[str, dict] = {}
    identity_mode = "strong_biodata" if _seed_has_strong_identity(seed) else "target_occurrence"
    if _seed_has_strong_identity(seed):
        profiles = {}
        for horse_id in candidates:
            profile = client.request_json(
                build_endpoint("horse_pro", horse_id=horse_id),
                allow_not_found=True,
            )
            if profile is not None:
                if not isinstance(profile, Mapping):
                    raise RacingApiSchemaError("horse pro response must be an object")
                profiles[horse_id] = profile
        selected_id = select_search_candidate(seed, search_payload, profiles)
        selected_profile_payload = profiles[selected_id]
        career_by_id[selected_id] = fetch_all_horse_results(
            client,
            horse_id=selected_id,
            max_pages=max_results_pages_per_horse,
        )
    else:
        for horse_id in candidates:
            career_by_id[horse_id] = fetch_all_horse_results(
                client,
                horse_id=horse_id,
                max_pages=max_results_pages_per_horse,
            )
        occurrence_candidate_ids = target_occurrence_candidate_ids(
            seed,
            search_payload,
            {horse_id: career["races"] for horse_id, career in career_by_id.items()},
        )
        if len(occurrence_candidate_ids) == 1:
            selected_id = occurrence_candidate_ids[0]
        elif (
            len(occurrence_candidate_ids) == 0
            and len(candidates) == 1
            and _profile_only_external_anchor_allowed(seed)
        ):
            selected_id = candidates[0]
            identity_mode = "external_anchor_profile_only"
        else:
            raise RacingApiSemanticGap(
                "target_occurrence_identity_unresolved",
                f"target occurrence candidate count must be 1, got {len(occurrence_candidate_ids)}",
            )

    if selected_profile_payload is None:
        profile = fetch_profile_with_fallback(client, horse_id=selected_id)
    else:
        profile = normalize_profile(selected_profile_payload, profile_kind="pro")
    if identity_mode == "external_anchor_profile_only":
        if normalize_identity_text(profile.get("name")) != normalize_identity_text(
            seed.get("name")
        ):
            raise ValueError("profile-only provider profile name drift")
        expected_country = normalize_space(seed.get("country_suffix")).upper()
        if expected_country and profile.get("country_suffix") != expected_country:
            raise ValueError("profile-only provider profile country drift")
    parent_profiles = fetch_parent_profiles(
        client,
        profile=profile,
        max_parent_profiles=max_parent_profiles,
    )
    career = career_by_id[selected_id]
    target = seed.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("targeted seed requires target object")
    if identity_mode == "external_anchor_profile_only":
        target_race = None
        scope_target_races = []
        career_authority = {
            "status": "provider_partial",
            "basis": "target_occurrence_missing_from_provider_results",
            "provider_results_pagination_complete": True,
        }
        target_occurrence = {
            "status": "missing_from_provider_results",
            "authority": "external_anchor",
            "expected_finish_position": normalize_space(seed.get("expected_finish_position")),
            "target": dict(target),
            "source": {
                "authority": normalize_space(seed.get("source_authority")),
                "url": normalize_space(seed.get("source_url")),
                "payload_sha256": normalize_space(seed.get("source_payload_sha256")).lower(),
            },
        }
    else:
        target_race = recover_target_race(
            target=target,
            target_horse_id=selected_id,
            races=career["races"],
        )
        scope_target_races = [target_race]
        career_authority = {
            "status": "provider_available",
            "basis": "target_occurrence_present_in_provider_results",
            "provider_results_pagination_complete": True,
        }
        target_occurrence = {
            "status": "confirmed_in_provider_results",
            "authority": "the_racing_api",
            "race_id": target_race["race_id"],
        }
    result = {
        "schema_version": "targeted-horse-export.v1",
        "database_writes": 0,
        "seed_id": normalize_space(seed.get("seed_id")),
        "horse_id": selected_id,
        "identity_mode": identity_mode,
        "profile": profile,
        "parent_profiles": parent_profiles,
        "career": career,
        "career_authority": career_authority,
        "target_occurrence": target_occurrence,
        "target_race": target_race,
        "scope_target_races": scope_target_races,
    }
    result["page_field_matrix"] = build_horse_page_field_matrix(
        horse_id=selected_id,
        profile=profile,
        parent_profiles=parent_profiles,
        career=career,
        provider_career_complete=(
            False if identity_mode == "external_anchor_profile_only" else None
        ),
        provider_career_complete_basis=(
            "target_occurrence_missing_from_provider_results"
            if identity_mode == "external_anchor_profile_only"
            else None
        ),
    )
    return result


def run_stable_id_seed(
    seed: Mapping[str, object],
    *,
    client: object,
    max_results_pages_per_horse: int = 5,
    max_parent_profiles: int = 0,
) -> dict:
    """按已经由目标赛事赛果证明的 provider horse ID 补全档案。

    该阶段不再搜索名字，也不会把生涯其他赛事中的同场马递归加入补全范围。seed 中的
    target_occurrences 是唯一允许扩展的赛事集合；每一项都必须在该 horse ID 的 career 中唯一命中。
    """

    schema_version = seed.get("schema_version")
    if schema_version not in {
        "targeted-runner-stable-id-seed.v1",
        "targeted-runner-stable-id-seed.v2",
    }:
        raise ValueError("stable-id seed schema drift")
    horse_id = normalize_space(seed.get("horse_id"))
    if not HORSE_ID_RE.fullmatch(horse_id):
        raise ValueError("stable-id seed requires a valid horse_id")
    if schema_version == "targeted-runner-stable-id-seed.v1":
        source_manifest_shas = [
            normalize_space(seed.get("source_targeted_batch_manifest_sha256")).lower()
        ]
    else:
        raw_source_manifest_shas = seed.get(
            "source_targeted_batch_manifest_sha256s"
        )
        if not isinstance(raw_source_manifest_shas, list):
            raise ValueError("stable-id v2 seed requires source targeted batch SHA-256s")
        source_manifest_shas = [
            normalize_space(value).lower() for value in raw_source_manifest_shas
        ]
    if (
        not source_manifest_shas
        or source_manifest_shas != sorted(set(source_manifest_shas))
        or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in source_manifest_shas)
    ):
        raise ValueError("stable-id seed requires source targeted batch SHA-256")
    occurrences = seed.get("target_occurrences")
    if not isinstance(occurrences, list) or not occurrences:
        raise ValueError("stable-id seed requires target_occurrences")

    profile = fetch_profile_with_fallback(client, horse_id=horse_id)
    parent_profiles = fetch_parent_profiles(
        client,
        profile=profile,
        max_parent_profiles=max_parent_profiles,
    )
    career = fetch_all_horse_results(
        client,
        horse_id=horse_id,
        max_pages=max_results_pages_per_horse,
    )
    target_races = []
    seen_race_ids = set()
    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping) or not isinstance(
            occurrence.get("target"), Mapping
        ):
            raise ValueError("stable-id target occurrence contract drift")
        expected_race_id = normalize_space(occurrence.get("race_id"))
        if not re.fullmatch(r"rac_[A-Za-z0-9_]+", expected_race_id):
            raise ValueError("stable-id occurrence requires a valid race_id")
        if expected_race_id in seen_race_ids:
            raise ValueError("stable-id occurrence race_id must be unique")
        target_race = recover_target_race(
            target=occurrence["target"],
            target_horse_id=horse_id,
            races=career["races"],
        )
        if target_race["race_id"] != expected_race_id:
            raise ValueError("stable-id occurrence race identity drift")
        expected_payload_sha = normalize_space(
            occurrence.get("target_race_payload_sha256")
        ).lower()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_payload_sha)
            or payload_sha256(
                {
                    key: value
                    for key, value in target_race.items()
                    if key
                    not in {
                        "actual_starters",
                        "excluded_non_runner_count",
                        "source_mode",
                    }
                }
            )
            != expected_payload_sha
        ):
            raise ValueError("stable-id target race payload changed")
        seen_race_ids.add(expected_race_id)
        target_races.append(target_race)

    result = {
        "schema_version": "targeted-horse-export.v1",
        "database_writes": 0,
        "seed_id": normalize_space(seed.get("seed_id")),
        "horse_id": horse_id,
        "identity_mode": "provider_stable_id_from_target_race",
        "profile": profile,
        "parent_profiles": parent_profiles,
        "career": career,
        "career_authority": {
            "status": "provider_available",
            "basis": "approved_target_occurrences_present_in_provider_results",
            "provider_results_pagination_complete": True,
        },
        "target_occurrence": {
            "status": "confirmed_in_provider_results",
            "authority": "the_racing_api",
            "race_id": target_races[0]["race_id"],
            "race_ids": [race["race_id"] for race in target_races],
        },
        "target_race": target_races[0],
        "scope_target_races": target_races,
    }
    result["page_field_matrix"] = build_horse_page_field_matrix(
        horse_id=horse_id,
        profile=profile,
        parent_profiles=parent_profiles,
        career=career,
    )
    return result


class RecordingClient:
    def __init__(self, client: object):
        self.client = client
        self.responses: list[dict] = []

    def request_json(self, url: str, *, allow_not_found: bool = False):
        payload = (
            self.client.request_json(url, allow_not_found=True)
            if allow_not_found
            else self.client.request_json(url)
        )
        self.responses.append(
            {
                "url": url,
                "allow_not_found": allow_not_found,
                "not_found": payload is None,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
        )
        return payload


def summarize_recorded_response(response: Mapping[str, object]) -> dict:
    """保留失败排查所需的结构计数，不把原始 provider payload 写进失败包。"""

    payload = response.get("payload")
    summary = {
        "url": normalize_space(response.get("url")),
        "allow_not_found": response.get("allow_not_found") is True,
        "not_found": response.get("not_found") is True,
        "payload_type": type(payload).__name__,
    }
    if payload is not None:
        summary["payload_sha256"] = payload_sha256(payload)
    if isinstance(payload, Mapping):
        search_rows = payload.get("search_results")
        if isinstance(search_rows, list):
            summary["search_result_count"] = len(search_rows)
            summary["search_result_ids"] = sorted(
                {
                    normalize_space(row.get("id"))
                    for row in search_rows
                    if isinstance(row, Mapping)
                    and HORSE_ID_RE.fullmatch(normalize_space(row.get("id")))
                }
            )
        result_rows = payload.get("results")
        if isinstance(result_rows, list):
            summary["result_page"] = {
                "returned_count": len(result_rows),
                "total": payload.get("total"),
                "limit": payload.get("limit"),
                "skip": payload.get("skip"),
            }
    return summary


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def load_openapi_fingerprint(path: Path, approved_sha256: str) -> dict:
    """Load the exact reviewed local OpenAPI fingerprint before any API request.

    This deliberately does not fetch ``/openapi.json``: that endpoint is outside
    the approved Montjeu G3 network path set.  Live responses are still checked
    by the endpoint-specific validators before pagination or the next request.
    """

    if path.is_symlink():
        raise ValueError("OpenAPI fingerprint must be a regular non-symlink file")
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except OSError as exc:
        raise ValueError("OpenAPI fingerprint file is unavailable") from exc
    if not resolved.is_file() or stat.st_size < 1 or stat.st_size > MAX_OPENAPI_FINGERPRINT_BYTES:
        raise ValueError("OpenAPI fingerprint file size is invalid")
    actual_sha256 = _sha256_path(resolved)
    if not re.fullmatch(r"[0-9a-f]{64}", approved_sha256) or actual_sha256 != approved_sha256:
        raise ValueError("approved OpenAPI fingerprint SHA-256 mismatch")
    try:
        payload = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid OpenAPI fingerprint JSON") from exc
    expected_root_keys = {
        "fingerprint_generated_at",
        "full_openapi_sha256",
        "openapi_version",
        "selected_contract",
        "selected_schema",
        "source_url",
    }
    if not isinstance(payload, dict) or set(payload) != expected_root_keys:
        raise ValueError("OpenAPI fingerprint root contract drift")
    selected_contract = payload.get("selected_contract")
    selected_schema = payload.get("selected_schema")
    if (
        not isinstance(selected_contract, dict)
        or set(selected_contract) != {"paths", "sha256"}
        or not isinstance(selected_schema, dict)
        or set(selected_schema) != {"names", "sha256"}
    ):
        raise ValueError("OpenAPI fingerprint selected contract drift")
    generated_at = payload.get("fingerprint_generated_at")
    try:
        generated_at_value = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("OpenAPI fingerprint generated_at is invalid") from exc
    if generated_at_value.tzinfo is None:
        raise ValueError("OpenAPI fingerprint generated_at must be timezone-aware")
    if (
        payload.get("source_url") != OPENAPI_SOURCE_URL
        or payload.get("openapi_version") != EXPECTED_OPENAPI_VERSION
        or payload.get("full_openapi_sha256") != EXPECTED_OPENAPI_FULL_SHA256
        or tuple(selected_contract.get("paths") or ()) != EXPECTED_OPENAPI_SELECTED_PATHS
        or selected_contract.get("sha256") != EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256
        or tuple(selected_schema.get("names") or ()) != EXPECTED_OPENAPI_SELECTED_SCHEMA_NAMES
        or selected_schema.get("sha256") != EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256
    ):
        raise ValueError("OpenAPI fingerprint reviewed contract drift")
    return {
        "path": str(resolved),
        "sha256": actual_sha256,
        "size": stat.st_size,
        "fingerprint_generated_at": generated_at,
        "source_url": OPENAPI_SOURCE_URL,
        "full_openapi_sha256": EXPECTED_OPENAPI_FULL_SHA256,
        "openapi_version": EXPECTED_OPENAPI_VERSION,
        "selected_contract_sha256": EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
        "selected_schema_sha256": EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
    }


def openapi_contract_manifest(fingerprint_identity: Mapping[str, object]) -> dict:
    if not isinstance(fingerprint_identity, Mapping):
        raise ValueError("OpenAPI fingerprint identity is required")
    required = {
        "path",
        "sha256",
        "size",
        "fingerprint_generated_at",
        "source_url",
        "full_openapi_sha256",
        "openapi_version",
        "selected_contract_sha256",
        "selected_schema_sha256",
    }
    if set(fingerprint_identity) != required:
        raise ValueError("OpenAPI fingerprint identity contract drift")
    if (
        not normalize_space(fingerprint_identity.get("path"))
        or not re.fullmatch(r"[0-9a-f]{64}", normalize_space(fingerprint_identity.get("sha256")))
        or isinstance(fingerprint_identity.get("size"), bool)
        or not isinstance(fingerprint_identity.get("size"), int)
        or int(fingerprint_identity["size"]) < 1
        or fingerprint_identity.get("source_url") != OPENAPI_SOURCE_URL
        or fingerprint_identity.get("full_openapi_sha256") != EXPECTED_OPENAPI_FULL_SHA256
        or fingerprint_identity.get("openapi_version") != EXPECTED_OPENAPI_VERSION
        or fingerprint_identity.get("selected_contract_sha256")
        != EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256
        or fingerprint_identity.get("selected_schema_sha256")
        != EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256
    ):
        raise ValueError("OpenAPI fingerprint identity mismatch")
    reloaded_identity = load_openapi_fingerprint(
        Path(str(fingerprint_identity["path"])),
        str(fingerprint_identity["sha256"]),
    )
    if dict(fingerprint_identity) != reloaded_identity:
        raise ValueError("OpenAPI fingerprint identity changed after preflight")
    return {
        "version": EXPECTED_OPENAPI_VERSION,
        "selected_contract_sha256": EXPECTED_OPENAPI_SELECTED_CONTRACT_SHA256,
        "selected_schema_sha256": EXPECTED_OPENAPI_SELECTED_SCHEMA_SHA256,
        "fingerprint": dict(fingerprint_identity),
    }


def _require_empty_output(output_dir: Path) -> None:
    if output_dir.is_symlink():
        raise ValueError("output directory cannot be a symlink")
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("output directory must be absent or empty")


def _load_seed(seed_path: Path, approved_seed_sha256: str) -> tuple[dict, dict]:
    resolved = seed_path.resolve(strict=True)
    if seed_path.is_symlink() or not resolved.is_file():
        raise ValueError("seed must be a regular non-symlink file")
    actual_sha = _sha256_path(resolved)
    if not re.fullmatch(r"[0-9a-f]{64}", approved_seed_sha256) or actual_sha != approved_seed_sha256:
        raise ValueError("approved seed SHA-256 mismatch")
    try:
        seed = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("invalid targeted seed JSON") from exc
    if not isinstance(seed, dict):
        raise ValueError("targeted seed root must be an object")
    return seed, {"path": str(resolved), "sha256": actual_sha, "size": resolved.stat().st_size}


def run_targeted_seed_artifact(
    *,
    seed_path: Path,
    approved_seed_sha256: str,
    output_dir: Path,
    client: object,
    max_search_candidates: int,
    max_results_pages_per_horse: int = 5,
    max_parent_profiles: int = 2,
    openapi_fingerprint_identity: Mapping[str, object],
    content_pool: ContentAddressedPool | None = None,
) -> dict:
    openapi_contract = openapi_contract_manifest(openapi_fingerprint_identity)
    _require_empty_output(output_dir)
    seed, seed_identity = _load_seed(seed_path, approved_seed_sha256)
    output_dir.mkdir(parents=True, exist_ok=True)
    request_count_before = int(getattr(client, "request_count", 0))
    request_ledger_before = len(getattr(client, "request_ledger", []))
    recording = RecordingClient(client)
    try:
        result = run_targeted_seed(
            seed,
            client=recording,
            max_search_candidates=max_search_candidates,
            max_results_pages_per_horse=max_results_pages_per_horse,
            max_parent_profiles=max_parent_profiles,
        )
    except (RacingApiError, ValueError) as exc:
        request_ledger = list(getattr(client, "request_ledger", []))[
            request_ledger_before:
        ]
        request_count_after = int(
            getattr(client, "request_count", len(recording.responses))
        )
        failure_category = "validation_error"
        if isinstance(exc, RacingApiSemanticGap):
            failure_category = "semantic_gap"
        elif isinstance(exc, RacingApiAuthError):
            failure_category = "auth_failure"
            if request_ledger:
                failure_category = str(
                    request_ledger[-1].get(
                        "auth_failure_category", "auth_failure"
                    )
                )
        elif isinstance(exc, RacingApiSchemaError):
            failure_category = "schema_error"
        elif isinstance(exc, RacingApiHttpError):
            failure_category = "http_error"
        failure_manifest = {
            "schema_version": "targeted-horse-run-failure.v1",
            "status": "failed",
            "database_writes": 0,
            "openapi_contract": openapi_contract,
            "seed": seed_identity,
            "request_ceiling": getattr(client, "request_ceiling", None),
            "max_search_candidates": max_search_candidates,
            "max_results_pages_per_horse": max_results_pages_per_horse,
            "max_parent_profiles": max_parent_profiles,
            "request_count": request_count_after - request_count_before,
            "global_request_count_after": request_count_after,
            "request_ledger": request_ledger,
            "successful_response_count": len(recording.responses),
            "response_summaries": [
                summarize_recorded_response(response)
                for response in recording.responses
            ],
            "failure": {
                "category": failure_category,
                "exception_type": type(exc).__name__,
                "message": normalize_space(str(exc))[:500],
            },
        }
        if isinstance(exc, RacingApiSemanticGap):
            failure_manifest["failure"]["gap_code"] = exc.code
        failure_path = output_dir / "run-failure.json"
        _atomic_write(
            failure_path,
            (
                json.dumps(
                    failure_manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        _atomic_write(
            output_dir / "FAILED",
            f"{_sha256_path(failure_path)}\n".encode("ascii"),
        )
        raise
    response_files = []
    for index, response in enumerate(recording.responses, 1):
        if content_pool is None:
            path = output_dir / "cache" / f"response-{index:04d}.json"
            _atomic_write(path, f"{canonical_json(response)}\n".encode("utf-8"))
            response_files.append(
                {
                    "path": str(path.relative_to(output_dir)),
                    "sha256": _sha256_path(path),
                    "size": path.stat().st_size,
                    "url": response["url"],
                }
            )
        else:
            response_files.append(
                {
                    "url": response["url"],
                    "object_ref": content_pool.put_json(
                        kind="http_response",
                        identity=hashlib.sha256(
                            str(response["url"]).encode("utf-8")
                        ).hexdigest(),
                        payload=response,
                        singleton_identity=False,
                    ),
                }
            )
    if content_pool is None:
        normalized_payload = result
        normalized_path = output_dir / "normalized" / "targeted-horse-export.json"
        run_schema_version = "targeted-horse-run.v1"
    else:
        normalized_payload = compact_targeted_export(result, pool=content_pool)
        normalized_path = (
            output_dir / "normalized" / "targeted-horse-export-ref.json"
        )
        run_schema_version = "targeted-horse-run.v2"
    _atomic_write(
        normalized_path,
        f"{canonical_json(normalized_payload)}\n".encode("utf-8"),
    )
    request_ledger = list(getattr(client, "request_ledger", []))[request_ledger_before:]
    request_count_after = int(getattr(client, "request_count", len(recording.responses)))
    run_manifest = {
        "schema_version": run_schema_version,
        "status": "complete",
        "database_writes": 0,
        "openapi_contract": openapi_contract,
        "seed": seed_identity,
        "request_ceiling": getattr(client, "request_ceiling", None),
        "max_search_candidates": max_search_candidates,
        "max_results_pages_per_horse": max_results_pages_per_horse,
        "max_parent_profiles": max_parent_profiles,
        "request_count": request_count_after - request_count_before,
        "global_request_count_after": request_count_after,
        "request_ledger": request_ledger,
        "responses": response_files,
        "normalized": {
            "path": str(normalized_path.relative_to(output_dir)),
            "sha256": _sha256_path(normalized_path),
            "size": normalized_path.stat().st_size,
            "schema_version": normalized_payload["schema_version"],
        },
        "result_summary": {
            "seed_id": result["seed_id"],
            "horse_id": result["horse_id"],
            "identity_mode": result["identity_mode"],
            "provider_career_rows": result["career"]["provider_row_count"],
            "unique_career_races": result["career"]["unique_race_count"],
            "target_race_id": (
                result["target_race"]["race_id"] if result["target_race"] else None
            ),
            "target_actual_starters": (
                len(result["target_race"]["actual_starters"])
                if result["target_race"]
                else 0
            ),
            "target_occurrence_status": result["target_occurrence"]["status"],
            "career_authority_status": result["career_authority"]["status"],
            "parent_profiles": len(result["parent_profiles"]),
        },
    }
    if content_pool is not None:
        run_manifest["content_pool"] = {
            "root_relative_to_run": os.path.relpath(
                content_pool.root, output_dir.resolve(strict=True)
            ),
            "index_sha256_after_seed": _sha256_path(content_pool.index_path),
        }
    manifest_path = output_dir / "run-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(run_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "COMPLETE", f"{_sha256_path(manifest_path)}\n".encode("ascii"))
    return run_manifest


def runner_disposition(position: object) -> str:
    value = normalize_space(position).upper()
    if FINISHED_POSITION_RE.fullmatch(value):
        return "finished"
    if value in STARTED_NON_FINISH:
        return "started_non_finish"
    if value in DISQUALIFIED:
        return "disqualified_after_start"
    if value in NON_RUNNER:
        return "non_runner"
    return "unresolved"


def _target_aliases(target: Mapping[str, object], field: str, alias_field: str) -> set[str]:
    aliases = target.get(alias_field, [])
    if aliases is None:
        aliases = []
    if not isinstance(aliases, list) or any(not isinstance(value, str) for value in aliases):
        raise ValueError(f"target {alias_field} must be a string list")
    return {
        normalized
        for normalized in (normalize_identity_text(value) for value in [target.get(field), *aliases])
        if normalized
    }


def _without_parenthetical_qualifiers(value: object) -> str:
    """Remove provider-added age/surface/grade suffixes before title matching."""

    return normalize_identity_text(re.sub(r"\([^)]*\)", " ", normalize_space(value)))


def _tokens_contain(haystack: str, needle: str) -> bool:
    haystack_tokens = haystack.split()
    needle_tokens = needle.split()
    if not needle_tokens or len(needle_tokens) > len(haystack_tokens):
        return False
    width = len(needle_tokens)
    return any(
        haystack_tokens[index : index + width] == needle_tokens
        for index in range(len(haystack_tokens) - width + 1)
    )


def _grand_prix_signature(value: str) -> tuple[str, ...] | None:
    tokens = value.split()
    expanded: list[str] = []
    index = 0
    while index < len(tokens):
        if index + 1 < len(tokens) and tokens[index : index + 2] == ["g", "p"]:
            expanded.extend(("grand", "prix"))
            index += 2
            continue
        if tokens[index] == "gp":
            expanded.extend(("grand", "prix"))
        else:
            expanded.append(tokens[index])
        index += 1
    if "grand" not in expanded or "prix" not in expanded:
        return None
    ignored = {"grand", "prix", "de", "du", "des", "d", "la", "le", "l"}
    identity = tuple(sorted(token for token in expanded if token not in ignored))
    return identity or None


def _race_name_matches(accepted_names: set[str], observed: object) -> bool:
    observed_full = normalize_identity_text(observed)
    observed_base = _without_parenthetical_qualifiers(observed)
    if observed_full in accepted_names or observed_base in accepted_names:
        return True
    if any(_tokens_contain(observed_base, alias) for alias in accepted_names):
        return True
    observed_grand_prix = _grand_prix_signature(observed_base)
    return bool(
        observed_grand_prix
        and any(
            _grand_prix_signature(alias) == observed_grand_prix
            for alias in accepted_names
        )
    )


def _normalized_pattern_grade(value: object) -> str:
    raw = normalize_space(value).upper()
    match = re.fullmatch(r"(?:GROUP|GRADE)\s*([123])", raw)
    return f"G{match.group(1)}" if match else raw


def _race_matches_target(target: Mapping[str, object], race: Mapping[str, object]) -> bool:
    region_code = REGION_CODES.get(normalize_space(target.get("country_region")))
    if not region_code or normalize_space(race.get("region")).upper() != region_code:
        return False
    raw_date = normalize_space(race.get("date"))
    if not raw_date.startswith(str(target.get("year"))):
        return False
    target_date = normalize_space(target.get("local_date"))
    if target_date and raw_date != target_date:
        return False
    accepted_names = _target_aliases(target, "canonical_name_original", "race_name_aliases")
    if not _race_name_matches(accepted_names, race.get("race_name")):
        return False
    accepted_courses = _target_aliases(target, "racecourse", "racecourse_aliases")
    observed_course = _without_parenthetical_qualifiers(race.get("course"))
    if accepted_courses and observed_course not in accepted_courses:
        return False
    if _normalized_pattern_grade(race.get("pattern")) != _normalized_pattern_grade(
        target.get("grade_text")
    ):
        return False
    target_discipline = normalize_space(target.get("discipline")).lower()
    race_type = normalize_space(race.get("type")).lower()
    if target_discipline == "flat" and race_type != "flat":
        return False
    if target_discipline == "jumps" and race_type not in {"chase", "hurdle", "nh flat", "nh_flat"}:
        return False
    return True


def recover_target_race(
    *,
    target: Mapping[str, object],
    target_horse_id: str,
    races: Iterable[Mapping[str, object]],
) -> dict:
    if not HORSE_ID_RE.fullmatch(target_horse_id):
        raise ValueError("invalid target horse id")
    matches = [dict(race) for race in races if _race_matches_target(target, race)]
    if len(matches) != 1:
        raise ValueError(f"target race candidate count must be 1, got {len(matches)}")
    race = matches[0]
    _validate_race(race)
    actual_starters = []
    non_runner_count = 0
    for runner in race["runners"]:
        if not isinstance(runner, Mapping):
            raise ValueError("runner must be an object")
        horse_id = normalize_space(runner.get("horse_id"))
        if not HORSE_ID_RE.fullmatch(horse_id):
            raise ValueError("runner has invalid horse id")
        disposition = runner_disposition(runner.get("position"))
        if disposition == "unresolved":
            raise ValueError(f"unresolved runner status: {runner.get('position')!r}")
        normalized_runner = {**runner, "participant_status": disposition}
        if disposition == "non_runner":
            non_runner_count += 1
        else:
            actual_starters.append(normalized_runner)
    if target_horse_id not in {runner["horse_id"] for runner in actual_starters}:
        raise ValueError("target horse was not an actual starter in matched race")
    return {
        **race,
        "actual_starters": actual_starters,
        "excluded_non_runner_count": non_runner_count,
        "source_mode": "targeted_horse",
    }


def _enabled(value: object) -> bool:
    return normalize_space(value).casefold() in {"1", "true", "yes", "on"}


def add_exclusive_account_budget_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account-budget-root", required=True, type=Path)
    parser.add_argument("--credential-alias", required=True)
    parser.add_argument("--account-scope-id", required=True)
    parser.add_argument("--account-scope-manifest-sha256", required=True)
    parser.add_argument("--account-request-ceiling", required=True, type=int)
    parser.add_argument("--exclusive-account-proof", required=True, type=Path)
    parser.add_argument("--exclusive-account-proof-sha256", required=True)


def add_openapi_fingerprint_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--openapi-fingerprint", required=True, type=Path)
    parser.add_argument("--approved-openapi-fingerprint-sha256", required=True)


def build_exclusive_account_budget(args: argparse.Namespace) -> FileAccountBudget:
    if args.account_request_ceiling < args.request_ceiling:
        raise ValueError("account request ceiling cannot be below run request ceiling")
    proof = load_exclusive_account_proof(
        args.exclusive_account_proof,
        expected_sha256=args.exclusive_account_proof_sha256,
        credential_alias=args.credential_alias,
        scope_id=args.account_scope_id,
        scope_manifest_sha256=args.account_scope_manifest_sha256,
        now=datetime.now(timezone.utc),
    )
    return FileAccountBudget(
        root=args.account_budget_root,
        credential_alias=args.credential_alias,
        scope_id=args.account_scope_id,
        scope_manifest_sha256=args.account_scope_manifest_sha256,
        request_ceiling=args.account_request_ceiling,
        min_interval_seconds=0.25,
        valid_until_epoch=datetime.fromisoformat(
            str(proof["valid_until"]).replace("Z", "+00:00")
        ).timestamp(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--approved-seed-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--request-ceiling", required=True, type=int)
    parser.add_argument("--max-search-candidates", type=int, default=10)
    parser.add_argument("--max-results-pages-per-horse", type=int, default=5)
    parser.add_argument("--max-parent-profiles", type=int, default=2)
    parser.add_argument("--allow-network", action="store_true")
    add_openapi_fingerprint_args(parser)
    add_exclusive_account_budget_args(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.allow_network or not _enabled(os.environ.get("RACING_API_HORSE_EXPORT_NETWORK_ENABLED")):
        raise SystemExit("network requires --allow-network and RACING_API_HORSE_EXPORT_NETWORK_ENABLED=true")
    expected_ceiling = (
        1
        + args.max_search_candidates * args.max_results_pages_per_horse
        + 2
        + 2 * args.max_parent_profiles
    )
    if args.request_ceiling != expected_ceiling:
        raise SystemExit(
            f"request ceiling must equal bounded targeted formula: {expected_ceiling}"
        )
    try:
        openapi_fingerprint_identity = load_openapi_fingerprint(
            args.openapi_fingerprint,
            args.approved_openapi_fingerprint_sha256,
        )
        account_budget = build_exclusive_account_budget(args)
        client = RacingApiClient(
            username=os.environ.get("RACING_API_USERNAME", ""),
            password=os.environ.get("RACING_API_PASSWORD", ""),
            request_ceiling=args.request_ceiling,
            min_interval_seconds=0,
            account_budget=account_budget,
        )
        manifest = run_targeted_seed_artifact(
            seed_path=args.seed,
            approved_seed_sha256=args.approved_seed_sha256,
            output_dir=args.output_dir,
            client=client,
            max_search_candidates=args.max_search_candidates,
            max_results_pages_per_horse=args.max_results_pages_per_horse,
            max_parent_profiles=args.max_parent_profiles,
            openapi_fingerprint_identity=openapi_fingerprint_identity,
        )
    except (RacingApiError, ValueError) as exc:
        print(f"safe-stop: {exc}", file=sys.stderr)
        return SAFE_STOP_EXIT_CODE
    print(json.dumps(manifest["result_summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
