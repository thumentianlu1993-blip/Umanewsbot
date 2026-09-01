#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from race_event_request_budget import before_network_request
from race_event_source_cache import write_source_cache_text

from bs4 import BeautifulSoup


WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "https://en.wikipedia.org/wiki/{title}"
USER_AGENT = "UmaFansBot/1.0 (+https://umafans.run; low-frequency history import)"


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_cell(value: str) -> str:
    value = re.sub(r"\[[^\]]+\]", "", value or "")
    value = value.replace("\xa0", " ")
    return _collapse(value)


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def _query_from_series(series_key: str, original_name: str) -> str:
    value = unicodedata.normalize("NFKC", original_name or "")
    value = value.replace("’", "'")
    value = re.sub(r"\bL\s*'\s*", "L'", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+-\s*", "-", value)
    value = re.sub(r"\bCHANTILL\s+Y\b", "CHANTILLY", value, flags=re.IGNORECASE)
    value = re.sub(r"\bL\s+YS\b", "LYS", value, flags=re.IGNORECASE)
    value = re.sub(r"\bO'REILL\s+Y\b", "O'REILLY", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*-\s*FONDS EUROPEEN DE L'?ELEVAGE.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+LONGINES$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+HONG KONG JOCKEY CLUB$", "", value, flags=re.IGNORECASE)
    for prefix in [
        "QATAR",
        "EMIRATES",
        "KRA",
        "DARLEY",
        "ARC",
        "SKY SPORTS RACING",
        "THE AGA KHAN STUDS",
        "LUCIEN BARRIERE",
        "RACING TV",
    ]:
        value = re.sub(rf"^{re.escape(prefix)}\s+", "", value, flags=re.IGNORECASE)
    match = re.search(r"\bPRIX\b.+$", value, flags=re.IGNORECASE)
    if match:
        value = match.group(0)
    value = re.sub(r"\s+", " ", value).strip()
    words = []
    for word in value.split():
        if word.upper() in {"DE", "DU", "DES", "LA", "LE", "LES", "D'"}:
            words.append(word.lower())
        elif word.upper().startswith("D'") and len(word) > 2:
            words.append("d'" + word[2:].capitalize())
        else:
            words.append(word.capitalize())
    return " ".join(words)


def _query_candidates(event: dict) -> list[str]:
    """Return bounded, deterministic discovery queries for one race series."""

    base = _query_from_series(
        str(event.get("series_key") or ""), str(event.get("original_name") or "")
    )
    region = str(event.get("country_region") or "")
    series_key = str(event.get("series_key") or "")
    expanded = re.sub(r"\bStp\b\.?", "Chase", base, flags=re.IGNORECASE)
    expanded = re.sub(r"\bS\.?\s*(?=\(|$)", "Stakes ", expanded, flags=re.IGNORECASE)
    specific = []
    if expanded != base:
        specific.append(expanded)
    if region == "france" and not re.match(r"^(Prix|Grand Prix)\b", base, re.IGNORECASE):
        specific.append(f"Prix {base}")
    if region == "united_states" and not re.search(
        r"\b(Stakes|Derby|Oaks|Cup|Handicap|Hurdle|Chase)\b", expanded, re.IGNORECASE
    ):
        specific.append(f"{expanded} Stakes")
    if region == "united_kingdom" and "gold-cup-ascot" in series_key:
        specific.append("Ascot Gold Cup")
    for racecourse in event.get("racecourse_aliases") or []:
        racecourse = _collapse(str(racecourse))
        if racecourse:
            specific.extend(
                [
                    f"{racecourse} {expanded}",
                    f"{expanded} {racecourse}",
                ]
            )
    values = specific + [base]
    values = [item for value in values for item in (value, f"{value} horse race")]
    return list(dict.fromkeys(_collapse(value) for value in values if _collapse(value)))


def _title_matches(title: str, aliases: list[str]) -> bool:
    title_norm = _norm(title)
    if not title_norm:
        return False
    for alias in aliases:
        alias = re.sub(r"\bhorse\s+race\b", "", alias, flags=re.IGNORECASE).strip()
        expected = _norm(alias)
        if expected and (title_norm == expected or expected in title_norm or title_norm in expected):
            return True
        ignored = {"and", "de", "des", "du", "et", "horse", "la", "le", "prix", "race", "s", "stakes", "the"}
        expected_tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9]+", unicodedata.normalize("NFKD", alias).encode("ascii", "ignore").decode("ascii"))
            if token.casefold() not in ignored
        }
        title_tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9]+", unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii"))
            if token.casefold() not in ignored
        }
        if expected_tokens and expected_tokens <= title_tokens:
            return True
    return False


def _search_result_matches(
    title: str, snippet: str, aliases: list[str], *, region: str = ""
) -> bool:
    """Match registered or historical race names to renamed Wikipedia pages.

    Wikipedia often stores a race under its current sponsored title while the
    calendar carries its registered or former title.  The fallback uses both
    the result title and snippet, but still requires a race-like page title so
    that a horse biography merely mentioning the race cannot be selected.
    """

    plain_snippet = BeautifulSoup(snippet or "", "lxml").get_text(" ", strip=True)

    def tokens(value: str) -> set[str]:
        return {
            token.casefold()
            for token in re.findall(
                r"[A-Za-z0-9]+",
                unicodedata.normalize("NFKD", value)
                .encode("ascii", "ignore")
                .decode("ascii"),
            )
        }

    title_tokens = tokens(title)
    searchable_tokens = tokens(f"{title} {plain_snippet}")
    race_title_signals = {
        "chase",
        "championship",
        "cup",
        "derby",
        "handicap",
        "hurdle",
        "memorial",
        "oaks",
        "prix",
        "stakes",
        "steeplechase",
        "trophy",
    }
    if not title_tokens.intersection(race_title_signals):
        return False
    region_signals = {
        "france": {"france", "french"},
        "ireland": {"ireland", "irish"},
        "united_kingdom": {
            "britain",
            "british",
            "england",
            "english",
            "scotland",
            "scottish",
            "united kingdom",
            "wales",
            "welsh",
        },
        "united_states": {"america", "american", "u s", "united states"},
    }
    geography_signals = {
        "america",
        "american",
        "argentina",
        "argentine",
        "australia",
        "australian",
        "britain",
        "british",
        "canada",
        "canadian",
        "france",
        "french",
        "germany",
        "german",
        "hong kong",
        "india",
        "indian",
        "england",
        "english",
        "ireland",
        "irish",
        "italian",
        "italy",
        "japan",
        "japanese",
        "new zealand",
        "scotland",
        "scottish",
        "south africa",
        "united kingdom",
        "united states",
        "united arab emirates",
        "wales",
        "welsh",
    }
    searchable_norm = _collapse(
        unicodedata.normalize("NFKD", f"{title} {plain_snippet}")
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    def has_signal(signal: str) -> bool:
        return bool(re.search(rf"\b{re.escape(signal)}\b", searchable_norm))

    desired_signals = region_signals.get(region, set())
    has_desired_region = any(has_signal(signal) for signal in desired_signals)
    conflicting_regions = geography_signals - desired_signals
    if any(has_signal(signal) for signal in conflicting_regions) and not has_desired_region:
        return False
    horse_race_context = any(
        has_signal(signal)
        for signal in {
            "horse race",
            "horse racing",
            "national hunt",
            "racehorse",
            "steeplechase",
            "thoroughbred",
        }
    )
    if not horse_race_context and not has_desired_region:
        return False
    if _title_matches(title, aliases):
        return True
    ignored = {
        "and",
        "de",
        "des",
        "du",
        "et",
        "horse",
        "la",
        "le",
        "prix",
        "race",
        "s",
        "stakes",
        "the",
    }
    for alias in aliases:
        alias = re.sub(r"\bhorse\s+race\b", "", alias, flags=re.IGNORECASE).strip()
        expected_tokens = tokens(alias) - ignored
        if len(expected_tokens) < 2:
            continue
        if expected_tokens <= searchable_tokens:
            return True
        overlap = len(expected_tokens.intersection(title_tokens))
        if overlap >= 2 and overlap / len(expected_tokens) >= 0.75:
            return True
    return False


def _request_text(url: str, cache_path: Path, *, allow_network: bool, timeout: int, sleep_seconds: float) -> str:
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace")
    if not allow_network:
        raise RuntimeError(f"缺少缓存且未允许网络请求：{cache_path}")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    before_network_request(url)
    with urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
    write_source_cache_text(cache_path, text, source_url=url)
    return text


def _cache_name(prefix: str, value: str, suffix: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return f"{prefix}_{key[-120:]}.{suffix}"


def _search_title(
    query: str,
    source_dir: Path,
    *,
    aliases: list[str],
    region: str,
    allow_network: bool,
    timeout: int,
    sleep_seconds: float,
) -> tuple[str, str]:
    url = f"{WIKI_API}?{urlencode({'action': 'query', 'list': 'search', 'srsearch': query, 'format': 'json', 'srlimit': 5})}"
    text = _request_text(url, source_dir / _cache_name("source_wiki_search", query, "json"), allow_network=allow_network, timeout=timeout, sleep_seconds=sleep_seconds)
    data = json.loads(text)
    best_title = ""
    for item in data.get("query", {}).get("search", []):
        title = item.get("title") or ""
        if _search_result_matches(
            title, item.get("snippet") or "", aliases, region=region
        ):
            best_title = title
            break
    if not best_title:
        return "", ""
    page_url = WIKI_PAGE.format(title=quote(best_title.replace(" ", "_")))
    return best_title, page_url


def _parse_winner_tables(html: str, *, page_url: str, min_year: int, max_year: int) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items: dict[int, dict] = {}
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [_clean_cell(cell.get_text(" ", strip=True)).lower() for cell in rows[0].find_all(["th", "td"])]
        if not headers:
            continue
        if "year" not in headers or "winner" not in headers:
            continue
        year_idx = headers.index("year")
        winner_idx = headers.index("winner")
        jockey_idx = headers.index("jockey") if "jockey" in headers else None
        trainer_idx = headers.index("trainer") if "trainer" in headers else None
        time_idx = headers.index("time") if "time" in headers else None
        for tr in rows[1:]:
            cells = [_clean_cell(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
            if len(cells) <= max(year_idx, winner_idx):
                continue
            year_match = re.search(r"\d{4}", cells[year_idx])
            if not year_match:
                continue
            year = int(year_match.group(0))
            if year < min_year or year > max_year:
                continue
            winner = cells[winner_idx]
            if not winner or "no race" in winner.lower() or "not run" in winner.lower():
                continue
            items[year] = {
                "winner_year": year,
                "horse_name": winner,
                "jockey_name": cells[jockey_idx] if jockey_idx is not None and len(cells) > jockey_idx else "",
                "trainer_name": cells[trainer_idx] if trainer_idx is not None and len(cells) > trainer_idx else "",
                "finish_time": cells[time_idx] if time_idx is not None and len(cells) > time_idx else "",
                "margin": "",
                "source_refs": {
                    "primary": page_url,
                    "source_language": "en",
                    "source_kind": "wikipedia_winners_table",
                },
            }
    return [items[year] for year in sorted(items, reverse=True)]


def _read_events(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _racecourse_aliases(
    path: Path, *, approved_sha256: str
) -> tuple[dict[str, list[str]], dict]:
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError("target ledger must be a regular non-symlink file")
    actual_sha = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", approved_sha256) or actual_sha != approved_sha256:
        raise ValueError("target ledger SHA-256 mismatch")
    aliases: dict[str, set[str]] = {}
    row_count = 0
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            series_key = str(row.get("series_key") or "")
            racecourse = _collapse(str(row.get("racecourse") or ""))
            if not series_key:
                raise ValueError(f"target ledger series key is missing at line {line_number}")
            if racecourse:
                aliases.setdefault(series_key, set()).add(racecourse)
            row_count += 1
    return {key: sorted(values) for key, values in aliases.items()}, {
        "path": str(resolved),
        "sha256": actual_sha,
        "size": resolved.stat().st_size,
        "rows": row_count,
    }


def _read_current_history(path: Path) -> dict[str, dict]:
    current: dict[str, dict] = {}
    if not path:
        return current
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            slug = record.get("slug") or ""
            items = ((record.get("modules") or {}).get("history_winners") or {}).get("items") or []
            if slug and items:
                current[slug] = record
    return current


def _materialize_current_source_page(
    record: dict, *, current_source_dir: Path, destination_source_dir: Path
) -> None:
    metadata = record.get("metadata") or {}
    title = str(metadata.get("wiki_title") or "")
    source_url = str(record.get("source_url") or "")
    filename = _cache_name("source_wiki_page", title, "html")
    manifest_path = current_source_dir / "source_cache_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("current Wikipedia source manifest is unreadable") from exc
    source_path = current_source_dir / filename
    identity = (manifest.get("files") or {}).get(filename)
    if (
        not title
        or not source_url.startswith("https://en.wikipedia.org/wiki/")
        or current_source_dir.is_symlink()
        or source_path.is_symlink()
        or not source_path.is_file()
        or manifest.get("schema_version") != "1.0"
        or Path(str(manifest.get("root") or "")).resolve() != current_source_dir.resolve()
        or not isinstance(identity, dict)
        or identity.get("source_url") != source_url
        or identity.get("size") != source_path.stat().st_size
        or identity.get("sha256")
        != hashlib.sha256(source_path.read_bytes()).hexdigest()
    ):
        raise ValueError("current Wikipedia source page identity drift")
    destination = destination_source_dir / filename
    destination_manifest_path = destination_source_dir / "source_cache_manifest.json"
    destination_manifest = None
    if destination_manifest_path.is_file() and not destination_manifest_path.is_symlink():
        try:
            destination_manifest = json.loads(
                destination_manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("destination Wikipedia source manifest is unreadable") from exc
    destination_identity = (
        (destination_manifest.get("files") or {}).get(filename)
        if isinstance(destination_manifest, dict)
        else None
    )
    if destination.exists() or destination.is_symlink() or destination_identity is not None:
        if (
            destination_source_dir.is_symlink()
            or destination.is_symlink()
            or not destination.is_file()
            or not isinstance(destination_manifest, dict)
            or destination_manifest.get("schema_version") != "1.0"
            or Path(str(destination_manifest.get("root") or "")).resolve()
            != destination_source_dir.resolve()
            or not isinstance(destination_identity, dict)
            or destination_identity.get("source_url") != source_url
            or destination_identity.get("size") != source_path.stat().st_size
            or destination_identity.get("sha256") != identity.get("sha256")
            or hashlib.sha256(destination.read_bytes()).hexdigest()
            != identity.get("sha256")
        ):
            raise ValueError("destination Wikipedia source page identity drift")
        return
    write_source_cache_text(
        destination,
        source_path.read_text(encoding="utf-8"),
        source_url=source_url,
    )


def _merge_items(wiki_items: list[dict], current_items: list[dict]) -> list[dict]:
    merged = {item["winner_year"]: item for item in wiki_items if item.get("winner_year")}
    for item in current_items:
        if item.get("winner_year"):
            merged[int(item["winner_year"])] = item
    return [merged[year] for year in sorted(merged, reverse=True)]


def prepare(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir)
    source_dir = output_dir / "sources"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(exist_ok=True)
    events = _read_events(Path(args.events_csv))
    target_ledger_value = str(getattr(args, "target_ledger", "") or "").strip()
    target_ledger_sha = str(
        getattr(args, "target_ledger_sha256", "") or ""
    ).strip()
    if bool(target_ledger_value) != bool(target_ledger_sha):
        raise ValueError("target ledger path and SHA-256 must be supplied together")
    target_ledger_identity = None
    if target_ledger_value:
        racecourses, target_ledger_identity = _racecourse_aliases(
            Path(target_ledger_value), approved_sha256=target_ledger_sha
        )
        for event in events:
            event["racecourse_aliases"] = racecourses.get(
                str(event.get("series_key") or ""), []
            )
    if args.limit:
        events = events[: args.limit]
    current_history = _read_current_history(Path(args.current_history_jsonl)) if args.current_history_jsonl else {}
    current_source_value = str(getattr(args, "current_source_dir", "") or "").strip()
    current_source_dir = Path(current_source_value)
    if current_history and (not current_source_value or not current_source_dir.is_dir()):
        raise ValueError("current history reuse requires its frozen source directory")

    jsonl_path = output_dir / "france_wikipedia_history_winner_candidates_2026.jsonl"
    review_path = output_dir / "france_wikipedia_history_winner_review_2026.csv"
    unmatched_path = output_dir / "france_wikipedia_history_winner_unmatched_2026.csv"
    summary = {
        "source": "wikipedia_winners_table",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(events),
        "events": 0,
        "history_items": 0,
        "events_without_history": 0,
        "events_skipped_partial": 0,
        "skipped": [],
        "errors": [],
        "target_ledger": target_ledger_identity,
    }
    review_rows = []
    unmatched_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for event in events:
            current_record = current_history.get(event["slug"])
            if current_record is not None:
                _materialize_current_source_page(
                    current_record,
                    current_source_dir=current_source_dir,
                    destination_source_dir=source_dir,
                )
                items = (
                    ((current_record.get("modules") or {}).get("history_winners") or {}).get(
                        "items"
                    )
                    or []
                )
                metadata = current_record.get("metadata") or {}
                title = str(metadata.get("wiki_title") or "")
                page_url = str(current_record.get("source_url") or "")
                jsonl.write(
                    json.dumps(current_record, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
                summary["events"] += 1
                summary["history_items"] += len(items)
                review_rows.append(
                    {
                        "slug": event["slug"],
                        "original_name": event.get("original_name", ""),
                        "history_count": len(items),
                        "first_year": min(item["winner_year"] for item in items),
                        "latest_year": max(item["winner_year"] for item in items),
                        "latest_winner": items[0]["horse_name"],
                        "wiki_title": title,
                        "source_url": page_url,
                    }
                )
                continue
            queries = _query_candidates(event)
            query = queries[0]
            diagnostics = []
            wiki_items = []
            title = ""
            page_url = ""
            selected_query = ""
            for candidate_query in queries:
                try:
                    candidate_title, candidate_url = _search_title(
                        candidate_query,
                        source_dir,
                        aliases=queries,
                        region=str(event.get("country_region") or ""),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                        sleep_seconds=args.sleep_seconds,
                    )
                    if not candidate_title:
                        raise RuntimeError("wikipedia_search_no_match")
                    html = _request_text(
                        candidate_url,
                        source_dir / _cache_name("source_wiki_page", candidate_title, "html"),
                        allow_network=args.allow_network,
                        timeout=args.timeout_seconds,
                        sleep_seconds=args.sleep_seconds,
                    )
                    candidate_items = _parse_winner_tables(
                        html, page_url=candidate_url, min_year=args.min_year, max_year=2026
                    )
                    if not candidate_items:
                        raise RuntimeError("wikipedia_winner_table_not_found")
                    title = candidate_title
                    page_url = candidate_url
                    selected_query = candidate_query
                    wiki_items = candidate_items
                    break
                except Exception as exc:
                    diagnostics.append(
                        {
                            "slug": event.get("slug"),
                            "query": candidate_query,
                            "error": str(exc),
                        }
                    )
            discovery_diagnostics = list(diagnostics)
            if not wiki_items:
                summary["errors"].extend(diagnostics)
            else:
                # Earlier discovery misses are expected bounded fallbacks, not
                # partial source failures once a complete winner table wins.
                diagnostics = []
            items = _merge_items(wiki_items, [])
            if not items:
                summary["events_without_history"] += 1
                unmatched_rows.append({"slug": event["slug"], "original_name": event.get("original_name", ""), "query": query, "wiki_title": title, "source_url": page_url})
                continue
            if diagnostics and not args.allow_partial_history:
                summary["events_skipped_partial"] += 1
                summary["skipped"].append(
                    {
                        "slug": event["slug"],
                        "reason": "partial_wikipedia_history",
                        "history_items": len(items),
                        "diagnostics": diagnostics,
                    }
                )
                continue
            record = {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": "wikipedia_winners_table",
                "source_url": page_url,
                "modules": {"history_winners": {"items": items}},
                "metadata": {
                    "source_kind": "wikipedia_winners_table",
                    "wiki_title": title,
                    "query": selected_query or query,
                    "attempted_queries": queries,
                    "partial_history": bool(diagnostics),
                    "diagnostics": diagnostics,
                    "discovery_diagnostics": discovery_diagnostics,
                },
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["history_items"] += len(items)
            review_rows.append(
                {
                    "slug": event["slug"],
                    "original_name": event.get("original_name", ""),
                    "history_count": len(items),
                    "first_year": min(item["winner_year"] for item in items),
                    "latest_year": max(item["winner_year"] for item in items),
                    "latest_winner": items[0]["horse_name"],
                    "wiki_title": title,
                    "source_url": page_url,
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "history_count", "first_year", "latest_year", "latest_winner", "wiki_title", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    with unmatched_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "query", "wiki_title", "source_url"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unmatched_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate France 2026 historical winner candidates from Wikipedia winners tables plus confirmed current winners.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--current-history-jsonl", default="")
    parser.add_argument("--current-source-dir", default="")
    parser.add_argument("--target-ledger", default="")
    parser.add_argument("--target-ledger-sha256", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-year", type=int, default=2020)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial-history", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    args = parser.parse_args()
    print(json.dumps(prepare(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
