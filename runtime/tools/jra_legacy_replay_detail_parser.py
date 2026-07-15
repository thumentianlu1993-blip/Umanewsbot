from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup


HEADER_ALIASES = {
    "着順": {"着順", "finish"},
    "枠": {"枠", "gate"},
    "馬番": {"馬番", "no"},
    "馬名": {"馬名", "horse"},
    "負担重量": {"負担重量", "weight"},
    "騎手": {"騎手", "jockey"},
    "タイム": {"タイム", "time"},
    "着差": {"着差", "margin"},
    "調教師": {"調教師", "trainer"},
    "単勝人気": {"単勝人気", "fav"},
}
NORMALIZED_HEADER_ALIASES = {
    unicodedata.normalize("NFKC", alias).replace(" ", "").casefold(): canonical
    for canonical, aliases in HEADER_ALIASES.items()
    for alias in aliases
}
LEGACY_REQUIRED_HEADERS = {"着順", "馬番", "馬名"}


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _decode_html(body: bytes) -> str:
    return body.decode("cp932", errors="replace")


def _expanded_headers(row) -> list[str]:
    headers = []
    for cell in row.find_all(["th", "td"], recursive=False):
        label = unicodedata.normalize("NFKC", _text(cell)).replace(" ", "").casefold()
        label = NORMALIZED_HEADER_ALIASES.get(label, label)
        try:
            colspan = max(1, int(cell.get("colspan", 1)))
        except (TypeError, ValueError):
            colspan = 1
        headers.extend([label] * colspan)
    return headers


def _legacy_result_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if first_row is None:
            continue
        headers = _expanded_headers(first_row)
        if LEGACY_REQUIRED_HEADERS.issubset(headers):
            return table, headers
    return None, []


def _finish_position(value: str) -> int | None:
    value = unicodedata.normalize("NFKC", value).strip()
    return int(value) if re.fullmatch(r"\d+", value) else None


def _running_status(value: str) -> str:
    value = value.strip()
    if value == "取消":
        return "withdrawn"
    if value == "除外":
        return "scratched"
    if value == "中止":
        return "unknown"
    return "declared"


def _legacy_distance_text(metadata_table) -> str:
    if metadata_table is None:
        return ""
    for cell in metadata_table.find_all(["th", "td"]):
        match = re.search(r"(?<!\d)\d{3,4}\s*[mｍＭ](?![A-Za-z])", _text(cell), re.IGNORECASE)
        if match:
            return re.sub(r"\s+", "", match.group())
    return ""


def try_parse_jra_legacy_replay_detail(
    body: bytes,
    *,
    source_url: str,
) -> tuple[list[dict], list[dict], dict] | None:
    soup = BeautifulSoup(_decode_html(body), "html.parser")
    table, headers = _legacy_result_table(soup)
    if table is None:
        return None

    column = {label: headers.index(label) for label in LEGACY_REQUIRED_HEADERS}
    for optional in ("枠", "負担重量", "騎手", "タイム", "着差", "調教師", "単勝人気"):
        if optional in headers:
            column[optional] = headers.index(optional)

    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td", recursive=False)
        if len(cells) != len(headers):
            continue

        def value(label: str) -> str:
            index = column.get(label)
            return _text(cells[index]) if index is not None else ""

        horse_number = value("馬番")
        horse_name = value("馬名")
        if not horse_number or not horse_name:
            continue
        finish_position_text = value("着順")
        finish_position = _finish_position(finish_position_text)
        source_refs = {
            "primary": source_url,
            "source_language": "ja",
            "source_kind": "jra_official_result_page",
            "jra_finish_position_text": finish_position_text,
        }
        rows.append(
            {
                "sort_order": len(rows) + 1,
                "finish_position": finish_position,
                "barrier": value("枠"),
                "horse_number": horse_number,
                "horse_name": horse_name,
                "jockey_name": value("騎手"),
                "trainer_name": value("調教師"),
                "carried_weight": value("負担重量"),
                "finish_time": value("タイム"),
                "margin": value("着差"),
                "popularity": value("単勝人気"),
                "running_status": _running_status(finish_position_text),
                "source_refs": source_refs,
            }
        )

    runners = [
        {
            key: row[key]
            for key in (
                "sort_order",
                "horse_number",
                "barrier",
                "horse_name",
                "jockey_name",
                "trainer_name",
                "carried_weight",
                "popularity",
                "running_status",
                "source_refs",
            )
        }
        for row in rows
    ]
    finished_rows = sorted(
        (row for row in rows if row["finish_position"] is not None),
        key=lambda row: row["finish_position"],
    )
    results = []
    for storage_position, row in enumerate(finished_rows, start=1):
        results.append(
            {
                "finish_position": storage_position,
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "finish_time": row["finish_time"],
                "margin": row["margin"],
                "popularity": row["popularity"],
                "running_status": row["running_status"],
                "is_confirmed": True,
                "source_refs": {
                    **row["source_refs"],
                    "official_finish_position": row["finish_position"],
                },
            }
        )

    if not runners or not results:
        raise RuntimeError(f"JRA legacy result table has no complete rows: {source_url}")

    metadata_table = table.find_previous("table")
    metadata_rows = metadata_table.find_all("tr") if metadata_table is not None else []
    return runners, results, {
        "race_header": _text(metadata_rows[0]) if metadata_rows else "",
        "race_title": _text(metadata_rows[1]) if len(metadata_rows) > 1 else "",
        "distance_text": _legacy_distance_text(metadata_table),
        "row_count": len(runners),
        "result_count": len(results),
    }
