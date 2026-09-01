#!/usr/bin/env python3
"""Prepare target-bound France Galop result occurrences from official bulletins.

The official bulletin index is the discovery authority: PDF URLs are never
guessed.  Result PDFs are cached with URL/SHA/size evidence and parsed in
two-column reading order.  A result is accepted only when the number of parsed
starter names exactly equals the bulletin's explicit ``N partants`` value.

Horse names emitted by this tool are lookup seeds, not canonical identities.
They may be used to search The Racing API and then bind stable ``hrs_*`` IDs,
but must never be merged into the horse database on name equality alone.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urljoin, urlparse, urlunparse


RESEARCH_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = Path(__file__).resolve().parents[1] / "tools"
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from race_event_request_budget import check_request_budget  # noqa: E402
from race_event_safe_http import fetch_https, validate_https_url  # noqa: E402
from race_event_source_cache import write_source_cache  # noqa: E402

from audit_legacy_historical_detail_bundle import (  # noqa: E402
    canonical_json,
    load_target_artifact,
    sha256_path,
)


SCHEMA_VERSION = "france-galop-bulletin-occurrence-proposal.v1"
OCCURRENCE_SCHEMA_VERSION = "graded-race-occurrence.v1"
SEED_SCHEMA_VERSION = "racing-api-horse-name-seed.v1"
INDEX_URL = "https://www.france-galop.com/fr/content/bulletins-officiels-valeurs"
ALLOWED_HOSTS = ("france-galop.com", "www.france-galop.com")
FRENCH_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}
FRENCH_WEEKDAY_RE = re.compile(
    r"^(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})(?:er)?\s+"
    r"(?P<month>janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[eé]cembre)\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
HEADER_RE = re.compile(
    r"^\s*(?P<race_number>\d{1,4})\s+(?P<race_code>\d{1,6})\s+"
    r"(?P<race_name>.+?)\s+(?P<distance>\d[\d ]{2,})\s*m\s*$",
    re.IGNORECASE,
)
# Flat bulletins normally use ``(Groupe I ...)`` while obstacle bulletins use
# ``(Haies - Groupe I)`` or ``(Steeple-Chase - Groupe III)``.  Keep the
# opening parenthesis in the contract so an unrelated prose reference to a
# Groupe race cannot silently become the grade of the preceding header.
GRADE_RE = re.compile(
    r"\(\s*(?:[^()\r\n]*?\s+-\s+)?Groupe\s+(?P<roman>III|II|I)\b",
    re.IGNORECASE,
)
PARTANTS_RE = re.compile(r"\b(?P<count>\d{1,2})\s+partants?\s*;", re.IGNORECASE)
STARTER_RE = re.compile(
    r"^\s*(?:(?:\d{1,5}\s+){0,2})(?P<horse_name>[^,]+?),\s*"
    r"(?P<sex>[fmh])\s*,",
    re.IGNORECASE,
)
AGE_ONLY_STARTER_RE = re.compile(
    r"^\s*(?:(?:\d{1,5}\s+){0,2})(?P<horse_name>[^,]+?),\s*"
    r"(?P<age>\d{1,2})\s+ans\b",
    re.IGNORECASE,
)
FINISH_MARKER_RE = re.compile(
    r"(?P<marker>\d{1,2}|[A-Z]{1,4}|[-–—])\s*$", re.IGNORECASE
)
BULLETIN_FILENAME_RE = re.compile(
    r"^(?P<year>(?:20)?\d{2})(?P<kind>plat|obst)_?(?P<issue>\d{1,2})"
    r"(?P<suffix>(?:_\d+)*)\.pdf$",
    re.IGNORECASE,
)
COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
PARSER_TOOL_PATH = Path(__file__).resolve()


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


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    body = "".join(canonical_json(row) + "\n" for row in rows).encode("utf-8")
    _atomic_write(path, body)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(character for character in normalized if not unicodedata.combining(character))
    ascii_text = ascii_text.replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", " ", ascii_text).strip().casefold()


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _fold(value)).strip()


def _race_core(value: str) -> str:
    core = re.sub(r"\([^)]*\)", " ", value or "")
    tokens = _key(core).split()
    while tokens and tokens[0] in {"prix", "grand"}:
        tokens.pop(0)
    return " ".join(tokens)


def _grade_from_roman(value: str) -> str:
    return {"I": "G1", "II": "G2", "III": "G3"}[value.upper()]


def _parse_french_date(line: str) -> date | None:
    match = DATE_RE.search(line)
    if match is None:
        return None
    month_key = _key(match.group("month"))
    try:
        return date(
            int(match.group("year")),
            FRENCH_MONTHS[month_key],
            int(match.group("day")),
        )
    except ValueError:
        return None


def _date_context_from_line(line: str) -> date | None:
    """Accept only page-header or standalone meeting-date lines."""

    parsed = _parse_french_date(line)
    if parsed is None:
        return None
    dash_count = sum(line.count(character) for character in ("-", "–", "—"))
    if dash_count >= 5:
        return parsed
    without_weekday = FRENCH_WEEKDAY_RE.sub("", line).strip()
    return parsed if DATE_RE.fullmatch(without_weekday) else None


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._current: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = str(dict(attrs).get("href") or "").strip()
        if href:
            self._current = {"href": href, "text": []}

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            self.links.append(
                {
                    "href": self._current["href"],
                    "text": re.sub(r"\s+", " ", " ".join(self._current["text"])).strip(),
                }
            )
            self._current = None


def discover_bulletin_urls(html: str, *, year: int, discipline: str) -> list[dict]:
    """Return regular official bulletin URLs for one result year.

    ``bis``, ``ter`` and other supplements are excluded because they contain
    code/rule updates rather than the regular result book.  Duplicate anchors
    collapse by URL; any issue number with competing regular URLs fails closed.
    """

    if discipline not in {"flat", "jumps"}:
        raise ValueError("discipline must be flat or jumps")
    parser = _IndexParser()
    parser.feed(html)
    expected_kind = "plat" if discipline == "flat" else "obst"
    candidates: dict[str, dict] = {}
    for link in parser.links:
        url = urljoin(INDEX_URL, link["href"])
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme in {"http", "https"} and host in ALLOWED_HOSTS:
            parsed = parsed._replace(scheme="https")
            url = urlunparse(parsed)
        filename = Path(unquote(parsed.path)).name
        match = BULLETIN_FILENAME_RE.fullmatch(filename)
        source_year = int(match.group("year")) if match is not None else 0
        if source_year < 100:
            source_year += 2000
        if (
            parsed.scheme != "https"
            or host not in ALLOWED_HOSTS
            or match is None
            or source_year != year
            or match.group("kind").casefold() != expected_kind
        ):
            continue
        candidates[url] = {
            "issue": int(match.group("issue")),
            "url": url,
            "filename": filename,
            "link_text": link["text"],
        }
    by_issue: dict[int, list[dict]] = defaultdict(list)
    for item in candidates.values():
        by_issue[item["issue"]].append(item)
    conflicts = {issue: rows for issue, rows in by_issue.items() if len(rows) != 1}
    if conflicts:
        raise ValueError(f"official bulletin index has ambiguous regular issues: {sorted(conflicts)}")
    results = [rows[0] for _, rows in sorted(by_issue.items())]
    if not results:
        raise ValueError("official bulletin index contains no matching regular bulletins")
    return results


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
        budget_label="France Galop bulletin",
    )
    body, _response = fetch_https(
        url,
        allowed_hosts=ALLOWED_HOSTS,
        timeout=timeout_seconds,
        headers={
            "User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency research capture)"
        },
    )
    write_source_cache(destination, body, source_url=url)
    return body


def _verify_cache_identity(source_dir: Path, source_path: Path, *, source_url: str) -> dict:
    if source_dir.is_symlink() or source_path.is_symlink() or not source_path.is_file():
        raise ValueError("source cache path is missing or unsafe")
    manifest_path = source_dir / "source_cache_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("source cache manifest is unreadable") from exc
    relative = str(source_path.resolve().relative_to(source_dir.resolve()))
    identity = (manifest.get("files") or {}).get(relative)
    if (
        manifest.get("schema_version") != "1.0"
        or Path(str(manifest.get("root") or "")).resolve() != source_dir.resolve()
        or not isinstance(identity, dict)
        or identity.get("source_url") != source_url
        or int(identity.get("size") or -1) != source_path.stat().st_size
        or identity.get("sha256") != sha256_path(source_path)
    ):
        raise ValueError("source cache identity is invalid or drifted")
    return {
        "cache_path": str(source_path.resolve()),
        "sha256": identity["sha256"],
        "size": identity["size"],
        "source_url": source_url,
        "cached_at": identity.get("cached_at"),
    }


def _reuse_frozen_sources(
    *,
    reuse_source_dir: Path,
    destination_source_dir: Path,
    year: int,
    discipline: str,
) -> None:
    configured = reuse_source_dir
    source_dir = configured.resolve(strict=True)
    if configured.is_symlink() or not source_dir.is_dir():
        raise ValueError("reuse source directory must be a regular non-symlink directory")
    if source_dir == destination_source_dir.resolve():
        raise ValueError("reuse source directory must differ from destination")
    source_index = source_dir / "bulletin-index.html"
    _verify_cache_identity(source_dir, source_index, source_url=INDEX_URL)
    write_source_cache(
        destination_source_dir / source_index.name,
        source_index.read_bytes(),
        source_url=INDEX_URL,
    )
    bulletins = discover_bulletin_urls(
        source_index.read_text(encoding="utf-8", errors="replace"),
        year=year,
        discipline=discipline,
    )
    for bulletin in bulletins:
        source_path = source_dir / bulletin["filename"]
        source_error = source_dir / f"{bulletin['filename']}.fetch-error.json"
        if source_path.is_file():
            _verify_cache_identity(
                source_dir, source_path, source_url=bulletin["url"]
            )
            write_source_cache(
                destination_source_dir / source_path.name,
                source_path.read_bytes(),
                source_url=bulletin["url"],
            )
            continue
        fetch_error = _load_persistent_fetch_error(
            source_error, source_url=bulletin["url"]
        )
        if fetch_error is None:
            raise ValueError(
                f"reused source cache is incomplete for official bulletin: {bulletin['url']}"
            )
        _atomic_write(
            destination_source_dir / source_error.name,
            (
                json.dumps(fetch_error, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8"),
        )


def _load_persistent_fetch_error(path: Path, *, source_url: str) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("source fetch-error evidence is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("source fetch-error evidence is unreadable") from exc
    if (
        payload.get("source_url") != source_url
        or int(payload.get("http_status") or 0) not in {404, 410}
        or not payload.get("observed_at")
    ):
        raise ValueError("source fetch-error evidence is invalid or drifted")
    return payload


def _write_persistent_fetch_error(
    path: Path, *, source_url: str, http_status: int, reason: str
) -> dict:
    if http_status not in {404, 410}:
        raise ValueError("only persistent missing-source responses may be cached")
    payload = {
        "source_url": source_url,
        "http_status": http_status,
        "reason": reason,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return payload


def _column_bboxes(width: float, height: float) -> list[tuple[str, tuple[float, ...]]]:
    """Return bulletin columns in publication reading order.

    Older bulletins store one portrait publication page per PDF page and need
    two columns.  Some 2024+ files store two portrait pages side by side on one
    landscape PDF page and therefore need four columns.  Treating the latter
    as two columns interleaves adjacent races and violates starter
    conservation.
    """

    column_count = 4 if width > height else 2
    column_width = width / column_count
    return [
        (
            f"column-{index + 1}-of-{column_count}",
            (index * column_width, 0, (index + 1) * column_width, height),
        )
        for index in range(column_count)
    ]


def extract_pdf_segments(pdf_path: Path) -> list[dict]:
    """Extract portrait or double-page bulletin columns in reading order."""

    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - environment-specific guard
        raise RuntimeError("pdfplumber is required to parse France Galop bulletins") from exc
    segments = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for column, bbox in _column_bboxes(page.width, page.height):
                text = page.crop(bbox).extract_text(x_tolerance=2, y_tolerance=3) or ""
                segments.append(
                    {"page_number": page_number, "column": column, "text": text}
                )
    return segments


def _line_records(segments: list[dict], *, known_courses: list[str]) -> list[dict]:
    records = []
    current_date: date | None = None
    current_course = ""
    course_keys = sorted(
        ((_fold(course), course) for course in set(known_courses) if course),
        key=lambda item: (-len(item[0]), item[0], item[1]),
        reverse=True,
    )
    for segment in segments:
        for raw_line in str(segment.get("text") or "").splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            parsed_date = _date_context_from_line(line)
            if parsed_date is not None:
                current_date = parsed_date
            line_key = _fold(line)
            for course_key, course in course_keys:
                if line_key == course_key or line_key.startswith(course_key + " "):
                    current_course = course
                    break
            records.append(
                {
                    "text": line,
                    "page_number": int(segment["page_number"]),
                    "column": str(segment["column"]),
                    "local_date": current_date.isoformat() if current_date else "",
                    "racecourse": current_course,
                }
            )
    return records


def _parse_starter_line(line: str, *, source_order: int) -> dict | None:
    # A wrapped runner can continue with e.g. ``57 k, h, Owner ... –``.  The
    # generic optional form-prefix expression would otherwise read ``k`` as a
    # one-letter horse name and ``h`` as the sex code.
    if re.match(
        r"^\s*\(?\d{1,3}(?:1/2)?\s*k\)?"
        r"(?:\s*\(\d{1,3}(?:1/2)?\s*k\))?\s*,\s*[fmh]\s*,",
        line,
        re.IGNORECASE,
    ):
        return None
    match = STARTER_RE.match(line)
    sex_code = ""
    if match is not None:
        sex_code = match.group("sex").lower()
    else:
        # France Galop's older flat bulletins sometimes omit the explicit
        # f/m/h token and start directly with ``<age> ans``.  Accept only that
        # bounded official form; downstream identity/profile data remains the
        # authority for sex rather than inferring it from race conditions.
        match = AGE_ONLY_STARTER_RE.match(line)
    if match is None:
        return None
    horse_name = re.sub(r"\s+", " ", match.group("horse_name")).strip()
    horse_name = re.sub(r"^(?:\d{1,5}\s+){1,2}", "", horse_name).strip()
    if not horse_name or _key(horse_name) in {"k", "kg"}:
        raise ValueError("official result contains an empty starter name")
    finish_match = FINISH_MARKER_RE.search(line)
    raw_marker = finish_match.group("marker").upper() if finish_match else ""
    finish_position = int(raw_marker) if raw_marker.isdigit() else None
    return {
        "source_order": source_order,
        "horse_name": horse_name,
        "horse_name_search": COUNTRY_SUFFIX_RE.sub("", horse_name).strip(),
        "sex_code": sex_code,
        "finish_position": finish_position,
        "finish_status": raw_marker or "unknown",
        "raw_first_line": line,
    }


def _target_matches_header(target: dict, *, race_name: str, grade: str, distance: int) -> bool:
    if target.get("grade_text") != grade:
        return False
    target_distance = re.sub(r"\D", "", str(target.get("distance_text") or ""))
    if target_distance and int(target_distance) != distance:
        return False
    target_core = _race_core(str(target.get("canonical_name_original") or target.get("original_name") or ""))
    source_core = _race_core(race_name)
    if not target_core or not source_core:
        return False
    target_tokens = set(target_core.split())
    source_tokens = set(source_core.split())
    return target_tokens.issubset(source_tokens) or source_tokens.issubset(target_tokens)


def parse_targeted_results(
    segments: list[dict],
    *,
    targets: list[dict],
    unresolved: list[dict] | None = None,
) -> list[dict]:
    """Parse target-bound Groupe results and enforce exact starter counts."""

    records = _line_records(
        segments,
        known_courses=[str(target.get("racecourse") or "") for target in targets],
    )
    results = []
    used_target_keys: set[str] = set()
    for header_index, record in enumerate(records):
        header_match = HEADER_RE.fullmatch(record["text"])
        if header_match is None:
            continue
        grade_match = None
        grade_index = None
        for offset in range(header_index + 1, min(header_index + 10, len(records))):
            grade_match = GRADE_RE.search(records[offset]["text"])
            if grade_match is not None:
                grade_index = offset
                break
        if grade_match is None or grade_index is None:
            continue
        grade = _grade_from_roman(grade_match.group("roman"))
        distance = int(re.sub(r"\s+", "", header_match.group("distance")))
        race_name = re.sub(r"\s+", " ", header_match.group("race_name")).strip()
        local_date = record["local_date"]
        if not local_date:
            raise ValueError(f"official result header has no date context: {race_name}")
        year = date.fromisoformat(local_date).year
        target_matches = [
            target
            for target in targets
            if int(target.get("year") or 0) == year
            and _target_matches_header(target, race_name=race_name, grade=grade, distance=distance)
        ]
        if not target_matches:
            continue
        if len(target_matches) != 1:
            source_core = _race_core(race_name)
            exact_matches = [
                target
                for target in target_matches
                if _race_core(
                    str(
                        target.get("canonical_name_original")
                        or target.get("original_name")
                        or ""
                    )
                )
                == source_core
            ]
            if len(exact_matches) != 1:
                raise ValueError(f"official result ambiguously matches targets: {race_name}")
            target = exact_matches[0]
        else:
            target = target_matches[0]
        target_key = str(target["target_key"])
        if target_key in used_target_keys:
            raise ValueError(f"target appears in more than one official result: {target_key}")

        partants_index = None
        partants_count = None
        next_header_index = len(records)
        for offset in range(header_index + 1, min(header_index + 500, len(records))):
            if offset > header_index + 1 and HEADER_RE.fullmatch(records[offset]["text"]):
                next_header_index = offset
                break
            count_match = PARTANTS_RE.search(records[offset]["text"])
            if count_match is not None:
                partants_index = offset
                partants_count = int(count_match.group("count"))
                break
        if partants_index is None or partants_count is None or partants_index >= next_header_index:
            if unresolved is None:
                raise ValueError(f"official result has no partants boundary: {race_name}")
            unresolved.append(
                {
                    "target_key": target_key,
                    "local_date": local_date,
                    "race_name": race_name,
                    "page_number": record["page_number"],
                    "column": record["column"],
                    "reason": "official_result_has_no_partants_boundary",
                    "interpretation": (
                        "not_selected_as_a_seed; target remains unresolved unless another "
                        "audited source supplies it"
                    ),
                }
            )
            continue

        starters = []
        for offset in range(grade_index + 1, partants_index):
            parsed = _parse_starter_line(records[offset]["text"], source_order=len(starters) + 1)
            if parsed is not None:
                starters.append(parsed)
        if len(starters) != partants_count:
            raise ValueError(
                f"official result starter conservation failed for {race_name}: "
                f"parsed={len(starters)} declared={partants_count}"
            )
        folded_names = [_key(starter["horse_name"]) for starter in starters]
        if len(set(folded_names)) != len(folded_names):
            raise ValueError(f"official result contains duplicate starter names: {race_name}")
        numeric_winners = [starter for starter in starters if starter["finish_position"] == 1]
        if len(numeric_winners) != 1:
            raise ValueError(f"official result must contain exactly one winner anchor: {race_name}")
        source_racecourse = record["racecourse"] or str(target.get("racecourse") or "")
        target_racecourse = str(target.get("racecourse") or "")
        racecourse_relation = (
            "matched_target_default"
            if _key(source_racecourse) == _key(target_racecourse)
            else "official_result_overrides_target_default"
        )
        used_target_keys.add(target_key)
        results.append(
            {
                "target_key": target_key,
                "series_key": target["series_key"],
                "edition_year": int(target["year"]),
                "local_date": local_date,
                "race_name": race_name,
                "racecourse": source_racecourse,
                "target_racecourse": target_racecourse,
                "racecourse_relation": racecourse_relation,
                "normalized_grade": grade,
                "distance_metres": distance,
                "race_number": header_match.group("race_number"),
                "race_code": header_match.group("race_code"),
                "page_number": record["page_number"],
                "column": record["column"],
                "actual_starter_count": partants_count,
                "winner": numeric_winners[0],
                "starters": starters,
            }
        )
    return sorted(results, key=lambda row: (row["local_date"], row["target_key"]))


def _require_resumable_output(output_dir: Path) -> None:
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError("output directory must be absent or a regular directory")
    if not output_dir.exists():
        return
    allowed_roots = {"sources", "request-budget.json", "request-budget.json.lock", "host-interval.json", "host-interval.json.lock"}
    for path in output_dir.iterdir():
        if path.name not in allowed_roots or path.is_symlink():
            raise ValueError("output directory contains non-resumable files")


def prepare_proposal(
    *,
    target_root: Path,
    year: int,
    discipline: str,
    output_dir: Path,
    allow_network: bool,
    timeout_seconds: int = 60,
    max_requests: int = 40,
    request_interval_seconds: float = 1.0,
    aqps_only: bool = False,
    reuse_source_dir: Path | None = None,
) -> dict:
    _require_resumable_output(output_dir)
    if year < 2000 or year > datetime.now(timezone.utc).year:
        raise ValueError("year is outside the supported research range")
    if timeout_seconds <= 0 or max_requests <= 0 or request_interval_seconds < 1.0:
        raise ValueError("network safety limits are invalid")
    target_rows, target_identity = load_target_artifact(target_root)
    targets = [
        row
        for row in target_rows
        if int(row.get("year") or 0) == year
        and row.get("country_region") == "france"
        and row.get("discipline") == discipline
        and (
            not aqps_only
            or row.get("source_scope") == "international_cataloguing_standards_aqps"
        )
    ]
    if not targets:
        raise ValueError("target artifact contains no matching France rows")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    if reuse_source_dir is not None:
        _reuse_frozen_sources(
            reuse_source_dir=reuse_source_dir,
            destination_source_dir=source_dir,
            year=year,
            discipline=discipline,
        )
    request_budget_path = output_dir / "request-budget.json"
    host_interval_path = output_dir / "host-interval.json"
    index_path = source_dir / "bulletin-index.html"
    index_body = _download(
        INDEX_URL,
        index_path,
        allow_network=allow_network,
        timeout_seconds=timeout_seconds,
        request_budget_path=request_budget_path,
        host_interval_path=host_interval_path,
        max_requests=max_requests,
        request_interval_seconds=request_interval_seconds,
    )
    index_identity = _verify_cache_identity(source_dir, index_path, source_url=INDEX_URL)
    bulletins = discover_bulletin_urls(
        index_body.decode("utf-8", errors="replace"), year=year, discipline=discipline
    )
    if len(bulletins) + (0 if index_path.is_file() else 1) > max_requests:
        raise ValueError("configured request budget cannot cover the discovered bulletin set")

    results = []
    source_identities = [index_identity]
    source_fetch_errors = []
    unresolved_official_results = []
    for bulletin in bulletins:
        bulletin_path = source_dir / bulletin["filename"]
        fetch_error_path = source_dir / f"{bulletin['filename']}.fetch-error.json"
        fetch_error = _load_persistent_fetch_error(
            fetch_error_path, source_url=bulletin["url"]
        )
        if fetch_error is not None:
            source_fetch_errors.append({**bulletin, **fetch_error})
            continue
        try:
            _download(
                bulletin["url"],
                bulletin_path,
                allow_network=allow_network,
                timeout_seconds=timeout_seconds,
                request_budget_path=request_budget_path,
                host_interval_path=host_interval_path,
                max_requests=max_requests,
                request_interval_seconds=request_interval_seconds,
            )
        except HTTPError as exc:
            if exc.code not in {404, 410}:
                raise
            fetch_error = _write_persistent_fetch_error(
                fetch_error_path,
                source_url=bulletin["url"],
                http_status=exc.code,
                reason=str(exc.reason or "official index link is unavailable"),
            )
            source_fetch_errors.append({**bulletin, **fetch_error})
            continue
        identity = _verify_cache_identity(
            source_dir, bulletin_path, source_url=bulletin["url"]
        )
        source_identities.append(identity)
        for parsed in parse_targeted_results(
            extract_pdf_segments(bulletin_path),
            targets=targets,
            unresolved=unresolved_official_results,
        ):
            parsed["source_evidence"] = {
                **identity,
                "source_provider": "france_galop",
                "source_authority": "organizer_official",
            }
            results.append(parsed)

    by_target: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        by_target[result["target_key"]].append(result)
    repeated_publications = []
    deduplicated_results = []
    for target_key, rows in sorted(by_target.items()):
        if len(rows) == 1:
            deduplicated_results.extend(rows)
            continue
        header_fields = (
            "local_date",
            "race_name",
            "racecourse",
            "normalized_grade",
            "distance_metres",
            "actual_starter_count",
        )
        header_identities = {
            canonical_json({field: row[field] for field in header_fields})
            for row in rows
        }
        winner_names = {row["winner"]["horse_name"] for row in rows}
        starter_name_sets = {
            tuple(sorted(starter["horse_name"] for starter in row["starters"]))
            for row in rows
        }
        if (
            len(header_identities) != 1
            or len(winner_names) != 1
            or len(starter_name_sets) != 1
        ):
            continue
        ordered = sorted(rows, key=lambda row: row["source_evidence"]["source_url"])
        selected = ordered[-1]
        deduplicated_results.append(selected)
        exact_rows_equal = len({canonical_json(row["starters"]) for row in rows}) == 1
        repeated_publications.append(
            {
                "target_key": target_key,
                "selected_source_url": selected["source_evidence"]["source_url"],
                "equivalent_source_urls": [
                    row["source_evidence"]["source_url"] for row in ordered
                ],
                "conservation": (
                    "exact_result_and_starter_rows_equal"
                    if exact_rows_equal
                    else "later_bulletin_correction_same_race_winner_and_starter_set"
                ),
            }
        )
        by_target[target_key] = [selected]
    duplicates = {key: rows for key, rows in by_target.items() if len(rows) != 1}
    if duplicates:
        raise ValueError(f"targets appear in multiple bulletin results: {sorted(duplicates)}")
    results = deduplicated_results

    occurrences = []
    seeds_by_name: dict[str, dict] = {}
    for parsed in sorted(results, key=lambda row: (row["local_date"], row["target_key"])):
        occurrence_key = (
            f"france:{parsed['local_date']}:france_galop:"
            f"{parsed['race_number']}:{parsed['race_code']}"
        )
        occurrence = {
            "schema_version": OCCURRENCE_SCHEMA_VERSION,
            "target_key": parsed["target_key"],
            "series_key": parsed["series_key"],
            "edition_year": parsed["edition_year"],
            "country_region": "france",
            "discipline": discipline,
            "normalized_grade": parsed["normalized_grade"],
            "occurrence_key": occurrence_key,
            "local_date": parsed["local_date"],
            "race_name": parsed["race_name"],
            "racecourse": parsed["racecourse"],
            "target_racecourse": parsed["target_racecourse"],
            "racecourse_relation": parsed["racecourse_relation"],
            "distance_metres": parsed["distance_metres"],
            "anchor_horse_name": parsed["winner"]["horse_name"],
            "source_status": "held",
            "actual_starter_count": parsed["actual_starter_count"],
            "source_evidence": parsed["source_evidence"],
            "source_locator": {
                "page_number": parsed["page_number"],
                "column": parsed["column"],
                "race_number": parsed["race_number"],
                "race_code": parsed["race_code"],
            },
            "starters": parsed["starters"],
        }
        occurrences.append(occurrence)
        for starter in parsed["starters"]:
            seed_key = _key(starter["horse_name"])
            seed = seeds_by_name.setdefault(
                seed_key,
                {
                    "schema_version": SEED_SCHEMA_VERSION,
                    "identity_status": "query_seed_only",
                    "country_region": "france",
                    "source_name_raw": starter["horse_name"],
                    "search_variants": sorted(
                        {starter["horse_name"], starter["horse_name_search"]}
                    ),
                    "occurrence_keys": [],
                    "target_keys": [],
                    "identity_rule": (
                        "resolve Racing API candidates, then bind stable hrs_* ID; "
                        "never merge by name equality"
                    ),
                },
            )
            seed["occurrence_keys"].append(occurrence_key)
            seed["target_keys"].append(parsed["target_key"])
    seeds = []
    for seed in seeds_by_name.values():
        seed["occurrence_keys"] = sorted(set(seed["occurrence_keys"]))
        seed["target_keys"] = sorted(set(seed["target_keys"]))
        seeds.append(seed)
    seeds.sort(key=lambda row: _key(row["source_name_raw"]))

    matched_target_keys = set(by_target)
    unmatched = [
        {
            "target_key": target["target_key"],
            "year": target["year"],
            "canonical_name_original": target.get("canonical_name_original"),
            "grade_text": target.get("grade_text"),
            "racecourse": target.get("racecourse"),
            "reason": "not_found_in_downloaded_official_result_bulletins",
        }
        for target in targets
        if target["target_key"] not in matched_target_keys
    ]
    unmatched.sort(key=lambda row: row["target_key"])

    occurrence_path = output_dir / "occurrences.jsonl"
    seed_path = output_dir / "horse-name-seeds.jsonl"
    unmatched_path = output_dir / "unmatched-targets.jsonl"
    _write_jsonl(occurrence_path, occurrences)
    _write_jsonl(seed_path, seeds)
    _write_jsonl(unmatched_path, unmatched)
    request_identity = None
    if request_budget_path.is_file():
        request_identity = {
            "path": request_budget_path.name,
            "sha256": sha256_path(request_budget_path),
            "size": request_budget_path.stat().st_size,
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "awaiting_target_and_identity_review",
        "completion_marker": "PREPARED",
        "approval": False,
        "database_writes": 0,
        "racing_api_requests": 0,
        "year": year,
        "discipline": discipline,
        "aqps_only": aqps_only,
        "target_artifact": target_identity,
        "target_artifact_reviewed_complete": target_identity["reviewed_complete"],
        "official_index": index_identity,
        "bulletins": {
            "discovered": len(bulletins),
            "cached_and_verified": len(source_identities) - 1,
            "persistent_fetch_errors": len(source_fetch_errors),
            "fetch_errors": source_fetch_errors,
            "sources": source_identities[1:],
        },
        "unresolved_official_results": unresolved_official_results,
        "repeated_official_publications": repeated_publications,
        "targets": {
            "in_scope": len(targets),
            "held_results": len(occurrences),
            "unmatched_or_not_due": len(unmatched),
        },
        "actual_starters": sum(row["actual_starter_count"] for row in occurrences),
        "unique_name_query_seeds": len(seeds),
        "outputs": {
            "occurrences": {
                "path": occurrence_path.name,
                "rows": len(occurrences),
                "sha256": sha256_path(occurrence_path),
                "size": occurrence_path.stat().st_size,
            },
            "horse_name_seeds": {
                "path": seed_path.name,
                "rows": len(seeds),
                "sha256": sha256_path(seed_path),
                "size": seed_path.stat().st_size,
            },
            "unmatched_targets": {
                "path": unmatched_path.name,
                "rows": len(unmatched),
                "sha256": sha256_path(unmatched_path),
                "size": unmatched_path.stat().st_size,
            },
        },
        "request_budget": request_identity,
        "parser": {
            "tool_path": str(PARSER_TOOL_PATH),
            "tool_sha256": sha256_path(PARSER_TOOL_PATH),
            "pdf_library": "pdfplumber",
            "pdf_library_version": importlib.metadata.version("pdfplumber"),
        },
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "review_required": [
            "resolve target-ledger source-count conflicts",
            "review unmatched targets against bulletin publication dates/cancellations",
            "resolve every horse-name seed to stable Racing API hrs_* candidates",
            "review homonyms and multilingual aliases before database apply",
        ],
    }
    manifest_path = output_dir / "proposal-manifest.json"
    _atomic_write(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "PREPARED", f"{sha256_path(manifest_path)}\n".encode("ascii"))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--discipline", required=True, choices=("flat", "jumps"))
    parser.add_argument("--output-dir", required=True, type=Path)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--allow-network", action="store_true")
    source_group.add_argument("--reuse-source-dir", type=Path)
    parser.add_argument("--aqps-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--max-requests", type=int, default=40)
    parser.add_argument("--request-interval-seconds", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = prepare_proposal(
        target_root=args.target_root,
        year=args.year,
        discipline=args.discipline,
        output_dir=args.output_dir,
        allow_network=args.allow_network,
        aqps_only=args.aqps_only,
        timeout_seconds=args.timeout_seconds,
        max_requests=args.max_requests,
        request_interval_seconds=args.request_interval_seconds,
        reuse_source_dir=args.reuse_source_dir,
    )
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
