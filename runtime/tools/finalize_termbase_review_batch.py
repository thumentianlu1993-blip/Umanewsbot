from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = [
    "term_type",
    "source_language",
    "racing_region",
    "source_ja",
    "target_zh",
    "aliases_ja",
    "aliases_zh",
    "priority",
    "is_active",
    "notes",
    "race_grade",
]
ALIAS_HEADERS = [
    "term_type",
    "primary_source_language",
    "primary_source_ja",
    "alias_language",
    "alias_text",
    "target_zh",
    "racing_region",
    "alias_source",
    "confidence",
    "notes",
]

COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Z]{2,4}\)\s*$")
YEAR_MARKER_RE = re.compile(
    r"\(\s*(?:(?:~|-)\s*)?\d{4}(?:\s*[,~\-]\s*(?:\d{2,4})?)*\s*\)"
    r"|\(\s*(?:Reg\.|Ex\.|Replaced)\s*\)",
    re.I,
)
NETKEIBA_SEARCH_URL = "https://db.netkeiba.com/?pid=horse_list&word={query}"


@dataclass
class LookupResult:
    japanese_name: str
    source_url: str
    confidence: str
    reason: str


def norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def identity(value: str) -> str:
    value = norm_text(value)
    value = re.sub(r"[^0-9A-Za-z\u3040-\u30ff\u4e00-\u9fff]+", "", value)
    return value.casefold()


def clean_horse_source(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", norm_text(value)).strip()


def clean_general(value: str) -> str:
    return norm_text(value)


def clean_year_markers(value: str) -> str:
    value = YEAR_MARKER_RE.sub("", norm_text(value))
    return re.sub(r"\s+", " ", value).strip()


def split_year_marked_pair(source: str, target: str) -> tuple[list[tuple[str, str]], str]:
    source = norm_text(source)
    target = norm_text(target)
    if not YEAR_MARKER_RE.search(source) and not YEAR_MARKER_RE.search(target):
        return [(source, target)], ""

    source_parts = split_after_year_markers(source)
    target_parts = split_after_year_markers(target)
    if len(source_parts) == len(target_parts) and len(source_parts) > 1:
        return [(s, t) for s, t in zip(source_parts, target_parts) if s and t], "split_year_markers"
    if len(source_parts) == len(target_parts) == 1:
        return [(source_parts[0], target_parts[0])], "removed_year_markers"
    return [(clean_year_markers(source), clean_year_markers(target))], (
        f"year_marker_count_mismatch:source={len(source_parts)},target={len(target_parts)}"
    )


def split_after_year_markers(value: str) -> list[str]:
    matches = list(YEAR_MARKER_RE.finditer(value))
    if not matches:
        cleaned = clean_year_markers(value)
        return [cleaned] if cleaned else []
    parts: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        part = clean_year_markers(value[start:end])
        if part:
            parts.append(part)
    return parts


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in headers})


def append_note(notes: str, addition: str) -> str:
    notes = norm_text(notes)
    if not addition:
        return notes
    if addition in notes:
        return notes
    return f"{notes}; {addition}" if notes else addition


def clean_candidate_rows(rows: list[dict[str, str]], *, source_label: str) -> tuple[list[dict[str, str]], Counter, list[dict[str, str]]]:
    output: list[dict[str, str]] = []
    stats: Counter = Counter()
    issues: list[dict[str, str]] = []
    for row in rows:
        base = {key: norm_text(row.get(key, "")) for key in HEADERS}
        base["aliases_ja"] = row.get("aliases_ja", "")
        base["aliases_zh"] = row.get("aliases_zh", "")
        before_source = base["source_ja"]
        before_target = base["target_zh"]

        if base["term_type"] == "horse":
            base["source_ja"] = clean_horse_source(base["source_ja"])
            if base["source_ja"] != before_source:
                base["notes"] = append_note(base["notes"], f"cleaned_country_suffix_from={before_source}")
                stats["horse_country_suffix_removed"] += 1
        else:
            base["source_ja"] = clean_general(base["source_ja"])
        base["target_zh"] = clean_general(base["target_zh"])

        if "&" in before_source or "&" in before_target:
            stats["html_entity_unescaped_or_ampersand_checked"] += 1

        if base["term_type"] == "race":
            pieces, reason = split_year_marked_pair(base["source_ja"], base["target_zh"])
            if reason:
                stats[reason.split(":", 1)[0]] += 1
                issues.append(
                    {
                        "source": source_label,
                        "reason": reason,
                        "original_source_ja": before_source,
                        "original_target_zh": before_target,
                        "piece_count": str(len(pieces)),
                    }
                )
            for index, (source_text, target_text) in enumerate(pieces):
                if not source_text or not target_text:
                    continue
                item = dict(base)
                item["source_ja"] = source_text
                item["target_zh"] = target_text
                if index > 0:
                    item["aliases_ja"] = ""
                    item["aliases_zh"] = ""
                if reason:
                    item["notes"] = append_note(
                        item["notes"],
                        f"{reason}; original_source={before_source}; original_target={before_target}",
                    )
                output.append(item)
            continue
        output.append(base)
    return output, stats, issues


def dedupe_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], Counter]:
    selected: dict[tuple[str, str, str], dict[str, str]] = {}
    stats: Counter = Counter()
    for row in rows:
        key = (row["term_type"], row["source_language"], identity(row["source_ja"]))
        existing = selected.get(key)
        if existing is None:
            selected[key] = row
            continue
        stats["deduped_rows"] += 1
        if source_rank(row) < source_rank(existing):
            selected[key] = row
        elif row.get("aliases_zh"):
            aliases = split_aliases(existing.get("aliases_zh", ""))
            for alias in split_aliases(row.get("aliases_zh", "")):
                if identity(alias) not in {identity(item) for item in aliases}:
                    aliases.append(alias)
            existing["aliases_zh"] = "\n".join(aliases)
    return sorted(selected.values(), key=lambda item: (item["term_type"], item["source_language"], item["racing_region"], item["source_ja"])), stats


def source_rank(row: dict[str, str]) -> tuple[int, int]:
    notes = row.get("notes", "")
    if "source=hkjc" in notes or "source=hkjc_overseas" in notes:
        return (0, -int(row.get("priority") or 0))
    return (10, -int(row.get("priority") or 0))


def split_aliases(raw: str) -> list[str]:
    values = re.split(r"[\r\n|,，、]+", raw or "")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = norm_text(value)
        key = identity(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def wpstud_maps_from_csv(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    rows = read_csv(path)
    english_to_japanese: dict[str, str] = {}
    for row in rows:
        if row.get("term_type") != "horse" or row.get("source_language") != "ja":
            continue
        japanese = norm_text(row.get("source_ja", ""))
        for alias in split_aliases(row.get("aliases_ja", "")):
            english_to_japanese[identity(alias)] = japanese
    return english_to_japanese, rows


def wpstud_japan_maps_from_html(cache_dir: Path) -> dict[tuple[str, str], str]:
    maps: dict[tuple[str, str], str] = {}
    for path in cache_dir.glob("wpstud_*.htm*"):
        text = read_text_guess(path)
        soup = BeautifulSoup(text, "lxml")
        page_text = soup.get_text(" ", strip=True)
        for table in soup.find_all("table"):
            rows = table_rows(table)
            if len(rows) < 2:
                continue
            headers = [header_key(value) for value in rows[0]]
            for values in rows[1:]:
                row = {headers[index]: values[index].strip() for index in range(min(len(headers), len(values))) if headers[index]}
                english_name = norm_text(row.get("english_name", ""))
                japanese_name = norm_text(row.get("japanese_name", ""))
                if not english_name or not japanese_name:
                    continue
                if row.get("race_grade"):
                    maps[("race", identity(english_name))] = japanese_name
                elif "騎師" in page_text:
                    maps[("jockey", identity(english_name))] = japanese_name
    return maps


def read_text_guess(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "big5", "cp950", "gb18030", "shift_jis", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def table_rows(table) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def header_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    normalized = normalized.replace(" ", "").replace("／", "/")
    mapping = {
        "賽事日文名稱": "japanese_name",
        "赛事日文名称": "japanese_name",
        "賽事英文名稱": "english_name",
        "赛事英文名称": "english_name",
        "賽事中文名稱": "target_zh",
        "赛事中文名称": "target_zh",
        "級數": "race_grade",
        "级数": "race_grade",
        "日文": "japanese_name",
        "英文": "english_name",
        "中文": "target_zh",
    }
    return mapping.get(normalized, "")


def load_lookup_cache(path: Path) -> dict[str, dict[str, str]]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_lookup_cache(path: Path, cache: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def lookup_netkeiba_japanese_name(name: str, *, cache: dict[str, dict[str, str]], sleep_seconds: float) -> LookupResult | None:
    key = identity(name)
    if key in cache:
        item = cache[key]
        if item.get("japanese_name"):
            return LookupResult(item["japanese_name"], item.get("source_url", ""), item.get("confidence", "cached"), item.get("reason", "cache"))
        return None

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; umafans-term-review/1.0)"})
    try:
        url = NETKEIBA_SEARCH_URL.format(query=quote(name))
        response = session.get(url, timeout=20)
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        result = parse_netkeiba_response(name, response.text, response.url, session=session)
    except Exception as exc:
        cache[key] = {"japanese_name": "", "source_url": "", "confidence": "error", "reason": str(exc)}
        return None
    finally:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    if result:
        cache[key] = {
            "japanese_name": result.japanese_name,
            "source_url": result.source_url,
            "confidence": result.confidence,
            "reason": result.reason,
        }
        return result
    cache[key] = {"japanese_name": "", "source_url": "", "confidence": "missing", "reason": "no_exact_match"}
    return None


def parse_netkeiba_response(name: str, text: str, url: str, *, session: requests.Session) -> LookupResult | None:
    soup = BeautifulSoup(text, "lxml")
    title = soup.find("title").get_text(" ", strip=True) if soup.find("title") else ""
    detail_result = parse_netkeiba_detail_title(name, title, url)
    if detail_result:
        return detail_result

    candidates: list[tuple[int, str, str]] = []
    for tr in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        link = tr.find("a", href=re.compile(r"/horse/\w+/?"))
        if not link or len(cells) < 4:
            continue
        japanese = norm_text(link.get_text(" ", strip=True))
        href = urljoin(url, link.get("href", ""))
        try:
            birth_year = int(re.search(r"\b(19|20)\d{2}\b", " ".join(cells)).group(0))
        except Exception:
            birth_year = 0
        if re.search(r"[\u3040-\u30ff]", japanese):
            candidates.append((birth_year, japanese, href))
    for _birth_year, _japanese, href in sorted(candidates, reverse=True)[:8]:
        try:
            response = session.get(href, timeout=20)
            response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        except Exception:
            continue
        detail_soup = BeautifulSoup(response.text, "lxml")
        detail_title = detail_soup.find("title").get_text(" ", strip=True) if detail_soup.find("title") else ""
        result = parse_netkeiba_detail_title(name, detail_title, response.url)
        if result:
            return LookupResult(result.japanese_name, result.source_url, "netkeiba_detail_from_search", "exact_english_in_detail_title")
        time.sleep(0.05)
    return None


def parse_netkeiba_detail_title(name: str, title: str, url: str) -> LookupResult | None:
    match = re.search(r"(?P<ja>[ァ-ヴー・A-Za-z0-9' .-]+)\s*\((?P<en>[^)]+)\)", title or "")
    if not match:
        return None
    japanese = norm_text(match.group("ja"))
    english = norm_text(match.group("en"))
    if identity(english) == identity(name) and re.search(r"[\u3040-\u30ff]", japanese):
        return LookupResult(japanese, url, "netkeiba_detail", "exact_english_in_detail_title")
    return None


def build_alias_rows(
    hkjc_rows: list[dict[str, str]],
    *,
    wpstud_horse_map: dict[str, str],
    wpstud_japan_map: dict[tuple[str, str], str],
    lookup_cache_path: Path,
    sleep_seconds: float,
    max_netkeiba: int | None,
) -> tuple[list[dict[str, str]], Counter, list[dict[str, str]]]:
    cache = load_lookup_cache(lookup_cache_path)
    alias_rows: list[dict[str, str]] = []
    stats: Counter = Counter()
    missing: list[dict[str, str]] = []
    netkeiba_count = 0

    for row in hkjc_rows:
        if row.get("racing_region") != "japan" or row.get("source_language") != "en":
            continue
        clean_source = clean_horse_source(row.get("source_ja", "")) if row.get("term_type") == "horse" else clean_general(row.get("source_ja", ""))
        if not clean_source:
            continue
        alias = ""
        alias_source = ""
        confidence = ""
        notes = ""
        if row.get("term_type") == "horse":
            alias = wpstud_horse_map.get(identity(clean_source), "")
            if alias:
                alias_source = "wpstud_horselist"
                confidence = "community_exact_english"
            elif max_netkeiba is None or netkeiba_count < max_netkeiba:
                result = lookup_netkeiba_japanese_name(clean_source, cache=cache, sleep_seconds=sleep_seconds)
                netkeiba_count += 1
                save_lookup_cache(lookup_cache_path, cache)
                if result:
                    alias = result.japanese_name
                    alias_source = result.source_url
                    confidence = result.confidence
                    notes = result.reason
        else:
            alias = wpstud_japan_map.get((row.get("term_type", ""), identity(clean_source)), "")
            if alias:
                alias_source = "wpstud_race_jockey_cache"
                confidence = "community_exact_english"
        if alias:
            alias_rows.append(
                {
                    "term_type": row["term_type"],
                    "primary_source_language": "en",
                    "primary_source_ja": clean_source,
                    "alias_language": "ja",
                    "alias_text": alias,
                    "target_zh": clean_general(row.get("target_zh", "")),
                    "racing_region": "japan",
                    "alias_source": alias_source,
                    "confidence": confidence,
                    "notes": notes,
                }
            )
            stats[f"alias_found_{row['term_type']}"] += 1
        else:
            missing.append(
                {
                    "term_type": row.get("term_type", ""),
                    "primary_source_ja": clean_source,
                    "target_zh": clean_general(row.get("target_zh", "")),
                    "reason": "no_japanese_alias_found",
                }
            )
            stats[f"alias_missing_{row.get('term_type', '')}"] += 1
    save_lookup_cache(lookup_cache_path, cache)
    return alias_rows, stats, missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hkjc-csv", required=True)
    parser.add_argument("--wpstud-csv", required=True)
    parser.add_argument("--wpstud-horse-csv", required=True)
    parser.add_argument("--wpstud-cache-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--netkeiba-cache", default="")
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--max-netkeiba", type=int, default=0, help="0 means no limit.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    hkjc_raw = read_csv(Path(args.hkjc_csv))
    wpstud_raw = read_csv(Path(args.wpstud_csv))
    wpstud_horse_map, wpstud_horse_rows = wpstud_maps_from_csv(Path(args.wpstud_horse_csv))
    wpstud_japan_map = wpstud_japan_maps_from_html(Path(args.wpstud_cache_dir))

    hkjc_cleaned, hkjc_stats, hkjc_issues = clean_candidate_rows(hkjc_raw, source_label="hkjc_overseas")
    wpstud_cleaned, wpstud_stats, wpstud_issues = clean_candidate_rows(wpstud_raw, source_label="wpstud")
    wpstud_horse_cleaned, horse_stats, horse_issues = clean_candidate_rows(wpstud_horse_rows, source_label="wpstud_horselist")

    netkeiba_cache = Path(args.netkeiba_cache) if args.netkeiba_cache else output_dir / "netkeiba_japan_horse_lookup.json"
    max_netkeiba = None if args.max_netkeiba == 0 else args.max_netkeiba
    alias_rows, alias_stats, missing_aliases = build_alias_rows(
        hkjc_cleaned,
        wpstud_horse_map=wpstud_horse_map,
        wpstud_japan_map=wpstud_japan_map,
        lookup_cache_path=netkeiba_cache,
        sleep_seconds=args.sleep_seconds,
        max_netkeiba=max_netkeiba,
    )
    alias_rows, alias_dedupe_stats = dedupe_alias_rows(alias_rows)
    alias_identity_keys = {
        (row["term_type"], row["alias_language"], identity(row["alias_text"]))
        for row in alias_rows
        if row.get("alias_language") and row.get("alias_text")
    }
    prefiltered_rows = [*hkjc_cleaned, *wpstud_cleaned]
    skipped_concept_duplicates: list[dict[str, str]] = []
    for row in wpstud_horse_cleaned:
        alias_key = (row.get("term_type", ""), row.get("source_language", ""), identity(row.get("source_ja", "")))
        if alias_key in alias_identity_keys:
            skipped_concept_duplicates.append(
                {
                    "term_type": row.get("term_type", ""),
                    "source_language": row.get("source_language", ""),
                    "source_ja": row.get("source_ja", ""),
                    "target_zh": row.get("target_zh", ""),
                    "reason": "represented_as_hkjc_cross_language_alias",
                }
            )
            continue
        prefiltered_rows.append(row)
    combined, dedupe_stats = dedupe_rows(prefiltered_rows)

    write_csv(output_dir / "seed_candidates_final.csv", combined, HEADERS)
    write_csv(output_dir / "hkjc_japan_ja_aliases.csv", alias_rows, ALIAS_HEADERS)
    write_csv(output_dir / "japan_aliases_missing.csv", missing_aliases, ["term_type", "primary_source_ja", "target_zh", "reason"])
    write_csv(
        output_dir / "wpstud_horse_skipped_hkjc_alias_overlap.csv",
        skipped_concept_duplicates,
        ["term_type", "source_language", "source_ja", "target_zh", "reason"],
    )
    write_csv(output_dir / "cleaning_issues.csv", [*hkjc_issues, *wpstud_issues, *horse_issues], ["source", "reason", "original_source_ja", "original_target_zh", "piece_count"])

    report = {
        "generated_at": datetime.now().isoformat(),
        "input_counts": {
            "hkjc": len(hkjc_raw),
            "wpstud_review": len(wpstud_raw),
            "wpstud_horselist": len(wpstud_horse_rows),
        },
        "output_counts": {
            "seed_candidates_final": len(combined),
            "hkjc_japan_ja_aliases": len(alias_rows),
            "japan_aliases_missing": len(missing_aliases),
            "wpstud_horse_skipped_hkjc_alias_overlap": len(skipped_concept_duplicates),
        },
        "stats": dict(hkjc_stats + wpstud_stats + horse_stats + dedupe_stats + alias_stats + alias_dedupe_stats),
        "by_type_language_region": {
            "|".join(key): count for key, count in Counter((row["term_type"], row["source_language"], row["racing_region"]) for row in combined).items()
        },
        "netkeiba_cache": str(netkeiba_cache),
    }
    (output_dir / "repair_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def dedupe_alias_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], Counter]:
    selected: dict[tuple[str, str, str, str], dict[str, str]] = {}
    stats: Counter = Counter()
    for row in rows:
        key = (
            row["term_type"],
            identity(row["primary_source_ja"]),
            row["alias_language"],
            identity(row["alias_text"]),
        )
        if key in selected:
            stats["deduped_alias_rows"] += 1
            continue
        selected[key] = row
    return sorted(selected.values(), key=lambda item: (item["term_type"], item["primary_source_ja"], item["alias_text"])), stats


if __name__ == "__main__":
    main()
