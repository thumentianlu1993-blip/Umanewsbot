from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

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


US_EXTERNAL_SOURCE = "horse_racing_nation"


class USImportError(Exception):
    pass


@dataclass(frozen=True)
class USImportOptions:
    dry_run: bool = True
    allow_network: bool = False
    request_interval_seconds: float = 8
    max_races: int = 20
    max_horses: int = 80
    max_requests: int = 200

    @classmethod
    def from_settings(cls, **overrides: Any) -> "USImportOptions":
        values = {
            "request_interval_seconds": getattr(settings, "US_IMPORT_REQUEST_INTERVAL_SECONDS", 8),
            "max_races": getattr(settings, "US_IMPORT_MAX_RACES_PER_RUN", 20),
            "max_horses": getattr(settings, "US_IMPORT_MAX_HORSES_PER_RUN", 80),
            "max_requests": getattr(settings, "US_IMPORT_MAX_REQUESTS_PER_RUN", 200),
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
    return dateparse.parse_date(raw.replace("/", "-")) if raw else None


class HorseRacingNationHTMLParser:
    def parse_track_day_links(self, html: str, *, race_date: str, source_url: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        links: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        pattern = re.compile(rf"/entries-results/([^/]+)/{re.escape(race_date)}")
        for anchor in soup.find_all("a", href=True):
            href = _string(anchor.get("href"))
            match = pattern.search(href)
            if not match:
                continue
            track_slug = match.group(1)
            key = (track_slug, race_date)
            if key in seen:
                continue
            seen.add(key)
            links.append(
                {
                    "track_slug": track_slug,
                    "race_date": race_date,
                    "track_name": _collapse_spaces(anchor.get_text(" ", strip=True)),
                    "url": urljoin(source_url, href),
                }
            )
        return links

    def parse_track_day_races(
        self,
        html: str,
        *,
        race_date: str,
        track_slug: str,
        track_name: str,
        source_url: str,
    ) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        races: list[dict[str, Any]] = []
        headings = [
            heading
            for heading in soup.find_all("h2")
            if re.search(r"Race\s*#\s*\d+", heading.get_text(" ", strip=True), re.IGNORECASE)
        ]
        for heading in headings:
            heading_text = _collapse_spaces(heading.get_text(" ", strip=True))
            race_no = self._first_match(heading_text, r"Race\s*#\s*(\d+)")
            start_time = self._first_match(heading_text, r",\s*([0-9:]+\s*[AP]M)")
            race = {
                "race_id": f"HRN_{track_slug}_{race_date}_{race_no}",
                "race_name": f"{track_name} Race # {race_no}",
                "race_date": race_date,
                "venue": track_name,
                "race_number": race_no,
                "scheduled_start_time": start_time,
                "entries": [],
                "results": [],
                "raw_payload": {"source_url": source_url, "heading": heading_text},
            }
            entries_table = heading.find_next("table", class_=lambda classes: classes and "table-entries" in classes)
            if entries_table:
                race["entries"] = self._entries(entries_table)
            payouts_table = entries_table.find_next("table", class_=lambda classes: classes and "table-payouts" in classes) if entries_table else None
            if payouts_table:
                race["results"] = self._results_from_payouts(payouts_table, race["entries"])
            else:
                race["results"] = [{**entry, "finish_position": ""} for entry in race["entries"]]
            races.append(race)
        return races

    def parse_horse_profile(self, html: str, *, horse_id: str, source_url: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        title = _collapse_spaces(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")
        text = _collapse_spaces(soup.get_text(" ", strip=True))
        pedigree_match = re.search(r"Pedigree:\s*(.*?)\s*-\s*(.*?)\s+by\s+([^ ](?:.*?))\s+Owner\(s\):", text)
        owner = self._field_between(text, "Owner(s):", "Trainer:")
        trainer = self._field_between(text, "Trainer:", "Bred:")
        country = self._field_between(text, "Bred:", "by")
        age = self._first_match(text, r"Age:\s*(\d+)\s+years")
        sex = self._first_match(text, r"years old\s*-\s*([A-Za-z]+)")
        return {
            "horse_id": horse_id,
            "horse_name_en": title,
            "age": age,
            "sex": sex,
            "sire": _collapse_spaces(pedigree_match.group(1)) if pedigree_match else "",
            "dam": _collapse_spaces(pedigree_match.group(2)) if pedigree_match else "",
            "dams_sire": _collapse_spaces(pedigree_match.group(3)) if pedigree_match else "",
            "owner": owner,
            "trainer": trainer,
            "country": country,
            "raw_payload": {"source_url": source_url},
        }

    def _entries(self, table) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 6:
                continue
            horse_cell = cells[2]
            horse_link = horse_cell.find("a", href=True)
            horse_url = _string(horse_link.get("href") if horse_link else "")
            horse_id = self._horse_id_from_url(horse_url)
            horse_name = _collapse_spaces(horse_link.get_text(" ", strip=True) if horse_link else "")
            if not horse_id or not horse_name:
                continue
            horse_text = _collapse_spaces(horse_cell.get_text(" ", strip=True))
            sire = horse_text.replace(horse_name, "", 1).strip()
            sire = re.sub(r"^\([^)]+\)\s*", "", sire).strip()
            trainer_jockey = _collapse_spaces(cells[3].get_text(" ", strip=True))
            trainer, jockey = self._trainer_jockey(trainer_jockey)
            entries.append(
                {
                    "horse_id": horse_id,
                    "horse_name_en": horse_name,
                    "horse_number": _collapse_spaces(cells[1].get_text(" ", strip=True)),
                    "sire": sire,
                    "trainer": trainer,
                    "jockey": jockey,
                    "odds": _collapse_spaces(cells[5].get_text(" ", strip=True)),
                    "raw_payload": {"horse_url": horse_url},
                }
            )
        return entries

    def _results_from_payouts(self, table, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_name = {entry["horse_name_en"]: entry for entry in entries}
        results: list[dict[str, Any]] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            runner = _collapse_spaces(cells[0].get_text(" ", strip=True))
            name = re.sub(r"\s+\([^)]*\)$", "", runner).strip()
            if not name or name.lower().startswith("runner"):
                continue
            base = by_name.get(name, {"horse_id": "", "horse_name_en": name})
            results.append(
                {
                    **base,
                    "finish_position": str(len(results) + 1),
                    "win_payout": _collapse_spaces(cells[1].get_text(" ", strip=True)),
                    "place_payout": _collapse_spaces(cells[2].get_text(" ", strip=True)) if len(cells) > 2 else "",
                    "show_payout": _collapse_spaces(cells[3].get_text(" ", strip=True)) if len(cells) > 3 else "",
                }
            )
        return results

    def _horse_id_from_url(self, url: str) -> str:
        path = urlparse(url).path
        match = re.search(r"/horse/([^/?#]+)", path)
        return match.group(1) if match else ""

    def _trainer_jockey(self, value: str) -> tuple[str, str]:
        if not value:
            return "", ""
        parts = value.split()
        if len(parts) <= 3:
            return value, ""
        return " ".join(parts[:-2]), " ".join(parts[-2:])

    def _first_match(self, text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        return _collapse_spaces(match.group(1)) if match else ""

    def _field_between(self, text: str, left: str, right: str) -> str:
        pattern = rf"{re.escape(left)}\s*(.*?)\s+{re.escape(right)}"
        match = re.search(pattern, text)
        return _collapse_spaces(match.group(1)) if match else ""


class USNetworkClient:
    user_agent = "umanewsbot/1.0 (+https://umafans.run; low-frequency data import)"

    def __init__(self, options: USImportOptions):
        self.options = options
        self.requests: list[dict[str, Any]] = []

    def get(self, url: str, *, target_type: str, target_id: str):
        if len(self.requests) >= self.options.max_requests:
            raise USImportError(f"US network import exceeded max_requests={self.options.max_requests}")
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
            raise USImportError(f"US network import failed with HTTP {response.status_code}: {url}")
        return response


class USExternalDataImporter:
    source = US_EXTERNAL_SOURCE
    racing_region = RacingRegion.UNITED_STATES
    source_language = SourceLanguage.ENGLISH

    def __init__(self, options: USImportOptions | None = None):
        self.options = options or USImportOptions.from_settings()

    def import_race_date(
        self,
        race_date: str | date,
        *,
        seed_track: str,
        limit_tracks: int | None = None,
        limit_races: int | None = None,
        limit_horses: int | None = None,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise USImportError("US real import requires --allow-network")
        parsed = _parse_date(race_date) if isinstance(race_date, str) else race_date
        if not parsed:
            raise USImportError(f"invalid race_date: {race_date}")
        payload, requests_info = self._fetch_race_date_payload(
            parsed,
            seed_track=seed_track,
            limit_tracks=limit_tracks,
            limit_races=limit_races,
            limit_horses=limit_horses,
        )
        result = self._import_payload("race_date", parsed.isoformat(), payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def import_recent_days(
        self,
        days: int,
        *,
        end_date: str | date | None = None,
        seed_track: str,
        limit_tracks: int | None = None,
        limit_races: int | None = None,
        limit_horses: int | None = None,
        skip_races: int = 0,
    ) -> dict[str, Any]:
        if days <= 0:
            raise USImportError("recent days must be positive")
        end = _parse_date(end_date) if end_date else timezone.localdate()
        if not end:
            raise USImportError(f"invalid end_date: {end_date}")
        start = end - timedelta(days=days - 1)
        return self.import_date_range(
            start,
            end,
            seed_track=seed_track,
            limit_tracks=limit_tracks,
            limit_races=limit_races,
            limit_horses=limit_horses,
            skip_races=skip_races,
        )

    def plan_recent_days(
        self,
        days: int,
        *,
        end_date: str | date | None = None,
        seed_track: str,
        limit_tracks: int | None = None,
        batch_size: int = 20,
    ) -> dict[str, Any]:
        if days <= 0:
            raise USImportError("recent days must be positive")
        end = _parse_date(end_date) if end_date else timezone.localdate()
        if not end:
            raise USImportError(f"invalid end_date: {end_date}")
        start = end - timedelta(days=days - 1)
        return self.plan_date_range(
            start,
            end,
            seed_track=seed_track,
            limit_tracks=limit_tracks,
            batch_size=batch_size,
        )

    def plan_date_range(
        self,
        start_date: str | date,
        end_date: str | date,
        *,
        seed_track: str,
        limit_tracks: int | None = None,
        batch_size: int = 20,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise USImportError("US real import requires --allow-network")
        if batch_size <= 0:
            raise USImportError("batch_size must be positive")
        start = _parse_date(start_date) if isinstance(start_date, str) else start_date
        end = _parse_date(end_date) if isinstance(end_date, str) else end_date
        if not start or not end or start > end:
            raise USImportError("invalid date range")
        races, requests_info, summary = self._fetch_date_range_races(
            start,
            end,
            seed_track=seed_track,
            limit_tracks=limit_tracks,
            limit_races=None,
        )
        batches = []
        for offset in range(0, len(races), batch_size):
            batch_races = races[offset : offset + batch_size]
            batches.append(
                {
                    "batch_index": len(batches) + 1,
                    "skip_races": offset,
                    "limit_races": len(batch_races),
                    "race_ids": [_string(race.get("race_id")) for race in batch_races],
                    "track_day_urls": sorted(
                        {
                            _string((race.get("raw_payload") or {}).get("source_url"))
                            for race in batch_races
                            if _string((race.get("raw_payload") or {}).get("source_url"))
                        }
                    ),
                }
            )
        return {
            "source": self.source,
            "target_type": "date_range",
            "target_id": f"{start.isoformat()}..{end.isoformat()}",
            "dry_run": True,
            "plan_only": True,
            "coverage_stats": {"races": len(races), "entries": 0, "results": 0, "horses": 0},
            "completion": {
                "is_complete": True,
                "stop_reason": "plan_only",
                "race_links_found": len(races),
                "batch_size": batch_size,
                "batches": len(batches),
                "coverage_scope_limited": limit_tracks is not None,
                "limit_tracks": limit_tracks,
                **summary,
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
        seed_track: str,
        limit_tracks: int | None = None,
        limit_races: int | None = None,
        limit_horses: int | None = None,
        skip_races: int = 0,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise USImportError("US real import requires --allow-network")
        start = _parse_date(start_date) if isinstance(start_date, str) else start_date
        end = _parse_date(end_date) if isinstance(end_date, str) else end_date
        if not start or not end or start > end:
            raise USImportError("invalid date range")
        payload, requests_info = self._fetch_date_range_payload(
            start,
            end,
            seed_track=seed_track,
            limit_tracks=limit_tracks,
            limit_races=limit_races,
            limit_horses=limit_horses,
            skip_races=skip_races,
        )
        result = self._import_payload("date_range", f"{start.isoformat()}..{end.isoformat()}", payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def import_race_ids(
        self,
        race_ids: list[str],
        *,
        limit_horses: int | None = None,
    ) -> dict[str, Any]:
        if not self.options.allow_network:
            raise USImportError("US real import requires --allow-network")
        normalized_ids = [_string(race_id) for race_id in race_ids if _string(race_id)]
        if not normalized_ids:
            raise USImportError("race_ids must not be empty")
        payload, requests_info = self._fetch_race_ids_payload(normalized_ids, limit_horses=limit_horses)
        result = self._import_payload("race_ids", ",".join(normalized_ids), payload)
        result["network_probe"] = True
        result["requests"] = requests_info
        return result

    def _fetch_date_range_races(
        self,
        start_date: date,
        end_date: date,
        *,
        seed_track: str,
        limit_tracks: int | None,
        limit_races: int | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        parser = HorseRacingNationHTMLParser()
        client = USNetworkClient(self.options)
        races: list[dict[str, Any]] = []
        race_dates_fetched = 0
        track_days_found = 0
        track_days_fetched = 0
        cursor = start_date
        while cursor <= end_date:
            if limit_races is not None and len(races) >= limit_races:
                break
            date_races, date_found, date_fetched = self._fetch_track_day_races(
                parser,
                client,
                race_date=cursor,
                seed_track=seed_track,
                use_date_index=True,
                limit_tracks=limit_tracks,
                limit_races=None if limit_races is None else max(limit_races - len(races), 0),
            )
            race_dates_fetched += 1
            track_days_found += date_found
            track_days_fetched += date_fetched
            races.extend(date_races)
            cursor += timedelta(days=1)
        return races, client.requests, {
            "race_dates_fetched": race_dates_fetched,
            "track_days_found": track_days_found,
            "track_days_fetched": track_days_fetched,
        }

    def _fetch_date_range_payload(
        self,
        start_date: date,
        end_date: date,
        *,
        seed_track: str,
        limit_tracks: int | None,
        limit_races: int | None,
        limit_horses: int | None,
        skip_races: int = 0,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if skip_races < 0:
            raise USImportError("skip_races must be non-negative")
        races_needed = None if limit_races is None else skip_races + limit_races
        races, requests_info, summary = self._fetch_date_range_races(
            start_date,
            end_date,
            seed_track=seed_track,
            limit_tracks=limit_tracks,
            limit_races=races_needed,
        )
        selected_races = races[skip_races:]
        if limit_races is not None:
            selected_races = selected_races[:limit_races]
        parser = HorseRacingNationHTMLParser()
        client = USNetworkClient(self.options)
        client.requests = requests_info
        horse_ids = self._unique_horse_ids(selected_races)
        horses = self._fetch_horse_profiles(parser, client, horse_ids, limit_horses=limit_horses)
        completion = {
            "is_complete": False if (limit_tracks is not None or limit_races is not None or (limit_horses is not None and len(horses) < len(horse_ids))) else True,
            "stop_reason": self._stop_reason(
                track_links=[{}] * summary["track_days_found"],
                races=selected_races,
                horse_ids=horse_ids,
                horses=horses,
                limit_tracks=limit_tracks,
                limit_races=limit_races,
                limit_horses=limit_horses,
            ),
            **summary,
            "races_imported": len(selected_races),
            "unique_horses_found": len(horse_ids),
            "horse_profiles_fetched": len(horses),
            "skip_races": skip_races,
            "race_links_found": len(races),
            "race_links_selected": len(selected_races),
            "race_ids_selected": [_string(race.get("race_id")) for race in selected_races],
            "max_requests": self.options.max_requests,
        }
        return {"races": selected_races, "horses": horses, "completion": completion}, client.requests

    def _fetch_race_ids_payload(
        self,
        race_ids: list[str],
        *,
        limit_horses: int | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        parser = HorseRacingNationHTMLParser()
        client = USNetworkClient(self.options)
        requested = list(dict.fromkeys(race_ids))
        requested_set = set(requested)
        groups: dict[tuple[str, date], list[str]] = {}
        for race_id in requested:
            track_slug, race_date, _race_number = self._parse_race_id(race_id)
            groups.setdefault((track_slug, race_date), []).append(race_id)

        selected_races: list[dict[str, Any]] = []
        found_ids: set[str] = set()
        for (track_slug, race_date), group_race_ids in groups.items():
            url = self._track_day_url(track_slug, race_date)
            response = client.get(url, target_type="track_day", target_id=f"{track_slug}:{race_date.isoformat()}")
            track_name = self._track_name_from_page(parser, response.text, race_date=race_date, track_slug=track_slug, source_url=client.requests[-1]["url"])
            for race in parser.parse_track_day_races(
                response.text,
                race_date=race_date.isoformat(),
                track_slug=track_slug,
                track_name=track_name,
                source_url=client.requests[-1]["url"],
            ):
                race_id = _string(race.get("race_id"))
                if race_id in group_race_ids:
                    selected_races.append(race)
                    found_ids.add(race_id)

        missing_ids = [race_id for race_id in requested if race_id not in found_ids]
        if missing_ids:
            raise USImportError(f"race_ids not found in HRN track-day pages: {', '.join(missing_ids)}")

        selected_races.sort(key=lambda race: requested.index(_string(race.get("race_id"))) if _string(race.get("race_id")) in requested_set else len(requested))
        horse_ids = self._unique_horse_ids(selected_races)
        horses = self._fetch_horse_profiles(parser, client, horse_ids, limit_horses=limit_horses)
        horse_limited = limit_horses is not None and len(horses) < len(horse_ids)
        completion = {
            "is_complete": not horse_limited,
            "stop_reason": "limit_horses_reached" if horse_limited else "complete",
            "track_days_found": len(groups),
            "track_days_fetched": len(groups),
            "races_imported": len(selected_races),
            "unique_horses_found": len(horse_ids),
            "horse_profiles_fetched": len(horses),
            "race_links_found": len(requested),
            "race_links_selected": len(selected_races),
            "race_ids_selected": [_string(race.get("race_id")) for race in selected_races],
            "max_requests": self.options.max_requests,
        }
        return {"races": selected_races, "horses": horses, "completion": completion}, client.requests

    def _fetch_race_date_payload(
        self,
        race_date: date,
        *,
        seed_track: str,
        limit_tracks: int | None,
        limit_races: int | None,
        limit_horses: int | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        parser = HorseRacingNationHTMLParser()
        client = USNetworkClient(self.options)
        races, track_days_found, track_days_fetched = self._fetch_track_day_races(
            parser,
            client,
            race_date=race_date,
            seed_track=seed_track,
            use_date_index=False,
            limit_tracks=limit_tracks,
            limit_races=limit_races,
        )
        horse_ids = self._unique_horse_ids(races)
        horses = self._fetch_horse_profiles(parser, client, horse_ids, limit_horses=limit_horses)
        completion = {
            "is_complete": False if (limit_tracks is not None or limit_races is not None or (limit_horses is not None and len(horses) < len(horse_ids))) else True,
            "stop_reason": self._stop_reason(
                track_links=[{}] * track_days_found,
                races=races,
                horse_ids=horse_ids,
                horses=horses,
                limit_tracks=limit_tracks,
                limit_races=limit_races,
                limit_horses=limit_horses,
            ),
            "track_days_found": track_days_found,
            "track_days_fetched": track_days_fetched,
            "races_imported": len(races),
            "unique_horses_found": len(horse_ids),
            "horse_profiles_fetched": len(horses),
            "max_requests": self.options.max_requests,
        }
        return {"races": races, "horses": horses, "completion": completion}, client.requests

    def _fetch_track_day_races(
        self,
        parser: HorseRacingNationHTMLParser,
        client: USNetworkClient,
        *,
        race_date: date,
        seed_track: str,
        use_date_index: bool,
        limit_tracks: int | None,
        limit_races: int | None,
    ) -> tuple[list[dict[str, Any]], int, int]:
        seed_url = self._date_index_url(race_date) if use_date_index else self._track_day_url(seed_track, race_date)
        seed_response = client.get(seed_url, target_type="track_day", target_id=f"{seed_track}:{race_date.isoformat()}")
        track_links = parser.parse_track_day_links(seed_response.text, race_date=race_date.isoformat(), source_url=client.requests[-1]["url"])
        track_days_found = len(track_links)
        if limit_tracks is not None:
            track_links = track_links[:limit_tracks]
        races: list[dict[str, Any]] = []
        track_days_fetched = 0
        for idx, track_link in enumerate(track_links):
            if limit_races is not None and len(races) >= limit_races:
                break
            html = seed_response.text if idx == 0 and track_link["track_slug"] == seed_track else client.get(
                track_link["url"],
                target_type="track_day",
                target_id=f"{track_link['track_slug']}:{race_date.isoformat()}",
            ).text
            track_days_fetched += 1
            for race in parser.parse_track_day_races(
                html,
                race_date=race_date.isoformat(),
                track_slug=track_link["track_slug"],
                track_name=track_link["track_name"],
                source_url=track_link["url"],
            ):
                races.append(race)
                if limit_races is not None and len(races) >= limit_races:
                    break
        return races, track_days_found, track_days_fetched

    def _unique_horse_ids(self, races: list[dict[str, Any]]) -> list[str]:
        horse_ids: list[str] = []
        seen_horses: set[str] = set()
        for race in races:
            for runner in [*(race.get("entries") or []), *(race.get("results") or [])]:
                horse_id = _string(runner.get("horse_id")) if isinstance(runner, dict) else ""
                if horse_id and horse_id not in seen_horses:
                    seen_horses.add(horse_id)
                    horse_ids.append(horse_id)
        return horse_ids

    def _fetch_horse_profiles(
        self,
        parser: HorseRacingNationHTMLParser,
        client: USNetworkClient,
        horse_ids: list[str],
        *,
        limit_horses: int | None,
    ) -> list[dict[str, Any]]:
        horses: list[dict[str, Any]] = []
        for horse_id in horse_ids:
            if limit_horses is not None and len(horses) >= limit_horses:
                break
            response = client.get(self._horse_url(horse_id), target_type="horse", target_id=horse_id)
            horses.append(parser.parse_horse_profile(response.text, horse_id=horse_id, source_url=client.requests[-1]["url"]))
        return horses

    def _stop_reason(self, *, track_links, races, horse_ids, horses, limit_tracks, limit_races, limit_horses) -> str:
        if limit_horses is not None and len(horses) < len(horse_ids):
            return "limit_horses_reached"
        if limit_races is not None and len(races) >= limit_races:
            return "limit_races_reached"
        if limit_tracks is not None:
            return "limit_tracks_reached"
        return "complete"

    def _parse_race_id(self, race_id: str) -> tuple[str, date, str]:
        match = re.match(r"^HRN_(?P<track_slug>.+)_(?P<race_date>\d{4}-\d{2}-\d{2})_(?P<race_number>\d+)$", race_id)
        if not match:
            raise USImportError(f"invalid HRN race_id: {race_id}")
        race_date = _parse_date(match.group("race_date"))
        if not race_date:
            raise USImportError(f"invalid HRN race date in race_id: {race_id}")
        return match.group("track_slug"), race_date, match.group("race_number")

    def _track_name_from_page(
        self,
        parser: HorseRacingNationHTMLParser,
        html: str,
        *,
        race_date: date,
        track_slug: str,
        source_url: str,
    ) -> str:
        for link in parser.parse_track_day_links(html, race_date=race_date.isoformat(), source_url=source_url):
            if link["track_slug"] == track_slug:
                return link["track_name"]
        return track_slug.replace("-", " ").title()

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
                raise USImportError(f"{self.source} import is already running")
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
                raise USImportError("Cannot commit unverified US import; completion.is_complete must be true")
        if completion.get("is_complete") is False:
            stop_reason = _string(completion.get("stop_reason")) or "unknown"
            raise USImportError(f"Cannot commit incomplete US import; stop_reason={stop_reason}")
        stop_reason = _string(completion.get("stop_reason"))
        if stop_reason and stop_reason != "complete":
            raise USImportError(f"Cannot commit inconsistent US import; stop_reason={stop_reason}")
        if _completion_horse_detail_metadata_missing(completion):
            raise USImportError("Cannot commit unverified US import; horse detail coverage metadata is required")
        if _completion_horse_detail_gap(completion):
            raise USImportError("Cannot commit inconsistent US import; horse_profiles_fetched is below unique_horses_found")

    def _validate_payload_limits(self, stats: dict[str, int]) -> None:
        for key in ("races", "entries", "results", "horses"):
            if int(stats.get(key) or 0) <= 0:
                raise USImportError(f"US payload missing required coverage: {key}")
        if stats["races"] > self.options.max_races:
            raise USImportError(f"US payload has {stats['races']} races; max_races is {self.options.max_races}")
        if stats["horses"] > self.options.max_horses:
            raise USImportError(f"US payload has {stats['horses']} horses; max_horses is {self.options.max_horses}")

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
                "jockey_name": _string(payload.get("jockey")),
                "trainer_name": _string(payload.get("trainer")),
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
                "odds_value": _string(payload.get("odds") or payload.get("win_payout")),
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
                "country": _string(payload.get("country")),
                "father_name": _string(payload.get("sire")),
                "mother_name": _string(payload.get("dam")),
                "owner_name": _string(payload.get("owner")),
                "trainer_name": _string(payload.get("trainer")),
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

    def _entries_base_url(self) -> str:
        return _string(getattr(settings, "US_IMPORT_ENTRIES_BASE_URL", "https://entries.horseracingnation.com")).rstrip("/")

    def _hrn_base_url(self) -> str:
        return _string(getattr(settings, "US_IMPORT_HRN_BASE_URL", "https://www.horseracingnation.com")).rstrip("/")

    def _track_day_url(self, track_slug: str, race_date: date) -> str:
        return f"{self._entries_base_url()}/entries-results/{track_slug}/{race_date.isoformat()}"

    def _date_index_url(self, race_date: date) -> str:
        return f"{self._entries_base_url()}/entries-results/{race_date.isoformat()}"

    def _horse_url(self, horse_id: str) -> str:
        return f"{self._hrn_base_url()}/horse/{horse_id}"
