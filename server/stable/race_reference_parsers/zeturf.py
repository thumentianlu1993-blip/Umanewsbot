"""Parse one ZEturf result page without I/O side effects."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from . import decode_html, legacy_hash, reference_runners, text


PARSER_NAME = "zeturf"
PARSER_VERSION = "reference-v1"

_URL_RE = re.compile(
    r"^/fr/course-du-jour/(?P<date>\d{4}-\d{2}-\d{2})/"
    r"R(?P<meeting>[1-9]\d*)C(?P<race>[1-9]\d*)-[^/]+/?$"
)
_TRAILING_HORSE_SUFFIX_RE = re.compile(
    r"\s*[\(\（](?P<suffix>NP|[A-Z]{2,3})[\)\）]\s*$",
    flags=re.IGNORECASE,
)


def _cell_text(node, selector: str) -> str:
    found = node.select_one(selector)
    return text(found.get_text(" ", strip=True) if found else "")


def _raw_horse_name(node) -> str:
    horse = node.select_one(".horse-name")
    return text(
        horse.get("title")
        if horse and horse.get("title")
        else (horse.get_text(" ", strip=True) if horse else "")
    )


def _horse_name(node) -> str:
    value = _raw_horse_name(node)
    while _TRAILING_HORSE_SUFFIX_RE.search(value):
        value = _TRAILING_HORSE_SUFFIX_RE.sub("", value).strip()
    return value


def _has_non_partant_suffix(raw: str) -> bool:
    value = text(raw)
    while True:
        match = _TRAILING_HORSE_SUFFIX_RE.search(value)
        if match is None:
            return False
        if match.group("suffix").casefold() == "np":
            return True
        value = value[: match.start()].strip()


def _title_parts(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title_node = soup.find("title")
    title = text(title_node.get_text(" ", strip=True) if title_node else "")
    match = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+-\s+(.+?)\s+-\s+(.+?):", title)
    if not match:
        return {"date": "", "venue": "", "race_name": ""}
    return {
        "date": f"{match.group(3)}-{match.group(2)}-{match.group(1)}",
        "venue": text(match.group(4)),
        "race_name": text(match.group(5)),
    }


def parse_legacy_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(html, "lxml")
    runners: list[dict] = []
    runner_by_number: dict[str, dict] = {}
    runner_table = soup.select_one("table.table-runners")
    if runner_table:
        for tr in runner_table.select("tbody tr[data-runner]"):
            number = _cell_text(tr, "td.numero")
            horse_name = _horse_name(tr)
            if not horse_name:
                continue
            jockey = _cell_text(tr, ".second-line .jockey")
            trainer = ""
            for trainer_node in tr.select(".second-line > span"):
                if "jockey" not in (trainer_node.get("class") or []):
                    trainer = text(trainer_node.get_text(" ", strip=True))
                    break
            horse_name_raw = _raw_horse_name(tr)
            running_status = (
                "withdrawn"
                if tr.select_one(".non-partant")
                or _has_non_partant_suffix(horse_name_raw)
                else "declared"
            )
            horse_link = tr.select_one("a.horse-name")
            row = {
                "sort_order": len(runners) + 1,
                "horse_number": number,
                "barrier": _cell_text(tr, "td.corde"),
                "horse_name": horse_name,
                "jockey_name": jockey,
                "trainer_name": trainer,
                "carried_weight": _cell_text(tr, "td.weight"),
                "odds_value": _cell_text(tr, "td.cote"),
                "running_status": running_status,
                "source_refs": {
                    "primary": source_url,
                    "source_language": "fr",
                    "source_kind": "zeturf_race_detail",
                    "horse_id": (
                        horse_link.get("data-runner", "") if horse_link else ""
                    ),
                    "horse_name_raw": horse_name_raw,
                },
            }
            runners.append(row)
            if number:
                runner_by_number[number] = row
    results: list[dict] = []
    arrival = soup.select_one("#arriveeTab table")
    if arrival:
        for tr in arrival.select("tbody tr[data-runner]"):
            cells = tr.find_all("td")
            if len(cells) < 4:
                continue
            position_match = re.search(r"\d+", cells[0].get_text(" ", strip=True))
            official_position = int(position_match.group(0)) if position_match else 0
            if official_position <= 0:
                continue
            number = text(cells[1].get_text(" ", strip=True))
            result_horse_name_raw = _raw_horse_name(cells[2])
            horse_name = _horse_name(cells[2]) or (
                runner_by_number.get(number) or {}
            ).get("horse_name", "")
            if not horse_name:
                continue
            base = runner_by_number.get(number) or {}
            results.append(
                {
                    "finish_position": len(results) + 1,
                    "horse_number": number,
                    "barrier": base.get("barrier", ""),
                    "horse_name": horse_name,
                    "jockey_name": _cell_text(cells[3], "a.jockey")
                    or base.get("jockey_name", ""),
                    "trainer_name": base.get("trainer_name", ""),
                    "carried_weight": base.get("carried_weight", ""),
                    "finish_time": "",
                    "margin": text(cells[-1].get_text(" ", strip=True)),
                    "odds_value": text(cells[-2].get_text(" ", strip=True)),
                    "running_status": base.get(
                        "running_status",
                        "declared",
                    ),
                    "is_confirmed": True,
                    "source_refs": {
                        **(base.get("source_refs") or {}),
                        "primary": source_url,
                        "official_finish_position": official_position,
                        "result_horse_name_raw": result_horse_name_raw,
                    },
                }
            )
    metadata = _title_parts(html)
    metadata.update({"row_count": len(runners), "result_count": len(results)})
    return runners, results, metadata


def parse_reference_page(raw_bytes, source_url, parser_context):
    match = _URL_RE.fullmatch(urlsplit(source_url).path)
    if match is None:
        raise RuntimeError("ZEturf source URL identity is invalid")
    expected = {
        "local_date": match.group("date"),
        "meeting": int(match.group("meeting")),
        "race": int(match.group("race")),
    }
    if parser_context != expected:
        raise RuntimeError("ZEturf parser context disagrees with URL")
    html = decode_html(raw_bytes)
    soup = BeautifulSoup(html, "lxml")
    page_identities: set[tuple[str, int, int]] = set()
    for canonical in soup.select('link[rel~="canonical"][href]'):
        canonical_parts = urlsplit(str(canonical.get("href") or "").strip())
        canonical_host = (canonical_parts.hostname or "").casefold().rstrip(".")
        if canonical_parts.netloc and (
            canonical_parts.scheme.casefold() != "https"
            or not (
                canonical_host == "zeturf.fr"
                or canonical_host.endswith(".zeturf.fr")
            )
        ):
            raise RuntimeError("ZEturf canonical URL host is outside source contract")
        if canonical_parts.query or canonical_parts.fragment:
            raise RuntimeError("ZEturf canonical URL route is not exact")
        canonical_match = _URL_RE.fullmatch(canonical_parts.path)
        if canonical_match is not None:
            page_identities.add(
                (
                    canonical_match.group("date"),
                    int(canonical_match.group("meeting")),
                    int(canonical_match.group("race")),
                )
            )
    for marker in soup.select("[data-race-code]"):
        marker_match = re.fullmatch(
            r"R(?P<meeting>[1-9]\d*)C(?P<race>[1-9]\d*)",
            str(marker.get("data-race-code") or "").strip(),
            flags=re.IGNORECASE,
        )
        if marker_match is not None:
            page_identities.add(
                (
                    expected["local_date"],
                    int(marker_match.group("meeting")),
                    int(marker_match.group("race")),
                )
            )
    expected_identity = (
        expected["local_date"],
        expected["meeting"],
        expected["race"],
    )
    if page_identities != {expected_identity}:
        raise RuntimeError(
            "ZEturf page does not uniquely prove the expected date/R/C identity"
        )
    runners, results, metadata = parse_legacy_page(
        html,
        source_url=source_url,
    )
    if metadata["date"] != expected["local_date"]:
        raise RuntimeError("ZEturf page date disagrees with URL")
    semantic_runners = reference_runners(runners, results)
    declared = [row for row in semantic_runners if row["running_status"] != "withdrawn"]
    placed = [row for row in declared if row["source_reported_finish_position"]]
    results_complete = bool(declared) and len(placed) == len(declared)
    gaps = [] if results_complete else ["zeturf_results_incomplete"]
    return {
        "provider_event_key": (
            f"zt:{expected['local_date']}:R{expected['meeting']}C{expected['race']}"
        ),
        "race": {
            "source_race_name": metadata["race_name"],
            "source_racecourse": metadata["venue"],
            "local_date": expected["local_date"],
            "source_start_time": "",
        },
        "runners": semantic_runners,
        "completeness": {
            "race_identity": "complete" if metadata["race_name"] and metadata["venue"] else "partial",
            "runners": "complete" if semantic_runners else "unknown",
            "results": "complete" if results_complete else "partial",
            "gap_codes": gaps,
        },
        "legacy_payload_sha256": legacy_hash(runners, results, metadata),
    }
