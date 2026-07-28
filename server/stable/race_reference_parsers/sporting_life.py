"""Parse one Sporting Life result page without I/O side effects."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from . import decode_html, legacy_hash, reference_runners, text


PARSER_NAME = "sporting_life"
PARSER_VERSION = "reference-v1"

_URL_RE = re.compile(
    r"^/racing/results/(?P<date>\d{4}-\d{2}-\d{2})/"
    r"(?P<course>[^/]+)/(?P<race_id>[1-9]\d*)/[^/]+/?$"
)

_CASUALTY_STATUS_BY_REASON = {
    "broughtdown": "brought_down",
    "carriedout": "did_not_finish",
    "fell": "fell",
    "pulledup": "pulled_up",
    "refused": "refused",
    "refusedtorace": "refused",
    "slippedup": "fell",
    "unseatedrider": "unseated_rider",
}


def _next_data(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise RuntimeError("Sporting Life 页面缺少 __NEXT_DATA__")
    try:
        value = json.loads(script.string)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Sporting Life __NEXT_DATA__ 不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Sporting Life __NEXT_DATA__ 根节点无效")
    return value


def _person_name(value) -> str:
    if isinstance(value, dict):
        return text(value.get("name") or value.get("display_name"))
    return text(value)


def _runner_status(ride: dict) -> str:
    try:
        if int(ride.get("finish_position")) > 0:
            return "declared"
    except (TypeError, ValueError):
        pass
    casualty = ride.get("casualty")
    if isinstance(casualty, dict):
        reason = re.sub(r"[^a-z0-9]", "", text(casualty.get("reason")).casefold())
        if reason in _CASUALTY_STATUS_BY_REASON:
            return _CASUALTY_STATUS_BY_REASON[reason]
    status_with_separators = re.sub(
        r"[_-]+",
        " ",
        text(ride.get("ride_status")).casefold(),
    )
    status = re.sub(r"[^a-z0-9]", "", status_with_separators)
    if status in {"nonrunner", "withdrawn"}:
        return "withdrawn"
    if status == "pulledup":
        return "pulled_up"
    description = re.sub(
        r"[_-]+",
        " ",
        text(ride.get("ride_description")).casefold(),
    )
    for pattern, result in (
        (r"\bnon\s*runner\b", "withdrawn"),
        (r"\bbrought\s+down\b", "brought_down"),
        (r"\b(?:unseated|lost)\s+(?:the\s+)?rider\b", "unseated_rider"),
        (r"\bpulled\s+up\b", "pulled_up"),
        (r"\b(?:fell|slipped\s+up)\b", "fell"),
        (r"\brefused\b", "refused"),
        (r"\b(?:carried\s+out|ran\s+out|failed\s+to\s+complete|stopped)\b", "did_not_finish"),
        (r"\bdisqualified\b", "disqualified"),
    ):
        if re.search(pattern, description):
            return result
    return "unknown"


def parse_legacy_page(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    try:
        race = _next_data(html)["props"]["pageProps"]["race"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("Sporting Life 页面缺少 race payload") from exc
    if not isinstance(race, dict):
        raise RuntimeError("Sporting Life race payload 无效")
    summary = race.get("race_summary") or {}
    runners: list[dict] = []
    result_rows: list[dict] = []
    for ride in race.get("rides") or []:
        horse = ride.get("horse") or {}
        horse_name = re.sub(
            r"\s*[\(\（][A-Z]{2,3}[\)\）]\s*$",
            "",
            text(horse.get("name")),
        ).strip()
        if not horse_name:
            continue
        try:
            finish_position = int(ride.get("finish_position"))
        except (TypeError, ValueError):
            finish_position = 0
        betting = ride.get("betting")
        odds = (
            text(betting.get("current_odds"))
            if isinstance(betting, dict)
            else ""
        )
        source_refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": "sporting_life_result_detail",
            "sporting_life_race_id": (
                (summary.get("race_summary_reference") or {}).get("id")
            ),
            "horse_id": (horse.get("horse_reference") or {}).get("id"),
            "horse_slug": horse.get("slug") or "",
            "horse_name_raw": horse.get("name") or "",
            "casualty_reason": (
                (ride.get("casualty") or {}).get("reason", "")
                if isinstance(ride.get("casualty"), dict)
                else ""
            ),
            "ride_status": ride.get("ride_status") or "",
            "ride_description": ride.get("ride_description") or "",
        }
        row = {
            "sort_order": len(runners) + 1,
            "horse_number": text(ride.get("cloth_number")),
            "barrier": text(ride.get("draw_number")),
            "horse_name": horse_name,
            "jockey_name": _person_name(ride.get("jockey")),
            "trainer_name": _person_name(ride.get("trainer")),
            "carried_weight": text(ride.get("handicap")),
            "odds_value": odds,
            "running_status": _runner_status(ride),
            "finish_position": finish_position,
            "finish_time": (
                text(summary.get("winning_time")) if finish_position == 1 else ""
            ),
            "margin": text(ride.get("finish_distance")),
            "source_refs": source_refs,
        }
        runners.append(
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
                    "odds_value",
                    "running_status",
                    "source_refs",
                )
            }
        )
        if row["running_status"] == "declared" and finish_position > 0:
            result_rows.append(row)
    results: list[dict] = []
    for position, row in enumerate(
        sorted(result_rows, key=lambda item: item["finish_position"]),
        start=1,
    ):
        results.append(
            {
                "finish_position": position,
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "horse_name": row["horse_name"],
                "jockey_name": row["jockey_name"],
                "trainer_name": row["trainer_name"],
                "carried_weight": row["carried_weight"],
                "finish_time": row["finish_time"],
                "margin": row["margin"],
                "odds_value": row["odds_value"],
                "running_status": row["running_status"],
                "is_confirmed": True,
                "source_refs": {
                    **row["source_refs"],
                    "official_finish_position": row["finish_position"],
                },
            }
        )
    metadata = {
        "race_title": summary.get("name") or "",
        "race_id": (summary.get("race_summary_reference") or {}).get("id"),
        "race_stage": summary.get("race_stage") or "",
        "row_count": len(runners),
        "result_count": len(results),
    }
    distance_text = text(summary.get("distance"))
    if distance_text:
        metadata["distance_text"] = distance_text
    return runners, results, metadata


def parse_reference_page(raw_bytes, source_url, parser_context):
    match = _URL_RE.fullmatch(urlsplit(source_url).path)
    if match is None:
        raise RuntimeError("Sporting Life source URL identity is invalid")
    if not isinstance(parser_context, dict) or set(parser_context) != {"race_id"}:
        raise RuntimeError("Sporting Life parser context fields are invalid")
    expected_race_id = parser_context["race_id"]
    if (
        isinstance(expected_race_id, bool)
        or not isinstance(expected_race_id, int)
        or expected_race_id != int(match.group("race_id"))
    ):
        raise RuntimeError("Sporting Life parser context disagrees with URL")
    runners, results, metadata = parse_legacy_page(
        decode_html(raw_bytes),
        source_url=source_url,
    )
    try:
        page_race_id = int(metadata.get("race_id"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Sporting Life page does not prove a race ID") from exc
    if page_race_id != expected_race_id:
        raise RuntimeError("Sporting Life page race ID mismatch")
    semantic_runners = reference_runners(runners, results)
    complete_statuses = {
        "declared",
        "withdrawn",
        "brought_down",
        "did_not_finish",
        "fell",
        "pulled_up",
        "refused",
        "unseated_rider",
        "disqualified",
    }
    results_complete = bool(semantic_runners) and all(
        row["running_status"] in complete_statuses
        and (
            row["running_status"] != "declared"
            or bool(row["source_reported_finish_position"])
        )
        for row in semantic_runners
    )
    gaps = [] if results_complete else ["sporting_life_results_incomplete"]
    return {
        "provider_event_key": f"sl:{expected_race_id}",
        "race": {
            "source_race_name": text(metadata.get("race_title")),
            "source_racecourse": match.group("course"),
            "local_date": match.group("date"),
            "source_start_time": "",
        },
        "runners": semantic_runners,
        "completeness": {
            "race_identity": "complete",
            "runners": "complete" if semantic_runners else "unknown",
            "results": "complete" if results_complete else "partial",
            "gap_codes": gaps,
        },
        "legacy_payload_sha256": legacy_hash(runners, results, metadata),
    }
