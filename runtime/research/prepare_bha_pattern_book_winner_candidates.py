#!/usr/bin/env python3
"""Capture BHA-official Pattern Book winner anchors for 2021-2024 targets."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

RESEARCH_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = Path(__file__).resolve().parents[1] / "tools"
for path in (RESEARCH_ROOT, TOOLS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_legacy_historical_detail_bundle import (
    canonical_json,
    load_target_artifact,
    sha256_path,
)
from race_event_request_budget import check_request_budget
from race_event_safe_http import fetch_https, validate_https_url
from race_event_source_cache import write_source_cache

SCHEMA_VERSION = "bha-pattern-book-winner-candidate-proposal.v1"
CANDIDATE_SCHEMA = "bha-pattern-book-winner-candidate.v1"
UNMATCHED_SCHEMA = "bha-pattern-book-winner-unmatched.v1"
ALLOWED_HOSTS = ("media.britishhorseracing.com",)
SOURCE_SPECS = (
    {
        "discipline": "flat",
        "source_url": (
            "https://media.britishhorseracing.com/bha/Publications/2021_Flat_Pattern.pdf"
        ),
        "filename": "bha-flat-pattern-listed-2021.pdf",
        "book_edition": "2021",
    },
    {
        "discipline": "jumps",
        "source_url": (
            "https://media.britishhorseracing.com/bha/Publications/"
            "Pattern_Listed_Books/British_Jump_Pattern_Listed_20_21.pdf"
        ),
        "filename": "bha-jump-pattern-listed-2020-2021.pdf",
        "book_edition": "2020/2021",
    },
    {
        "discipline": "flat",
        "source_url": (
            "https://media.britishhorseracing.com/bha/Publications/"
            "Pattern_Listed_Books/2025_British_Flat_Pattern_Listed_Races.pdf"
        ),
        "filename": "bha-flat-pattern-listed-2025.pdf",
        "book_edition": "2025",
    },
    {
        "discipline": "jumps",
        "source_url": (
            "https://media.britishhorseracing.com/bha/Publications/"
            "Pattern_Listed_Books/British_Jump_Pattern_Listed_2526.pdf"
        ),
        "filename": "bha-jump-pattern-listed-2025-2026.pdf",
        "book_edition": "2025/2026",
    },
)
PAGE_MARKER_RE = re.compile(r"^\[\[BHA_PAGE_(\d{4})\]\]$", re.MULTILINE)
DATE_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"(?:\s+\([^)]+\))?,\s+"
    r"(?P<month>[A-Za-z]+)\s+\d{1,2}(?:st|nd|rd|th)$",
    re.IGNORECASE,
)
GRADE_RE = re.compile(r"\((?:Group|Grade)\s*([123])\)", re.IGNORECASE)
REGISTERED_RE = re.compile(
    r"^\(Registered as\s+(?:the\s+)?(.+?)\)\s*(?:\(|$)", re.IGNORECASE
)
FLAT_WINNER_RE = re.compile(
    r"^\*?(?P<year>20\d{2})\s+(?P<name>.+?)\s+\d{1,2}-\d{1,2}-\d{1,2}\s+"
)
JUMP_WINNER_RE = re.compile(
    r"^\*?(?P<start>20\d{2})/(?P<end>20\d{2})\s+"
    r"(?P<name>.+?)\s+\d{1,2}-\d{1,2}-\d{1,2}\s+"
)
COUNTRY_RE = re.compile(r"\s*\(\s*([A-Z]{2,3})\s*\)\s*$")
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
STOPWORDS = {
    "and",
    "as",
    "at",
    "class",
    "for",
    "grade",
    "group",
    "of",
    "race",
    "registered",
    "s",
    "stakes",
    "the",
    "trophy",
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
    text = re.sub(r"\bstp\.?\b", " steeple chase ", text)
    text = re.sub(r"\bnhf\b", " national hunt flat ", text)
    text = re.sub(r"\bnovices?\b", " novice ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _tokens(value: object) -> set[str]:
    return {token for token in _fold(value).split() if token not in STOPWORDS}


def _course_key(value: object) -> str:
    return "".join(
        token
        for token in _fold(value).split()
        if token not in {"park", "racecourse", "the"}
    )


def _name(value: str) -> tuple[str, str]:
    text = " ".join(value.split())
    match = COUNTRY_RE.search(text)
    if match is None:
        return text, ""
    return text[: match.start()].strip(), match.group(1)


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
        raise ValueError(
            f"BHA source cache is missing and network is disabled: {destination}"
        )
    check_request_budget(
        url,
        artifact_path=request_budget_path,
        host_interval_path=host_interval_path,
        max_requests=max_requests,
        interval=request_interval_seconds,
        budget_label="BHA official Pattern Books",
    )
    body, _response = fetch_https(
        url,
        allowed_hosts=ALLOWED_HOSTS,
        timeout=timeout_seconds,
        headers={
            "User-Agent": "umanewsbot/1.0 (+https://umafans.run; low-frequency result research)"
        },
    )
    if not body.startswith(b"%PDF"):
        raise ValueError("BHA Pattern Book response is not a PDF")
    write_source_cache(destination, body, source_url=url)
    return body


def _cache_identity(source_dir: Path, source_path: Path, *, source_url: str) -> dict:
    manifest = json.loads(
        (source_dir / "source_cache_manifest.json").read_text(encoding="utf-8")
    )
    relative = str(source_path.resolve().relative_to(source_dir.resolve()))
    identity = (manifest.get("files") or {}).get(relative)
    parsed = urlsplit(source_url)
    if (
        source_path.is_symlink()
        or not source_path.is_file()
        or parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or manifest.get("schema_version") != "1.0"
        or Path(str(manifest.get("root") or "")).resolve() != source_dir.resolve()
        or not isinstance(identity, Mapping)
        or identity.get("source_url") != source_url
        or identity.get("sha256") != sha256_path(source_path)
        or identity.get("size") != source_path.stat().st_size
    ):
        raise ValueError("BHA source cache identity drift")
    return {
        "cache_path": str(source_path.resolve()),
        "source_url": source_url,
        "sha256": identity["sha256"],
        "size": identity["size"],
        "cached_at": identity.get("cached_at"),
        "source_provider": "british_horseracing_authority",
        "source_authority": "organizer_official",
    }


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    parts = []
    for page_number, page in enumerate(PdfReader(path).pages, 1):
        parts.append(f"[[BHA_PAGE_{page_number:04d}]]\n{page.extract_text() or ''}")
    return "\n".join(parts)


def _scheduled_context(block: str) -> tuple[str, str, int]:
    lines = [" ".join(line.split()) for line in block.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        match = DATE_RE.fullmatch(line)
        if match is not None and index > 0:
            course = lines[index - 1]
            month = MONTHS[match.group("month").casefold()]
            return course, line, month
        if index == 0 or not re.match(
            r"^\*?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
            line,
            re.IGNORECASE,
        ):
            continue
        compact = re.sub(r"[^A-Za-z]", "", line).casefold()
        month_matches = [value for name, value in MONTHS.items() if name in compact]
        if len(month_matches) != 1:
            continue
        course = lines[index - 1]
        return course, line, month_matches[0]
    raise ValueError("BHA race block has no scheduled course/date context")


def _aliases(block: str) -> tuple[list[str], list[str], str]:
    lines = [" ".join(line.split()) for line in block.splitlines() if line.strip()]
    title = next((line for line in lines if re.match(r"^THE", line, re.IGNORECASE)), "")
    if not title:
        raise ValueError("BHA race block has no title")
    title = re.split(r"\s+\(CLASS\s+\d+\)", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = GRADE_RE.sub("", title).strip()
    title_alias = re.sub(r"^THE\s*", "", title, flags=re.IGNORECASE)
    registered_aliases = []
    for line in lines:
        match = REGISTERED_RE.match(line)
        if match is not None:
            registered_aliases.append(re.sub(r"\s*\(.*$", "", match.group(1)).strip())
    aliases = sorted({title_alias, *registered_aliases})
    return aliases, sorted(set(registered_aliases)) or [title_alias], title


def parse_pattern_book(
    text: str, *, discipline: str, source_evidence: dict
) -> list[dict]:
    starts = [
        match.start()
        for match in re.finditer(r"(?m)^(?:TO CLOSE BY NOON|CLOSED ON)", text)
    ]
    rows = []
    for block_number, start in enumerate(starts, 1):
        end = starts[block_number] if block_number < len(starts) else len(text)
        block = text[start:end]
        if "HORSE NAME AGE/WEIGHT" not in block:
            continue
        grade_match = GRADE_RE.search(block)
        if grade_match is None:
            continue
        course, scheduled_date, scheduled_month = _scheduled_context(block)
        aliases, match_aliases, published_title = _aliases(block)
        page_matches = list(PAGE_MARKER_RE.finditer(text, 0, start))
        page_number = int(page_matches[-1].group(1)) if page_matches else 0
        history = block.split("HORSE NAME AGE/WEIGHT", 1)[1]
        winners_by_year: dict[int, list[dict]] = {}
        for source_order, raw_line in enumerate(history.splitlines(), 1):
            line = " ".join(raw_line.split())
            if discipline == "flat":
                match = FLAT_WINNER_RE.match(line)
                edition_year = int(match.group("year")) if match else 0
                raw_name = match.group("name") if match else ""
                season = ""
            else:
                match = JUMP_WINNER_RE.match(line)
                start_year = int(match.group("start")) if match else 0
                end_year = int(match.group("end")) if match else 0
                edition_year = start_year if scheduled_month >= 7 else end_year
                raw_name = match.group("name") if match else ""
                season = f"{start_year}/{end_year}" if match else ""
            if match is None or not 2016 <= edition_year <= 2024:
                continue
            horse_name, country_suffix = _name(raw_name)
            winner = {
                "horse_name": horse_name,
                "horse_name_raw": raw_name,
                "source_order": source_order,
            }
            if country_suffix:
                winner["country_suffix"] = country_suffix
            if season:
                winner["source_season"] = season
            winners_by_year.setdefault(edition_year, []).append(winner)
        for edition_year, winners in sorted(winners_by_year.items()):
            rows.append(
                {
                    "edition_year": edition_year,
                    "discipline": discipline,
                    "normalized_grade": f"G{grade_match.group(1)}",
                    "racecourse": course,
                    "scheduled_date_in_book": scheduled_date,
                    "race_name": aliases[0],
                    "race_name_aliases": aliases,
                    "match_name_aliases": match_aliases,
                    "published_title": published_title,
                    "winner": winners[0],
                    "co_winners": winners,
                    "page_number": page_number,
                    "block_number": block_number,
                    "source_evidence": source_evidence,
                }
            )
    return rows


def _alias_score(result: dict, target: dict) -> tuple[float, int, bool]:
    target_aliases = [
        str(target.get("canonical_name_original") or ""),
        str(target.get("original_name") or ""),
    ]
    best = (0.0, 0, False)
    for source_alias in result["match_name_aliases"]:
        source_tokens = _tokens(source_alias)
        for target_alias in target_aliases:
            target_tokens = _tokens(target_alias)
            if not source_tokens or not target_tokens:
                continue
            overlap = len(source_tokens & target_tokens)
            score = max(overlap / len(target_tokens), overlap / len(source_tokens))
            best = max(best, (score, overlap, source_tokens == target_tokens))
    return best


def match_target(result: dict, targets: list[dict]) -> tuple[dict | None, list[dict]]:
    candidates = []
    for target in targets:
        if (
            int(target.get("year") or 0) != result["edition_year"]
            or target.get("country_region") != "united_kingdom"
            or target.get("discipline") != result["discipline"]
            or target.get("grade_text") != result["normalized_grade"]
        ):
            continue
        score, overlap, exact_tokens = _alias_score(result, target)
        course_match = _course_key(target.get("racecourse")) == _course_key(
            result["racecourse"]
        )
        if score >= 0.6 and (overlap >= 2 or exact_tokens):
            candidates.append(
                {
                    "target": target,
                    "score": score,
                    "overlap": overlap,
                    "exact_tokens": exact_tokens,
                    "course_match": course_match,
                }
            )
    candidates.sort(
        key=lambda row: (
            -row["score"],
            -row["overlap"],
            -int(row["exact_tokens"]),
            -int(row["course_match"]),
            str(row["target"]["target_key"]),
        )
    )
    diagnostics = [
        {
            "target_key": row["target"]["target_key"],
            "score": round(row["score"], 6),
            "overlap": row["overlap"],
            "exact_tokens": row["exact_tokens"],
            "scheduled_course_matches_target_default": row["course_match"],
        }
        for row in candidates
    ]
    if not candidates:
        return None, diagnostics
    if len(candidates) > 1:
        first = candidates[0]
        second = candidates[1]
        if (
            first["score"],
            first["overlap"],
            first["exact_tokens"],
            first["course_match"],
        ) == (
            second["score"],
            second["overlap"],
            second["exact_tokens"],
            second["course_match"],
        ):
            return None, diagnostics
    return candidates[0]["target"], diagnostics


def resolve_global_target_conflicts(
    matched: list[dict], unmatched: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Keep only a unique best source block for each exact target key."""

    by_target: dict[str, list[dict]] = {}
    for row in matched:
        by_target.setdefault(str(row["target_key"]), []).append(row)
    resolved = []
    for target_key, rows in sorted(by_target.items()):
        if len(rows) == 1:
            resolved.extend(rows)
            continue

        def confidence(row: dict) -> tuple[int, float, int, int]:
            diagnostic = next(
                item
                for item in row["match_diagnostics"]
                if item["target_key"] == target_key
            )
            return (
                int(bool(diagnostic["exact_tokens"])),
                float(diagnostic["score"]),
                int(diagnostic["overlap"]),
                int(bool(diagnostic["scheduled_course_matches_target_default"])),
            )

        ranked = sorted(
            rows,
            key=lambda row: (
                *[-value for value in confidence(row)],
                int(row["block_number"]),
            ),
        )
        best = confidence(ranked[0])
        best_rows = [row for row in ranked if confidence(row) == best]
        selected = best_rows[0] if len(best_rows) == 1 else None
        if selected is not None:
            resolved.append(selected)
        for row in rows:
            if row is selected:
                continue
            unmatched.append(
                {
                    **row,
                    "schema_version": UNMATCHED_SCHEMA,
                    "match_rejection": (
                        "duplicate_target_lower_confidence"
                        if selected is not None
                        else "duplicate_target_equal_confidence"
                    ),
                }
            )
    return resolved, unmatched


def _resumable(output_dir: Path) -> None:
    if output_dir.is_symlink() or (output_dir.exists() and not output_dir.is_dir()):
        raise ValueError("output directory must be absent or a regular directory")
    allowed = {
        "sources",
        "request-budget.json",
        "request-budget.json.lock",
        "host-interval.json",
        "host-interval.json.lock",
    }
    if output_dir.exists() and any(
        path.name not in allowed or path.is_symlink() for path in output_dir.iterdir()
    ):
        raise ValueError("output directory contains non-resumable files")


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    _resumable(output_dir)
    targets, target_identity = load_target_artifact(Path(args.target_root))
    targets = [
        row
        for row in targets
        if row.get("country_region") == "united_kingdom"
        and 2016 <= int(row.get("year") or 0) <= 2024
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "sources"
    source_dir.mkdir(exist_ok=True)
    budget_path = output_dir / "request-budget.json"
    interval_path = output_dir / "host-interval.json"
    official_results = []
    source_identities = []
    for spec in SOURCE_SPECS:
        path = source_dir / spec["filename"]
        _download(
            spec["source_url"],
            path,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout_seconds,
            request_budget_path=budget_path,
            host_interval_path=interval_path,
            max_requests=args.max_requests,
            request_interval_seconds=args.request_interval_seconds,
        )
        identity = {
            **_cache_identity(source_dir, path, source_url=spec["source_url"]),
            **spec,
        }
        source_identities.append(identity)
        official_results.extend(
            parse_pattern_book(
                extract_pdf_text(path),
                discipline=spec["discipline"],
                source_evidence=identity,
            )
        )
    matched = []
    unmatched = []
    for result in official_results:
        target, diagnostics = match_target(result, targets)
        if target is None:
            unmatched.append(
                {
                    "schema_version": UNMATCHED_SCHEMA,
                    **result,
                    "match_diagnostics": diagnostics,
                }
            )
            continue
        matched.append(
            {
                "schema_version": CANDIDATE_SCHEMA,
                "target_key": target["target_key"],
                "series_key": target["series_key"],
                "country_region": "united_kingdom",
                **result,
                "match_diagnostics": diagnostics,
            }
        )
    matched, unmatched = resolve_global_target_conflicts(matched, unmatched)
    keys = [row["target_key"] for row in matched]
    if len(keys) != len(set(keys)):
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        raise ValueError(f"BHA books matched one target more than once: {duplicates}")
    matched.sort(key=lambda row: row["target_key"])
    unmatched.sort(
        key=lambda row: (row["edition_year"], row["discipline"], row["block_number"])
    )
    matched_path = output_dir / "bha-pattern-book-winner-candidates.jsonl"
    unmatched_path = output_dir / "bha-pattern-book-winner-unmatched.jsonl"
    _atomic(
        matched_path, "".join(canonical_json(row) + "\n" for row in matched).encode()
    )
    _atomic(
        unmatched_path,
        "".join(canonical_json(row) + "\n" for row in unmatched).encode(),
    )
    outputs = {}
    for label, path, rows in (
        ("candidates", matched_path, matched),
        ("unmatched", unmatched_path, unmatched),
    ):
        outputs[label] = {
            "path": path.name,
            "rows": len(rows),
            "sha256": sha256_path(path),
            "size": path.stat().st_size,
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PROPOSED_NOT_APPROVED",
        "completion_marker": "PREPARED",
        "approval": False,
        "database_writes": 0,
        "racing_api_requests": 0,
        "target_artifact": target_identity,
        "sources": source_identities,
        "counts": {
            "target_rows_in_scope": len(targets),
            "official_winner_rows": len(official_results),
            "matched_targets": len(matched),
            "unmatched_official_rows": len(unmatched),
        },
        "outputs": outputs,
        "request_budget": {
            "path": budget_path.name,
            "sha256": sha256_path(budget_path),
            "size": budget_path.stat().st_size,
        },
        "parser": {
            "path": Path(__file__).name,
            "sha256": sha256_path(Path(__file__)),
            "pdf_library": "pypdf",
            "pdf_library_version": importlib.metadata.version("pypdf"),
        },
    }
    manifest_path = output_dir / "proposal-manifest.json"
    _atomic(
        manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
    _atomic(
        output_dir / "PREPARED", (sha256_path(manifest_path) + "\n").encode("ascii")
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--request-interval-seconds", type=float, default=1.25)
    return parser.parse_args()


def main() -> int:
    print(canonical_json(prepare(parse_args())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
