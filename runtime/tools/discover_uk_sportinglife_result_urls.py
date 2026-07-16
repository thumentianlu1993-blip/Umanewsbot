#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.request import Request, urlopen

from historical_race_detail_http import ControlledHTTPError, _validated_url
from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache


BASE_URL = "https://www.sportinglife.com"
API_PATH_RE = r"/api/horse-racing/racing/racecards/\d{4}-\d{2}-\d{2}"
RESULT_PATH_RE = r"/racing/results/\d{4}-\d{2}-\d{2}/[a-z0-9-]+/\d+/[a-z0-9-]+"
OFFICIAL_HOST = "www.sportinglife.com"
SOURCE_AUTHORITY = "third_party_high_access"
VALID_TIERS = {"historical_hard", "historical_best_effort", "new_formal"}
UK_COUNTRY_NAMES = {
    "eng",
    "england",
    "gb",
    "gbr",
    "great britain",
    "sco",
    "scotland",
    "uk",
    "united kingdom",
    "wal",
    "wales",
}
STAGED_EVENT_FIELDS = [
    "target_id",
    "target_sha256",
    "inventory_artifact_sha256",
    "year",
    "slug",
    "original_name",
    "chinese_name",
    "country_region",
    "racecourse",
    "grade_text",
    "normalized_grade",
    "surface",
    "distance_text",
    "status",
    "local_date",
    "source_refs",
]
NAME_STOPWORDS = {
    "a",
    "and",
    "as",
    "at",
    "class",
    "for",
    "gbb",
    "grade",
    "group",
    "race",
    "registered",
    "sponsored",
    "stake",
    "stakes",
    "the",
}
COURSE_ALIASES = {
    "royalascot": "ascot",
    "epsom": "epsomdowns",
    "epsomdowns": "epsomdowns",
    "haydock": "haydockpark",
    "haydockpark": "haydockpark",
    "kempton": "kemptonpark",
    "kemptonpark": "kemptonpark",
    "lingfield": "lingfieldpark",
    "lingfieldpark": "lingfieldpark",
    "sandown": "sandownpark",
    "sandownpark": "sandownpark",
}


class DiscoveryError(RuntimeError):
    pass


def _orchestration_id(value: object, *, label: str) -> str:
    normalized = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", normalized) is None:
        raise DiscoveryError(f"{label} is invalid")
    return normalized


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_identity(path: Path) -> dict:
    if not path.is_file():
        raise DiscoveryError(f"input file is missing: {path}")
    body = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "size": len(body),
        "sha256": _sha256_bytes(body),
    }


def _atomic_write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: object) -> None:
    body = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(path, body)


def _atomic_write_jsonl(path: Path, rows: list[dict]) -> None:
    body = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
        for row in rows
    ).encode("utf-8")
    _atomic_write_bytes(path, body)


def _atomic_write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write_bytes(path, buffer.getvalue().encode("utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DiscoveryError(f"pending master targets are unreadable: {path}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(
                f"pending master targets contain invalid JSON at line {line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise DiscoveryError(
                f"pending master target must be an object at line {line_number}"
            )
        rows.append(row)
    return rows


def _read_events(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise DiscoveryError(f"events CSV is unreadable: {path}") from exc
    if not rows:
        return []
    required = {
        "target_id",
        "target_sha256",
        "slug",
        "original_name",
        "country_region",
        "racecourse",
        "status",
        "local_date",
    }
    if not required <= set(rows[0]):
        raise DiscoveryError("events CSV is missing required columns")
    return rows


def _target_id(value: object) -> int:
    if isinstance(value, bool):
        raise DiscoveryError("target id is invalid")
    try:
        normalized = int(str(value))
    except (TypeError, ValueError) as exc:
        raise DiscoveryError("target id is invalid") from exc
    if normalized <= 0:
        raise DiscoveryError("target id is invalid")
    return normalized


def _target_sha(value: object) -> str:
    normalized = str(value or "").lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise DiscoveryError("target SHA is invalid")
    return normalized


def _coverage_index(rows: list[dict]) -> dict[int, dict]:
    indexed: dict[int, dict] = {}
    for row in rows:
        target_id = _target_id(row.get("target_id"))
        if target_id in indexed:
            raise DiscoveryError(f"duplicate coverage row for target {target_id}")
        indexed[target_id] = {
            **row,
            "target_id": target_id,
            "target_sha256": _target_sha(row.get("target_sha256")),
        }
    return indexed


def _master_region(row: dict) -> str:
    region = str(row.get("region") or "")
    legacy_region = str(row.get("country_region") or "")
    if region and legacy_region and region != legacy_region:
        raise DiscoveryError(
            f"master region mismatch for target {_target_id(row.get('target_id'))}"
        )
    return region or legacy_region


def _selected_targets(
    rows: list[dict],
    coverage_rows: list[dict],
    coverage_tiers: list[str],
    *,
    require_master_region: bool,
) -> list[dict]:
    tiers = set(coverage_tiers)
    if not tiers or not tiers <= VALID_TIERS:
        raise DiscoveryError("coverage tiers are invalid")
    coverage_by_target = _coverage_index(coverage_rows)
    selected = []
    seen: set[int] = set()
    for row in rows:
        if require_master_region and "region" not in row:
            raise DiscoveryError(
                f"master region missing for target {_target_id(row.get('target_id'))}"
            )
        if _master_region(row) != "united_kingdom":
            continue
        if row.get("reason") != "url_discovery_pending":
            continue
        target_id = _target_id(row.get("target_id"))
        if target_id in seen:
            raise DiscoveryError(f"duplicate pending target id: {target_id}")
        seen.add(target_id)
        target_sha = _target_sha(row.get("target_sha256"))
        coverage = coverage_by_target.get(target_id)
        if coverage is None:
            raise DiscoveryError(f"coverage row missing for target {target_id}")
        if coverage["target_sha256"] != target_sha:
            raise DiscoveryError(f"coverage target SHA mismatch for target {target_id}")
        coverage_region = str(coverage.get("country_region") or "")
        if coverage_region != "united_kingdom":
            raise DiscoveryError(f"coverage region mismatch for target {target_id}")
        coverage_tier = str(coverage.get("coverage_tier") or "")
        if coverage_tier not in VALID_TIERS:
            raise DiscoveryError(f"coverage tier is invalid for target {target_id}")
        if coverage_tier not in tiers:
            continue
        selected.append(
            {
                **row,
                "target_id": target_id,
                "target_sha256": target_sha,
                "country_region": "united_kingdom",
                "coverage_tier": coverage_tier,
            }
        )
    return sorted(selected, key=lambda row: row["target_id"])


def _join_events(targets: list[dict], events: list[dict]) -> list[dict]:
    by_id: dict[int, dict] = {}
    for row in events:
        target_id = _target_id(row.get("target_id"))
        if target_id in by_id:
            raise DiscoveryError(f"duplicate event target id: {target_id}")
        by_id[target_id] = row
    joined = []
    for target in targets:
        event = by_id.get(target["target_id"])
        if event is None:
            raise DiscoveryError(
                f"event row is missing for target {target['target_id']}"
            )
        event_sha = _target_sha(event.get("target_sha256"))
        if event_sha != target["target_sha256"]:
            raise DiscoveryError(
                f"target SHA mismatch for target {target['target_id']}"
            )
        if event.get("country_region") != "united_kingdom":
            raise DiscoveryError(
                f"event region mismatch for target {target['target_id']}"
            )
        master_slug = str(target.get("slug") or "")
        event_slug = str(event.get("slug") or "")
        if master_slug and master_slug != event_slug:
            raise DiscoveryError(f"slug mismatch for target {target['target_id']}")
        if target.get("year") not in (None, ""):
            try:
                master_year = int(target.get("year"))
                event_year = int(event.get("year"))
            except (TypeError, ValueError) as exc:
                raise DiscoveryError(
                    f"year mismatch for target {target['target_id']}"
                ) from exc
            if master_year <= 0 or master_year != event_year:
                raise DiscoveryError(f"year mismatch for target {target['target_id']}")
        master_date = str(target.get("local_date") or "")
        event_date = str(event.get("local_date") or "")
        if master_date and master_date != event_date:
            raise DiscoveryError(
                f"local_date mismatch for target {target['target_id']}"
            )
        if event.get("status") != "finished":
            raise DiscoveryError(
                f"event status mismatch for target {target['target_id']}"
            )
        joined.append(
            {
                **event,
                "target_id": target["target_id"],
                "target_sha256": event_sha,
                "coverage_tier": target["coverage_tier"],
            }
        )
    return joined


def _resume_identity(output_dir: Path, input_identity: dict) -> None:
    summary_path = output_dir / "sportinglife_url_discovery_summary.json"
    if not summary_path.exists():
        return
    try:
        previous = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError("existing discovery summary identity is unreadable") from exc
    if previous.get("input_identity") != input_identity:
        raise DiscoveryError("input identity drift detected on resume")


def _request_budget_identity() -> dict:
    try:
        max_requests = max(
            0,
            int(os.environ.get("RACE_EVENT_CRAWL_MAX_REQUESTS", "0") or 0),
        )
        interval = max(
            0.0,
            float(
                os.environ.get(
                    "RACE_EVENT_CRAWL_REQUEST_INTERVAL_SECONDS",
                    "0",
                )
                or 0
            ),
        )
    except ValueError as exc:
        raise DiscoveryError("request budget configuration is invalid") from exc
    artifact_value = os.environ.get(
        "RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT", ""
    ).strip()
    if not artifact_value:
        raise DiscoveryError("request budget artifact is required")
    artifact = Path(artifact_value)
    identity = {
        "artifact_path": str(artifact.resolve()),
        "max_requests": max_requests,
        "request_interval_seconds": interval,
    }
    if max_requests <= 0:
        raise DiscoveryError("request budget must be positive")
    if not artifact.exists():
        return identity
    try:
        state = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError("request budget artifact is unreadable") from exc
    if not isinstance(state, dict):
        raise DiscoveryError("request budget artifact is invalid")
    recorded_max = state.get("max_requests")
    recorded_interval = state.get("request_interval_seconds")
    if recorded_max != max_requests or float(recorded_interval or 0.0) != interval:
        raise DiscoveryError("request budget configuration drift detected")
    return identity


def _validate_official_url(url: str, *, result: bool = False) -> str:
    patterns = {
        OFFICIAL_HOST: [RESULT_PATH_RE if result else API_PATH_RE],
    }
    try:
        validated, _host = _validated_url(
            url,
            hosts={OFFICIAL_HOST},
            patterns=patterns,
            query_patterns={},
        )
    except ControlledHTTPError as exc:
        raise DiscoveryError(str(exc)) from exc
    return validated


def _cache_manifest_path(cache_path: Path) -> Path:
    configured = os.environ.get(
        "RACE_EVENT_CRAWL_SOURCE_CACHE_MANIFEST", ""
    ).strip()
    return Path(configured) if configured else cache_path.parent / "source_cache_manifest.json"


def _read_verified_cache(cache_path: Path, *, source_url: str) -> tuple[bytes, dict]:
    manifest_path = _cache_manifest_path(cache_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError("cache manifest identity is unreadable") from exc
    root = Path(manifest.get("root") or manifest_path.parent).resolve()
    if root != manifest_path.parent.resolve():
        raise DiscoveryError("cache manifest identity root mismatch")
    try:
        relative = str(cache_path.resolve().relative_to(root))
    except ValueError as exc:
        raise DiscoveryError("cache path identity is outside the cache root") from exc
    item = (manifest.get("files") or {}).get(relative)
    if not isinstance(item, dict):
        raise DiscoveryError("cache response identity is missing")
    try:
        body = cache_path.read_bytes()
    except OSError as exc:
        raise DiscoveryError("cache response identity is unreadable") from exc
    if (
        item.get("source_url") != source_url
        or item.get("size") != len(body)
        or item.get("sha256") != _sha256_bytes(body)
    ):
        raise DiscoveryError("cache response identity mismatch")
    return body, item


def _load_date_response(
    date: str,
    *,
    output_dir: Path,
    allow_network: bool,
    timeout_seconds: int,
    sleep_seconds: float,
) -> tuple[list[dict], dict]:
    source_url = _validate_official_url(
        f"{BASE_URL}/api/horse-racing/racing/racecards/{date}"
    )
    cache_path = output_dir / "sources" / f"sportinglife_racecards_{date}.json"
    if cache_path.exists():
        body, cache_identity = _read_verified_cache(
            cache_path,
            source_url=source_url,
        )
    else:
        if not allow_network:
            raise DiscoveryError(f"cache is missing and network is disabled: {date}")
        before_network_request(source_url)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        request = Request(
            source_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "umanewsbot/1.0 (+https://umafans.run; historical URL discovery)",
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else source_url
            _validate_official_url(final_url)
            body = response.read()
        cache_identity = write_source_cache(
            cache_path,
            body,
            source_url=source_url,
        )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"Sporting Life response is invalid JSON: {date}") from exc
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise DiscoveryError(f"Sporting Life response has invalid shape: {date}")
    response_sha = _sha256_bytes(body)
    if cache_identity.get("sha256") != response_sha:
        raise DiscoveryError("cache response identity mismatch")
    return payload, {
        "date": date,
        "source_url": source_url,
        "response_sha256": response_sha,
        "cache": cache_identity,
    }


def _plain(value: object) -> str:
    return " ".join(str(value or "").split())


def _slugify(value: object) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _plain(value).casefold()).strip("-")
    return slug or "race"


def _course_key(value: object) -> str:
    key = re.sub(r"[^a-z0-9]+", "", _plain(value).casefold())
    return COURSE_ALIASES.get(key, key)


def _name_variants(value: object) -> list[str]:
    text = _plain(value).casefold().replace("&", " and ")
    variants = [text]
    registered = re.findall(r"registered\s+as\s+(?:the\s+)?([^)]+)", text)
    variants.extend(registered)
    variants.append(re.sub(r"\[[^]]+\]", " ", text))
    variants.append(re.sub(r"\((?:group|grade|class|gbb)[^)]*\)", " ", text))
    variants.append(
        re.split(r"\b(?:presented by|sponsored by)\b", text, maxsplit=1)[0]
    )
    normalized = []
    for variant in variants:
        tokens = re.findall(r"[a-z0-9]+", variant)
        tokens = [
            {"novice": "novices", "nov": "novices", "hdle": "hurdle"}.get(
                token, token
            )
            for token in tokens
            if token not in NAME_STOPWORDS and not token.isdigit()
        ]
        key = " ".join(tokens)
        if key and key not in normalized:
            normalized.append(key)
    return normalized


def _name_score(expected: object, actual: object) -> float:
    best = 0.0
    for left in _name_variants(expected):
        left_tokens = set(left.split())
        for right in _name_variants(actual):
            if left == right:
                return 1.0
            right_tokens = set(right.split())
            overlap = len(left_tokens & right_tokens)
            if overlap == 0:
                continue
            shorter_coverage = overlap / min(len(left_tokens), len(right_tokens))
            jaccard = overlap / len(left_tokens | right_tokens)
            ratio = SequenceMatcher(None, left, right).ratio()
            score = shorter_coverage * 0.55 + jaccard * 0.25 + ratio * 0.20
            best = max(best, score)
    return best


def _flatten_meetings(payload: list[dict]) -> list[dict]:
    flattened = []
    for meeting in payload:
        summary = meeting.get("meeting_summary") or {}
        course = summary.get("course") or {}
        country = course.get("country") or {}
        for race in meeting.get("races") or []:
            if not isinstance(race, dict):
                continue
            flattened.append(
                {
                    **race,
                    "_meeting_date": _plain(summary.get("date")),
                    "_meeting_course": _plain(course.get("name")),
                    "_country": _plain(
                        country.get("short_name") or country.get("long_name")
                    ).casefold(),
                }
            )
    return flattened


def _gap(event: dict, reason: str, *, candidates: list[dict] | None = None) -> dict:
    return {
        "accounting_status": "gap",
        "coverage_tier": event["coverage_tier"],
        "gap_reason": reason,
        "local_date": event.get("local_date") or "",
        "racecourse": event.get("racecourse") or "",
        "slug": event.get("slug") or "",
        "target_id": event["target_id"],
        "target_sha256": event["target_sha256"],
        "candidate_race_ids": sorted(
            {
                int((row.get("race_summary_reference") or {}).get("id") or 0)
                for row in candidates or []
                if int((row.get("race_summary_reference") or {}).get("id") or 0) > 0
            }
        ),
    }


def _match_event(event: dict, races: list[dict], response_sha: str) -> tuple[dict | None, dict | None]:
    expected_course = _course_key(event.get("racecourse"))
    expected_date = _plain(event.get("local_date"))
    course_matches = []
    for race in races:
        race_course = race.get("course_name") or race.get("_meeting_course")
        if _course_key(race_course) != expected_course:
            continue
        course_matches.append(race)

    def hard_match(race: dict) -> bool:
        return (
            race.get("_country") in UK_COUNTRY_NAMES
            and _plain(race.get("date")) == expected_date
            and _plain(race.get("_meeting_date")) == expected_date
            and _plain(race.get("race_stage")).upper() == "WEIGHEDIN"
        )

    def scored_matches(candidates: list[dict]) -> list[tuple[float, dict]]:
        scored = []
        for race in candidates:
            score = _name_score(event.get("original_name"), race.get("name"))
            if score >= 0.82:
                scored.append((score, race))
        return scored

    scored = scored_matches([race for race in course_matches if hard_match(race)])
    if not scored:
        diagnostic = scored_matches(course_matches)
        if not diagnostic:
            return None, _gap(event, "no_match")
        diagnostic_score = max(score for score, _race in diagnostic)
        diagnostic_candidates = [
            race
            for score, race in diagnostic
            if diagnostic_score - score <= 0.02
        ]
        if len(diagnostic_candidates) != 1:
            return None, _gap(
                event,
                "ambiguous_match",
                candidates=diagnostic_candidates,
            )
        diagnostic_race = diagnostic_candidates[0]
        if diagnostic_race.get("_country") not in UK_COUNTRY_NAMES:
            return None, _gap(event, "region_drift", candidates=[diagnostic_race])
        if (
            _plain(diagnostic_race.get("date")) != expected_date
            or _plain(diagnostic_race.get("_meeting_date")) != expected_date
        ):
            return None, _gap(event, "date_drift", candidates=[diagnostic_race])
        return None, _gap(event, "non_terminal_race", candidates=[diagnostic_race])
    top_score = max(score for score, _race in scored)
    candidates = [race for score, race in scored if top_score - score <= 0.02]
    if len(candidates) != 1:
        return None, _gap(event, "ambiguous_match", candidates=candidates)
    race = candidates[0]
    race_id = int((race.get("race_summary_reference") or {}).get("id") or 0)
    if race_id <= 0:
        return None, _gap(event, "no_match")
    course_slug = _slugify(race.get("course_name") or race.get("_meeting_course"))
    display_slug = _slugify(race.get("race_slug") or race.get("name"))
    result_url = _validate_official_url(
        f"{BASE_URL}/racing/results/{expected_date}/{course_slug}/{race_id}/{display_slug}",
        result=True,
    )
    return {
        "discovery_status": "url_discovered",
        "coverage_tier": event["coverage_tier"],
        "local_date": expected_date,
        "match_score": round(top_score, 6),
        "race_id": race_id,
        "race_name": _plain(race.get("name")),
        "racecourse": _plain(event.get("racecourse")),
        "response_sha256": response_sha,
        "result_url": result_url,
        "slug": event.get("slug") or "",
        "source_authority": SOURCE_AUTHORITY,
        "source_provider": "uk_sportinglife",
        "target_id": event["target_id"],
        "target_sha256": event["target_sha256"],
        "year": int(event["year"]),
    }, None


def _source_refs(value: object, *, target_id: int) -> dict:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        parsed = value
    else:
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise DiscoveryError(
                f"event source_refs are invalid for target {target_id}"
            ) from exc
    if not isinstance(parsed, dict):
        raise DiscoveryError(
            f"event source_refs must be an object for target {target_id}"
        )
    return parsed


def _staged_events(
    events: list[dict],
    discovered: list[dict],
    *,
    plan_id: str,
    shard_id: str,
) -> list[dict]:
    events_by_target = {event["target_id"]: event for event in events}
    rows = []
    for result in discovered:
        target_id = result["target_id"]
        event = events_by_target[target_id]
        source_refs = _source_refs(event.get("source_refs"), target_id=target_id)
        detail_discovery = source_refs.setdefault("detail_discovery", {})
        if not isinstance(detail_discovery, dict):
            raise DiscoveryError(
                f"event detail_discovery must be an object for target {target_id}"
            )
        urls = detail_discovery.setdefault("urls", {})
        if not isinstance(urls, dict):
            raise DiscoveryError(
                f"event detail discovery URLs must be an object for target {target_id}"
            )
        evidence = {
            "plan_id": plan_id,
            "race_id": result["race_id"],
            "response_sha256": result["response_sha256"],
            "shard_id": shard_id,
            "source_authority": SOURCE_AUTHORITY,
            "source_provider": "uk_sportinglife",
            "target_id": target_id,
            "target_sha256": result["target_sha256"],
            "url": result["result_url"],
        }
        existing = urls.get("result_url")
        if existing not in (None, "", evidence):
            raise DiscoveryError(
                f"existing result URL evidence conflicts for target {target_id}"
            )
        urls["result_url"] = evidence
        detail_discovery["plan_id"] = plan_id
        detail_discovery["shard_id"] = shard_id
        detail_discovery["source_authority"] = SOURCE_AUTHORITY
        detail_discovery["source_provider"] = "uk_sportinglife"
        detail_discovery["source_url"] = result["result_url"]
        row = {field: event.get(field, "") for field in STAGED_EVENT_FIELDS}
        row.update(
            {
                "target_id": target_id,
                "target_sha256": result["target_sha256"],
                "country_region": "united_kingdom",
                "source_refs": json.dumps(
                    source_refs,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        )
        rows.append(row)
    return sorted(rows, key=lambda row: row["target_id"])


def _date_fragment(
    input_identity: dict,
    discovered: list[dict],
    *,
    plan_id: str,
    shard_id: str,
) -> dict:
    requests = []
    for result in discovered:
        requests.append(
            {
                "discovery_status": "url_discovered",
                "evidence_source_url": result["result_url"],
                "local_date": result["local_date"],
                "plan_id": plan_id,
                "race_id": result["race_id"],
                "response_sha256": result["response_sha256"],
                "source_authority": SOURCE_AUTHORITY,
                "source_name": "sporting_life",
                "source_provider": "uk_sportinglife",
                "source_url": result["result_url"],
                "shard_id": shard_id,
                "target_id": result["target_id"],
                "target_sha256": result["target_sha256"],
                "year": result["year"],
            }
        )
    return {
        "artifact_kind": "historical_race_detail_source_fragment",
        "input_identity": input_identity,
        "plan_id": plan_id,
        "region": "united_kingdom",
        "requests": sorted(requests, key=lambda row: row["target_id"]),
        "schema_version": "1.0",
        "shard_id": shard_id,
        "source_authority": SOURCE_AUTHORITY,
        "source_provider": "uk_sportinglife",
        "target_count": len(requests),
    }


def discover_urls(args) -> dict:
    plan_id = _orchestration_id(getattr(args, "plan_id", None), label="plan_id")
    shard_id = _orchestration_id(getattr(args, "shard_id", None), label="shard_id")
    if shard_id != "united_kingdom" and not shard_id.startswith(
        "united_kingdom-"
    ):
        raise DiscoveryError("shard_id does not identify the united_kingdom region")
    pending_path = Path(args.pending_master_targets)
    events_path = Path(args.events_csv)
    output_dir = Path(args.output_dir)
    coverage_tiers = list(args.coverage_tiers)
    master_rows = _read_jsonl(pending_path)
    pending_identity = _file_identity(pending_path)
    coverage_value = str(getattr(args, "coverage_ledger", "") or "").strip()
    if coverage_value:
        coverage_path = Path(coverage_value)
        coverage_rows = _read_jsonl(coverage_path)
        coverage_identity = _file_identity(coverage_path)
    else:
        if any("region" in row for row in master_rows):
            raise DiscoveryError("coverage ledger is required for region-based master targets")
        coverage_rows = master_rows
        coverage_identity = {
            "mode": "legacy_inline_fixture",
            "sha256": pending_identity["sha256"],
        }
    input_identity = {
        "coverage_tiers": sorted(coverage_tiers),
        "coverage_ledger": coverage_identity,
        "events_csv": _file_identity(events_path),
        "pending_master_targets": pending_identity,
        "plan_id": plan_id,
        "shard_id": shard_id,
    }
    targets = _selected_targets(
        master_rows,
        coverage_rows,
        coverage_tiers,
        require_master_region=bool(coverage_value),
    )
    events = _join_events(targets, _read_events(events_path))
    _resume_identity(output_dir, input_identity)
    request_budget = _request_budget_identity()
    dates = sorted({_plain(event.get("local_date")) for event in events})
    if "" in dates or any(re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) is None for date in dates):
        raise DiscoveryError("event local date is invalid")

    responses: dict[str, tuple[list[dict], dict]] = {}
    for date in dates:
        responses[date] = _load_date_response(
            date,
            output_dir=output_dir,
            allow_network=bool(args.allow_network),
            timeout_seconds=int(args.timeout_seconds),
            sleep_seconds=float(args.sleep_seconds),
        )

    discovered = []
    gaps = []
    for event in events:
        payload, source = responses[event["local_date"]]
        result, gap = _match_event(
            event,
            _flatten_meetings(payload),
            source["response_sha256"],
        )
        if result is not None:
            discovered.append(result)
        if gap is not None:
            gaps.append(gap)
    discovered.sort(key=lambda row: row["target_id"])
    gaps.sort(key=lambda row: row["target_id"])
    source_rows = [responses[date][1] for date in dates]
    source_map = {
        "schema_version": "1.0",
        "source_provider": "uk_sportinglife",
        "responses": source_rows,
    }
    source_map_body = (
        json.dumps(source_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    staged_events = _staged_events(
        events,
        discovered,
        plan_id=plan_id,
        shard_id=shard_id,
    )
    date_fragment = _date_fragment(
        input_identity,
        discovered,
        plan_id=plan_id,
        shard_id=shard_id,
    )
    summary = {
        "schema_version": "1.0",
        "source_provider": "uk_sportinglife",
        "selected_targets": len(events),
        "discovered_count": len(discovered),
        "gap_count": len(gaps),
        "unique_dates": len(dates),
        "input_identity": input_identity,
        "request_budget": request_budget,
        "source_map_sha256": _sha256_bytes(source_map_body),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    result_urls_path = output_dir / "sportinglife_result_urls.jsonl"
    gaps_path = output_dir / "sportinglife_url_discovery_gaps.jsonl"
    source_map_path = output_dir / "sportinglife_source_map.json"
    staged_events_path = output_dir / "staged-events.csv"
    date_fragment_path = output_dir / "sportinglife_date_fragment.json"
    _atomic_write_jsonl(result_urls_path, discovered)
    _atomic_write_jsonl(
        gaps_path,
        gaps,
    )
    _atomic_write_bytes(source_map_path, source_map_body)
    _atomic_write_csv(staged_events_path, STAGED_EVENT_FIELDS, staged_events)
    _atomic_write_json(date_fragment_path, date_fragment)
    summary["output_identities"] = {
        "date_fragment": _file_identity(date_fragment_path),
        "gaps": _file_identity(gaps_path),
        "result_urls": _file_identity(result_urls_path),
        "source_map": _file_identity(source_map_path),
        "staged_events": _file_identity(staged_events_path),
    }
    _atomic_write_json(
        output_dir / "sportinglife_url_discovery_summary.json",
        summary,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover Sporting Life historical result URLs for pending UK targets."
    )
    parser.add_argument("--pending-master-targets", required=True)
    parser.add_argument("--coverage-ledger", required=True)
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--shard-id", required=True)
    parser.add_argument(
        "--coverage-tiers",
        "--coverage-tier",
        nargs="+",
        default=["historical_hard", "new_formal"],
        dest="coverage_tiers",
    )
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()
    print(json.dumps(discover_urls(args), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
