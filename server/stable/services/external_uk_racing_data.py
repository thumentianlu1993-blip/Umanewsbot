from __future__ import annotations

import re
import time
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


UK_EXTERNAL_SOURCE = "sporting_life"

UK_SPORTING_LIFE_VENUE_SLUGS = {
    "aintree",
    "ascot",
    "ayr",
    "bangor-on-dee",
    "bath",
    "beverley",
    "brighton",
    "carlisle",
    "cartmel",
    "catterick",
    "chelmsford-city",
    "chepstow",
    "chester",
    "doncaster",
    "epsom",
    "exeter",
    "ffos-las",
    "fontwell",
    "goodwood",
    "great-yarmouth",
    "hamilton",
    "haydock",
    "hereford",
    "hexham",
    "huntingdon",
    "kelso",
    "kempton",
    "leicester",
    "lingfield",
    "ludlow",
    "market-rasen",
    "musselburgh",
    "newbury",
    "newcastle",
    "newmarket",
    "newton-abbot",
    "nottingham",
    "perth",
    "plumpton",
    "pontefract",
    "redcar",
    "ripon",
    "salisbury",
    "sandown",
    "sedgefield",
    "southwell",
    "stratford",
    "taunton",
    "thirsk",
    "uttoxeter",
    "warwick",
    "wetherby",
    "wincanton",
    "windsor",
    "wolverhampton",
    "worcester",
    "yarmouth",
    "york",
}


class UKImportError(Exception):
    pass


@dataclass(frozen=True)
class UKImportOptions:
    dry_run: bool = True
    allow_network: bool = False
    request_interval_seconds: float = 8
    max_races: int = 20
    max_horses: int = 80
    max_requests: int = 200

    @classmethod
    def from_settings(cls, **overrides: Any) -> "UKImportOptions":
        values = {
            "request_interval_seconds": getattr(settings, "UK_IMPORT_REQUEST_INTERVAL_SECONDS", 8),
            "max_races": getattr(settings, "UK_IMPORT_MAX_RACES_PER_RUN", 20),
            "max_horses": getattr(settings, "UK_IMPORT_MAX_HORSES_PER_RUN", 80),
            "max_requests": getattr(settings, "UK_IMPORT_MAX_REQUESTS_PER_RUN", 200),
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


def _parse_date(value: Any):
    raw = _string(value)
    if not raw:
        return None
    parsed = dateparse.parse_date(raw.replace("/", "-"))
    if parsed:
        return parsed
    return None


def _normalize_name(value: str) -> str:
    return _collapse_spaces(value)


class SportingLifeHTMLParser:
    def parse_result_race_links(self, html: str, *, source_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        pattern = re.compile(r"/racing/racecards/(\d{4}-\d{2}-\d{2})/([^/]+)/racecard/(\d+)/[^\"'<> ]*")
        for anchor in soup.find_all("a", href=True):
            href = _string(anchor.get("href"))
            match = pattern.search(href)
            if not match:
                continue
            race_id = f"SL{match.group(3)}"
            if race_id in seen:
                continue
            seen.add(race_id)
            links.append(
                {
                    "race_id": race_id,
                    "race_date": match.group(1),
                    "venue": match.group(2),
                    "race_no": match.group(3),
                    "url": urljoin(source_url, href),
                }
            )
        return links

    def parse_racecard(
        self,
        html: str,
        *,
        race_id: str,
        race_date: str,
        venue: str,
        source_url: str,
    ) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        title = _collapse_spaces((soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""))
        detail_text = _collapse_spaces(soup.get_text(" ", strip=True))
        race = {
            "race_id": _string(race_id),
            "race_date": _string(race_date),
            "venue": _string(venue),
            "race_number": _string(race_id).removeprefix("SL"),
            "race_name": title,
            "race_class": self._first_match(detail_text, r"\b(Class\s+\d+)\b"),
            "distance": self._first_match(detail_text, r"\b(\d+m\s+\d+f|\d+m|\d+f)\b"),
            "going": self._first_match(detail_text, r"\b(Good to Firm|Good to Soft|Good|Soft|Heavy|Standard)\b"),
            "surface": self._first_match(detail_text, r"\b(Turf|Dirt|AW)\b"),
            "prize_money": self._first_match(detail_text, r"Winner\s+£[0-9,]+"),
            "entries": [],
            "results": [],
            "raw_payload": {"source_url": source_url},
        }
        rows = self._runner_rows(soup)
        if not rows:
            rows = self._runner_rows_from_links(soup)
        for row in rows:
            race["entries"].append(row)
            race["results"].append(
                {
                    **row,
                    "finish_position": row.get("finish_position", ""),
                    "odds": row.get("odds", ""),
                }
            )
        return race

    def parse_horse_profile(self, html: str, *, horse_id: str, source_url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        title = _collapse_spaces((soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""))
        name = re.sub(r"\s+Race Record.*$", "", title, flags=re.IGNORECASE).strip()
        fields = self._dl_fields(soup)
        return {
            "horse_id": _string(horse_id),
            "horse_name_en": name,
            "age": fields.get("Age", ""),
            "sex": fields.get("Sex", ""),
            "trainer": fields.get("Trainer", ""),
            "owner": fields.get("Owner", ""),
            "sire": fields.get("Sire", ""),
            "dam": fields.get("Dam", ""),
            "country": fields.get("Country", ""),
            "record_summary": fields.get("Form", ""),
            "raw_payload": {"source_url": source_url, "fields": fields},
        }

    def _runner_rows(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for table in soup.find_all("table"):
            table_rows = table.find_all("tr")
            if not table_rows:
                continue
            headers = [_collapse_spaces(cell.get_text(" ", strip=True)).lower() for cell in table_rows[0].find_all(["th", "td"])]
            if "horse" not in headers:
                continue
            index = {header: idx for idx, header in enumerate(headers)}
            for tr in table_rows[1:]:
                cells = tr.find_all(["td", "th"])
                if not cells:
                    continue
                horse_cell = cells[index["horse"]] if index["horse"] < len(cells) else None
                horse_link = horse_cell.find("a", href=True) if horse_cell else None
                horse_href = _string(horse_link.get("href") if horse_link else "")
                horse_id = self._horse_id_from_url(horse_href)
                horse_name = _collapse_spaces(horse_link.get_text(" ", strip=True) if horse_link else horse_cell.get_text(" ", strip=True))
                if not horse_id and not horse_name:
                    continue
                rows.append(
                    {
                        "horse_id": horse_id,
                        "horse_name_en": horse_name,
                        "horse_number": self._cell(cells, index, "no"),
                        "finish_position": self._cell(cells, index, "pos"),
                        "jockey": self._cell(cells, index, "jockey"),
                        "trainer": self._cell(cells, index, "trainer"),
                        "barrier": self._cell(cells, index, "draw"),
                        "odds": self._cell(cells, index, "sp"),
                        "raw_payload": {"horse_href": horse_href},
                    }
                )
            break
        return rows

    def _runner_rows_from_links(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            horse_id = self._horse_id_from_url(_string(anchor.get("href")))
            name = _collapse_spaces(anchor.get_text(" ", strip=True))
            if not horse_id or horse_id in seen:
                continue
            seen.add(horse_id)
            rows.append(
                {
                    "horse_id": horse_id,
                    "horse_name_en": name,
                    "raw_payload": {"horse_href": _string(anchor.get("href"))},
                }
            )
        return rows

    def _dl_fields(self, soup: BeautifulSoup) -> dict[str, str]:
        fields: dict[str, str] = {}
        for dl in soup.find_all("dl"):
            terms = dl.find_all("dt")
            values = dl.find_all("dd")
            for term, value in zip(terms, values):
                fields[_collapse_spaces(term.get_text(" ", strip=True))] = _collapse_spaces(value.get_text(" ", strip=True))
        return fields

    def _cell(self, cells: list, index: dict[str, int], header: str) -> str:
        idx = index.get(header)
        if idx is None or idx >= len(cells):
            return ""
        return _collapse_spaces(cells[idx].get_text(" ", strip=True))

    def _first_match(self, text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        return _collapse_spaces(match.group(1) if match.groups() else match.group(0)) if match else ""

    def _horse_id_from_url(self, url: str) -> str:
        match = re.search(r"/racing/profiles/horse/(\d+)", url)
        return match.group(1) if match else ""


class UKNetworkClient:
    user_agent = "umanewsbot/1.0 (+https://umafans.run; low-frequency data import)"

    def __init__(self, options: UKImportOptions):
        self.options = options
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, *, target_type: str, target_id: str):
        if len(self.requests) >= self.options.max_requests:
            raise UKImportError(f"UK network import exceeded max_requests={self.options.max_requests}")
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
            raise UKImportError(f"UK network import failed with HTTP {response.status_code}: {url}")
        return response


class UKExternalDataImporter:
    source = UK_EXTERNAL_SOURCE
    racing_region = RacingRegion.UNITED_KINGDOM
    source_language = SourceLanguage.ENGLISH

    def __init__(self, options: UKImportOptions | None = None):
        self.options = options or UKImportOptions.from_settings()

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
            raise UKImportError("recent days must be positive")
        end = _parse_date(end_date) if end_date else timezone.localdate()
        if not end:
            raise UKImportError(f"invalid end_date: {end_date}")
        start = end - timedelta(days=days - 1)
        return self.import_date_range(start, end, limit_races=limit_races, limit_horses=limit_horses, skip_races=skip_races)

    def plan_recent_days(
        self,
        days: int,
        *,
        end_date: str | date | None = None,
        batch_size: int = 20,
    ) -> dict[str, Any]:
        if days <= 0:
            raise UKImportError("recent days must be positive")
        end = _parse_date(end_date) if end_date else timezone.localdate()
        if not end:
            raise UKImportError(f"invalid end_date: {end_date}")
        start = end - timedelta(days=days - 1)
        return self.plan_date_range(start, end, batch_size=batch_size)

    def plan_date_range(self, start_date: str | date, end_date: str | date, *, batch_size: int = 20) -> dict[str, Any]:
        if not self.options.allow_network:
            raise UKImportError("UK real import requires --allow-network")
        if batch_size <= 0:
            raise UKImportError("batch_size must be positive")
        start = _parse_date(start_date) if isinstance(start_date, str) else start_date
        end = _parse_date(end_date) if isinstance(end_date, str) else end_date
        if not start or not end:
            raise UKImportError("invalid date range")
        race_links, requests_info = self._fetch_race_links(start, end)
        batches = []
        for offset in range(0, len(race_links), batch_size):
            batch_links = race_links[offset : offset + batch_size]
            batches.append(
                {
                    "batch_index": len(batches) + 1,
                    "skip_races": offset,
                    "limit_races": len(batch_links),
                    "race_ids": [link["race_id"] for link in batch_links],
                    "race_urls": [link["url"] for link in batch_links],
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
        limit_horses: int | None = None,
        skip_races: int = 0,
    ) -> dict:
        if not self.options.allow_network:
            raise UKImportError("UK real import requires --allow-network")
        start = _parse_date(start_date) if isinstance(start_date, str) else start_date
        end = _parse_date(end_date) if isinstance(end_date, str) else end_date
        if not start or not end:
            raise UKImportError("invalid date range")
        payload, requests_info = self._fetch_date_range_payload(start, end, limit_races=limit_races, limit_horses=limit_horses, skip_races=skip_races)
        result = self._import_payload("date_range", f"{start.isoformat()}..{end.isoformat()}", payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def import_race_urls(
        self,
        race_urls: list[str],
        *,
        limit_horses: int | None = None,
    ) -> dict:
        if not self.options.allow_network:
            raise UKImportError("UK real import requires --allow-network")
        race_links = [self._race_link_from_url(url) for url in race_urls if _string(url)]
        if not race_links:
            raise UKImportError("race_urls must not be empty")
        payload, requests_info = self._fetch_race_links_payload(race_links, limit_horses=limit_horses)
        target_id = ",".join(link["race_id"] for link in race_links)
        result = self._import_payload("race_urls", target_id, payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def _fetch_date_range_payload(
        self,
        start_date: date,
        end_date: date,
        *,
        limit_races: int | None,
        limit_horses: int | None,
        skip_races: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if skip_races < 0:
            raise UKImportError("skip_races must be non-negative")
        parser = SportingLifeHTMLParser()
        client = UKNetworkClient(self.options)
        race_links_needed = None if limit_races is None else skip_races + limit_races
        race_links = self._fetch_race_links_with_client(parser, client, start_date, end_date, race_links_needed=race_links_needed)
        selected_race_links = race_links[skip_races:]
        if limit_races is not None:
            selected_race_links = selected_race_links[:limit_races]
        payload, requests_info = self._fetch_race_links_payload(
            selected_race_links,
            limit_horses=limit_horses,
            parser=parser,
            client=client,
            all_race_links=race_links,
            skip_races=skip_races,
            limit_races=limit_races,
        )
        payload["raw_payload"].update(
            {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "skip_races": skip_races,
            }
        )
        return payload, requests_info

    def _fetch_race_links_payload(
        self,
        selected_race_links: list[dict[str, str]],
        *,
        limit_horses: int | None,
        parser: SportingLifeHTMLParser | None = None,
        client: UKNetworkClient | None = None,
        all_race_links: list[dict[str, str]] | None = None,
        skip_races: int = 0,
        limit_races: int | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        parser = parser or SportingLifeHTMLParser()
        client = client or UKNetworkClient(self.options)
        race_links = all_race_links if all_race_links is not None else selected_race_links
        races: list[dict[str, Any]] = []
        horse_ids: list[str] = []
        seen_horse_ids: set[str] = set()
        for link in selected_race_links:
            response = client.get(link["url"], target_type="race", target_id=link["race_id"])
            race = parser.parse_racecard(
                response.text,
                race_id=link["race_id"],
                race_date=link["race_date"],
                venue=link["venue"],
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
            response = client.get(self._horse_url(horse_id), target_type="horse", target_id=horse_id)
            horses.append(parser.parse_horse_profile(response.text, horse_id=horse_id, source_url=client.requests[-1]["url"]))
        completion = self._completion(
            race_links=race_links,
            races=races,
            horse_ids=horse_ids,
            horses=horses,
            limit_races=limit_races,
            limit_horses=limit_horses,
            skip_races=skip_races,
            race_links_selected=len(selected_race_links),
        )
        return (
            {
                "races": races,
                "horses": horses,
                "completion": completion,
                "raw_payload": {
                    "limit_races": limit_races,
                    "limit_horses": limit_horses,
                    "skip_races": skip_races,
                    "race_urls": [link["url"] for link in selected_race_links],
                },
            },
            client.requests,
        )

    def _fetch_race_links(self, start_date: date, end_date: date) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        parser = SportingLifeHTMLParser()
        client = UKNetworkClient(self.options)
        race_links = self._fetch_race_links_with_client(parser, client, start_date, end_date, race_links_needed=None)
        return race_links, client.requests

    def _fetch_race_links_with_client(
        self,
        parser: SportingLifeHTMLParser,
        client: UKNetworkClient,
        start_date: date,
        end_date: date,
        *,
        race_links_needed: int | None,
    ) -> list[dict[str, str]]:
        race_links: list[dict[str, str]] = []
        cursor = start_date
        while cursor <= end_date:
            result_url = self._result_date_url(cursor)
            response = client.get(result_url, target_type="result_date", target_id=cursor.isoformat())
            for link in parser.parse_result_race_links(response.text, source_url=client.requests[-1]["url"]):
                if link["venue"] not in UK_SPORTING_LIFE_VENUE_SLUGS:
                    continue
                race_links.append(link)
                if race_links_needed is not None and len(race_links) >= race_links_needed:
                    break
            if race_links_needed is not None and len(race_links) >= race_links_needed:
                break
            cursor += timedelta(days=1)
        return race_links

    def _completion(
        self,
        *,
        race_links: list[dict[str, str]],
        races: list[dict[str, Any]],
        horse_ids: list[str],
        horses: list[dict[str, Any]],
        limit_races: int | None,
        limit_horses: int | None,
        skip_races: int = 0,
        race_links_selected: int | None = None,
    ) -> dict[str, Any]:
        stop_reason = "complete"
        is_complete = True
        if limit_races is not None and (race_links_selected or 0) >= limit_races:
            stop_reason = "limit_races_reached"
            is_complete = False
        if limit_horses is not None and len(horses) < len(horse_ids):
            stop_reason = "limit_horses_reached"
            is_complete = False
        return {
            "is_complete": is_complete,
            "stop_reason": stop_reason,
            "races_imported": len(races),
            "unique_horses_found": len(horse_ids),
            "horse_profiles_fetched": len(horses),
            "limit_races": limit_races,
            "limit_horses": limit_horses,
            "skip_races": skip_races,
            "race_links_found": len(race_links),
            "race_links_selected": race_links_selected if race_links_selected is not None else len(race_links),
            "max_requests": self.options.max_requests,
        }

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
                raise UKImportError(f"{self.source} import is already running")
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
                raise UKImportError("Cannot commit unverified UK import; completion.is_complete must be true")
        if completion.get("is_complete") is False:
            stop_reason = _string(completion.get("stop_reason")) or "unknown"
            raise UKImportError(f"Cannot commit incomplete UK import; stop_reason={stop_reason}")
        stop_reason = _string(completion.get("stop_reason"))
        if stop_reason and stop_reason != "complete":
            raise UKImportError(f"Cannot commit inconsistent UK import; stop_reason={stop_reason}")
        if _completion_horse_detail_metadata_missing(completion):
            raise UKImportError("Cannot commit unverified UK import; horse detail coverage metadata is required")
        if _completion_horse_detail_gap(completion):
            raise UKImportError("Cannot commit inconsistent UK import; horse_profiles_fetched is below unique_horses_found")

    def _payload_stats(self, payload: dict[str, Any]) -> dict[str, int]:
        races = [item for item in payload.get("races", []) if isinstance(item, dict)]
        horses = [item for item in payload.get("horses", []) if isinstance(item, dict)]
        entries = sum(len([item for item in race.get("entries", []) if isinstance(item, dict)]) for race in races)
        results = sum(len([item for item in race.get("results", []) if isinstance(item, dict)]) for race in races)
        horse_ids = {_string(horse.get("horse_id")) for horse in horses if isinstance(horse, dict)}
        for race in races:
            for runner in [*(race.get("entries") or []), *(race.get("results") or [])]:
                if isinstance(runner, dict) and _string(runner.get("horse_id")):
                    horse_ids.add(_string(runner.get("horse_id")))
        return {"races": len(races), "entries": entries, "results": results, "horses": len(horse_ids)}

    def _validate_payload_limits(self, stats: dict[str, int]) -> None:
        for key in ("races", "entries", "results", "horses"):
            if int(stats.get(key) or 0) <= 0:
                raise UKImportError(f"UK payload missing required coverage: {key}")
        if stats["races"] > self.options.max_races:
            raise UKImportError(f"UK payload has {stats['races']} races; max_races is {self.options.max_races}")
        if stats["horses"] > self.options.max_horses:
            raise UKImportError(f"UK payload has {stats['horses']} horses; max_horses is {self.options.max_horses}")

    def _upsert_payload(self, payload: dict[str, Any]) -> int:
        written = 0
        for race_payload in payload.get("races", []):
            race = self._upsert_race(race_payload)
            written += 1
            for entry_payload in race_payload.get("entries") or []:
                self._upsert_entry(race, entry_payload)
                written += 1
                self._upsert_alias_from_payload(entry_payload)
            for result_payload in race_payload.get("results") or []:
                self._upsert_result(race, result_payload)
                written += 1
                self._upsert_alias_from_payload(result_payload)
        for horse_payload in payload.get("horses", []):
            self._upsert_horse(horse_payload)
            written += 1
            self._upsert_alias_from_payload(horse_payload)
        return written

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
                "race_class": _string(payload.get("race_class")),
                "surface": _string(payload.get("surface")),
                "distance": _string(payload.get("distance")),
                "going": _string(payload.get("going")),
                "prize_money": _string(payload.get("prize_money")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )
        return race

    def _upsert_entry(self, race: ExternalRace, payload: dict[str, Any]) -> None:
        horse_id = _string(payload.get("horse_id"))
        entry_key = _string(payload.get("horse_number") or horse_id or payload.get("horse_name_en"))
        ExternalRaceEntry.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            entry_key=entry_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": _string(payload.get("horse_name_en") or payload.get("horse_name")),
                "normalized_horse_name": _normalize_name(_string(payload.get("horse_name_en") or payload.get("horse_name"))),
                "horse_number": _string(payload.get("horse_number")),
                "barrier": _string(payload.get("barrier")),
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
                "raw_payload": payload,
                "last_seen_at": timezone.now(),
            },
        )

    def _upsert_result(self, race: ExternalRace, payload: dict[str, Any]) -> None:
        horse_id = _string(payload.get("horse_id"))
        result_key = _string(payload.get("finish_position") or horse_id or payload.get("horse_name_en"))
        ExternalRaceResult.objects.update_or_create(
            source=self.source,
            external_race_id=race.race_id,
            result_key=result_key,
            defaults={
                "racing_region": self.racing_region,
                "source_language": self.source_language,
                "race": race,
                "horse_id": horse_id,
                "horse_name": _string(payload.get("horse_name_en") or payload.get("horse_name")),
                "normalized_horse_name": _normalize_name(_string(payload.get("horse_name_en") or payload.get("horse_name"))),
                "horse_number": _string(payload.get("horse_number")),
                "finish_position": _string(payload.get("finish_position")),
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
        horse_name = _string(payload.get("horse_name_en") or payload.get("name"))
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
                "country": _string(payload.get("country")),
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
                "source_language": SourceLanguage.ENGLISH,
                "name_ja": name,
                "name_en": name,
                "confidence": 100,
                "alias_source": self.source,
                "last_seen_at": timezone.now(),
            },
        )

    def _base_url(self) -> str:
        return _string(getattr(settings, "UK_IMPORT_NETWORK_BASE_URL", "https://www.sportinglife.com")).rstrip("/")

    def _result_date_url(self, race_date: date) -> str:
        return f"{self._base_url()}/racing/results/{race_date.isoformat()}"

    def _horse_url(self, horse_id: str) -> str:
        return f"{self._base_url()}/racing/profiles/horse/{horse_id}"

    def _race_link_from_url(self, url: str) -> dict[str, str]:
        full_url = urljoin(f"{self._base_url()}/", _string(url))
        match = re.search(r"/racing/racecards/(\d{4}-\d{2}-\d{2})/([^/]+)/racecard/(\d+)/[^\"'<> ]*", full_url)
        if not match:
            raise UKImportError(f"invalid Sporting Life race URL: {url}")
        return {
            "race_id": f"SL{match.group(3)}",
            "race_date": match.group(1),
            "venue": match.group(2),
            "race_no": match.group(3),
            "url": full_url,
        }
