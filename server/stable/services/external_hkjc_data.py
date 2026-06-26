from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import dateparse, timezone

from stable.models import (
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceResult,
    ExternalImportStatus,
    RacingRegion,
    SourceLanguage,
)


class HKJCImportError(Exception):
    pass


@dataclass(frozen=True)
class HKJCImportOptions:
    dry_run: bool = True
    allow_network: bool = False
    request_interval_seconds: float = 8
    max_races: int = 20
    max_horses: int = 80
    max_requests: int = 200

    @classmethod
    def from_settings(cls, **overrides: Any) -> "HKJCImportOptions":
        values = {
            "request_interval_seconds": getattr(settings, "HKJC_IMPORT_REQUEST_INTERVAL_SECONDS", 8),
            "max_races": getattr(settings, "HKJC_IMPORT_MAX_RACES_PER_RUN", 20),
            "max_horses": getattr(settings, "HKJC_IMPORT_MAX_HORSES_PER_RUN", 80),
            "max_requests": getattr(settings, "HKJC_IMPORT_MAX_REQUESTS_PER_RUN", 200),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def _horse_identity(payload: dict) -> str:
    horse_id = _string(payload.get("horse_id") or payload.get("horseCode") or payload.get("id"))
    if horse_id:
        return f"id:{horse_id}"
    for field_name in (
        "horse_name_en",
        "english_name",
        "horse_name_zh_hant",
        "chinese_name",
        "horse_name",
        "name",
    ):
        normalized = _normalize_name(_string(payload.get(field_name)))
        if normalized:
            return f"name:{normalized.casefold()}"
    return ""


def _parse_date(value: Any):
    raw = _string(value)
    if not raw:
        return None
    normalized = raw.replace("/", "-")
    parsed = dateparse.parse_date(normalized)
    if parsed:
        return parsed
    for fmt in ("%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: Any):
    raw = _string(value)
    if not raw:
        return None
    parsed = dateparse.parse_datetime(raw)
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _load_json_file(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise HKJCImportError("HKJC payload file must contain a JSON object")
    return payload


class HKJCHTMLParser:
    def parse_result_meetings(
        self,
        html: str,
        *,
        start_date: str | date,
        end_date: str | date,
        source_url: str,
    ) -> list[dict[str, str]]:
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        soup = BeautifulSoup(html, "lxml")
        meetings: list[dict[str, str]] = []
        for option in soup.select("select#selectId option"):
            value = _string(option.get("value"))
            if not value:
                continue
            try:
                data = json.loads(value)
            except json.JSONDecodeError:
                continue
            raw_date = _string(data.get("date"))
            venue = _string(data.get("venue")).upper()
            if venue and venue not in {"HV", "ST"}:
                continue
            race_date = _parse_date(raw_date)
            if not race_date or race_date < start or race_date > end:
                continue
            meetings.append(
                {
                    "race_date": race_date.isoformat(),
                    "raw_date": raw_date,
                    "venue": venue,
                    "source_url": source_url,
                }
            )
        return meetings

    def parse_result_race_links(self, html: str, *, source_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = _string(anchor.get("href"))
            if "localresults" not in href or "RaceNo" not in href:
                continue
            absolute_url = urljoin(source_url, href)
            parsed = urlparse(absolute_url)
            params = parse_qs(parsed.query)
            raw_date = _first_query_value(params, "racedate")
            racecourse = _first_query_value(params, "Racecourse").upper()
            race_no = _first_query_value(params, "RaceNo")
            if racecourse not in {"HV", "ST"}:
                continue
            race_date = _parse_date(raw_date)
            if not race_date or not racecourse or not race_no:
                continue
            race_id = f"HK{race_date.strftime('%Y%m%d')}{racecourse}{int(race_no):02d}"
            if race_id in seen:
                continue
            seen.add(race_id)
            links.append(
                {
                    "race_id": race_id,
                    "race_date": race_date.isoformat(),
                    "racecourse": racecourse,
                    "race_no": str(int(race_no)),
                    "url": absolute_url,
                }
            )
        return links

    def parse_race_result(
        self,
        html: str,
        *,
        race_date: str,
        racecourse: str,
        race_no: str,
        source_url: str,
    ) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        parsed_date = _coerce_date(race_date)
        race_no_text = _string(race_no)
        race_id = f"HK{parsed_date.strftime('%Y%m%d')}{_string(racecourse).upper()}{int(race_no_text):02d}"
        header_text = self._race_header_text(soup)
        race = {
            "race_id": race_id,
            "race_date": parsed_date.isoformat(),
            "venue": _hkjc_venue_name(racecourse),
            "race_number": race_no_text,
            "race_name": self._race_name_from_header(header_text),
            "race_class": self._race_class_from_header(header_text),
            "distance": self._distance_from_header(header_text),
            "going": self._going_from_header(header_text),
            "course": self._field_after_label(header_text, "Course"),
            "prize_money": self._prize_money_from_header(header_text),
            "entries": [],
            "results": [],
            "raw_payload": {
                "source_url": source_url,
                "racecourse": _string(racecourse).upper(),
                "header": header_text,
            },
        }
        for row in self._result_rows(soup):
            entry = {
                "horse_id": row["horse_id"],
                "horse_name_en": row["horse_name"],
                "horse_number": row["horse_number"],
                "barrier": row["barrier"],
                "jockey": row["jockey"],
                "trainer": row["trainer"],
                "weight": row["carried_weight"],
            "raw_payload": row["raw_payload"],
        }
            result = {
                **entry,
                "finish_position": row["finish_position"],
                "finish_time": row["finish_time"],
                "margin": row["margin"],
                "odds": row["odds"],
                "running_position": row["running_position"],
            }
            race["entries"].append(entry)
            race["results"].append(result)
        return race

    def parse_horse_profile(self, html: str, *, horse_id: str, source_url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        profile_text = _collapse_spaces(soup.get_text(" ", strip=True))
        name_match = re.search(r"\b([A-Z][A-Z0-9' -]+)\s+\(([A-Z]\d+)\)", profile_text)
        fields = self._profile_fields(soup)
        country, age = _split_slash(fields.get("Country of Origin / Age", ""))
        color, sex = _split_slash(fields.get("Colour / Sex", ""))
        horse = {
            "horse_id": _string(horse_id),
            "horse_name_en": _collapse_spaces(name_match.group(1)) if name_match else "",
            "brand_number": name_match.group(2) if name_match else "",
            "country": country,
            "age": age,
            "color": color,
            "sex": sex,
            "import_type": fields.get("Import Type", ""),
            "trainer": fields.get("Trainer", ""),
            "owner": fields.get("Owner", ""),
            "rating": fields.get("Current Rating", ""),
            "sire": fields.get("Sire", ""),
            "dam": fields.get("Dam", ""),
            "dams_sire": fields.get("Dam's Sire", ""),
            "record_summary": fields.get("No. of 1-2-3-Starts*", ""),
            "raw_payload": {
                "source_url": source_url,
                "fields": fields,
            },
        }
        return horse

    def _race_header_text(self, soup: BeautifulSoup) -> str:
        for table in soup.find_all("table"):
            rows = [_collapse_spaces(row.get_text(" ", strip=True)) for row in table.find_all("tr")]
            text = " | ".join(row for row in rows if row)
            if "RACE" in text.upper() and "Going" in text:
                return text
        return ""

    def _result_rows(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for table in soup.find_all("table"):
            table_rows = table.find_all("tr")
            if not table_rows:
                continue
            header_cells = [
                _collapse_spaces(cell.get_text(" ", strip=True))
                for cell in table_rows[0].find_all(["td", "th"], recursive=False)
            ]
            if "Pla." not in header_cells or "Horse" not in header_cells:
                continue
            for tr in table_rows[1:]:
                cells = tr.find_all(["td", "th"], recursive=False)
                if len(cells) < 12:
                    continue
                horse_cell = cells[2]
                horse_link = horse_cell.find("a", href=True)
                horse_name = _collapse_spaces(horse_link.get_text(" ", strip=True) if horse_link else horse_cell.get_text(" ", strip=True))
                horse_id = _query_param(_string(horse_link.get("href") if horse_link else ""), "horseid")
                values = [_collapse_spaces(cell.get_text(" ", strip=True)) for cell in cells]
                rows.append(
                    {
                        "finish_position": values[0],
                        "horse_number": values[1],
                        "horse_name": horse_name,
                        "horse_id": horse_id,
                        "jockey": values[3],
                        "trainer": values[4],
                        "carried_weight": values[5],
                        "declar_horse_weight": values[6],
                        "barrier": values[7],
                        "margin": "" if values[8] == "---" else values[8],
                        "running_position": values[9],
                        "finish_time": values[10],
                        "odds": values[11],
                        "raw_payload": {
                            "row": values,
                            "horse_href": _string(horse_link.get("href") if horse_link else ""),
                        },
                    }
                )
            break
        return rows

    def _race_name_from_header(self, header_text: str) -> str:
        going_pattern = self._going_pattern()
        match = re.search(rf"Going\s*:\s*(?:{going_pattern})\s+(.+?)\s+Course\s*:", header_text, re.IGNORECASE)
        if match:
            return _collapse_spaces(match.group(1).strip(" |"))
        for part in header_text.split("|"):
            normalized = _collapse_spaces(part)
            if normalized and "HANDICAP" in normalized.upper() and "RACE" not in normalized.upper():
                return normalized
        return ""

    def _race_class_from_header(self, header_text: str) -> str:
        match = re.search(r"\b(Class\s+\d+)\b", header_text, re.IGNORECASE)
        return match.group(1) if match else ""

    def _distance_from_header(self, header_text: str) -> str:
        match = re.search(r"\b(\d{3,4}M)\b", header_text, re.IGNORECASE)
        return match.group(1).upper() if match else ""

    def _field_after_label(self, header_text: str, label: str) -> str:
        match = re.search(rf"{re.escape(label)}\s*:\s*([^|]+?)(?=\s*\||\s+HK\$|$)", header_text)
        return _collapse_spaces(match.group(1)) if match else ""

    def _going_from_header(self, header_text: str) -> str:
        match = re.search(rf"Going\s*:\s*({self._going_pattern()})\b", header_text, re.IGNORECASE)
        return match.group(1).upper() if match else ""

    def _going_pattern(self) -> str:
        return r"GOOD TO FIRM|GOOD TO YIELDING|GOOD|YIELDING TO SOFT|YIELDING|SOFT|FIRM|FAST|WET SLOW|SLOW"

    def _prize_money_from_header(self, header_text: str) -> str:
        match = re.search(r"HK\$\s*[0-9,]+", header_text)
        return match.group(0) if match else ""

    def _profile_fields(self, soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        for tr in soup.find_all("tr"):
            cells = [_collapse_spaces(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"], recursive=False)]
            if len(cells) >= 3 and cells[1] == ":":
                fields[cells[0]] = cells[2]
        return fields


def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    parsed = _parse_date(value)
    if not parsed:
        raise HKJCImportError(f"invalid date: {value}")
    return parsed


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _query_param(url: str, key: str) -> str:
    match = re.search(rf"[?&]{re.escape(key)}=([^&#]+)", url, re.IGNORECASE)
    return match.group(1) if match else ""


def _first_query_value(params: dict[str, list[str]], key: str) -> str:
    for existing_key, values in params.items():
        if existing_key.lower() == key.lower() and values:
            return _string(values[0])
    return ""


def _hkjc_venue_name(racecourse: str) -> str:
    return {
        "HV": "Happy Valley",
        "ST": "Sha Tin",
    }.get(_string(racecourse).upper(), _string(racecourse).upper())


def _split_slash(value: str) -> tuple[str, str]:
    left, _, right = _string(value).partition("/")
    return _collapse_spaces(left), _collapse_spaces(right)


def _parse_hkjc_race_id(race_id: str) -> tuple[date, str, str]:
    match = re.fullmatch(r"HK(\d{8})([A-Z]+)(\d{2})", _string(race_id).upper())
    if not match:
        raise HKJCImportError(f"invalid HKJC race_id: {race_id}")
    parsed_date = datetime.strptime(match.group(1), "%Y%m%d").date()
    return parsed_date, match.group(2), match.group(3)


class HKJCNetworkClient:
    user_agent = "umanewsbot/1.0 (+https://umafans.run; low-frequency data import)"

    def __init__(self, options: HKJCImportOptions):
        self.options = options
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, *, target_type: str, target_id: str):
        if len(self.requests) >= self.options.max_requests:
            raise HKJCImportError(f"HKJC network import exceeded max_requests={self.options.max_requests}")
        if self.requests and self.options.request_interval_seconds > 0:
            time.sleep(self.options.request_interval_seconds)
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": self.user_agent},
        )
        request_info = {
            "url": getattr(response, "url", url),
            "status_code": response.status_code,
            "target_type": target_type,
            "target_id": target_id,
        }
        self.requests.append(request_info)
        if response.status_code >= 400:
            raise HKJCImportError(f"HKJC network import failed with HTTP {response.status_code}: {url}")
        return response


class HKJCExternalDataImporter:
    source = ExternalDataSource.HKJC
    racing_region = RacingRegion.HONG_KONG
    source_language = SourceLanguage.ENGLISH

    def __init__(self, options: HKJCImportOptions | None = None):
        self.options = options or HKJCImportOptions.from_settings()

    def import_race_date(self, race_date: str, *, payload_file: str = "") -> dict:
        return self._import_target("race_date", race_date, payload_file=payload_file)

    def import_race(self, race_id: str, *, payload_file: str = "") -> dict:
        return self._import_target("race", race_id, payload_file=payload_file)

    def import_race_batch(self, race_ids: list[str], *, limit_horses: int | None = None) -> dict:
        cleaned_race_ids = [_string(race_id) for race_id in race_ids if _string(race_id)]
        if not cleaned_race_ids:
            raise HKJCImportError("race_ids must not be empty")
        if not self.options.allow_network:
            raise HKJCImportError("HKJC race-id batch import requires --allow-network")
        return self._import_target(
            "race_batch",
            ",".join(cleaned_race_ids),
            network_kwargs={"race_ids": cleaned_race_ids, "limit_horses": limit_horses},
        )

    def import_horse(self, horse_id: str, *, payload_file: str = "") -> dict:
        return self._import_target("horse", horse_id, payload_file=payload_file)

    def import_date_range(
        self,
        start_date: str | date,
        end_date: str | date,
        *,
        limit_races: int | None = None,
        limit_horses: int | None = None,
        skip_races: int = 0,
    ) -> dict:
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        return self._import_target(
            "date_range",
            f"{start.isoformat()}..{end.isoformat()}",
            network_kwargs={
                "start_date": start,
                "end_date": end,
                "limit_races": limit_races,
                "limit_horses": limit_horses,
                "skip_races": skip_races,
            },
        )

    def import_recent_days(
        self,
        days: int,
        *,
        end_date: str | date | None = None,
        limit_races: int | None = None,
        limit_horses: int | None = None,
        skip_races: int = 0,
    ) -> dict:
        if days <= 0:
            raise HKJCImportError("recent days must be positive")
        end = _coerce_date(end_date) if end_date else timezone.localdate()
        start = end - timedelta(days=days)
        return self.import_date_range(start, end, limit_races=limit_races, limit_horses=limit_horses, skip_races=skip_races)

    def plan_date_range(
        self,
        start_date: str | date,
        end_date: str | date,
        *,
        suggested_limit_races: int | None = None,
    ) -> dict:
        if not self.options.allow_network:
            raise HKJCImportError("HKJC plan-only requires --allow-network")
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        parser = HKJCHTMLParser()
        client = HKJCNetworkClient(self.options)
        meeting_response = client.get(self._meeting_list_url(), target_type="meeting_list", target_id=f"{start.isoformat()}..{end.isoformat()}")
        meetings = parser.parse_result_meetings(
            meeting_response.text,
            start_date=start,
            end_date=end,
            source_url=client.requests[-1]["url"],
        )
        race_links: list[dict[str, str]] = []
        for meeting in meetings:
            race_date = meeting["race_date"]
            date_response = client.get(self._race_date_url(race_date), target_type="race_date", target_id=race_date)
            race_links.extend(parser.parse_result_race_links(date_response.text, source_url=client.requests[-1]["url"]))
        batch_size = suggested_limit_races or self.options.max_races
        batches = self._race_plan_batches(race_links, batch_size=batch_size)
        return {
            "source": self.source,
            "target_type": "date_range",
            "target_id": f"{start.isoformat()}..{end.isoformat()}",
            "dry_run": True,
            "plan_only": True,
            "coverage_stats": {
                "meetings": len(meetings),
                "races": len(race_links),
                "estimated_requests_without_horses": 1 + len(meetings) + len(race_links),
            },
            "batches": batches,
            "requests": client.requests,
            "would_write_formal_tables": False,
        }

    def plan_recent_days(
        self,
        days: int,
        *,
        end_date: str | date | None = None,
        suggested_limit_races: int | None = None,
    ) -> dict:
        if days <= 0:
            raise HKJCImportError("recent days must be positive")
        end = _coerce_date(end_date) if end_date else timezone.localdate()
        start = end - timedelta(days=days)
        return self.plan_date_range(start, end, suggested_limit_races=suggested_limit_races)

    def _race_plan_batches(self, race_links: list[dict[str, str]], *, batch_size: int) -> list[dict[str, Any]]:
        if batch_size <= 0:
            raise HKJCImportError("batch race limit must be positive")
        batches: list[dict[str, Any]] = []
        for index in range(0, len(race_links), batch_size):
            chunk = race_links[index : index + batch_size]
            if not chunk:
                continue
            batches.append(
                {
                    "batch_no": len(batches) + 1,
                    "skip_races": index,
                    "start_date": chunk[0]["race_date"],
                    "end_date": chunk[-1]["race_date"],
                    "race_ids": [race["race_id"] for race in chunk],
                    "race_count": len(chunk),
                    "suggested_limit_races": batch_size,
                }
            )
        return batches

    def _import_target(
        self,
        target_type: str,
        target_id: str,
        *,
        payload_file: str = "",
        network_kwargs: dict[str, Any] | None = None,
    ) -> dict:
        if payload_file:
            payload = _load_json_file(payload_file)
            return self._import_payload(target_type, target_id, payload, has_payload_file=True)
        if self.options.allow_network:
            payload, request_info = self._fetch_network_payload(target_type, target_id, **(network_kwargs or {}))
            result = self._import_payload(target_type, target_id, payload, has_payload_file=True)
            result["network_probe"] = True
            result["requests"] = request_info
            return result
        payload = self._placeholder_payload(target_type, target_id)
        return self._import_payload(target_type, target_id, payload, has_payload_file=False)

    def _placeholder_payload(self, target_type: str, target_id: str) -> dict:
        if target_type == "race_date":
            return {"races": [], "race_date": target_id}
        if target_type == "race":
            return {"race": {"race_id": target_id}}
        return {"horses": [{"horse_id": target_id}]}

    def _fetch_network_payload(self, target_type: str, target_id: str, **kwargs: Any) -> tuple[dict, list[dict]]:
        if target_type == "race_batch":
            payload, client = self._fetch_race_batch_payload(
                kwargs["race_ids"],
                limit_horses=kwargs.get("limit_horses"),
            )
            return payload, client.requests
        if target_type == "date_range":
            payload, client = self._fetch_date_range_payload(
                kwargs["start_date"],
                kwargs["end_date"],
                limit_races=kwargs.get("limit_races"),
                limit_horses=kwargs.get("limit_horses"),
                skip_races=kwargs.get("skip_races", 0),
            )
            return payload, client.requests
        url = self._network_url(target_type, target_id)
        client = HKJCNetworkClient(self.options)
        response = client.get(url, target_type=target_type, target_id=target_id)
        try:
            payload = response.json()
        except ValueError as exc:
            if target_type == "race":
                payload = {"race": self._parse_network_race_html(target_id, response.text, client.requests[-1]["url"])}
            elif target_type == "horse":
                payload = {"horse": HKJCHTMLParser().parse_horse_profile(response.text, horse_id=target_id, source_url=client.requests[-1]["url"])}
            else:
                raise HKJCImportError("HKJC network dry-run did not return JSON payload") from exc
        if not isinstance(payload, dict):
            raise HKJCImportError("HKJC network dry-run payload must be a JSON object")
        return payload, client.requests

    def _fetch_race_batch_payload(
        self,
        race_ids: list[str],
        *,
        limit_horses: int | None,
    ) -> tuple[dict, HKJCNetworkClient]:
        parser = HKJCHTMLParser()
        client = HKJCNetworkClient(self.options)
        races: list[dict[str, Any]] = []
        horse_ids: list[str] = []
        seen_horse_ids: set[str] = set()
        for race_id in race_ids:
            race_date, racecourse, race_no = _parse_hkjc_race_id(race_id)
            race_response = client.get(self._network_url("race", race_id), target_type="race", target_id=race_id)
            race = parser.parse_race_result(
                race_response.text,
                race_date=race_date,
                racecourse=racecourse,
                race_no=race_no,
                source_url=client.requests[-1]["url"],
            )
            races.append(race)
            for runner in [*(race.get("entries") or []), *(race.get("results") or [])]:
                horse_id = _string(runner.get("horse_id")) if isinstance(runner, dict) else ""
                if horse_id and horse_id not in seen_horse_ids:
                    seen_horse_ids.add(horse_id)
                    horse_ids.append(horse_id)
        horses: list[dict[str, Any]] = []
        for horse_id in horse_ids:
            if limit_horses is not None and len(horses) >= limit_horses:
                break
            horse_response = client.get(self._horse_url(horse_id), target_type="horse", target_id=horse_id)
            horses.append(
                parser.parse_horse_profile(
                    horse_response.text,
                    horse_id=horse_id,
                    source_url=client.requests[-1]["url"],
                )
            )
        completion = self._race_batch_completion(
            race_ids=race_ids,
            races=races,
            horse_ids=horse_ids,
            horses=horses,
            limit_horses=limit_horses,
        )
        return (
            {
                "races": races,
                "horses": horses,
                "completion": completion,
                "raw_payload": {
                    "race_ids": race_ids,
                    "limit_horses": limit_horses,
                },
            },
            client,
        )

    def _fetch_date_range_payload(
        self,
        start_date: date,
        end_date: date,
        *,
        limit_races: int | None,
        limit_horses: int | None,
        skip_races: int = 0,
    ) -> tuple[dict, HKJCNetworkClient]:
        if skip_races < 0:
            raise HKJCImportError("skip_races must be non-negative")
        parser = HKJCHTMLParser()
        client = HKJCNetworkClient(self.options)
        meeting_response = client.get(self._meeting_list_url(), target_type="meeting_list", target_id=f"{start_date.isoformat()}..{end_date.isoformat()}")
        meetings = parser.parse_result_meetings(
            meeting_response.text,
            start_date=start_date,
            end_date=end_date,
            source_url=client.requests[-1]["url"],
        )
        races: list[dict[str, Any]] = []
        horse_ids: list[str] = []
        seen_horse_ids: set[str] = set()
        race_seen = 0
        for meeting in meetings:
            if limit_races is not None and len(races) >= limit_races:
                break
            race_date = meeting["race_date"]
            date_response = client.get(self._race_date_url(race_date), target_type="race_date", target_id=race_date)
            race_links = parser.parse_result_race_links(date_response.text, source_url=client.requests[-1]["url"])
            for race_link in race_links:
                if race_seen < skip_races:
                    race_seen += 1
                    continue
                if limit_races is not None and len(races) >= limit_races:
                    break
                race_seen += 1
                race_response = client.get(race_link["url"], target_type="race", target_id=race_link["race_id"])
                race = parser.parse_race_result(
                    race_response.text,
                    race_date=race_link["race_date"],
                    racecourse=race_link["racecourse"],
                    race_no=race_link["race_no"],
                    source_url=client.requests[-1]["url"],
                )
                races.append(race)
                for runner in [*(race.get("entries") or []), *(race.get("results") or [])]:
                    horse_id = _string(runner.get("horse_id")) if isinstance(runner, dict) else ""
                    if horse_id and horse_id not in seen_horse_ids:
                        seen_horse_ids.add(horse_id)
                        horse_ids.append(horse_id)
        horses: list[dict[str, Any]] = []
        for horse_id in horse_ids:
            if limit_horses is not None and len(horses) >= limit_horses:
                break
            horse_response = client.get(self._horse_url(horse_id), target_type="horse", target_id=horse_id)
            horses.append(
                parser.parse_horse_profile(
                    horse_response.text,
                    horse_id=horse_id,
                    source_url=client.requests[-1]["url"],
                )
            )
        completion = self._date_range_completion(
            meetings=meetings,
            races=races,
            horse_ids=horse_ids,
            horses=horses,
            limit_races=limit_races,
            limit_horses=limit_horses,
            skip_races=skip_races,
        )
        return (
            {
                "races": races,
                "horses": horses,
                "meetings": meetings,
                "completion": completion,
                "raw_payload": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "limit_races": limit_races,
                    "limit_horses": limit_horses,
                    "skip_races": skip_races,
                },
            },
            client,
        )

    def _race_batch_completion(
        self,
        *,
        race_ids: list[str],
        races: list[dict[str, Any]],
        horse_ids: list[str],
        horses: list[dict[str, Any]],
        limit_horses: int | None,
    ) -> dict[str, Any]:
        stop_reason = "complete"
        is_complete = True
        if limit_horses is not None and len(horses) < len(horse_ids):
            stop_reason = "limit_horses_reached"
            is_complete = False
        return {
            "is_complete": is_complete,
            "stop_reason": stop_reason,
            "race_ids": race_ids,
            "races_imported": len(races),
            "unique_horses_found": len(horse_ids),
            "horse_profiles_fetched": len(horses),
            "limit_horses": limit_horses,
            "max_requests": self.options.max_requests,
        }

    def _date_range_completion(
        self,
        *,
        meetings: list[dict[str, Any]],
        races: list[dict[str, Any]],
        horse_ids: list[str],
        horses: list[dict[str, Any]],
        limit_races: int | None,
        limit_horses: int | None,
        skip_races: int,
    ) -> dict[str, Any]:
        stop_reason = "complete"
        is_complete = True
        if limit_races is not None and len(races) >= limit_races:
            stop_reason = "limit_races_reached"
            is_complete = False
        if limit_horses is not None and len(horses) < len(horse_ids):
            stop_reason = "limit_horses_reached"
            is_complete = False
        return {
            "is_complete": is_complete,
            "stop_reason": stop_reason,
            "meetings_found": len(meetings),
            "races_imported": len(races),
            "unique_horses_found": len(horse_ids),
            "horse_profiles_fetched": len(horses),
            "limit_races": limit_races,
            "limit_horses": limit_horses,
            "skip_races": skip_races,
            "max_requests": self.options.max_requests,
        }

    def _network_url(self, target_type: str, target_id: str) -> str:
        base_url = self._base_url()
        path_by_target = {
            "race_date": "racing",
            "race": "race",
            "horse": "horse",
        }
        if target_type == "race":
            race_date, racecourse, race_no = _parse_hkjc_race_id(target_id)
            return (
                f"{base_url}/en-us/local/information/localresults"
                f"?racedate={race_date.strftime('%Y/%m/%d')}&Racecourse={racecourse}&RaceNo={int(race_no)}"
            )
        if target_type == "horse":
            return self._horse_url(target_id)
        return f"{base_url}/{path_by_target[target_type]}/{target_id}"

    def _base_url(self) -> str:
        return _string(getattr(settings, "HKJC_IMPORT_NETWORK_BASE_URL", "https://racing.hkjc.com")).rstrip("/")

    def _meeting_list_url(self) -> str:
        return f"{self._base_url()}/en-us/local/information/localresults"

    def _race_date_url(self, race_date: str | date) -> str:
        parsed = _coerce_date(race_date)
        return f"{self._meeting_list_url()}?racedate={parsed.strftime('%Y/%m/%d')}"

    def _horse_url(self, horse_id: str) -> str:
        return f"{self._base_url()}/en-us/local/information/horse?horseid={horse_id}"

    def _parse_network_race_html(self, race_id: str, html: str, source_url: str) -> dict:
        race_date, racecourse, race_no = _parse_hkjc_race_id(race_id)
        return HKJCHTMLParser().parse_race_result(
            html,
            race_date=race_date,
            racecourse=racecourse,
            race_no=race_no,
            source_url=source_url,
        )

    def _import_payload(self, target_type: str, target_id: str, payload: dict, *, has_payload_file: bool) -> dict:
        stats = self._payload_stats(payload)
        completion = payload.get("completion") if isinstance(payload.get("completion"), dict) else {}
        if self.options.dry_run:
            return {
                "source": self.source,
                "target_type": target_type,
                "target_id": target_id,
                "dry_run": True,
                "coverage_stats": stats,
                "completion": completion,
                "would_write_formal_tables": False,
            }
        if not has_payload_file:
            raise HKJCImportError("HKJC commit import requires --payload-file until network import is implemented")
        self._validate_payload_limits(stats)
        with transaction.atomic():
            lock, _ = ExternalDataImportLock.objects.select_for_update().get_or_create(
                source=self.source,
                defaults={"racing_region": self.racing_region},
            )
            if lock.locked_by_run and lock.locked_by_run.status == ExternalImportStatus.STARTED:
                raise HKJCImportError(f"{self.source} import is already running")
            run = ExternalDataImportRun.objects.create(
                source=self.source,
                racing_region=self.racing_region,
                source_language=self.source_language,
                target_type=target_type,
                parameters={"target_id": target_id, "completion": completion},
                dry_run=False,
                status=ExternalImportStatus.STARTED,
            )
            lock.locked_by_run = run
            lock.acquired_at = timezone.now()
            lock.racing_region = self.racing_region
            lock.save(update_fields=["locked_by_run", "acquired_at", "racing_region", "updated_at"])
            try:
                written = self._upsert_payload(payload)
                run.success_count = written
                run.coverage_stats = stats
                run.status = ExternalImportStatus.SUCCESS
                run.finished_at = timezone.now()
                run.save()
            finally:
                ExternalDataImportLock.objects.filter(source=self.source, locked_by_run=run).update(
                    locked_by_run=None,
                    acquired_at=None,
                )
        return {
            "run_id": run.id,
            "source": self.source,
            "target_type": target_type,
            "target_id": target_id,
            "dry_run": False,
            "success_count": run.success_count,
            "coverage_stats": stats,
            "completion": completion,
        }

    def _payload_stats(self, payload: dict) -> dict:
        races = self._races(payload)
        horses = self._horses(payload)
        entries = 0
        results = 0
        horse_identities: set[str] = set()
        for horse in horses:
            identity = _horse_identity(horse)
            if identity:
                horse_identities.add(identity)
        for race in races:
            race_entries = [item for item in race.get("entries") or [] if isinstance(item, dict)]
            race_results = [item for item in race.get("results") or [] if isinstance(item, dict)]
            entries += len(race_entries)
            results += len(race_results)
            for horse_payload in [*race_entries, *race_results]:
                identity = _horse_identity(horse_payload)
                if identity:
                    horse_identities.add(identity)
        return {"races": len(races), "entries": entries, "results": results, "horses": len(horse_identities)}

    def _validate_payload_limits(self, stats: dict) -> None:
        if stats["races"] > self.options.max_races:
            raise HKJCImportError(f"HKJC payload has {stats['races']} races; max_races is {self.options.max_races}")
        if stats["horses"] > self.options.max_horses:
            raise HKJCImportError(f"HKJC payload has {stats['horses']} horses; max_horses is {self.options.max_horses}")

    def _races(self, payload: dict) -> list[dict]:
        if isinstance(payload.get("races"), list):
            return [item for item in payload["races"] if isinstance(item, dict)]
        race = payload.get("race")
        return [race] if isinstance(race, dict) else []

    def _horses(self, payload: dict) -> list[dict]:
        if isinstance(payload.get("horses"), list):
            return [item for item in payload["horses"] if isinstance(item, dict)]
        horse = payload.get("horse")
        return [horse] if isinstance(horse, dict) else []

    def _upsert_payload(self, payload: dict) -> int:
        written = 0
        for race_payload in self._races(payload):
            race = self._upsert_race(race_payload)
            written += 1
            for entry_payload in race_payload.get("entries") or []:
                if isinstance(entry_payload, dict):
                    self._upsert_entry(race, entry_payload)
                    written += 1
                    self._upsert_alias_from_payload(entry_payload)
            for result_payload in race_payload.get("results") or []:
                if isinstance(result_payload, dict):
                    self._upsert_result(race, result_payload)
                    written += 1
                    self._upsert_alias_from_payload(result_payload)
        for horse_payload in self._horses(payload):
            self._upsert_horse(horse_payload)
            written += 1
            self._upsert_alias_from_payload(horse_payload)
        return written

    def _upsert_race(self, payload: dict) -> ExternalRace:
        race_id = _string(payload.get("race_id") or payload.get("raceNo") or payload.get("id"))
        if not race_id:
            raise HKJCImportError("HKJC race payload missing race_id")
        scheduled_start_at = _parse_datetime(payload.get("scheduled_start_at") or payload.get("start_time"))
        race, _ = ExternalRace.objects.update_or_create(
            source=self.source,
            race_id=race_id,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race_name": _string(payload.get("race_name") or payload.get("name")),
                "race_date": _parse_date(payload.get("race_date") or payload.get("date")),
                "course": _string(payload.get("course")),
                "venue": _string(payload.get("venue") or payload.get("racecourse")),
                "race_number": _string(payload.get("race_number") or payload.get("raceNo")),
                "race_grade": _string(payload.get("grade")),
                "race_class": _string(payload.get("class")),
                "surface": _string(payload.get("surface")),
                "track": _string(payload.get("track")),
                "distance": _string(payload.get("distance")),
                "weather": _string(payload.get("weather")),
                "going": _string(payload.get("going") or payload.get("track_condition")),
                "prize_money": _string(payload.get("prize_money") or payload.get("stakes")),
                "scheduled_start_at": scheduled_start_at,
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )
        return race

    def _upsert_entry(self, race: ExternalRace, payload: dict) -> None:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode"))
        entry_key = _string(payload.get("entry_key") or payload.get("horse_number") or horse_id or payload.get("horse_name"))
        ExternalRaceEntry.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            entry_key=entry_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": _string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name")),
                "normalized_horse_name": _normalize_name(_string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name"))),
                "horse_number": _string(payload.get("horse_number") or payload.get("no")),
                "frame_number": _string(payload.get("frame_number")),
                "barrier": _string(payload.get("barrier") or payload.get("draw")),
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
                "carried_weight": _string(payload.get("weight") or payload.get("carried_weight")),
                "equipment": _string(payload.get("equipment")),
                "rating": _string(payload.get("rating")),
                "owner_name": _string(payload.get("owner")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )

    def _upsert_result(self, race: ExternalRace, payload: dict) -> None:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode"))
        result_key = _string(payload.get("result_key") or payload.get("finish_position") or horse_id or payload.get("horse_name"))
        ExternalRaceResult.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            result_key=result_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": _string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name")),
                "normalized_horse_name": _normalize_name(_string(payload.get("horse_name") or payload.get("horse_name_en") or payload.get("name"))),
                "horse_number": _string(payload.get("horse_number") or payload.get("no")),
                "finish_position": _string(payload.get("finish_position") or payload.get("position")),
                "finish_time": _string(payload.get("finish_time") or payload.get("time")),
                "margin": _string(payload.get("margin")),
                "odds_value": _string(payload.get("odds")),
                "running_position": _string(payload.get("running_position")),
                "sectional_time": _string(payload.get("sectional_time")),
                "barrier": _string(payload.get("barrier") or payload.get("draw")),
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )

    def _upsert_horse(self, payload: dict) -> ExternalHorse:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode") or payload.get("id"))
        if not horse_id:
            raise HKJCImportError("HKJC horse payload missing horse_id")
        horse_name_en = _string(payload.get("horse_name_en") or payload.get("english_name") or payload.get("name"))
        horse_name_zh_hant = _string(payload.get("horse_name_zh_hant") or payload.get("chinese_name"))
        horse_name = horse_name_en or horse_name_zh_hant
        horse, _ = ExternalHorse.objects.update_or_create(
            source=self.source,
            horse_id=horse_id,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "horse_name": horse_name,
                "horse_name_en": horse_name_en,
                "horse_name_zh_hant": horse_name_zh_hant,
                "normalized_horse_name": _normalize_name(horse_name),
                "sex": _string(payload.get("sex")),
                "birth_date": _parse_date(payload.get("birth_date") or payload.get("date_of_birth")),
                "country": _string(payload.get("country")),
                "color": _string(payload.get("color") or payload.get("colour")),
                "father_name": _string(payload.get("sire") or payload.get("father_name")),
                "mother_name": _string(payload.get("dam") or payload.get("mother_name")),
                "owner_name": _string(payload.get("owner")),
                "trainer_name": _string(payload.get("trainer")),
                "record_summary": _string(payload.get("record_summary") or payload.get("career_record")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )
        return horse

    def _upsert_alias_from_payload(self, payload: dict) -> None:
        horse_id = _string(payload.get("horse_id") or payload.get("horseCode") or payload.get("id"))
        if not horse_id:
            return
        horse = ExternalHorse.objects.filter(source=self.source, horse_id=horse_id).first()
        names = [
            (_string(payload.get("horse_name_en") or payload.get("english_name") or payload.get("horse_name") or payload.get("name")), SourceLanguage.ENGLISH),
            (_string(payload.get("horse_name_zh_hant") or payload.get("chinese_name")), SourceLanguage.CHINESE_TRADITIONAL),
        ]
        for name, language in names:
            if not name:
                continue
            ExternalHorseAlias.objects.update_or_create(
                source=self.source,
                external_horse_id=horse_id,
                normalized_name=_normalize_name(name),
                defaults={
                    "horse": horse,
                    "racing_region": self.racing_region,
                    "source_language": language,
                    "name_ja": name,
                    "name_en": name if language == SourceLanguage.ENGLISH else "",
                    "name_zh_hant": name if language == SourceLanguage.CHINESE_TRADITIONAL else "",
                    "confidence": 100,
                    "alias_source": "hkjc",
                    "last_seen_at": timezone.now(),
                },
            )

    def lookup_alias(self, name: str) -> list[ExternalHorseAlias]:
        normalized = _normalize_name(name)
        return list(
            ExternalHorseAlias.objects.filter(source=self.source, normalized_name=normalized)
            .order_by("-confidence", "-last_seen_at", "external_horse_id")
        )
