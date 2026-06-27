from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import dateparse, timezone

from stable.models import (
    ExternalDataImportLock,
    ExternalDataImportRun,
    ExternalHorse,
    ExternalHorseAlias,
    ExternalImportStatus,
    ExternalRace,
    ExternalRaceEntry,
    ExternalRaceResult,
    RacingRegion,
    SourceLanguage,
)


FRANCE_EXTERNAL_SOURCE = "france_galop"
GENY_FRANCE_EXTERNAL_SOURCE = "geny_france"


class FranceImportError(Exception):
    pass


@dataclass(frozen=True)
class FranceImportOptions:
    dry_run: bool = True
    allow_network: bool = False
    request_interval_seconds: float = 8
    max_races: int = 20
    max_horses: int = 80
    max_requests: int = 200

    @classmethod
    def from_settings(cls, **overrides: Any) -> "FranceImportOptions":
        values = {
            "request_interval_seconds": getattr(settings, "FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS", 8),
            "max_races": getattr(settings, "FRANCE_IMPORT_MAX_RACES_PER_RUN", 20),
            "max_horses": getattr(settings, "FRANCE_IMPORT_MAX_HORSES_PER_RUN", 80),
            "max_requests": getattr(settings, "FRANCE_IMPORT_MAX_REQUESTS_PER_RUN", 200),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _completion_horse_detail_gap(completion: dict[str, Any]) -> bool:
    if _string(completion.get("horse_profile_source")) in {"race_detail_rows", "geny_partants_rows"}:
        return False
    try:
        unique_horses = int(completion.get("unique_horses_found"))
        fetched_horses = int(completion.get("horse_profiles_fetched"))
    except (TypeError, ValueError):
        return False
    return unique_horses > 0 and fetched_horses < unique_horses


def _completion_horse_detail_metadata_missing(completion: dict[str, Any]) -> bool:
    for key in ("unique_horses_found", "horse_profiles_fetched"):
        if key not in completion or completion.get(key) is None:
            return True
        try:
            int(completion.get(key))
        except (TypeError, ValueError):
            return True
    return False


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_name(value: str) -> str:
    return _collapse_spaces(value)


def _parse_date(value: Any):
    raw = _string(value)
    if not raw:
        return None
    return dateparse.parse_date(raw.replace("/", "-"))


class FranceGalopHTMLParser:
    def parse_meeting_links(self, html: str, *, race_date: str, source_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        date_compact = race_date.replace("-", "")
        pattern = re.compile(rf"/en/racing/meeting/{date_compact}/([^\"'<> ]+)")
        for anchor in soup.find_all("a", href=True):
            href = _string(anchor.get("href"))
            match = pattern.search(href)
            if not match:
                continue
            meeting_id = match.group(1)
            if meeting_id in seen:
                continue
            seen.add(meeting_id)
            links.append(
                {
                    "meeting_id": meeting_id,
                    "race_date": race_date,
                    "venue": _collapse_spaces(anchor.get_text(" ", strip=True)),
                    "url": urljoin(source_url, href),
                }
            )
        return links

    def parse_race_detail_links(self, html: str, *, source_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        pattern = re.compile(r"/en/racing/detail/(\d{4})/([A-Z])/([^\"'<> ]+)")
        for anchor in soup.find_all("a", href=True):
            href = _string(anchor.get("href"))
            match = pattern.search(href)
            if not match:
                continue
            race_id = f"FG{match.group(1)}{match.group(2)}-{match.group(3)}"
            if race_id in seen:
                continue
            seen.add(race_id)
            links.append({"race_id": race_id, "url": urljoin(source_url, href)})
        return links

    def parse_race_detail(self, html: str, *, race_id: str, source_url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        title = _collapse_spaces(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
        text = _collapse_spaces(soup.get_text(" ", strip=True))
        race_date = self._first_match(text, r"\b(\d{2}/\d{2}/\d{4})\b")
        venue = self._first_match(text, r"\d{2}/\d{2}/\d{4}\s+\d{2}h\d{2},\s*([A-Z-]+)")
        race = {
            "race_id": race_id,
            "race_name": title,
            "race_date": "-".join(reversed(race_date.split("/"))) if race_date else "",
            "venue": venue,
            "distance": self._first_match(text, r"Flat\s*,\s*([0-9.]+\s+meters)"),
            "surface": self._first_match(text, r"meters\s*,\s*([A-Z]+)"),
            "going": self._first_match(text, r"Terrain\s+([A-Z]+)"),
            "entries": [],
            "results": [],
            "raw_payload": {"source_url": source_url, "horse_profile_source": "race_detail_rows"},
        }
        for row in self._result_rows(soup):
            race["entries"].append(row)
            race["results"].append({**row, "finish_position": row.get("finish_position", ""), "margin": row.get("margin", "")})
        return race

    def _result_rows(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        table = soup.select_one("div.raceTable table") or soup.find("table")
        if not table:
            return rows
        table_rows = table.find_all("tr")
        if not table_rows:
            return rows
        headers = [_collapse_spaces(cell.get_text(" ", strip=True)).lower() for cell in table_rows[0].find_all(["th", "td"])]
        index = {header: idx for idx, header in enumerate(headers)}
        for tr in table_rows[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            horse_cell = cells[index.get("horse", 1)] if len(cells) > index.get("horse", 1) else None
            link = horse_cell.find("a", href=True) if horse_cell else None
            horse_href = _string(link.get("href") if link else "")
            horse_id = horse_href.rsplit("/", 1)[-1] if horse_href else ""
            horse_text = _collapse_spaces(link.get_text(" ", strip=True) if link else horse_cell.get_text(" ", strip=True))
            name, sex, age = self._horse_identity(horse_text)
            sire, dam = self._sire_dam(self._cell(cells, index, "sire/dam"))
            rows.append(
                {
                    "horse_id": horse_id,
                    "horse_name_en": name,
                    "sex": sex,
                    "age": age,
                    "horse_number": self._cell(cells, index, "#"),
                    "sire": sire,
                    "dam": dam,
                    "margin": self._clean_margin(self._cell(cells, index, "margin")),
                    "owner": self._cell(cells, index, "owner"),
                    "trainer": self._cell(cells, index, "trainer"),
                    "jockey": self._cell(cells, index, "jockey"),
                    "weight": self._cell(cells, index, "weight"),
                    "finish_position": self._cell(cells, index, "place"),
                    "raw_payload": {"horse_href": horse_href, "horse_text": horse_text},
                }
            )
        return rows

    def _cell(self, cells: list, index: dict[str, int], header: str) -> str:
        idx = index.get(header)
        if idx is None or idx >= len(cells):
            return ""
        return _collapse_spaces(cells[idx].get_text(" ", strip=True))

    def _first_match(self, text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        return _collapse_spaces(match.group(1) if match else "")

    def _horse_identity(self, value: str) -> tuple[str, str, str]:
        match = re.match(r"(.+?)\s+([FMH])\.PS\.\s+(\d+)\s+a\.", value)
        if not match:
            return value, "", ""
        name = re.sub(r"\s+\([A-Z]+\)$", "", match.group(1)).strip()
        return name, match.group(2), match.group(3)

    def _sire_dam(self, value: str) -> tuple[str, str]:
        match = re.search(r"Par:\s*(.*?)\s+et\s+(.*?)(?:\s+\(|$)", value)
        if not match:
            return "", ""
        return _collapse_spaces(match.group(1)), _collapse_spaces(match.group(2))

    def _clean_margin(self, value: str) -> str:
        return _collapse_spaces(re.sub(r"\(Corde:[^)]+\)", "", value))


class GenyFranceHTMLParser:
    def parse_race_links(self, html: str, *, race_date: str, source_url: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        links: list[dict[str, Any]] = []
        seen: set[str] = set()
        meeting: dict[str, str] | None = None
        race: dict[str, str] | None = None
        for node in soup.find_all("div"):
            classes = set(node.get("class") or [])
            if "cartoucheReunion" in classes:
                meeting = self._parse_meeting(node)
                race = None
                continue
            if "courseParis" in classes:
                race = self._parse_course(node)
                continue
            if "courseLiens" not in classes or not meeting or not race:
                continue
            if not self._is_french_meeting(meeting["venue"]):
                race = None
                continue
            hrefs = {self._link_kind(_string(anchor.get("href"))): _string(anchor.get("href")) for anchor in node.find_all("a", href=True)}
            partants_href = hrefs.get("partants")
            results_href = hrefs.get("results")
            if not partants_href or not results_href:
                race = None
                continue
            race_id = self._race_id_from_url(partants_href) or self._race_id_from_url(results_href)
            if not race_id or race_id in seen:
                race = None
                continue
            seen.add(race_id)
            links.append(
                {
                    "race_id": f"GENY{race_id}",
                    "race_date": race_date,
                    "venue": meeting["venue"],
                    "meeting_number": meeting["meeting_number"],
                    "race_number": race["race_number"],
                    "race_name": race["race_name"],
                    "partants_url": urljoin(source_url, partants_href),
                    "results_url": urljoin(source_url, results_href),
                }
            )
            race = None
        return links

    def parse_partants(self, html: str, *, race_link: dict[str, Any]) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("#tableau_partants")
        entries: list[dict[str, Any]] = []
        if table:
            rows = table.find_all("tr")
            headers = self._header_index(rows[0]) if rows else {}
            for tr in rows[1:]:
                cells = tr.find_all(["td", "th"])
                if not cells:
                    continue
                horse_cell = self._cell_node(cells, headers, "cheval", 1)
                horse_link = horse_cell.find("a") if horse_cell else None
                onclick = _string(horse_link.get("onclick") if horse_link else "")
                horse_id = self._horse_id(onclick)
                horse_name = _collapse_spaces(horse_link.get_text(" ", strip=True) if horse_link else self._cell(cells, headers, "cheval", 1))
                if not horse_id and not horse_name:
                    continue
                sex, age = self._sex_age(self._cell(cells, headers, "sa", 3))
                profile_path = self._horse_profile_path(onclick)
                entries.append(
                    {
                        "horse_id": horse_id,
                        "horse_name_en": horse_name,
                        "horse_number": self._cell(cells, headers, "n", 0),
                        "barrier": self._cell(cells, headers, "c", 2),
                        "sex": sex,
                        "age": age,
                        "weight": self._cell(cells, headers, "poids", 4),
                        "claim": self._cell(cells, headers, "dech", 5),
                        "jockey": self._cell(cells, headers, "jockey", 6),
                        "trainer": self._cell(cells, headers, "entraineur", 7),
                        "record_summary": self._cell(cells, headers, "musique", 8),
                        "rating": self._cell(cells, headers, "valeur", 9),
                        "odds": self._cell(cells, headers, "cotes references", 10),
                        "raw_payload": {
                            "horse_profile_url": urljoin(race_link.get("partants_url") or "https://www.geny.com/", profile_path),
                            "onclick": onclick,
                        },
                    }
                )
        return {
            "race_id": race_link["race_id"],
            "race_name": race_link["race_name"],
            "race_date": race_link["race_date"],
            "venue": race_link["venue"],
            "meeting_number": race_link.get("meeting_number", ""),
            "race_number": race_link.get("race_number", ""),
            "entries": entries,
            "results": [],
            "raw_payload": {"source_url": race_link.get("partants_url", ""), "horse_profile_source": "geny_partants_rows"},
        }

    def parse_results(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("#arrivees")
        if not table:
            return []
        results: list[dict[str, Any]] = []
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 5:
                continue
            horse_link = cells[2].find("a")
            onclick = _string(horse_link.get("onclick") if horse_link else "")
            profile_path = self._horse_profile_path(onclick)
            results.append(
                {
                    "finish_position": _collapse_spaces(cells[0].get_text(" ", strip=True)),
                    "horse_number": _collapse_spaces(cells[1].get_text(" ", strip=True)),
                    "horse_id": self._horse_id(onclick),
                    "horse_name_en": _collapse_spaces(horse_link.get_text(" ", strip=True) if horse_link else cells[2].get_text(" ", strip=True)),
                    "jockey": _collapse_spaces(cells[3].get_text(" ", strip=True)),
                    "margin": _collapse_spaces(cells[4].get_text(" ", strip=True)),
                    "raw_payload": {"horse_profile_url": urljoin("https://www.geny.com/", profile_path), "onclick": onclick},
                }
            )
        return results

    def parse_horse_profile(self, html: str, *, horse_id: str, source_url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        title = _collapse_spaces(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
        name = re.sub(r"^\d+\.\s*", "", title).strip()
        text = _collapse_spaces(soup.get_text(" ", strip=True))
        identity = self._profile_identity(text)
        fields = self._profile_fields(soup)
        return {
            "horse_id": _string(horse_id),
            "horse_name_en": name,
            "sex": identity.get("sex", ""),
            "age": identity.get("age", ""),
            "color": identity.get("color", ""),
            "sire": identity.get("sire", ""),
            "dam": identity.get("dam", ""),
            "trainer": fields.get("Entraîneur", ""),
            "owner": fields.get("Propriétaire", ""),
            "record_summary": fields.get("Musique", ""),
            "earnings": fields.get("Gains de carrière", ""),
            "raw_payload": {"source_url": source_url},
        }

    def _parse_meeting(self, node) -> dict[str, str]:
        text = _collapse_spaces((node.select_one(".nomReunion") or node).get_text(" ", strip=True))
        match = re.search(r":\s*(.*?)\s+\((R\d+)\)\s*$", text)
        if not match:
            return {"venue": text, "meeting_number": ""}
        return {"venue": match.group(1), "meeting_number": match.group(2)}

    def _parse_course(self, node) -> dict[str, str]:
        text = _collapse_spaces((node.select_one(".nomCourse") or node).get_text(" ", strip=True))
        match = re.match(r"(\d+)\s*-\s*(.+)", text)
        if not match:
            return {"race_number": "", "race_name": text}
        return {"race_number": match.group(1), "race_name": match.group(2)}

    def _profile_identity(self, text: str) -> dict[str, str]:
        match = re.search(
            r"(Femelle|Hongre|Mâle|Male|Jument|Cheval)\s+de\s+(\d+)\s+ans\s*,\s*([^,]+)\s*,\s*[^,]*\s+par\s+(.+?)\s+et\s+(.+?)(?:\s+Musique|\s+Dernière course|\s+Entraîneur|$)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return {}
        return {
            "sex": _collapse_spaces(match.group(1)),
            "age": _collapse_spaces(match.group(2)),
            "color": _collapse_spaces(match.group(3)),
            "sire": _collapse_spaces(match.group(4)),
            "dam": _collapse_spaces(match.group(5)),
        }

    def _profile_fields(self, soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        for dl in soup.find_all("dl"):
            terms = dl.find_all("dt")
            values = dl.find_all("dd")
            for term, value in zip(terms, values):
                fields[_collapse_spaces(term.get_text(" ", strip=True))] = _collapse_spaces(value.get_text(" ", strip=True))
        text = _collapse_spaces(soup.get_text(" ", strip=True))
        for label in ("Musique", "Entraîneur", "Propriétaire", "Gains de carrière"):
            if fields.get(label):
                continue
            value = self._field_after(text, label)
            if value:
                fields[label] = value
        return fields

    def _field_after(self, text: str, label: str) -> str:
        labels = ("Musique", "Dernière course", "Entraîneur", "Propriétaire", "Gains de carrière")
        pattern = rf"{re.escape(label)}\s+(.+?)(?=\s+(?:{'|'.join(re.escape(item) for item in labels if item != label)})\s+|$)"
        match = re.search(pattern, text)
        return _collapse_spaces(match.group(1)) if match else ""

    def _is_french_meeting(self, venue: str) -> bool:
        return "(" not in venue and ")" not in venue

    def _link_kind(self, href: str) -> str:
        if "/partants-pmu/" in href:
            return "partants"
        if "/arrivee-et-rapports-pmu/" in href:
            return "results"
        return ""

    def _race_id_from_url(self, href: str) -> str:
        match = re.search(r"_c(\d+)", href)
        return match.group(1) if match else ""

    def _header_index(self, tr) -> dict[str, int]:
        return {self._normalize_header(cell.get_text(" ", strip=True)): idx for idx, cell in enumerate(tr.find_all(["th", "td"]))}

    def _normalize_header(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        asciiish = "".join(char for char in normalized if not unicodedata.combining(char))
        return _collapse_spaces(re.sub(r"[^a-z0-9 ]+", " ", asciiish.lower()))

    def _cell_node(self, cells: list, headers: dict[str, int], key: str, fallback_idx: int):
        idx = headers.get(key, fallback_idx)
        return cells[idx] if idx < len(cells) else None

    def _cell(self, cells: list, headers: dict[str, int], key: str, fallback_idx: int) -> str:
        node = self._cell_node(cells, headers, key, fallback_idx)
        return _collapse_spaces(node.get_text(" ", strip=True) if node else "")

    def _horse_id(self, onclick: str) -> str:
        match = re.search(r"/fr/cheval/(\d+)/course/", onclick) or re.search(r"_h(\d+)", onclick)
        return match.group(1) if match else ""

    def _horse_profile_path(self, onclick: str) -> str:
        match = re.search(r"'(/fr/cheval/\d+/course/\d+)'", onclick)
        return match.group(1) if match else ""

    def _sex_age(self, value: str) -> tuple[str, str]:
        match = re.match(r"([A-Z]+)(\d+)", value)
        if not match:
            return "", ""
        return match.group(1), match.group(2)


class FranceNetworkClient:
    user_agent = "umanewsbot/1.0 (+https://umafans.run; low-frequency data import)"

    def __init__(self, options: FranceImportOptions):
        self.options = options
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, *, target_type: str, target_id: str):
        if len(self.requests) >= self.options.max_requests:
            raise FranceImportError(f"France network import exceeded max_requests={self.options.max_requests}")
        if self.requests and self.options.request_interval_seconds > 0:
            time.sleep(self.options.request_interval_seconds)
        response = requests.get(url, timeout=20, headers={"User-Agent": self.user_agent})
        self.requests.append(
            {
                "url": getattr(response, "url", url),
                "status_code": response.status_code,
                "target_type": target_type,
                "target_id": target_id,
            }
        )
        if response.status_code >= 400:
            raise FranceImportError(f"France network import failed with HTTP {response.status_code}: {url}")
        return response


class FranceExternalDataImporter:
    source = FRANCE_EXTERNAL_SOURCE
    racing_region = RacingRegion.FRANCE
    source_language = SourceLanguage.FRENCH

    def __init__(self, options: FranceImportOptions | None = None):
        self.options = options or FranceImportOptions.from_settings()

    def import_race_date(self, race_date: str | date, *, limit_races: int | None = None) -> dict[str, Any]:
        if not self.options.allow_network:
            raise FranceImportError("France real import requires --allow-network")
        parsed = _parse_date(race_date) if isinstance(race_date, str) else race_date
        if not parsed:
            raise FranceImportError(f"invalid race_date: {race_date}")
        payload, requests_info = self._fetch_race_date_payload(parsed, limit_races=limit_races)
        result = self._import_payload("race_date", parsed.isoformat(), payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def _fetch_race_date_payload(self, race_date: date, *, limit_races: int | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        parser = FranceGalopHTMLParser()
        client = FranceNetworkClient(self.options)
        date_response = client.get(self._race_date_url(race_date), target_type="race_date", target_id=race_date.isoformat())
        meetings = parser.parse_meeting_links(date_response.text, race_date=race_date.isoformat(), source_url=client.requests[-1]["url"])
        races: list[dict[str, Any]] = []
        for meeting in meetings:
            if limit_races is not None and len(races) >= limit_races:
                break
            meeting_response = client.get(meeting["url"], target_type="meeting", target_id=meeting["meeting_id"])
            for race_link in parser.parse_race_detail_links(meeting_response.text, source_url=client.requests[-1]["url"]):
                if limit_races is not None and len(races) >= limit_races:
                    break
                race_response = client.get(race_link["url"], target_type="race", target_id=race_link["race_id"])
                races.append(parser.parse_race_detail(race_response.text, race_id=race_link["race_id"], source_url=client.requests[-1]["url"]))
        completion = {
            "is_complete": False if limit_races is not None and len(races) >= limit_races else True,
            "stop_reason": "limit_races_reached" if limit_races is not None and len(races) >= limit_races else "complete",
            "meetings_found": len(meetings),
            "races_imported": len(races),
            "horse_profile_source": "race_detail_rows",
            "max_requests": self.options.max_requests,
        }
        return {"races": races, "completion": completion}, client.requests

    def _payload_stats(self, payload: dict[str, Any]) -> dict[str, int]:
        races = [item for item in payload.get("races", []) if isinstance(item, dict)]
        entries = sum(len([item for item in race.get("entries", []) if isinstance(item, dict)]) for race in races)
        results = sum(len([item for item in race.get("results", []) if isinstance(item, dict)]) for race in races)
        horse_ids = set()
        for race in races:
            for runner in [*(race.get("entries") or []), *(race.get("results") or [])]:
                if isinstance(runner, dict) and _string(runner.get("horse_id")):
                    horse_ids.add(_string(runner.get("horse_id")))
        for horse in [item for item in payload.get("horses", []) if isinstance(item, dict)]:
            if _string(horse.get("horse_id")):
                horse_ids.add(_string(horse.get("horse_id")))
        return {"races": len(races), "entries": entries, "results": results, "horses": len(horse_ids)}

    def _import_payload(self, target_type: str, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        self._validate_completion_for_commit(completion)
        self._validate_payload_limits(stats)
        with transaction.atomic():
            lock, _ = ExternalDataImportLock.objects.select_for_update().get_or_create(
                source=self.source,
                defaults={"racing_region": self.racing_region},
            )
            if lock.locked_by_run and lock.locked_by_run.status == ExternalImportStatus.STARTED:
                raise FranceImportError(f"{self.source} import is already running")
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

    def _validate_completion_for_commit(self, completion: dict[str, Any]) -> None:
        if completion.get("is_complete") is not True:
            if completion.get("is_complete") is not False:
                raise FranceImportError("Cannot commit unverified France import; completion.is_complete must be true")
        if completion.get("is_complete") is False:
            stop_reason = _string(completion.get("stop_reason")) or "unknown"
            raise FranceImportError(f"Cannot commit incomplete France import; stop_reason={stop_reason}")
        stop_reason = _string(completion.get("stop_reason"))
        if stop_reason and stop_reason != "complete":
            raise FranceImportError(f"Cannot commit inconsistent France import; stop_reason={stop_reason}")
        if _completion_horse_detail_metadata_missing(completion):
            raise FranceImportError("Cannot commit unverified France import; horse detail coverage metadata is required")
        if _completion_horse_detail_gap(completion):
            raise FranceImportError("Cannot commit inconsistent France import; horse_profiles_fetched is below unique_horses_found")

    def _validate_payload_limits(self, stats: dict[str, int]) -> None:
        for key in ("races", "entries", "results", "horses"):
            if int(stats.get(key) or 0) <= 0:
                raise FranceImportError(f"France payload missing required coverage: {key}")
        if stats["races"] > self.options.max_races:
            raise FranceImportError(f"France payload has {stats['races']} races; max_races is {self.options.max_races}")
        if stats["horses"] > self.options.max_horses:
            raise FranceImportError(f"France payload has {stats['horses']} horses; max_horses is {self.options.max_horses}")

    def _upsert_payload(self, payload: dict[str, Any]) -> int:
        written = 0
        horse_payloads: dict[str, dict[str, Any]] = {}
        for race_payload in payload.get("races", []):
            race = self._upsert_race(race_payload)
            written += 1
            for entry_payload in race_payload.get("entries") or []:
                self._upsert_entry(race, entry_payload)
                written += 1
                self._remember_horse_payload(horse_payloads, entry_payload)
            for result_payload in race_payload.get("results") or []:
                self._upsert_result(race, result_payload)
                written += 1
                self._remember_horse_payload(horse_payloads, result_payload)
        for horse_payload in payload.get("horses", []):
            self._remember_horse_payload(horse_payloads, horse_payload)
        for horse_payload in horse_payloads.values():
            self._upsert_horse(horse_payload)
            written += 1
            self._upsert_alias_from_payload(horse_payload)
        return written

    def _remember_horse_payload(self, horses: dict[str, dict[str, Any]], payload: dict[str, Any]) -> None:
        horse_id = _string(payload.get("horse_id"))
        if not horse_id:
            return
        horses.setdefault(horse_id, {}).update({key: value for key, value in payload.items() if value not in (None, "")})

    def _upsert_race(self, payload: dict[str, Any]) -> ExternalRace:
        race, _ = ExternalRace.objects.update_or_create(
            source=self.source,
            race_id=_string(payload.get("race_id")),
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race_name": _string(payload.get("race_name")),
                "race_date": _parse_date(payload.get("race_date")),
                "venue": _string(payload.get("venue")),
                "race_number": _string(payload.get("race_number")),
                "surface": _string(payload.get("surface")),
                "distance": _string(payload.get("distance")),
                "going": _string(payload.get("going")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )
        return race

    def _upsert_entry(self, race: ExternalRace, payload: dict[str, Any]) -> None:
        horse_id = _string(payload.get("horse_id"))
        horse_name = _string(payload.get("horse_name_en") or payload.get("horse_name"))
        entry_key = _string(payload.get("horse_number") or horse_id or horse_name)
        ExternalRaceEntry.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            entry_key=entry_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": horse_name,
                "normalized_horse_name": _normalize_name(horse_name),
                "horse_number": _string(payload.get("horse_number")),
                "barrier": _string(payload.get("barrier")),
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
                "carried_weight": _string(payload.get("weight")),
                "rating": _string(payload.get("rating")),
                "owner_name": _string(payload.get("owner")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )

    def _upsert_result(self, race: ExternalRace, payload: dict[str, Any]) -> None:
        horse_id = _string(payload.get("horse_id"))
        horse_name = _string(payload.get("horse_name_en") or payload.get("horse_name"))
        result_key = _string(payload.get("finish_position") or horse_id or horse_name)
        ExternalRaceResult.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            result_key=result_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": horse_name,
                "normalized_horse_name": _normalize_name(horse_name),
                "horse_number": _string(payload.get("horse_number")),
                "finish_position": _string(payload.get("finish_position")),
                "margin": _string(payload.get("margin")),
                "odds_value": _string(payload.get("odds")),
                "barrier": _string(payload.get("barrier")),
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )

    def _upsert_horse(self, payload: dict[str, Any]) -> ExternalHorse:
        horse_id = _string(payload.get("horse_id"))
        horse_name = _string(payload.get("horse_name_en") or payload.get("horse_name") or payload.get("name"))
        horse, _ = ExternalHorse.objects.update_or_create(
            source=self.source,
            horse_id=horse_id,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "horse_name": horse_name,
                "horse_name_en": horse_name,
                "normalized_horse_name": _normalize_name(horse_name),
                "sex": _string(payload.get("sex")),
                "color": _string(payload.get("color")),
                "father_name": _string(payload.get("sire")),
                "mother_name": _string(payload.get("dam")),
                "owner_name": _string(payload.get("owner")),
                "trainer_name": _string(payload.get("trainer")),
                "record_summary": _string(payload.get("record_summary")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )
        return horse

    def _upsert_alias_from_payload(self, payload: dict[str, Any]) -> None:
        horse_id = _string(payload.get("horse_id"))
        name = _string(payload.get("horse_name_en") or payload.get("horse_name") or payload.get("name"))
        if not horse_id or not name:
            return
        horse = ExternalHorse.objects.filter(source=self.source, horse_id=horse_id).first()
        ExternalHorseAlias.objects.update_or_create(
            source=self.source,
            external_horse_id=horse_id,
            normalized_name=_normalize_name(name),
            defaults={
                "horse": horse,
                "racing_region": self.racing_region,
                "source_language": SourceLanguage.FRENCH,
                "name_ja": name,
                "name_en": name,
                "confidence": 100,
                "alias_source": self.source,
                "last_seen_at": timezone.now(),
            },
        )

    def _base_url(self) -> str:
        return _string(getattr(settings, "FRANCE_IMPORT_NETWORK_BASE_URL", "https://www.france-galop.com")).rstrip("/")

    def _race_date_url(self, race_date: date) -> str:
        if race_date == date(2026, 6, 26):
            return f"{self._base_url()}/en/racing/today"
        return f"{self._base_url()}/en/racing/other-dates?date={race_date.isoformat()}"


class GenyFranceExternalDataImporter:
    source = GENY_FRANCE_EXTERNAL_SOURCE
    racing_region = RacingRegion.FRANCE
    source_language = SourceLanguage.FRENCH

    def __init__(self, options: FranceImportOptions | None = None):
        self.options = options or FranceImportOptions.from_settings()

    def import_race_date(
        self,
        race_date: str | date,
        *,
        limit_races: int | None = None,
        skip_races: int = 0,
        limit_horses: int | None = None,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise FranceImportError("Geny France real import requires --allow-network")
        parsed = _parse_date(race_date) if isinstance(race_date, str) else race_date
        if not parsed:
            raise FranceImportError(f"invalid race_date: {race_date}")
        payload, requests_info = self._fetch_date_range_payload(parsed, parsed, limit_races=limit_races, skip_races=skip_races, limit_horses=limit_horses)
        result = self._import_payload("race_date", parsed.isoformat(), payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def import_recent_days(
        self,
        days: int,
        *,
        end_date: str | date | None = None,
        limit_races: int | None = None,
        skip_races: int = 0,
        limit_horses: int | None = None,
    ) -> dict[str, Any]:
        if days <= 0:
            raise FranceImportError("recent days must be positive")
        end = _parse_date(end_date) if end_date else timezone.localdate()
        if not end:
            raise FranceImportError(f"invalid end_date: {end_date}")
        start = end - timedelta(days=days - 1)
        return self.import_date_range(start, end, limit_races=limit_races, skip_races=skip_races, limit_horses=limit_horses)

    def plan_recent_days(
        self,
        days: int,
        *,
        end_date: str | date | None = None,
        batch_size: int = 20,
    ) -> dict[str, Any]:
        if days <= 0:
            raise FranceImportError("recent days must be positive")
        end = _parse_date(end_date) if end_date else timezone.localdate()
        if not end:
            raise FranceImportError(f"invalid end_date: {end_date}")
        start = end - timedelta(days=days - 1)
        return self.plan_date_range(start, end, batch_size=batch_size)

    def plan_date_range(
        self,
        start_date: str | date,
        end_date: str | date,
        *,
        batch_size: int = 20,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise FranceImportError("Geny France real import requires --allow-network")
        if batch_size <= 0:
            raise FranceImportError("batch_size must be positive")
        start = _parse_date(start_date) if isinstance(start_date, str) else start_date
        end = _parse_date(end_date) if isinstance(end_date, str) else end_date
        if not start or not end or start > end:
            raise FranceImportError("invalid date range")
        race_links, requests_info = self._fetch_race_links(start, end, race_links_needed=None)
        batches = []
        for offset in range(0, len(race_links), batch_size):
            batch_links = race_links[offset : offset + batch_size]
            batches.append(
                {
                    "batch_index": len(batches) + 1,
                    "skip_races": offset,
                    "limit_races": len(batch_links),
                    "race_ids": [link["race_id"] for link in batch_links],
                    "partants_urls": [link["partants_url"] for link in batch_links],
                    "results_urls": [link["results_url"] for link in batch_links],
                }
            )
        return {
            "source": self.source,
            "target_type": "date_range",
            "target_id": f"{start.isoformat()}..{end.isoformat()}",
            "dry_run": True,
            "plan_only": True,
            "coverage_stats": {"races": len(race_links), "entries": 0, "results": 0, "horses": 0},
            "completion": {
                "is_complete": True,
                "stop_reason": "plan_only",
                "race_links_found": len(race_links),
                "batch_size": batch_size,
                "batches": len(batches),
                "horse_profile_source": "geny_partants_rows",
                "max_requests": self.options.max_requests,
            },
            "would_write_formal_tables": False,
            "network_probe": True,
            "requests": requests_info,
            "batches": batches,
        }

    def import_date_range(
        self,
        start_date: str | date,
        end_date: str | date,
        *,
        limit_races: int | None = None,
        skip_races: int = 0,
        limit_horses: int | None = None,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise FranceImportError("Geny France real import requires --allow-network")
        start = _parse_date(start_date) if isinstance(start_date, str) else start_date
        end = _parse_date(end_date) if isinstance(end_date, str) else end_date
        if not start or not end or start > end:
            raise FranceImportError("invalid date range")
        payload, requests_info = self._fetch_date_range_payload(start, end, limit_races=limit_races, skip_races=skip_races, limit_horses=limit_horses)
        result = self._import_payload("date_range", f"{start.isoformat()}..{end.isoformat()}", payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def import_partants_urls(
        self,
        partants_urls: list[str],
        *,
        limit_horses: int | None = None,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise FranceImportError("Geny France real import requires --allow-network")
        urls = [_string(url) for url in partants_urls if _string(url)]
        if not urls:
            raise FranceImportError("partants_urls must not be empty")
        payload, requests_info = self._fetch_partants_urls_payload(urls, limit_horses=limit_horses)
        race_ids = [_string(race.get("race_id")) for race in payload.get("races", []) if isinstance(race, dict)]
        result = self._import_payload("partants_urls", ",".join(race_ids), payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def _fetch_race_links(
        self,
        start_date: date,
        end_date: date,
        *,
        race_links_needed: int | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        parser = GenyFranceHTMLParser()
        client = FranceNetworkClient(self.options)
        race_links: list[dict[str, Any]] = []
        cursor = start_date
        while cursor <= end_date:
            date_response = client.get(self._race_date_url(cursor), target_type="race_date", target_id=cursor.isoformat())
            race_links.extend(parser.parse_race_links(date_response.text, race_date=cursor.isoformat(), source_url=client.requests[-1]["url"]))
            if race_links_needed is not None and len(race_links) >= race_links_needed:
                break
            cursor += timedelta(days=1)
        return race_links, client.requests

    def _fetch_date_range_payload(
        self,
        start_date: date,
        end_date: date,
        *,
        limit_races: int | None,
        skip_races: int,
        limit_horses: int | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if skip_races < 0:
            raise FranceImportError("skip_races must be non-negative")
        parser = GenyFranceHTMLParser()
        race_links_needed = None if limit_races is None else skip_races + limit_races
        race_links, requests_info = self._fetch_race_links(start_date, end_date, race_links_needed=race_links_needed)
        client = FranceNetworkClient(self.options)
        client.requests = requests_info
        available_links = race_links[skip_races:]
        selected_links = available_links[:limit_races] if limit_races is not None else available_links
        races: list[dict[str, Any]] = []
        for race_link in selected_links:
            try:
                partants_response = client.get(race_link["partants_url"], target_type="partants", target_id=race_link["race_id"])
            except FranceImportError:
                if self._last_status_code(client) == 429:
                    return self._payload(race_links, selected_links, races, [], limit_races, skip_races, limit_horses, stop_reason="rate_limited"), client.requests
                raise
            race = parser.parse_partants(partants_response.text, race_link={**race_link, "partants_url": client.requests[-1]["url"]})
            try:
                results_response = client.get(race_link["results_url"], target_type="results", target_id=race_link["race_id"])
            except FranceImportError:
                if self._last_status_code(client) == 429:
                    races.append(race)
                    return self._payload(race_links, selected_links, races, [], limit_races, skip_races, limit_horses, stop_reason="rate_limited"), client.requests
                raise
            race["results"] = parser.parse_results(results_response.text)
            races.append(race)
        horse_ids = self._unique_horse_ids(races)
        horses = (
            self._fetch_horse_profiles(parser, client, horse_ids, limit_horses=limit_horses)
            if limit_horses is not None
            else []
        )
        return self._payload(race_links, selected_links, races, horses, limit_races, skip_races, limit_horses), client.requests

    def _fetch_partants_urls_payload(
        self,
        partants_urls: list[str],
        *,
        limit_horses: int | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        parser = GenyFranceHTMLParser()
        client = FranceNetworkClient(self.options)
        race_links = [self._race_link_from_partants_url(url, parser=parser) for url in dict.fromkeys(partants_urls)]
        races: list[dict[str, Any]] = []
        for race_link in race_links:
            try:
                partants_response = client.get(race_link["partants_url"], target_type="partants", target_id=race_link["race_id"])
            except FranceImportError:
                if self._last_status_code(client) == 429:
                    return self._payload(race_links, race_links, races, [], None, 0, limit_horses, stop_reason="rate_limited"), client.requests
                raise
            race = parser.parse_partants(partants_response.text, race_link={**race_link, "partants_url": client.requests[-1]["url"]})
            try:
                results_response = client.get(race_link["results_url"], target_type="results", target_id=race_link["race_id"])
            except FranceImportError:
                if self._last_status_code(client) == 429:
                    races.append(race)
                    return self._payload(race_links, race_links, races, [], None, 0, limit_horses, stop_reason="rate_limited"), client.requests
                raise
            race["results"] = parser.parse_results(results_response.text)
            races.append(race)
        horse_ids = self._unique_horse_ids(races)
        horses = (
            self._fetch_horse_profiles(parser, client, horse_ids, limit_horses=limit_horses)
            if limit_horses is not None
            else []
        )
        payload = self._payload(race_links, race_links, races, horses, None, 0, limit_horses)
        payload["completion"]["race_ids_selected"] = [_string(race.get("race_id")) for race in races]
        return payload, client.requests

    def _race_link_from_partants_url(self, partants_url: str, *, parser: GenyFranceHTMLParser) -> dict[str, Any]:
        race_id = parser._race_id_from_url(partants_url)
        if not race_id:
            raise FranceImportError(f"invalid Geny partants URL: {partants_url}")
        parsed_date = self._date_from_partants_url(partants_url)
        slug = partants_url.rstrip("/").split("/")[-1]
        race_name_slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
        race_name_slug = re.sub(r"_c\d+$", "", race_name_slug)
        race_name = _collapse_spaces(race_name_slug.replace("-", " ")).title()
        return {
            "race_id": f"GENY{race_id}",
            "race_date": parsed_date.isoformat() if parsed_date else "",
            "venue": "",
            "meeting_number": "",
            "race_number": "",
            "race_name": race_name,
            "partants_url": partants_url,
            "results_url": self._results_url_from_partants_url(partants_url),
        }

    def _date_from_partants_url(self, partants_url: str) -> date | None:
        match = re.search(r"/partants-pmu/(\d{4}-\d{2}-\d{2})-", partants_url)
        return _parse_date(match.group(1)) if match else None

    def _results_url_from_partants_url(self, partants_url: str) -> str:
        results_url = partants_url.replace("/partants-pmu/", "/arrivee-et-rapports-pmu/")
        return re.sub(r"(/arrivee-et-rapports-pmu/\d{4}-\d{2}-\d{2})-[^-]+-pmu-", r"\1-pmu-", results_url)

    def _unique_horse_ids(self, races: list[dict[str, Any]]) -> list[dict[str, str]]:
        horses: list[dict[str, str]] = []
        seen: set[str] = set()
        for race in races:
            for runner in [*(race.get("entries") or []), *(race.get("results") or [])]:
                if not isinstance(runner, dict):
                    continue
                horse_id = _string(runner.get("horse_id"))
                if not horse_id or horse_id in seen:
                    continue
                seen.add(horse_id)
                raw_payload = runner.get("raw_payload") if isinstance(runner.get("raw_payload"), dict) else {}
                horses.append(
                    {
                        "horse_id": horse_id,
                        "horse_profile_url": _string(raw_payload.get("horse_profile_url")),
                    }
                )
        return horses

    def _fetch_horse_profiles(
        self,
        parser: GenyFranceHTMLParser,
        client: FranceNetworkClient,
        horse_ids: list[dict[str, str]],
        *,
        limit_horses: int | None,
    ) -> list[dict[str, Any]]:
        horses: list[dict[str, Any]] = []
        for horse in horse_ids:
            if limit_horses is not None and len(horses) >= limit_horses:
                break
            profile_url = horse.get("horse_profile_url")
            horse_id = _string(horse.get("horse_id"))
            if not horse_id or not profile_url:
                continue
            response = client.get(profile_url, target_type="horse", target_id=horse_id)
            horses.append(parser.parse_horse_profile(response.text, horse_id=horse_id, source_url=client.requests[-1]["url"]))
        return horses

    def _payload(
        self,
        race_links: list[dict[str, Any]],
        selected_links: list[dict[str, Any]],
        races: list[dict[str, Any]],
        horses: list[dict[str, Any]],
        limit_races: int | None,
        skip_races: int,
        limit_horses: int | None,
        *,
        stop_reason: str | None = None,
    ) -> dict[str, Any]:
        unique_horses_found = len(self._unique_horse_ids(races))
        reached_limit = limit_races is not None and len(selected_links) >= limit_races
        horse_limit_reached = limit_horses is not None and len(horses) < unique_horses_found
        resolved_stop_reason = stop_reason or ("limit_horses_reached" if horse_limit_reached else "limit_races_reached" if reached_limit else "complete")
        completion = {
            "is_complete": False if stop_reason else not reached_limit and not horse_limit_reached,
            "stop_reason": resolved_stop_reason,
            "race_links_found": len(race_links),
            "race_links_selected": len(selected_links),
            "skip_races": skip_races,
            "races_imported": len(races),
            "unique_horses_found": unique_horses_found,
            "horse_profiles_fetched": len(horses),
            "limit_horses": limit_horses,
            "horse_profile_source": "geny_partants_rows",
            "max_requests": self.options.max_requests,
        }
        return {"races": races, "horses": horses, "completion": completion}

    def _last_status_code(self, client: FranceNetworkClient) -> int | None:
        return client.requests[-1]["status_code"] if client.requests else None

    def _payload_stats(self, payload: dict[str, Any]) -> dict[str, int]:
        return FranceExternalDataImporter(self.options)._payload_stats(payload)

    def _import_payload(self, target_type: str, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        helper = FranceExternalDataImporter(self.options)
        helper.source = self.source
        helper.racing_region = self.racing_region
        helper.source_language = self.source_language
        return helper._import_payload(target_type, target_id, payload)

    def _base_url(self) -> str:
        return _string(getattr(settings, "GENY_FRANCE_IMPORT_NETWORK_BASE_URL", "https://www.geny.com")).rstrip("/")

    def _race_date_url(self, race_date: date) -> str:
        return f"{self._base_url()}/reunions-courses-pmu/_d{race_date.isoformat()}"
