"""JRA modern result parser shared by live adapters and historical tools; no I/O."""

import re
import unicodedata
from bs4 import BeautifulSoup

WAKU_RE = re.compile(r"枠(\d+)")
STRUCTURED_DISTANCE_RE = re.compile(
    r"(?<!\d)(\d{1,2}(?:,\d{3})|\d{3,4})\s*(?:m|メートル)(?![A-Za-z])",
    re.IGNORECASE,
)


def _text(node) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _decode_jra_html(body: bytes) -> str:
    return body.decode("cp932", errors="replace")


def _canonical_structured_distance(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    match = STRUCTURED_DISTANCE_RE.search(normalized)
    if match is None:
        return ""
    return f"{match.group(1).replace(',', '')}m"


def _structured_distance_text(soup: BeautifulSoup) -> str:
    for selector in (".raceKyoriTrack", ".cell.course"):
        for node in soup.select(selector):
            distance = _canonical_structured_distance(_text(node))
            if distance:
                return distance
    for node in soup.select("td.gray12"):
        normalized = unicodedata.normalize("NFKC", _text(node))
        if re.fullmatch(r"\d{3,4}\s*m", normalized, re.IGNORECASE):
            return _canonical_structured_distance(normalized)
    return ""


def _parse_barrier(cell) -> str:
    if cell is None:
        return ""
    alt_text = " ".join(img.get("alt", "") for img in cell.find_all("img"))
    match = WAKU_RE.search(alt_text)
    if match:
        return match.group(1)
    return _text(cell)


def _parse_finish_position(value: str) -> int | None:
    value = value.strip()
    if not value.isdigit():
        return None
    return int(value)


def _runner_status_from_finish_position(value: str) -> str:
    value = value.strip()
    if value == "取消":
        return "withdrawn"
    if value == "除外":
        return "scratched"
    if value == "中止":
        return "pulled_up"
    return "declared"


def _parse_detail_page(
    body: bytes, *, source_url: str
) -> tuple[list[dict], list[dict], dict]:
    soup = BeautifulSoup(_decode_jra_html(body), "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError(f"JRA 结果页没有找到主表：{source_url}")

    header = _text(soup.select_one(".race_header"))
    race_title = _text(soup.select_one(".race_title"))
    rows: list[dict] = []
    for index, tr in enumerate(table.find_all("tr")[1:], start=1):
        cells = {
            "place": tr.find("td", class_="place"),
            "waku": tr.find("td", class_="waku"),
            "num": tr.find("td", class_="num"),
            "horse": tr.find("td", class_="horse"),
            "weight": tr.find("td", class_="weight"),
            "jockey": tr.find("td", class_="jockey"),
            "time": tr.find("td", class_="time"),
            "margin": tr.find("td", class_="margin"),
            "trainer": tr.find("td", class_="trainer"),
            "pop": tr.find("td", class_="pop"),
        }
        horse_name = _text(cells["horse"])
        if not horse_name:
            continue
        finish_position_text = _text(cells["place"])
        row = {
            "sort_order": index,
            "finish_position_text": finish_position_text,
            "finish_position": _parse_finish_position(finish_position_text),
            "barrier": _parse_barrier(cells["waku"]),
            "horse_number": _text(cells["num"]),
            "horse_name": horse_name,
            "jockey_name": _text(cells["jockey"]),
            "trainer_name": _text(cells["trainer"]),
            "carried_weight": _text(cells["weight"]),
            "finish_time": _text(cells["time"]),
            "margin": _text(cells["margin"]),
            "popularity": _text(cells["pop"]),
            "running_status": _runner_status_from_finish_position(finish_position_text),
            "source_refs": {
                "primary": source_url,
                "source_language": "ja",
                "source_kind": "jra_official_result_page",
                "jra_finish_position_text": finish_position_text,
            },
        }
        rows.append(row)

    runners = []
    results = []
    result_order = 0
    for row in rows:
        runners.append(
            {
                "sort_order": row["sort_order"],
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "popularity": row["popularity"],
                "running_status": row["running_status"],
                "source_refs": row["source_refs"],
            }
        )
        if row["finish_position"] is None:
            continue
        result_order += 1
        source_refs = {
            **row["source_refs"],
            "official_finish_position": row["finish_position"],
        }
        results.append(
            {
                "finish_position": result_order,
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
                "source_refs": source_refs,
            }
        )
    metadata = {
        "race_header": header,
        "race_title": race_title,
        "distance_text": _structured_distance_text(soup),
        "row_count": len(rows),
        "result_count": len(results),
    }
    if runners and results:
        return runners, results, metadata

    raise RuntimeError(f"JRA result page has no complete rows: {source_url}")
