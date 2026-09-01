#!/usr/bin/env python3
"""Capture and target-match organizer-official HRI graded-race winners by date."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup


RESEARCH_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = Path(__file__).resolve().parents[1] / "tools"
for path in (RESEARCH_ROOT, TOOLS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_legacy_historical_detail_bundle import canonical_json, load_target_artifact, sha256_path
from race_event_request_budget import check_request_budget
from race_event_safe_http import fetch_https, validate_https_url
from race_event_source_cache import write_source_cache


SCHEMA_VERSION = "hri-graded-winner-candidate-proposal.v1"
CANDIDATE_SCHEMA = "hri-graded-winner-candidate.v1"
UNMATCHED_SCHEMA = "hri-graded-result-unmatched.v1"
FETCH_ERROR_SCHEMA = "hri-result-date-fetch-error.v1"
FETCH_ERROR_INTERPRETATION = (
    "source_unavailable_not_evidence_of_no_race; "
    "target remains unresolved unless another audited source supplies it"
)
RETRYABLE_HTTP_STATUSES = {404, 410, 500, 502, 503, 504}
BASE_URL = "https://www.hri.ie"
ALLOWED_HOSTS = ("hri.ie", "www.hri.ie")
GRADE_RE = re.compile(r"\((?:Grade|Group)\s*([123])\)", re.IGNORECASE)
COUNTRY_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
STOPWORDS = {
    "and", "at", "for", "grade", "group", "of", "race", "s", "stakes", "the",
}


def _atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fold(value: object) -> str:
    text = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    text = re.sub(r"\bstp\.?\b", " steeplechase ", text)
    text = re.sub(r"\bhcap\b", " handicap ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _tokens(value: object) -> set[str]:
    return {token for token in _fold(value).split() if token not in STOPWORDS}


def _course_key(value: object) -> str:
    tokens = [token for token in _fold(value).split() if token not in {"park", "the"}]
    return "".join(tokens)


def _horse_name(value: object) -> tuple[str, str]:
    text = " ".join(str(value or "").split())
    match = COUNTRY_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), match.group(1)


def _source_filename(day: date) -> str:
    return f"hri-results-{day.isoformat()}.html"


def _fetch_error_path(source_dir: Path, day: date) -> Path:
    return source_dir / f"hri-results-{day.isoformat()}.fetch-error.json"


def _load_fetch_error(path: Path, *, local_date: str, source_url: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("HRI fetch-error evidence must be a regular non-symlink file")
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("HRI fetch-error evidence is unreadable") from exc
    if not isinstance(row, dict):
        raise ValueError("HRI fetch-error evidence must be a JSON object")
    required_keys = {
        "schema_version",
        "local_date",
        "source_url",
        "http_status",
        "reason",
        "observed_at",
        "interpretation",
    }
    try:
        observed_at = datetime.fromisoformat(str(row.get("observed_at") or ""))
    except ValueError as exc:
        raise ValueError("HRI fetch-error observed_at is invalid") from exc
    if (
        set(row) != required_keys
        or row.get("schema_version") != FETCH_ERROR_SCHEMA
        or row.get("local_date") != local_date
        or row.get("source_url") != source_url
        or isinstance(row.get("http_status"), bool)
        or row.get("http_status") not in RETRYABLE_HTTP_STATUSES
        or not isinstance(row.get("reason"), str)
        or not row["reason"].strip()
        or observed_at.tzinfo is None
        or row.get("interpretation") != FETCH_ERROR_INTERPRETATION
    ):
        raise ValueError("HRI fetch-error evidence identity or schema drift")
    return row


def _write_fetch_error(
    path: Path,
    *,
    local_date: str,
    source_url: str,
    http_status: int,
    reason: str,
) -> dict:
    row = {
        "schema_version": FETCH_ERROR_SCHEMA,
        "local_date": local_date,
        "source_url": source_url,
        "http_status": http_status,
        "reason": reason,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "interpretation": FETCH_ERROR_INTERPRETATION,
    }
    _atomic(path, (canonical_json(row) + "\n").encode())
    return _load_fetch_error(path, local_date=local_date, source_url=source_url)


def _download(
    url: str,
    destination: Path,
    *,
    allow_network: bool,
    timeout_seconds: int,
    request_budget_path: Path,
    host_interval_path: Path,
    max_requests: int,
    request_interval_seconds: float,
) -> bytes:
    validate_https_url(url, allowed_hosts=ALLOWED_HOSTS)
    if destination.is_file():
        return destination.read_bytes()
    if not allow_network:
        raise ValueError(f"source cache is missing and network is disabled: {destination}")
    check_request_budget(
        url,
        artifact_path=request_budget_path,
        host_interval_path=host_interval_path,
        max_requests=max_requests,
        interval=request_interval_seconds,
        budget_label="HRI official graded results",
    )
    body, _response = fetch_https(
        url,
        allowed_hosts=ALLOWED_HOSTS,
        timeout=timeout_seconds,
        headers={
            "User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency result research)"
        },
    )
    write_source_cache(destination, body, source_url=url)
    return body


def _cache_identity(source_dir: Path, source_path: Path, *, source_url: str) -> dict:
    manifest_path = source_dir / "source_cache_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("HRI source cache manifest is unreadable") from exc
    relative = str(source_path.resolve().relative_to(source_dir.resolve()))
    identity = (manifest.get("files") or {}).get(relative)
    if (
        source_path.is_symlink()
        or not source_path.is_file()
        or manifest.get("schema_version") != "1.0"
        or Path(str(manifest.get("root") or "")).resolve() != source_dir.resolve()
        or not isinstance(identity, dict)
        or identity.get("source_url") != source_url
        or identity.get("sha256") != sha256_path(source_path)
        or identity.get("size") != source_path.stat().st_size
    ):
        raise ValueError("HRI source cache identity drift")
    return {
        "cache_path": str(source_path.resolve()),
        "source_url": source_url,
        "sha256": identity["sha256"],
        "size": identity["size"],
        "cached_at": identity.get("cached_at"),
        "source_provider": "horse_racing_ireland",
        "source_authority": "organizer_official",
    }


def _venue_codes(html: bytes) -> tuple[set[str], set[str]]:
    soup = BeautifulSoup(html, "lxml")
    course_names = {
        " ".join(node.get_text(" ", strip=True).split())
        for node in soup.select("p.h3")
        if node.get_text(" ", strip=True)
    }
    venue_codes = set()
    for link in soup.select(".race-result-item h2 a"):
        query = parse_qs(urlparse(str(link.get("href") or "")).query)
        venue_code = str((query.get("venue") or [""])[0]).upper()
        if venue_code:
            venue_codes.add(venue_code)
    return course_names, venue_codes


def infer_venue_course_map(source_paths: list[Path]) -> dict[str, str]:
    """Infer HRI venue codes only from single-meeting official date pages."""

    candidates: dict[str, set[str]] = {}
    observed_codes = set()
    for source_path in source_paths:
        course_names, venue_codes = _venue_codes(source_path.read_bytes())
        observed_codes.update(venue_codes)
        if len(course_names) == 1 and len(venue_codes) == 1:
            venue_code = next(iter(venue_codes))
            candidates.setdefault(venue_code, set()).update(course_names)
    conflicts = {
        venue_code: sorted(course_names)
        for venue_code, course_names in candidates.items()
        if len(course_names) != 1
    }
    missing = sorted(observed_codes - set(candidates))
    if conflicts or missing:
        raise ValueError(
            f"HRI venue/course inference is incomplete: conflicts={conflicts} missing={missing}"
        )
    return {
        venue_code: next(iter(candidates[venue_code]))
        for venue_code in sorted(candidates)
    }


def parse_date_page(
    html: bytes,
    *,
    local_date: str,
    source_evidence: dict,
    venue_course_map: Mapping[str, str] | None = None,
) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()
    for item in soup.select(".race-result-item"):
        title_link = item.select_one("h2 a")
        if title_link is None:
            continue
        race_name = " ".join(title_link.get_text(" ", strip=True).split())
        grade_match = GRADE_RE.search(race_name)
        if grade_match is None:
            continue
        result_href = str(title_link.get("href") or "")
        result_url = urljoin(BASE_URL, result_href)
        validate_https_url(result_url, allowed_hosts=ALLOWED_HOSTS)
        if venue_course_map is None:
            course_node = item.find_previous("p", class_="h3")
            racecourse = (
                " ".join(course_node.get_text(" ", strip=True).split())
                if course_node is not None
                else ""
            )
        else:
            result_query = parse_qs(urlparse(result_url).query)
            venue_code = str((result_query.get("venue") or [""])[0]).upper()
            racecourse = str(venue_course_map.get(venue_code) or "")
        if not racecourse:
            raise ValueError(f"HRI graded result has no racecourse: {local_date} {race_name}")
        placings = []
        for tr in item.select("tbody tr"):
            cells = [" ".join(td.get_text(" ", strip=True).split()) for td in tr.select("td")]
            if len(cells) < 4:
                continue
            position_match = re.match(r"(\d+)", cells[0])
            horse_raw = cells[3]
            if position_match is None or not horse_raw:
                continue
            horse, country_suffix = _horse_name(horse_raw)
            placing = {
                "finish_position": int(position_match.group(1)),
                "horse_name": horse,
                "horse_name_raw": horse_raw,
            }
            if country_suffix:
                placing["country_suffix"] = country_suffix
            placings.append(placing)
        winners = [row for row in placings if row["finish_position"] == 1]
        identity = (local_date, result_url)
        if identity in seen or len(winners) != 1:
            raise ValueError(f"HRI graded result winner/identity conservation failed: {identity}")
        seen.add(identity)
        results.append(
            {
                "local_date": local_date,
                "edition_year": int(local_date[:4]),
                "racecourse": racecourse,
                "race_name": race_name,
                "normalized_grade": f"G{grade_match.group(1)}",
                "result_url": result_url,
                "winner": winners[0],
                "published_placings": placings,
                "source_evidence": source_evidence,
            }
        )
    return results


def _alias_score(race_name: str, alias: str) -> tuple[float, int]:
    race_tokens = _tokens(GRADE_RE.sub(" ", race_name))
    alias_tokens = _tokens(alias)
    if not race_tokens or not alias_tokens:
        return 0.0, 0
    overlap = len(race_tokens & alias_tokens)
    coverage = max(overlap / len(race_tokens), overlap / len(alias_tokens))
    sequence = SequenceMatcher(None, _fold(race_name), _fold(alias)).ratio()
    return max(coverage, sequence), overlap


def _target_candidates(result: dict, targets: list[dict]) -> list[dict]:
    candidates = []
    for target in targets:
        if (
            int(target.get("year") or 0) != result["edition_year"]
            or target.get("country_region") != "ireland"
            or target.get("grade_text") != result["normalized_grade"]
            or _course_key(target.get("racecourse")) != _course_key(result["racecourse"])
        ):
            continue
        aliases = [
            str(target.get("canonical_name_original") or ""),
            str(target.get("original_name") or ""),
        ]
        score, overlap = max((_alias_score(result["race_name"], alias) for alias in aliases))
        if overlap >= 2 and score >= 0.5:
            candidates.append(
                {
                    "target": target,
                    "score": round(score, 6),
                    "overlap": overlap,
                }
            )
    candidates.sort(
        key=lambda row: (-row["score"], -row["overlap"], str(row["target"]["target_key"]))
    )
    return candidates


def _candidate_diagnostics(candidates: list[dict]) -> list[dict]:
    return [
        {
            "target_key": row["target"]["target_key"],
            "score": row["score"],
            "overlap": row["overlap"],
        }
        for row in candidates
    ]


def match_target(result: dict, targets: list[dict]) -> tuple[dict | None, list[dict]]:
    candidates = _target_candidates(result, targets)
    diagnostics = _candidate_diagnostics(candidates)
    if not candidates:
        return None, diagnostics
    if len(candidates) > 1 and (
        candidates[0]["score"] - candidates[1]["score"] < 0.05
        and candidates[0]["overlap"] <= candidates[1]["overlap"]
    ):
        return None, diagnostics
    return candidates[0]["target"], diagnostics


def _hungarian_max(weights: list[list[int]]) -> tuple[list[int], int]:
    """Return the maximum-weight column assignment for a rectangular matrix."""

    if not weights:
        return [], 0
    row_count = len(weights)
    column_count = len(weights[0])
    if column_count < row_count or any(len(row) != column_count for row in weights):
        raise ValueError("HRI assignment matrix is invalid")
    maximum = max(max(row) for row in weights)
    costs = [[maximum - value for value in row] for row in weights]
    u = [0] * (row_count + 1)
    v = [0] * (column_count + 1)
    matching = [0] * (column_count + 1)
    way = [0] * (column_count + 1)
    for row_index in range(1, row_count + 1):
        matching[0] = row_index
        minimum = [10**30] * (column_count + 1)
        used = [False] * (column_count + 1)
        column = 0
        while True:
            used[column] = True
            active_row = matching[column]
            delta = 10**30
            next_column = 0
            for candidate_column in range(1, column_count + 1):
                if used[candidate_column]:
                    continue
                current = (
                    costs[active_row - 1][candidate_column - 1]
                    - u[active_row]
                    - v[candidate_column]
                )
                if current < minimum[candidate_column]:
                    minimum[candidate_column] = current
                    way[candidate_column] = column
                if minimum[candidate_column] < delta:
                    delta = minimum[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(column_count + 1):
                if used[candidate_column]:
                    u[matching[candidate_column]] += delta
                    v[candidate_column] -= delta
                else:
                    minimum[candidate_column] -= delta
            column = next_column
            if matching[column] == 0:
                break
        while True:
            previous = way[column]
            matching[column] = matching[previous]
            column = previous
            if column == 0:
                break
    assignment = [-1] * row_count
    for column in range(1, column_count + 1):
        if matching[column]:
            assignment[matching[column] - 1] = column - 1
    return assignment, sum(weights[row][column] for row, column in enumerate(assignment))


def assign_targets_globally(
    results: list[dict], targets: list[dict]
) -> tuple[list[tuple[dict, dict, list[dict]]], list[tuple[dict, list[dict]]]]:
    """Resolve same-meeting sponsored-name collisions by unique global assignment."""

    grouped: dict[tuple[int, str, str], list[tuple[dict, list[dict]]]] = {}
    unmatched = []
    for result in results:
        candidates = _target_candidates(result, targets)
        diagnostics = _candidate_diagnostics(candidates)
        if not candidates:
            unmatched.append((result, diagnostics))
            continue
        key = (
            int(result["edition_year"]),
            str(result["normalized_grade"]),
            _course_key(result["racecourse"]),
        )
        grouped.setdefault(key, []).append((result, candidates))

    matched = []
    match_bonus = 10**12
    forbidden = -(10**15)
    # Require more than a five-point aggregate alias-score advantage.  The
    # small overlap suffix is only a deterministic tie-break and must not turn
    # an exact 0.05 boundary into an approved identity.
    minimum_margin = 5_000_100
    for key in sorted(grouped):
        rows = grouped[key]
        target_by_key = {
            str(candidate["target"]["target_key"]): candidate["target"]
            for _result, candidates in rows
            for candidate in candidates
        }
        target_keys = sorted(target_by_key)
        target_index = {target_key: index for index, target_key in enumerate(target_keys)}
        weights = []
        candidate_maps = []
        for _result, candidates in rows:
            candidate_map = {
                str(candidate["target"]["target_key"]): candidate
                for candidate in candidates
            }
            candidate_maps.append(candidate_map)
            row_weights = [forbidden] * len(target_keys)
            for target_key, candidate in candidate_map.items():
                row_weights[target_index[target_key]] = (
                    match_bonus
                    + int(round(float(candidate["score"]) * 1_000_000)) * 100
                    + int(candidate["overlap"])
                )
            row_weights.extend([0] * len(rows))
            weights.append(row_weights)
        assignment, best_score = _hungarian_max(weights)
        assigned_edges = [
            (row_index, column)
            for row_index, column in enumerate(assignment)
            if column < len(target_keys) and weights[row_index][column] > 0
        ]
        edge_margins = {}
        for row_index, column in assigned_edges:
            alternative = [list(values) for values in weights]
            alternative[row_index][column] = forbidden
            _alternative_assignment, alternative_score = _hungarian_max(alternative)
            edge_margins[(row_index, column)] = best_score - alternative_score
        accepted_edges = [
            edge
            for edge in assigned_edges
            if edge_margins[edge] >= minimum_margin
        ]
        assigned_rows = {row_index for row_index, _column in accepted_edges}
        for row_index, column in accepted_edges:
            target_key = target_keys[column]
            candidate = candidate_maps[row_index][target_key]
            matched.append(
                (
                    rows[row_index][0],
                    candidate["target"],
                    _candidate_diagnostics(rows[row_index][1]),
                )
            )
        unmatched.extend(
            (rows[row_index][0], _candidate_diagnostics(rows[row_index][1]))
            for row_index in range(len(rows))
            if row_index not in assigned_rows
        )
    return matched, unmatched


def _require_resumable(output_dir: Path) -> None:
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError("output directory must be absent or a regular directory")
    if not output_dir.exists():
        return
    allowed = {
        "sources", "request-budget.json", "request-budget.json.lock",
        "host-interval.json", "host-interval.json.lock",
    }
    if any(path.name not in allowed or path.is_symlink() for path in output_dir.iterdir()):
        raise ValueError("output directory contains non-resumable files")


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    _require_resumable(output_dir)
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if start > end or start.year < 2000 or end >= date.today():
        raise ValueError("date range is invalid or includes today/future")
    day_count = (end - start).days + 1
    if day_count > args.max_requests:
        raise ValueError("request ceiling cannot cover the requested date range")
    target_rows, target_identity = load_target_artifact(Path(args.target_root))
    targets = [
        row
        for row in target_rows
        if row.get("country_region") == "ireland"
        and start.year <= int(row.get("year") or 0) <= end.year
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    reuse_source_dir = None
    if getattr(args, "reuse_source_dir", None):
        configured = Path(args.reuse_source_dir)
        reuse_source_dir = configured.resolve(strict=True)
        if configured.is_symlink() or not reuse_source_dir.is_dir():
            raise ValueError("reuse source directory must be a regular non-symlink directory")
    request_budget = output_dir / "request-budget.json"
    host_interval = output_dir / "host-interval.json"
    matched = []
    unmatched = []
    all_results = []
    fetch_errors = []
    verified_pages = []
    cursor = start
    while cursor <= end:
        source_url = f"{BASE_URL}/results?date={cursor.isoformat()}"
        source_path = source_dir / _source_filename(cursor)
        fetch_error_path = _fetch_error_path(source_dir, cursor)
        if not source_path.is_file() and (
            fetch_error_path.exists() or fetch_error_path.is_symlink()
        ):
            fetch_errors.append(
                _load_fetch_error(
                    fetch_error_path,
                    local_date=cursor.isoformat(),
                    source_url=source_url,
                )
            )
            cursor += timedelta(days=1)
            continue
        if not source_path.is_file() and reuse_source_dir is not None:
            reused_source_path = reuse_source_dir / _source_filename(cursor)
            reused_error_path = _fetch_error_path(reuse_source_dir, cursor)
            if reused_source_path.is_file() or reused_source_path.is_symlink():
                source = _cache_identity(
                    reuse_source_dir,
                    reused_source_path,
                    source_url=source_url,
                )
                verified_pages.append(
                    {
                        "local_date": cursor.isoformat(),
                        "source_path": reused_source_path,
                        "source_evidence": source,
                    }
                )
                cursor += timedelta(days=1)
                continue
            if reused_error_path.exists() or reused_error_path.is_symlink():
                row = _load_fetch_error(
                    reused_error_path,
                    local_date=cursor.isoformat(),
                    source_url=source_url,
                )
                _atomic(fetch_error_path, (canonical_json(row) + "\n").encode())
                fetch_errors.append(row)
                cursor += timedelta(days=1)
                continue
        try:
            body = _download(
                source_url,
                source_path,
                allow_network=args.allow_network,
                timeout_seconds=args.timeout_seconds,
                request_budget_path=request_budget,
                host_interval_path=host_interval,
                max_requests=args.max_requests,
                request_interval_seconds=args.request_interval_seconds,
            )
        except HTTPError as exc:
            if exc.code not in RETRYABLE_HTTP_STATUSES:
                raise
            fetch_errors.append(
                _write_fetch_error(
                    fetch_error_path,
                    local_date=cursor.isoformat(),
                    source_url=source_url,
                    http_status=exc.code,
                    reason=str(exc.reason or "HRI date page unavailable"),
                )
            )
            cursor += timedelta(days=1)
            continue
        source = _cache_identity(source_dir, source_path, source_url=source_url)
        verified_pages.append(
            {
                "local_date": cursor.isoformat(),
                "source_path": source_path,
                "source_evidence": source,
            }
        )
        cursor += timedelta(days=1)
    venue_course_map = infer_venue_course_map(
        [row["source_path"] for row in verified_pages]
    )
    for page in verified_pages:
        for result in parse_date_page(
            page["source_path"].read_bytes(),
            local_date=page["local_date"],
            source_evidence=page["source_evidence"],
            venue_course_map=venue_course_map,
        ):
            all_results.append(result)
    assignments, unmatched_results = assign_targets_globally(all_results, targets)
    for result, target, diagnostics in assignments:
        matched.append(
            {
                "schema_version": CANDIDATE_SCHEMA,
                "target_key": target["target_key"],
                "series_key": target["series_key"],
                "country_region": "ireland",
                "discipline": target["discipline"],
                **result,
                "match_diagnostics": diagnostics,
            }
        )
    for result, diagnostics in unmatched_results:
        unmatched.append(
            {
                "schema_version": UNMATCHED_SCHEMA,
                **result,
                "match_diagnostics": diagnostics,
            }
        )
    target_keys = [row["target_key"] for row in matched]
    if len(target_keys) != len(set(target_keys)):
        duplicates = sorted(key for key, count in Counter(target_keys).items() if count > 1)
        raise ValueError(f"HRI results matched one target more than once: {duplicates}")
    matched.sort(key=lambda row: row["target_key"])
    unmatched.sort(key=lambda row: (row["local_date"], row["result_url"]))
    candidates_path = output_dir / "hri-graded-winner-candidates.jsonl"
    unmatched_path = output_dir / "hri-graded-result-unmatched.jsonl"
    fetch_errors_path = output_dir / "hri-result-date-fetch-errors.jsonl"
    _atomic(candidates_path, "".join(canonical_json(row) + "\n" for row in matched).encode())
    _atomic(unmatched_path, "".join(canonical_json(row) + "\n" for row in unmatched).encode())
    _atomic(
        fetch_errors_path,
        "".join(canonical_json(row) + "\n" for row in fetch_errors).encode(),
    )
    identities = {}
    for key, path, rows in (
        ("candidates", candidates_path, matched),
        ("unmatched", unmatched_path, unmatched),
        ("fetch_errors", fetch_errors_path, fetch_errors),
    ):
        identities[key] = {
            "path": path.name,
            "rows": len(rows),
            "sha256": sha256_path(path),
            "size": path.stat().st_size,
        }
    request_identity = None
    if request_budget.is_file():
        request_identity = {
            "path": request_budget.name,
            "sha256": sha256_path(request_budget),
            "size": request_budget.stat().st_size,
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PROPOSED_NOT_APPROVED",
        "completion_marker": "PREPARED",
        "approval": False,
        "database_writes": 0,
        "racing_api_requests": 0,
        "date_range": {"start": start.isoformat(), "end": end.isoformat(), "days": day_count},
        "target_artifact": target_identity,
        "counts": {
            "official_graded_results": len(all_results),
            "matched_targets": len(matched),
            "unmatched_official_results": len(unmatched),
            "target_rows_in_scope": len(targets),
            "date_pages_unavailable": len(fetch_errors),
            "date_pages_verified": day_count - len(fetch_errors),
        },
        "outputs": identities,
        "request_budget": request_identity,
        "venue_course_map": venue_course_map,
        "reuse_source_root": str(reuse_source_dir) if reuse_source_dir else None,
        "generator": {"path": Path(__file__).name, "sha256": sha256_path(Path(__file__))},
    }
    manifest_path = output_dir / "proposal-manifest.json"
    _atomic(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )
    _atomic(output_dir / "PREPARED", (sha256_path(manifest_path) + "\n").encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-requests", type=int, default=2000)
    parser.add_argument("--request-interval-seconds", type=float, default=1.25)
    parser.add_argument("--reuse-source-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    manifest = prepare(parse_args())
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
