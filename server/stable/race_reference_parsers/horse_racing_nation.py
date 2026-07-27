"""Parse one exact HRN track-day race without I/O side effects."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from . import decode_html, legacy_hash, reference_runners, text


PARSER_NAME = "horse_racing_nation"
PARSER_VERSION = "reference-v1"

_URL_RE = re.compile(
    r"^/entries-results/(?P<track>[a-z0-9]+(?:-[a-z0-9]+)*)/"
    r"(?P<date>\d{4}-\d{2}-\d{2})/?$"
)
_HEADING_RE = re.compile(r"Race\s*#?\s*(\d+)(?:,\s*([0-9:]+\s*[AP]M))?", re.I)


def _normalized_horse_name(raw: str) -> str:
    display = re.sub(r"\s*\(\d+\)\s*$", "", text(raw)).strip()
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", display).strip()


def _trainer_jockey(cell) -> tuple[str, str, str]:
    parts = [
        text(part.get_text(" ", strip=True))
        for part in cell.find_all("p", recursive=False)
        if text(part.get_text(" ", strip=True))
    ]
    raw = text(cell.get_text(" ", strip=True))
    if len(parts) >= 2:
        return parts[0], parts[1], raw
    words = raw.split()
    if len(words) <= 3:
        return raw, "", raw
    return " ".join(words[:-2]), " ".join(words[-2:]), raw


def _horse_name(cell) -> tuple[str, str, str]:
    link = cell.find("a", href=True)
    raw = text(link.get_text(" ", strip=True) if link else cell.get_text(" ", strip=True))
    return _normalized_horse_name(raw), raw, link["href"] if link else ""


def _parse_entries(table, *, source_url: str, race_no: str, race_meta: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 6:
            continue
        horse_name, raw_name, horse_url = _horse_name(cells[2])
        if not horse_name:
            continue
        number = text(cells[1].get_text(" ", strip=True))
        identity = (number, horse_name, horse_url)
        if identity in seen:
            continue
        seen.add(identity)
        trainer, jockey, trainer_jockey_raw = _trainer_jockey(cells[3])
        rows.append(
            {
                "sort_order": len(rows) + 1,
                "horse_number": number,
                "barrier": "",
                "horse_name": horse_name,
                "jockey_name": jockey,
                "trainer_name": trainer,
                "odds_value": text(cells[5].get_text(" ", strip=True)),
                "running_status": "declared",
                "source_refs": {
                    "primary": source_url,
                    "source_language": "en",
                    "source_kind": "horse_racing_nation_track_day",
                    "hrn_race_no": race_no,
                    "hrn_race_meta": race_meta,
                    "horse_name_raw": raw_name,
                    "horse_url": horse_url,
                    "trainer_jockey_raw": trainer_jockey_raw,
                },
            }
        )
    return rows


def _race_block_elements(heading) -> list:
    elements = []
    for node in heading.next_elements:
        if getattr(node, "name", None) == "h2" and _HEADING_RE.search(
            text(node.get_text(" ", strip=True))
        ):
            break
        elements.append(node)
    return elements


def _race_meta_from_block(elements: list) -> str:
    for node in elements:
        if getattr(node, "name", None) == "div" and "row" in (
            node.get("class") or []
        ):
            value = text(node.get_text(" ", strip=True))
            if value:
                return value
    return ""


def _race_title(meta: str) -> str:
    parts = [part.strip() for part in meta.split(",")]
    value = parts[2] if len(parts) >= 3 else meta
    return text(value.split("Purse:", 1)[0].split("|", 1)[0])


def _result_names(
    payout_table,
    *,
    trailing_block_elements: list,
) -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = []
    normalized_seen: set[str] = set()
    if payout_table is not None:
        for tr in payout_table.find_all("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue
            raw = text(cells[0].get_text(" ", strip=True))
            if not raw or raw.casefold().startswith("runner") or raw.startswith("*"):
                continue
            name = _normalized_horse_name(raw)
            if name and name not in normalized_seen:
                names.append((name, raw))
                normalized_seen.add(name)
        for node in trailing_block_elements:
            if not isinstance(node, str) or "Also rans:" not in node:
                continue
            value = text(str(node)).split("Also rans:", 1)[1]
            value = value.split("Pool", 1)[0]
            for raw in value.split(","):
                raw_name = text(raw)
                name = _normalized_horse_name(raw_name)
                if name and name not in normalized_seen:
                    names.append((name, raw_name))
                    normalized_seen.add(name)
            break
    return names


def _parse_track_day(html: str, *, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    races: list[dict] = []
    for heading in soup.find_all("h2"):
        match = _HEADING_RE.search(text(heading.get_text(" ", strip=True)))
        if not match:
            continue
        race_no = match.group(1)
        start_time = match.group(2) or ""
        block_elements = _race_block_elements(heading)
        race_meta = _race_meta_from_block(block_elements)
        entries = next(
            (
                node
                for node in block_elements
                if getattr(node, "name", None) == "table"
                and "table-entries" in (node.get("class") or [])
            ),
            None,
        )
        if entries is None:
            continue
        entries_index = block_elements.index(entries)
        payout = next(
            (
                node
                for node in block_elements[entries_index + 1 :]
                if getattr(node, "name", None) == "table"
                and "table-payouts" in (node.get("class") or [])
            ),
            None,
        )
        runners = _parse_entries(
            entries,
            source_url=source_url,
            race_no=race_no,
            race_meta=race_meta,
        )
        source_entry_count = 0
        for tr in entries.find_all("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) >= 6 and _horse_name(cells[2])[0]:
                source_entry_count += 1
        by_name = {row["horse_name"]: row for row in runners}
        results: list[dict] = []
        payout_index = (
            block_elements.index(payout)
            if payout is not None
            else len(block_elements)
        )
        for position, (name, result_name_raw) in enumerate(
            _result_names(
                payout,
                trailing_block_elements=block_elements[payout_index + 1 :],
            ),
            start=1,
        ):
            runner = by_name.get(name)
            if runner is None:
                continue
            results.append(
                {
                    "finish_position": position,
                    "horse_number": runner["horse_number"],
                    "barrier": runner["barrier"],
                    "horse_name": runner["horse_name"],
                    "jockey_name": runner["jockey_name"],
                    "trainer_name": runner["trainer_name"],
                    "odds_value": runner["odds_value"],
                    "running_status": runner["running_status"],
                    "is_confirmed": True,
                    "source_refs": {
                        **runner["source_refs"],
                        "official_finish_position": position,
                        "hrn_result_source": "payout_table_plus_also_rans",
                        "hrn_result_horse_name_raw": result_name_raw,
                    },
                }
            )
        races.append(
            {
                "race_no": race_no,
                "start_time": start_time,
                "race_meta": race_meta,
                "race_title": _race_title(race_meta),
                "runners": runners,
                "results": results,
                "duplicate_count": max(0, source_entry_count - len(runners)),
            }
        )
    return races


def parse_reference_page(raw_bytes, source_url, parser_context):
    match = _URL_RE.fullmatch(urlsplit(source_url).path)
    if match is None:
        raise RuntimeError("HRN source URL identity is invalid")
    if not isinstance(parser_context, dict) or set(parser_context) != {
        "track_slug",
        "local_date",
        "race",
    }:
        raise RuntimeError("HRN parser context fields are invalid")
    expected = {
        "track_slug": match.group("track"),
        "local_date": match.group("date"),
        "race": parser_context.get("race"),
    }
    if (
        parser_context.get("track_slug") != expected["track_slug"]
        or parser_context.get("local_date") != expected["local_date"]
        or isinstance(expected["race"], bool)
        or not isinstance(expected["race"], int)
        or expected["race"] <= 0
    ):
        raise RuntimeError("HRN parser context disagrees with URL")
    races = _parse_track_day(decode_html(raw_bytes), source_url=source_url)
    selected = [
        race for race in races if race.get("race_no") == str(expected["race"])
    ]
    if len(selected) != 1:
        raise RuntimeError(
            f"HRN expected exactly one race #{expected['race']}; found {len(selected)}"
        )
    race = selected[0]
    semantic_runners = reference_runners(race["runners"], race["results"])
    return {
        "provider_event_key": (
            f"hrn:{expected['track_slug']}:{expected['local_date']}:R{expected['race']}"
        ),
        "race": {
            "source_race_name": race.get("race_title", ""),
            "source_racecourse": expected["track_slug"],
            "local_date": expected["local_date"],
            "source_start_time": race.get("start_time", ""),
        },
        "runners": semantic_runners,
        "completeness": {
            "race_identity": "complete",
            "runners": "complete" if semantic_runners else "unknown",
            "results": "partial",
            "gap_codes": ["hrn_results_partial"],
        },
        "parser_evidence": {
            "duplicate_entry_count": race.get("duplicate_count", 0),
            "trainer_jockey_split": "heuristic_with_raw_cell",
            "result_source": "payout_table_plus_also_rans",
        },
        "legacy_payload_sha256": legacy_hash(
            race["runners"],
            race["results"],
            {
                "race_no": race["race_no"],
                "start_time": race.get("start_time", ""),
                "race_meta": race.get("race_meta", ""),
                "race_title": race.get("race_title", ""),
            },
        ),
    }
