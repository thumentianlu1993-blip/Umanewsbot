#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup


JRA_BASE_URL = "https://www.jra.go.jp"
JRA_SUBMIT_RE = re.compile(r"doSubmit\('(?P<year>\d{4})','(?P<month_day>\d{4})'")
SPONSOR_RE = re.compile(r"\[[^]]+]")

JRA_COURSES = {
    "札幌": "SAPPORO",
    "函館": "HAKODATE",
    "福島": "FUKUSHIMA",
    "新潟": "NIIGATA",
    "東京": "TOKYO",
    "中山": "NAKAYAMA",
    "中京": "CHUKYO",
    "京都": "KYOTO",
    "阪神": "HANSHIN",
    "小倉": "KOKURA",
}

JRA_OFFICIAL_NAME_ALIASES = {
    "japan-daily-hai-nisai": "デイリー杯2歳S",
    "japan-hanshin-jump": "阪神ジャンプS",
    "japan-hanshin-spring-jump": "阪神スプリングジャンプ",
    "japan-kansai-television-co-ltd-sho-rose": "ローズS",
    "japan-kansai-television-corporation-sho-rose": "ローズS",
    "japan-kokura-jump": "小倉ジャンプS",
    "japan-kokura-summer-jump": "小倉サマージャンプ",
    "japan-kyoto-high-jump": "京都ハイジャンプ",
    "japan-kyoto-jump": "京都ジャンプS",
    "japan-laurel-racecourse-sho-nakayama-himba": "中山牝馬S",
    "japan-mbs-sho-swan": "スワンS",
    "japan-niigata-jump": "新潟ジャンプS",
    "japan-tokyo-high-jump": "東京ハイジャンプ",
    "japan-tokyo-jump": "東京ジャンプS",
    "japan-tv-nishi-nippon-corporation-sho-kitakyushu-kinen": "北九州記念",
}

TRACK_CODES = {
    "aqueduct": {"AQU", "BAQ"},
    "belmont at aqueduct": {"AQU", "BAQ"},
    "belmont at the big a": {"AQU", "BAQ"},
    "belmont park": {"BEL"},
    "churchill downs": {"CD"},
    "charles town": {"CT"},
    "delaware park": {"DEL"},
    "del mar": {"DMR"},
    "ellis park": {"ELP"},
    "fair grounds": {"FG"},
    "gulfstream park": {"GP"},
    "keeneland": {"KEE"},
    "kentucky downs": {"KD"},
    "laurel park": {"LRL"},
    "lone star park": {"LS"},
    "los alamitos": {"LRC"},
    "monmouth park": {"MTH"},
    "mountaineer park": {"MNR"},
    "oaklawn park": {"OP"},
    "parx racing": {"PRX"},
    "penn national": {"PEN"},
    "pimlico": {"PIM"},
    "prairie meadows": {"PRM"},
    "presque isle downs": {"PID"},
    "remington park": {"RP"},
    "santa anita": {"SA"},
    "santa anita park": {"SA"},
    "saratoga": {"SAR"},
    "tampa bay downs": {"TAM"},
    "thistledown": {"TDN"},
    "colonial downs": {"CNL"},
}

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

FRENCH_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}

BHA_COURSES = {
    "AINTREE": "Aintree",
    "ASCOT": "Ascot",
    "AYR": "Ayr",
    "CHESTER": "Chester",
    "CHELTENHAM": "Cheltenham",
    "CHEPSTOW": "Chepstow",
    "DONCASTER": "Doncaster",
    "EPSOMDOWNS": "Epsom Downs",
    "EXETER": "Exeter",
    "FONTWELLPARK": "Fontwell",
    "GOODWOOD": "Goodwood",
    "HAYDOCKPARK": "Haydock Park",
    "KEMPTONPARK": "Kempton Park",
    "LINGFIELDPARK": "Lingfield",
    "MARKETRASEN": "Market Rasen",
    "NEWBURY": "Newbury",
    "NEWMARKET": "Newmarket",
    "NEWCASTLE": "Newcastle",
    "SALISBURY": "Salisbury",
    "SANDOWNPARK": "Sandown Park",
    "SOUTHWELL": "Southwell",
    "UTTOXETER": "Uttoxeter",
    "WARWICK": "Warwick",
    "WETHERBY": "Wetherby",
    "WINCANTON": "Wincanton",
    "WINDSOR": "Windsor",
    "YORK": "York",
}

FRANCE_COURSES = (
    "Bordeaux-Le Bouscat",
    "Cagnes-sur-Mer",
    "La Teste - Bassin d’Arcachon",
    "La Teste - Bassin d'Arcachon",
    "Lyon-Parilly",
    "Marseille-Borély",
    "ParisLongchamp",
    "Saint-Cloud",
    "Clairefontaine",
    "Fontainebleau",
    "Le Lion d’Angers",
    "Le Lion d'Angers",
    "Chantilly",
    "Compiègne",
    "Deauville",
    "Strasbourg",
    "Toulouse",
    "Vichy",
    "Craon",
    "Nantes",
)

COMPACT_RACE_WORDS = (
    "CHAMPIONS",
    "CORONATION",
    "CELEBRATION",
    "LONGDISTANCE",
    "SKYSPORTS",
    "WILLIAMHILL",
    "SODEXOLIVE",
    "BET365",
    "ASTONPARK",
    "GOLDCUP",
    "MILE",
    "ULTIMA",
)

TOBA_CORE_NAME_QUALIFIERS = ("FILLIES", "TURF", "SPRINT")

TOBA_SERIES_ALIASES = {
    "united-states-awesome-again": ("California Crown Stakes",),
    "united-states-chandelier": ("Oak Leaf Stakes",),
    "united-states-princess-rooney-invitational": ("Princess Rooney Stakes",),
    "united-states-runhappy": ("Elite Power Stakes",),
    "united-states-unzip-me": ("John C. Harris Stakes",),
    "united-states-virginia-derby": ("Old Dominion Derby",),
}

TOBA_REVIEWED_RELOCATIONS = {
    "united-states-belmont-derby-invitational",
    "united-states-pennine-ridge",
    "united-states-soaring-softly",
    "united-states-victory-ride",
    "united-states-wonder-again",
}

CALENDAR_SERIES_ALIASES = {
    "france-la-coupe": (
        "La Coupe",
    ),
    "france-la-coupe-de-maisons-laffitte": (
        "La Coupe de M-L",
    ),
    "france-jean-luc-lagardere-grand-criterium": (
        "F J-L Lagardere",
        "Jean-Luc Lagardere",
    ),
    "france-grand-prix-de-pau-stp": (
        "Andre Labarrere",
        "Grand Prix de Pau",
        "GD PX DE PAU",
    ),
    "france-grand-prix-de-la-ville-de-nice-bernard-secly-stp": (
        "Grand Prix de la Ville de Nice",
        "GD PX DE NICE",
    ),
    "france-drags-des-stp": (
        "Prix des Drags",
        "Les Drags",
    ),
    "france-christian-de-tredern-hurdle": (
        "Christian de Tredern",
        "Tredern",
    ),
    "france-magalen-bryant-bournosienne-hurdle": (
        "Haras d'Etreham Magalen Bryant",
        "Magalen Bryant",
        "Bournosienne",
    ),
    "france-paris-g-p-de": (
        "F GD Prix Paris",
        "Grand Prix de Paris",
    ),
    "france-renaud-du-vivier-hurdle": (
        "Renaud du Vivier",
    ),
    "france-vichy-g-p-de": (
        "Grand Px Vichy",
        "Grand Prix de Vichy",
    ),
    "GBR_BRISTOL_NOVICES_HURDLE": (
        "Albert Bartlett Bristol Novices Hurdle",
        "Bristol Novices Hurdle",
    ),
    "GBR_AINTREE_BRIDLE_ROAD_HANDICAP_HURDLE": (
        "William Hill Top Price Guarantee Handicap Hurdle",
        "William Hill Handicap Hurdle",
    ),
    "GBR_AINTREE_ORRELL_PARK_HANDICAP_HURDLE": (
        "William Hill Handicap Hurdle",
    ),
    "GBR_ASCOT_AUTUMN_GOLD_CUP_HANDICAP_CHASE": (
        "Sodexo Live Gold Cup Handicap Chase",
    ),
    "GBR_ASCOT_HURST_PARK_HANDICAP_CHASE": (
        "Byrne Group Handicap Chase",
        "1965 Chase",
    ),
    "GBR_CHELTENHAM_FESTIVAL_TROPHY_HANDICAP_CHASE": (
        "Ultima Handicap Chase",
    ),
    "GBR_CHELTENHAM_COUNTDOWN_PODCAST_HANDICAP_CHASE": (
        "Paddy Power Cheltenham Countdown Podcast Handicap Chase",
    ),
    "GBR_CHELTENHAM_DECEMBER_GOLD_CUP": (
        "December Gold Cup Handicap Chase",
        "Nyetimber Gold Cup Handicap Chase",
    ),
    "GBR_CHELTENHAM_DECEMBER_3M2F_HANDICAP_CHASE": (
        "Southam Handicap Chase",
    ),
    "GBR_CHELTENHAM_NOVEMBER_LONG_DISTANCE_HANDICAP_CHASE": (
        "Holland Cooper Handicap Chase",
        "Oddschecker Handicap Chase",
        "Jewson Handicap Chase",
        "Prestbury Handicap Chase",
    ),
    "GBR_CHELTENHAM_PADDY_POWER_GOLD_CUP": (
        "Paddy Power Gold Cup Handicap Chase",
    ),
    "united-kingdom-acomb": (
        "Tattersalls Acomb",
    ),
    "united-kingdom-ascot-hurdle": (
        "Howden Ascot Hurdle",
    ),
    "united-kingdom-classic-novices-hurdle": (
        "SSS Super Alloys Novices Hurdle",
        "Classic Novices Hurdle",
    ),
    "united-kingdom-aintree-mares-nhf": (
        "Goffs Nickel Coin Mares Standard Open NH Flat Race",
        "Nickel Coin Mares NHF Race",
    ),
    "united-kingdom-aintree-champion-nhf-race": (
        "Weatherbys nhstallions.co.uk Standard Open NH Flat Race",
    ),
    "united-kingdom-1965-stp": (
        "Copybet 1965 Chase",
        "Nirvana Spa 1965 Chase",
        "Chanelle Pharma 1965 Chase",
        "1965 Chase",
    ),
    "united-kingdom-british-champions-sprint": (
        "QIPCO British Champions Sprint",
        "British Champions Sprint",
    ),
    "united-kingdom-champion-s-british-champion-middle-distance": (
        "QIPCO Champion",
        "Champion Stakes",
    ),
    "united-kingdom-clarence-house-stp": (
        "Clarence House Chase",
    ),
    "united-kingdom-cleeve-hurdle": (
        "Cleeve Hurdle",
    ),
    "united-kingdom-denman-stp": (
        "Betfair Denman Chase",
        "Denman Chase",
    ),
    "united-kingdom-fillies-juvenile-hurdle": (
        "Safran Landing Systems Juvenile Handicap Hurdle",
    ),
    "united-kingdom-fred-winter-juvenile-hurdle": (
        "Boodles Fred Winter Juvenile Handicap Hurdle",
    ),
    "united-kingdom-game-spirit-stp": (
        "Betfair Exchange Game Spirit Chase",
        "Game Spirit Chase",
    ),
    "united-kingdom-hyde-novices-hurdle": (
        "Albert Bartlett Hyde Novices Hurdle",
        "Hyde Novices Hurdle",
    ),
    "united-kingdom-jockey-club": (
        "Jockey Club Stakes",
        "Jockey Club",
    ),
    "united-kingdom-joel": (
        "Al Basti Equiworld Dubai Joel",
        "Joel Stakes",
    ),
    "united-kingdom-july": (
        "Kingdom of Bahrain July",
        "July Stakes",
    ),
    "united-kingdom-kingwell-hurdle": (
        "JenningsBet Kingwell Hurdle",
        "Kingwell Hurdle",
    ),
    "united-kingdom-national-spirit-hurdle": (
        "National Spirit Hurdle",
    ),
    "united-kingdom-silver-cup-stp": (
        "Howden Silver Cup Handicap Chase",
        "Silver Cup Handicap Chase",
    ),
    "united-kingdom-summer-plate-stp": (
        "Unibet Summer Plate Handicap Chase",
        "Summer Plate Handicap Chase",
    ),
    "united-kingdom-swinley-stp": (
        "Betfair Swinley Handicap Chase",
        "Swinley Handicap Chase",
    ),
    "hong-kong-queen-elizabeth-ii-cup": (
        "FWD QEII Cup",
        "QEII Cup",
    ),
    "france-alain-du-breil-course-de-haies-de-printemps-des-4-ans-hurdle": (
        "Alain du Breil",
    ),
    "france-carmarthen-hurdle": (
        "Carmarthen",
    ),
    "france-chambly-de-hurdle": (
        "de Chambly",
    ),
    "france-compiegne-de-hurdle": (
        "de Compiegne",
        "Compiegne",
    ),
    "france-d-indy-hurdle": (
        "d'Indy",
    ),
}

CALENDAR_SERIES_RELOCATIONS = {
    "france-compiegne-de-hurdle",
}

HKJC_PATTERN_RACECOURSES = {
    "JANUARYCUP": "Happy Valley",
    "JANUARYCUPH": "Happy Valley",
}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _iso_date(year: int, month: int, day: int) -> str:
    return datetime(year, month, day).date().isoformat()


def _month_number(value: str) -> int:
    key = value.strip().rstrip(".").lower()
    if key not in MONTHS:
        raise ValueError(f"unsupported month: {value}")
    return MONTHS[key]


def _display_compact_race_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").upper()
    value = value.replace("H’CAP", "HANDICAP").replace("H'CAP", "HANDICAP")
    value = value.replace("!", " ")
    replacements = {
        "SKYSPORTS": "SKY SPORTS ",
        "WILLIAMHILL": "WILLIAM HILL ",
        "SODEXOLIVE": "SODEXO LIVE ",
        "BET365CELEBRATION": "BET365 CELEBRATION",
        "RACINGASTON": "RACING ASTON",
        "ASTONPARK": "ASTON PARK",
        "CORONATIONCUP": "CORONATION CUP",
        "CELEBRATIONMILE": "CELEBRATION MILE",
        "ULTIMAHANDICAP": "ULTIMA HANDICAP",
        "CUPHANDICAP": "CUP HANDICAP",
        "GOLDCUP": "GOLD CUP",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    value = re.sub(r"\([^)]*\)", " ", value)
    return _collapse(value)


def _calendar_key(value: str) -> str:
    value = SPONSOR_RE.sub(" ", unicodedata.normalize("NFKC", value or ""))
    value = re.split(r"\s+-\s+(?:First|Second|Final)\s+Leg\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = value.replace("H’Cap", "Handicap").replace("H'Cap", "Handicap")
    value = re.sub(r"\bH\.?\s*(?=(?:Hurdle|Stp|Chase))", "Handicap ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bStp\.?\b", "Chase", value, flags=re.IGNORECASE)
    value = re.sub(r"\bS(?:takes?)?\.?(?=\s|$)", " ", value, flags=re.IGNORECASE)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char)).upper()
    return re.sub(r"[^A-Z0-9]+", "", value)


def _calendar_name_score(target_name: str, source_name: str) -> float:
    left = _calendar_key(target_name)
    right = _calendar_key(source_name)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if min(len(left), len(right)) >= 5 and (left in right or right in left):
        ratio = min(len(left), len(right)) / max(len(left), len(right))
        return 0.85 + ratio * 0.15
    return SequenceMatcher(None, left, right).ratio() * 0.8


def _calendar_course_key(value: str) -> str:
    key = _calendar_key(value)
    aliases = {
        "CAGNES": "CAGNESSURMER",
        "EPSOMDOWNS": "EPSOM",
        "FONTAINEBLEAUGALOP": "FONTAINEBLEAU",
        "HAYDOCKPARK": "HAYDOCK",
        "KEMPTONPARK": "KEMPTON",
        "SANDOWNPARK": "SANDOWN",
    }
    return aliases.get(key, key)


def _distance_measurement(value: str, region: str) -> tuple[str, float] | None:
    raw = _collapse(value).lower().replace("½", ".5")
    raw = re.sub(
        r"(?P<whole>\d+)\s+1/2f",
        lambda match: f"{int(match.group('whole')) + 0.5:g}f",
        raw,
    )
    raw = re.sub(
        r"(?P<whole>\d*)1/2f",
        lambda match: f"{int(match.group('whole') or 0) + 0.5:g}f",
        raw,
    )
    if not raw:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        if region in {"france", "hong_kong", "japan"}:
            return ("metric", float(raw))
        numeric = float(raw)
        return ("imperial", numeric * (220 if numeric >= 5 else 1760))
    metric = re.fullmatch(r"(?P<metres>\d+(?:\.\d+)?)\s*m", raw)
    if metric:
        return ("metric", float(metric.group("metres")))
    furlongs = re.fullmatch(r"(?P<furlongs>\d+(?:\.\d+)?)\s*f", raw)
    if furlongs:
        return ("imperial", float(furlongs.group("furlongs")) * 220)
    imperial = re.fullmatch(
        r"(?:(?P<miles>\d+(?:\.\d+)?)\s*m)?\s*"
        r"(?:(?P<furlongs>\d+(?:\.\d+)?)\s*f)?\s*"
        r"(?:(?P<yards>\d+(?:\.\d+)?)\s*y(?:ds?)?)?",
        raw,
    )
    if imperial and any(imperial.groupdict().values()):
        yards = float(imperial.group("miles") or 0) * 1760
        yards += float(imperial.group("furlongs") or 0) * 220
        yards += float(imperial.group("yards") or 0)
        return ("imperial", yards)
    return None


def _distance_compatible(target: dict, source: dict) -> bool:
    left = _distance_measurement(str(target.get("distance_text") or ""), str(target.get("country_region") or ""))
    right = _distance_measurement(str(source.get("distance_text") or ""), str(target.get("country_region") or ""))
    if left is None or right is None or left[0] != right[0]:
        return True
    largest = max(left[1], right[1], 1)
    return abs(left[1] - right[1]) / largest <= 0.08


def _target_calendar_names(target: dict) -> list[str]:
    names = [str(target.get("original_name") or "")]
    names.extend(CALENDAR_SERIES_ALIASES.get(str(target.get("series_key") or ""), ()))
    series_key = str(target.get("series_key") or "")
    if series_key:
        region_prefix = f"{str(target.get('country_region') or '').replace('_', '-')}-"
        if series_key.lower().startswith(region_prefix.lower()):
            series_key = series_key[len(region_prefix) :]
        parts = series_key.split("_")
        if parts and parts[0] == "GBR":
            parts = parts[2:]
        names.append(" ".join(parts).replace("-", " "))
    return [name for name in names if _calendar_key(name)]


def match_official_schedule_targets(targets: list[dict], schedule_rows: list[dict]) -> dict:
    matches = []
    issues = []
    event_date_counts = defaultdict(lambda: defaultdict(int))
    for source in schedule_rows:
        event_identity = (
            source.get("edition_year"),
            _calendar_course_key(str(source.get("racecourse") or "")),
            _calendar_key(str(source.get("race_name") or "")),
        )
        event_date_counts[event_identity][source.get("local_date")] += 1
    majority_dates = {}
    for event_identity, date_counts in event_date_counts.items():
        maximum = max(date_counts.values(), default=0)
        winners = [date for date, count in date_counts.items() if count == maximum]
        if maximum >= 2 and len(winners) == 1:
            majority_dates[event_identity] = winners[0]

    sources_by_identity = {}
    for source in schedule_rows:
        event_identity = (
            source.get("edition_year"),
            _calendar_course_key(str(source.get("racecourse") or "")),
            _calendar_key(str(source.get("race_name") or "")),
        )
        if (
            event_identity in majority_dates
            and source.get("local_date") != majority_dates[event_identity]
        ):
            continue
        identity = (
            source.get("edition_year"),
            source.get("local_date"),
            _calendar_course_key(str(source.get("racecourse") or "")),
            _calendar_key(str(source.get("race_name") or "")),
        )
        existing = sources_by_identity.get(identity)
        if existing is None:
            sources_by_identity[identity] = dict(source)
            continue
        for key, value in source.items():
            if value and not existing.get(key):
                existing[key] = value
    deduped_sources = list(sources_by_identity.values())
    for target in targets:
        year = int(target.get("year") or 0)
        series_key = str(target.get("series_key") or "")
        minimum_name_score = 0.5 if target.get("country_region") == "france" else 0.35
        course_key = _calendar_course_key(str(target.get("racecourse") or ""))
        candidates = []
        for source in deduped_sources:
            source_year = int(source.get("edition_year") or str(source.get("local_date") or "0")[:4] or 0)
            if source_year != year:
                continue
            source_course_key = _calendar_course_key(str(source.get("racecourse") or ""))
            score = max(
                (_calendar_name_score(name, str(source.get("race_name") or "")) for name in _target_calendar_names(target)),
                default=0.0,
            )
            if score < minimum_name_score:
                continue
            if source_course_key != course_key and not (series_key in CALENDAR_SERIES_RELOCATIONS and score >= 0.8):
                continue
            candidates.append((score, source))
        if not candidates:
            issues.append({"target_id": target.get("target_id"), "code": "official_schedule_match_missing"})
            continue
        target_grade = str(target.get("normalized_grade") or "").upper()
        grade_candidates = [
            (score, source)
            for score, source in candidates
            if target_grade and str(source.get("normalized_grade") or "").upper() == target_grade
        ]
        if grade_candidates:
            candidates = grade_candidates
        distance_candidates = [
            (score, source)
            for score, source in candidates
            if _distance_compatible(target, source)
        ]
        if distance_candidates:
            candidates = distance_candidates
        detailed_candidates = [
            (score, source)
            for score, source in candidates
            if source.get("calendar_source_parser") != "france_obstacle_summary"
        ]
        summary_candidates = [
            (score, source)
            for score, source in candidates
            if source.get("calendar_source_parser") == "france_obstacle_summary"
        ]
        if (
            detailed_candidates
            and summary_candidates
            and max(score for score, _source in detailed_candidates)
            >= max(score for score, _source in summary_candidates)
        ):
            candidates = detailed_candidates
        best_score = max(score for score, _source in candidates)
        best = [source for score, source in candidates if abs(score - best_score) < 1e-9]
        if len(best) != 1:
            issues.append(
                {
                    "target_id": target.get("target_id"),
                    "code": "official_schedule_match_not_unique",
                    "match_count": len(best),
                }
            )
            continue
        source = best[0]
        matches.append(
            {
                "target_id": target.get("target_id"),
                "series_key": target.get("series_key"),
                "edition_year": year,
                "local_date": source.get("local_date"),
                "racecourse": source.get("racecourse"),
                "race_name": source.get("race_name"),
                "distance_text": source.get("distance_text") or _distance_with_unit(target),
                "normalized_grade": source.get("normalized_grade") or target.get("normalized_grade") or "",
                "name_score": round(best_score, 6),
                "calendar_source_url": source.get("calendar_source_url") or "",
                "calendar_source_provider": source.get("calendar_source_provider") or "",
                "calendar_source_authority": source.get("calendar_source_authority") or "",
                "annual_surface": source.get("annual_surface") or "",
                "annual_discipline": source.get("annual_discipline") or "",
            }
        )
    source_users = defaultdict(list)
    for match in matches:
        identity = (
            match.get("edition_year"),
            match.get("local_date"),
            _calendar_course_key(str(match.get("racecourse") or "")),
            _calendar_key(str(match.get("race_name") or "")),
        )
        source_users[identity].append(int(match["target_id"]))
    reused_target_ids = {
        target_id
        for target_ids in source_users.values()
        if len(target_ids) > 1
        for target_id in target_ids
    }
    if reused_target_ids:
        matches = [match for match in matches if int(match["target_id"]) not in reused_target_ids]
        for target_ids in source_users.values():
            if len(target_ids) <= 1:
                continue
            for target_id in sorted(target_ids):
                issues.append(
                    {
                        "target_id": target_id,
                        "code": "official_schedule_source_reused",
                        "conflicting_target_ids": sorted(target_ids),
                    }
                )
    return {
        "matches": sorted(matches, key=lambda row: int(row["target_id"])),
        "issues": sorted(issues, key=lambda row: int(row.get("target_id") or 0)),
    }


def merge_manual_calendar_evidence(targets: list[dict], result: dict, manual_rows: list[dict]) -> dict:
    target_by_id = {int(target["target_id"]): target for target in targets}
    matches = list(result.get("matches") or [])
    matched_ids = {int(match["target_id"]) for match in matches}
    manual_ids = set()
    for row in manual_rows:
        target_id = int(row.get("target_id") or 0)
        target = target_by_id.get(target_id)
        if (
            target is None
            or str(row.get("series_key") or "") != str(target.get("series_key") or "")
            or int(row.get("edition_year") or 0) != int(target.get("year") or 0)
        ):
            raise ValueError(f"manual evidence identity mismatch: {target_id}")
        if target_id in matched_ids or target_id in manual_ids:
            raise ValueError(f"manual evidence duplicates matched target: {target_id}")
        manual_ids.add(target_id)
        matches.append(dict(row))
    issues = [issue for issue in (result.get("issues") or []) if int(issue.get("target_id") or 0) not in manual_ids]
    return {
        "matches": sorted(matches, key=lambda row: int(row["target_id"])),
        "issues": sorted(issues, key=lambda row: int(row.get("target_id") or 0)),
    }


def _calendar_event_slug(target: dict) -> str:
    region = str(target.get("country_region") or "")
    series_key = str(target.get("series_key") or "")
    prefix = f"{region}-"
    base = series_key if series_key.startswith(prefix) else f"{prefix}{series_key}"
    suffix = f"-{int(target['year'])}"
    return f"{base[: 160 - len(suffix)]}{suffix}"


def build_calendar_event_input_rows(targets: list[dict], matches: list[dict]) -> list[dict]:
    target_by_id = {int(target["target_id"]): target for target in targets}
    rows = []
    seen = set()
    for match in matches:
        target_id = int(match.get("target_id") or 0)
        target = target_by_id.get(target_id)
        if target is None or target_id in seen:
            raise ValueError(f"calendar match target is missing or duplicated: {target_id}")
        if (
            str(match.get("series_key") or "") != str(target.get("series_key") or "")
            or int(match.get("edition_year") or 0) != int(target.get("year") or 0)
        ):
            raise ValueError(f"calendar match identity mismatch: {target_id}")
        seen.add(target_id)
        source_refs = json.loads(json.dumps(target.get("source_refs") or {}, ensure_ascii=False))
        calendar_discovery = {
            key: value
            for key, value in match.items()
            if key not in {"target_id", "series_key"} and value is not None and value != ""
        }
        source_refs["calendar_discovery"] = calendar_discovery
        source_url = str(match.get("source_url") or "")
        source_provider = str(match.get("source_provider") or "")
        source_authority = str(match.get("source_authority") or "")
        if source_url and source_provider:
            source_refs["detail_discovery"] = {
                "adapter_key": source_provider,
                "urls": {
                    "result_url": {
                        "url": source_url,
                        "source_provider": source_provider,
                        "source_authority": source_authority,
                        "redirect_chain": [],
                    }
                },
            }
        rows.append(
            {
                "target_id": target_id,
                "target_sha256": target.get("target_sha256") or "",
                "inventory_artifact_sha256": target.get("artifact_sha256") or "",
                "year": int(target["year"]),
                "slug": _calendar_event_slug(target),
                "original_name": target.get("original_name") or "",
                "chinese_name": target.get("chinese_name") or "",
                "country_region": target.get("country_region") or "",
                "racecourse": match.get("racecourse") or target.get("racecourse") or "",
                "grade_text": match.get("normalized_grade") or target.get("grade_text") or "",
                "normalized_grade": match.get("normalized_grade") or target.get("normalized_grade") or "",
                "surface": match.get("annual_surface") or target.get("surface") or "",
                "distance_text": match.get("distance_text") or target.get("distance_text") or "",
                "status": "finished",
                "local_date": match.get("local_date") or "",
                "source_refs": source_refs,
            }
        )
    return sorted(rows, key=lambda row: (row["country_region"], row["year"], row["slug"]))


def write_calendar_event_inputs(rows: list[dict], output_dir: Path) -> dict[str, str]:
    fieldnames = [
        "target_id",
        "target_sha256",
        "inventory_artifact_sha256",
        "year",
        "slug",
        "original_name",
        "chinese_name",
        "country_region",
        "racecourse",
        "grade_text",
        "normalized_grade",
        "surface",
        "distance_text",
        "status",
        "local_date",
        "source_refs",
    ]
    by_region = defaultdict(list)
    for row in rows:
        by_region[row["country_region"]].append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for region, region_rows in sorted(by_region.items()):
        path = output_dir / f"events_{region}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in region_rows:
                payload = dict(row)
                payload["source_refs"] = json.dumps(
                    payload.get("source_refs") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                writer.writerow(payload)
        files[region] = str(path)
    return files


def _hkjc_date_in_season(year: int, month: int, edition_year: int | None) -> bool:
    return edition_year is None or (
        (year == edition_year and month <= 6)
        or (year == edition_year - 1 and month >= 7)
    )


def _parse_hkjc_chronological_group_table(
    text: str, *, edition_year: int | None
) -> list[dict]:
    marker = "List of Group Races in"
    if marker not in text:
        return []
    section = text.split(marker, 1)[1].split("List of Group Race Closing Dates", 1)[0]
    pattern = re.compile(
        r"^\s*(?:(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})\s+(?P<year>\d{4})\s+)?"
        r"(?P<name>.+?)\s+(?P<status>HKG[123]|G[123])\s+\$[\d,]+\s+"
        r"(?P<distance>\d{3,4})\b",
        re.IGNORECASE,
    )
    month_numbers = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    rows = []
    current_date: tuple[int, int, int] | None = None
    for line in section.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        if match.group("day"):
            month = month_numbers.get(match.group("month").casefold())
            if month is None:
                continue
            current_date = (int(match.group("year")), month, int(match.group("day")))
        if current_date is None:
            continue
        year, month, day = current_date
        if not _hkjc_date_in_season(year, month, edition_year):
            continue
        race_name = _collapse(match.group("name"))
        rows.append(
            {
                "local_date": _iso_date(year, month, day),
                "edition_year": edition_year or year,
                "racecourse": HKJC_PATTERN_RACECOURSES.get(
                    _calendar_key(race_name), "Sha Tin"
                ),
                "race_name": race_name,
                "normalized_grade": f"G{match.group('status')[-1]}",
                "distance_text": f"{int(match.group('distance'))}m",
            }
        )
    return rows


def _parse_hkjc_course_records_table(
    text: str, *, edition_year: int | None
) -> list[dict]:
    marker = "Black Type Races for"
    if "COURSE RECORDS" not in text or marker not in text:
        return []
    section = text[text.index(marker) :]
    course_header = re.compile(
        r"^\s*(?:(?P<distance>\d{4})\s+)?(?P<course>Sha Tin|Happy Valley)\s+-\s+"
        r"[A-Z]+\s+.+?\s+[A-Z]{2,3}\s+\d{2}\s+[A-Za-z]{3}\s+\d{4}\s+"
        r"\d+\.\d+\.\d+\s+(?P<race>.+)$"
    )
    race_pattern = re.compile(
        r"^(?P<name>.+?)\s+(?P<status>G[123]|4yo)\s+"
        r"(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{2})\s+[\d,]+\s+\d+\s*$",
        re.IGNORECASE,
    )
    rows = []
    current_distance = 0
    current_course = ""
    for line in section.splitlines():
        line = _collapse(line)
        header_match = course_header.match(line)
        if header_match is not None:
            if header_match.group("distance"):
                current_distance = int(header_match.group("distance"))
            current_course = header_match.group("course")
            line = header_match.group("race")
        match = race_pattern.match(line)
        if match is None or not current_distance or not current_course:
            continue
        year = 2000 + int(match.group("year"))
        month = int(match.group("month"))
        if not _hkjc_date_in_season(year, month, edition_year):
            continue
        status = match.group("status").upper()
        rows.append(
            {
                "local_date": _iso_date(year, month, int(match.group("day"))),
                "edition_year": edition_year or year,
                "racecourse": current_course,
                "race_name": _collapse(match.group("name")),
                "normalized_grade": status if status.startswith("G") else "",
                "distance_text": f"{current_distance}m",
            }
        )
    return rows


def parse_hkjc_pattern_schedule_text(text: str, *, edition_year: int | None = None) -> list[dict]:
    rows = [
        *_parse_hkjc_chronological_group_table(text, edition_year=edition_year),
        *_parse_hkjc_course_records_table(text, edition_year=edition_year),
    ]
    pattern = re.compile(
        r"^\s*(?:[A-Z]{3}\s+)?(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{2})\s+"
        r"(?P<name>.+?)\s+G(?P<grade>[123])\s+.*?\b\dyo\+?\s+(?P<distance>\d{3,4})\b",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        match = pattern.search(line)
        if match is None:
            continue
        year = 2000 + int(match.group("year"))
        month = int(match.group("month"))
        if not _hkjc_date_in_season(year, month, edition_year):
            continue
        race_name = _collapse(match.group("name"))
        rows.append(
            {
                "local_date": _iso_date(year, month, int(match.group("day"))),
                "edition_year": edition_year or year,
                "racecourse": HKJC_PATTERN_RACECOURSES.get(_calendar_key(race_name), "Sha Tin"),
                "race_name": race_name,
                "normalized_grade": f"G{match.group('grade')}",
                "distance_text": f"{int(match.group('distance'))}m",
            }
        )
    deduplicated = {
        (
            row["local_date"],
            _calendar_key(row["race_name"]),
            _calendar_course_key(row["racecourse"]),
            row["distance_text"],
        ): row
        for row in rows
    }
    return list(deduplicated.values())


def parse_hkjc_results_all_schedule(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    grade_words = {"ONE": "G1", "TWO": "G2", "THREE": "G3"}
    for block in soup.select("div.race_result div.f_fs13.margin_top15"):
        direct_divs = block.find_all("div", recursive=False)
        race_label = next((_collapse(node.get_text(" ", strip=True)) for node in direct_divs if "Race" in node.get_text()), "")
        race_match = re.search(r"\bRace\s*(\d+)\b", race_label, re.IGNORECASE)
        descriptor = next(
            (
                _collapse(node.get_text(" ", strip=True))
                for node in direct_divs
                if " - " in node.get_text(" ", strip=True) and "M" in node.get_text(" ", strip=True).upper()
            ),
            "",
        )
        distance_match = re.search(r"\b(\d{3,4})M\b", descriptor, re.IGNORECASE)
        if race_match is None or distance_match is None:
            continue
        grade_match = re.search(r"\bGroup\s+(One|Two|Three)\b", descriptor, re.IGNORECASE)
        race_name = _collapse(descriptor.rsplit(" - ", 1)[-1])
        rows.append(
            {
                "race_no": str(int(race_match.group(1))),
                "race_name": race_name,
                "normalized_grade": grade_words.get(grade_match.group(1).upper(), "") if grade_match else "",
                "distance_text": f"{int(distance_match.group(1))}m",
            }
        )
    return rows


def resolve_hkjc_result_urls(matches: list[dict], result_pages: dict[tuple[str, str], list[dict]]) -> dict:
    course_codes = {"SHATIN": "ST", "HAPPYVALLEY": "HV"}
    resolved = []
    issues = []
    used = defaultdict(list)
    for match in matches:
        course_code = course_codes.get(_calendar_course_key(str(match.get("racecourse") or "")), "")
        page_rows = result_pages.get((str(match.get("local_date") or ""), course_code), [])
        candidates = []
        for row in page_rows:
            score = _calendar_name_score(str(match.get("race_name") or ""), str(row.get("race_name") or ""))
            if score < 0.5:
                continue
            candidates.append((score, row))
        if candidates:
            best_score = max(score for score, _row in candidates)
            best = [row for score, row in candidates if abs(score - best_score) < 1e-9]
            target_grade = str(match.get("normalized_grade") or "").upper()
            grade_matches = [row for row in best if str(row.get("normalized_grade") or "").upper() == target_grade]
            if grade_matches:
                best = grade_matches
            distance_matches = [row for row in best if _distance_compatible({**match, "country_region": "hong_kong"}, row)]
            if distance_matches:
                best = distance_matches
        else:
            best = []
        if len(best) != 1 or not course_code:
            issues.append(
                {
                    "target_id": match.get("target_id"),
                    "code": "hkjc_result_url_match_not_unique",
                    "match_count": len(best),
                }
            )
            continue
        row = best[0]
        identity = (match.get("local_date"), course_code, row["race_no"])
        used[identity].append(int(match["target_id"]))
        resolved.append(
            {
                **match,
                "source_url": (
                    "https://racing.hkjc.com/en-us/local/information/localresults"
                    f"?racedate={match['local_date'].replace('-', '/')}&Racecourse={course_code}&RaceNo={row['race_no']}"
                ),
                "source_provider": "hkjc",
                "source_authority": "official",
                "result_race_name": row["race_name"],
                "result_race_no": row["race_no"],
            }
        )
    reused = {target_id for ids in used.values() if len(ids) > 1 for target_id in ids}
    if reused:
        resolved = [row for row in resolved if int(row["target_id"]) not in reused]
        for identity, target_ids in used.items():
            if len(target_ids) > 1:
                for target_id in sorted(target_ids):
                    issues.append(
                        {
                            "target_id": target_id,
                            "code": "hkjc_result_url_reused",
                            "conflicting_target_ids": sorted(target_ids),
                        }
                    )
    return {
        "matches": sorted(resolved, key=lambda row: int(row["target_id"])),
        "issues": sorted(issues, key=lambda row: int(row.get("target_id") or 0)),
    }


def parse_bha_flat_schedule_text(text: str, *, year: int) -> list[dict]:
    rows = []
    course_pattern = "|".join(
        re.sub(r"(PARK|DOWNS|RASEN)$", r"\\s*\1", key)
        for key in sorted(BHA_COURSES, key=len, reverse=True)
    )
    closing_date_pattern = re.compile(
        rf"^\s*(?:(?:[A-Z][a-z]{{2,3}}\.?)|[”\"])\s*\d{{1,2}}\s+"
        rf"(?P<course>{course_pattern})\s+"
        rf"(?P<month>[A-Z][a-z]{{2,3}})\.?\s*(?P<day>\d{{1,2}})\s+"
        rf"(?P<name>.+?)\(P(?P<grade>[123])(?:\.[A-Z])*\.\)",
        re.IGNORECASE,
    )
    chronological_pattern = re.compile(
        rf"^\s*(?P<month>[A-Z][a-z]{{2,3}}\.?|[”\"])\s*(?P<day>\d{{1,2}})\s+"
        rf"(?P<course>{course_pattern})\s+"
        rf"(?P<name>.+?)\(P(?P<grade>[123])(?:\.[A-Z])*\.\)",
        re.IGNORECASE,
    )
    raw_lines = text.splitlines()
    logical_lines = []
    for index, line in enumerate(raw_lines):
        combined = line
        if not re.search(r"\(P[123]", combined):
            for continuation in raw_lines[index + 1 : index + 3]:
                if re.match(r"^\s*(?:(?:[A-Z][a-z]{2,3}\.?|[”\"])\s*\d{1,2})\b", continuation):
                    break
                combined += continuation.strip()
                if re.search(r"\(P[123]", combined):
                    break
        logical_lines.append(combined)
    current_month = None
    for line in logical_lines:
        match = closing_date_pattern.search(line)
        explicit_race_date = match is not None
        if match is not None:
            month = _month_number(match.group("month"))
        else:
            match = chronological_pattern.search(line)
            if match is None:
                continue
            month_text = match.group("month")
            if month_text in {'”', '"'}:
                if current_month is None:
                    continue
                month = current_month
            else:
                month = _month_number(month_text)
                current_month = month
        if match is None:
            continue
        try:
            local_date = _iso_date(year, month, int(match.group("day")))
        except ValueError:
            continue
        rows.append(
            {
                "local_date": local_date,
                "racecourse": BHA_COURSES[re.sub(r"\s+", "", match.group("course")).upper()],
                "race_name": _display_compact_race_name(match.group("name")),
                "normalized_grade": f"G{match.group('grade')}",
                "distance_text": "",
                "_explicit_race_date": explicit_race_date,
            }
        )
    authoritative = {
        (
            _calendar_course_key(row["racecourse"]),
            _calendar_key(row["race_name"]),
            row["normalized_grade"],
        )
        for row in rows
        if row["_explicit_race_date"]
    }
    return [
        {key: value for key, value in row.items() if key != "_explicit_race_date"}
        for row in rows
        if row["_explicit_race_date"]
        or (
            _calendar_course_key(row["racecourse"]),
            _calendar_key(row["race_name"]),
            row["normalized_grade"],
        )
        not in authoritative
    ]


def parse_bha_jump_schedule_text(text: str, *, season_start_year: int) -> list[dict]:
    rows = []
    course_pattern = "|".join(
        re.sub(r"(PARK|DOWNS|RASEN)$", r"\\s*\1", key)
        for key in sorted(BHA_COURSES, key=len, reverse=True)
    )
    index_pattern = re.compile(
        rf"^\s*(?P<month>[A-Z][a-z]{{2,3}})\.?\s*(?P<day>\d{{1,2}})\s+"
        rf"(?P<course>{course_pattern})\s+(?P<name>.+?)\s+"
        rf"\d(?:\+|-\d)?(?:F)?\s+(?P<grade>Prem|Listed|[123])\s+\d+\s*$",
        re.IGNORECASE,
    )
    detail_pattern = re.compile(
        rf"^\s*(?P<month>[A-Z][a-z]{{2,3}})\.?\s*(?P<day>\d{{1,2}})\s+"
        rf"(?P<course>{course_pattern})\s+(?P<name>.+?)\s+"
        rf"(?P<distance>(?:\d+m(?:\d+(?:/\d+)?f)?|\d+(?:/\d+)?f)\+?)\s+"
        rf"(?P<grade>Prem|Listed|[123])\s+[\d,]+\s*$",
        re.IGNORECASE,
    )
    raw_lines = text.splitlines()
    logical_lines = []
    for index, line in enumerate(raw_lines):
        combined = line
        if detail_pattern.search(combined) is None and index_pattern.search(combined) is None:
            for continuation in raw_lines[index + 1 : index + 3]:
                if re.match(r"^\s*[A-Z][a-z]{2,3}\.?\s*\d{1,2}\b", continuation):
                    break
                combined += continuation.strip()
                if detail_pattern.search(combined) is not None or index_pattern.search(combined) is not None:
                    break
        logical_lines.append(combined)
    for line in logical_lines:
        match = detail_pattern.search(line) or index_pattern.search(line)
        if match is None:
            continue
        month = _month_number(match.group("month"))
        year = season_start_year if month >= 7 else season_start_year + 1
        grade = match.group("grade").upper()
        rows.append(
            {
                "local_date": _iso_date(year, month, int(match.group("day"))),
                "racecourse": BHA_COURSES[re.sub(r"\s+", "", match.group("course")).upper()],
                "race_name": _display_compact_race_name(match.group("name")),
                "normalized_grade": "G3" if grade == "PREM" else (f"G{grade}" if grade.isdigit() else grade),
                "distance_text": match.groupdict().get("distance") or "",
            }
        )
    return rows


def parse_france_galop_flat_schedule_text(text: str, *, year: int) -> list[dict]:
    rows = []
    for line in text.splitlines():
        date_match = re.match(r"^\s*(?P<day>\d{1,2})-(?P<month>\d{2})\s+(?P<body>.+)$", line)
        if date_match is None or "Groupe " not in line:
            continue
        body = date_match.group("body")
        course = next((item for item in FRANCE_COURSES if body.startswith(item + " ")), "")
        if not course:
            continue
        remainder = body[len(course) :].strip()
        group_match = re.search(r"\s+Groupe\s+(?P<grade>I{1,3})\s+(?P<distance>[\d ]+)\s*$", remainder)
        if group_match is None:
            continue
        prefix = remainder[: group_match.start()].strip()
        name_match = re.match(
            r"^.*(?:\b\d+\s+ans\b|\b\d+\s*&\s*\+)\s+(?:[FMH]\s+)?(?P<name>.+)$",
            prefix,
        )
        if name_match is None:
            continue
        distance = int(re.sub(r"\s+", "", group_match.group("distance")))
        rows.append(
            {
                "local_date": _iso_date(year, int(date_match.group("month")), int(date_match.group("day"))),
                "racecourse": course.replace("'", "’"),
                "race_name": _collapse(name_match.group("name")),
                "normalized_grade": f"G{len(group_match.group('grade'))}",
                "distance_text": f"{distance}m",
            }
        )
    return rows


def parse_france_galop_flat_program_text(text: str, *, year: int) -> list[dict]:
    rows = []
    in_aqps_index = False
    section_end = re.compile(
        r"^(?:Anglo-Arabes|Arabes Purs|Filiere obstacle|Filière obstacle)\s*$",
        re.IGNORECASE,
    )
    row_pattern = re.compile(
        r"^\s*(?P<day>\d{1,2})-(?P<month>\d{2})\s+"
        r"(?P<course>.+?)\s+"
        r"\d{1,3}(?:\s+\d{3})+\s+"
        r"(?:\d+\s+ans|\d+\s*&\s*(?:\d+|\+)|\d+\s*,\s*\d+\s*&\s*\d+)\s+"
        r"(?:(?:F|M|H)(?:\s+(?:F|M|H))?\s+)?"
        r"(?:[•·]\s+)?"
        r"(?P<name>.+?)\s+"
        r"(?P<distance>\d(?:\s+\d{3})?)\s*$",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        compact = _collapse(line)
        if re.sub(r"[^A-Z]", "", compact.upper()) == "AQPS":
            in_aqps_index = True
            continue
        if not in_aqps_index:
            continue
        if section_end.match(compact):
            break
        match = row_pattern.match(compact)
        if match is None:
            continue
        rows.append(
            {
                "local_date": _iso_date(
                    year,
                    int(match.group("month")),
                    int(match.group("day")),
                ),
                "racecourse": _collapse(match.group("course")).replace("'", "’"),
                "race_name": _collapse(match.group("name")),
                "normalized_grade": "",
                "distance_text": f"{int(re.sub(r'\s+', '', match.group('distance')))}m",
            }
        )
    return rows


def parse_france_galop_obstacle_schedule_text(
    text: str,
    *,
    year: int,
    date_start: str = "",
    date_end: str = "",
) -> list[dict]:
    rows = []
    start = datetime.fromisoformat(date_start).date() if date_start else None
    end = datetime.fromisoformat(date_end).date() if date_end else None
    if (start is None) != (end is None) or (start is not None and start > end):
        raise ValueError("France obstacle date window is invalid")

    def source_date(month: int, day: int) -> str | None:
        if start is None or end is None:
            return _iso_date(year, month, day)
        candidates = []
        for candidate_year in range(start.year, end.year + 1):
            try:
                candidate = datetime(candidate_year, month, day).date()
            except ValueError:
                continue
            if start <= candidate <= end:
                candidates.append(candidate)
        if len(candidates) != 1 or candidates[0].year != year:
            return None
        return candidates[0].isoformat()

    pattern = re.compile(
        r"^\s*(?P<day>\d{1,2})-(?P<month>\d{2})\s+"
        r"(?P<course>[A-Za-zÀ-ÿ’' -]+?)\s+"
        r"\d[\d ]*?\s+"
        r"\d+\s+(?:ans|&\s*\+)\s+"
        r"(?:(?:F|M|H)\s+)*"
        r"(?P<name>.+?)\s+Groupe\s+(?P<grade>I{1,3})\s+"
        r"(?P<distance>[\d ]+)\s*$",
        re.IGNORECASE,
    )
    alphabetical_pattern = re.compile(
        r"^\s*(?P<name>.+?)\s+(?:\.\s*){3,}"
        r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-zÀ-ÿ]+)\s+"
        r"(?P<course>[A-ZÀ-Ý’' -]+?)\s+\d+\s+\d+\s*$",
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if match is not None:
            local_date = source_date(int(match.group("month")), int(match.group("day")))
            if local_date is None:
                continue
            rows.append(
                {
                    "local_date": local_date,
                    "racecourse": _collapse(match.group("course")).replace("'", "’"),
                    "race_name": _collapse(match.group("name")),
                    "normalized_grade": f"G{len(match.group('grade'))}",
                    "distance_text": f"{int(re.sub(r'\s+', '', match.group('distance')))}m",
                }
            )
            continue
        match = alphabetical_pattern.match(line)
        if match is None:
            continue
        month_key = _calendar_key(match.group("month")).lower()
        if month_key not in FRENCH_MONTHS:
            continue
        local_date = source_date(FRENCH_MONTHS[month_key], int(match.group("day")))
        if local_date is None:
            continue
        rows.append(
            {
                "local_date": local_date,
                "racecourse": _collapse(match.group("course")).title().replace("'", "’"),
                "race_name": _collapse(match.group("name")).rstrip("."),
                "normalized_grade": "",
                "distance_text": "",
            }
        )
    return rows


def parse_france_galop_obstacle_group_summary_text(
    text: str,
    *,
    year: int,
) -> list[dict]:
    """Parse the fixed-width five-column France Galop obstacle group summary."""
    header_pattern = re.compile(r"\b(?:3|4)\s+ans\b|\b5\s+et\s+\+", re.IGNORECASE)
    date_pattern = re.compile(
        r"(?P<day>\d{1,2})/(?P<month>\d{2})\s*\((?P<course>[^)]+)\)"
    )
    grade_pattern = re.compile(r"\[G(?P<grade>[123])\]", re.IGNORECASE)
    distance_pattern = re.compile(r"(?<!\d)(?P<distance>[2-6]\s?\d{3})(?!\d)")
    ignored_names = {"HAIES", "STEEPLECHASE", "PROGRAMMENATIONALGROUPES"}
    french_month_names = {_calendar_key(name) for name in FRENCH_MONTHS}

    column_starts: list[int] = []
    states = [{} for _ in range(5)]
    rows = []

    def finish(column: int) -> None:
        state = states[column]
        required = {"name", "day", "month", "course", "grade", "distance"}
        if not required.issubset(state):
            return
        rows.append(
            {
                "local_date": _iso_date(year, state["month"], state["day"]),
                "racecourse": _collapse(state["course"]).title().replace("'", "’"),
                "race_name": _collapse(state["name"]),
                "normalized_grade": f"G{state['grade']}",
                "distance_text": f"{state['distance']}m",
            }
        )
        states[column] = {}

    def nearest_column(position: int) -> int:
        return min(
            range(len(column_starts)),
            key=lambda column: abs(column_starts[column] - position),
        )

    for line in text.splitlines():
        headers = list(header_pattern.finditer(line))
        if len(headers) == 5:
            column_starts = [match.start() for match in headers]
            states = [{} for _ in range(5)]
            continue
        if not column_starts:
            continue

        date_matches = list(date_pattern.finditer(line))
        grade_matches = list(grade_pattern.finditer(line))
        distance_matches = list(distance_pattern.finditer(line))
        for date_match in date_matches:
            column = nearest_column(date_match.start())
            states[column].update(
                {
                    "day": int(date_match.group("day")),
                    "month": int(date_match.group("month")),
                    "course": date_match.group("course"),
                }
            )
            finish(column)

        for index, grade_match in enumerate(grade_matches):
            column = nearest_column(grade_match.start())
            states[column]["grade"] = int(grade_match.group("grade"))
            segment_end = (
                grade_matches[index + 1].start()
                if index + 1 < len(grade_matches)
                else len(line)
            )
            distance_match = distance_pattern.search(
                line,
                grade_match.end(),
                segment_end,
            )
            if distance_match is not None:
                states[column]["distance"] = int(
                    re.sub(r"\s+", "", distance_match.group("distance"))
                )
            finish(column)

        if not grade_matches:
            for distance_match in distance_matches:
                column = nearest_column(distance_match.start())
                if "grade" not in states[column]:
                    continue
                states[column]["distance"] = int(
                    re.sub(r"\s+", "", distance_match.group("distance"))
                )
                finish(column)

        if not date_matches and not grade_matches and not distance_matches:
            chunks = re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", line)
            for chunk in chunks:
                cell = _collapse(chunk.group())
                if not cell:
                    continue
                column = nearest_column(chunk.start())
                state = states[column]
                name_key = _calendar_key(cell)
                is_name = (
                    any(char.isalpha() for char in cell)
                    and cell == cell.upper()
                    and name_key not in ignored_names
                    and name_key not in french_month_names
                    and not re.search(
                        r"\b(?:ans|mois|semestre)\b",
                        cell,
                        re.IGNORECASE,
                    )
                )
                if not is_name:
                    continue
                if state and state.get("name") != cell:
                    states[column] = {"name": cell}
                else:
                    state["name"] = cell
                finish(column)

    rows.sort(key=lambda row: (row["local_date"], row["race_name"]))
    return rows


def _normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", SPONSOR_RE.sub("", value or "")).upper()
    value = value.replace("STAKES", "S").replace("HANDICAP", "H")
    value = re.sub(r"\bTHE\b", "", value)
    return re.sub(r"[^A-Z0-9]+", "", value)


def _target_names(target: dict) -> set[str]:
    names = [target.get("original_name") or ""]
    names.extend(re.split(r"[|,]", str(target.get("aliases") or "")))
    return {_normalize_name(name) for name in names if _normalize_name(name)}


def _base_race_key(value: str) -> str:
    return value[:-1] if len(value) > 5 and value.endswith(("S", "H")) else value


def _name_score(left: str, right: str) -> float:
    left = _base_race_key(left)
    right = _base_race_key(right)
    if left == right:
        return 1.0
    if min(len(left), len(right)) >= 5 and (left in right or right in left):
        return min(len(left), len(right)) / max(len(left), len(right))
    return 0.0


def _best_name_matches(keys: set[str], sources: list[dict]) -> list[dict]:
    scored = []
    for source in sources:
        score = max((_name_score(key, source["race_key"]) for key in keys), default=0.0)
        if score > 0:
            scored.append((score, source))
    if not scored:
        return []
    best = max(score for score, _source in scored)
    return [source for score, source in scored if score == best]


def _toba_core_name_qualifiers(value: str) -> set[str]:
    words = set(re.findall(r"[A-Z0-9]+", unicodedata.normalize("NFKC", value or "").upper()))
    return {qualifier for qualifier in TOBA_CORE_NAME_QUALIFIERS if qualifier in words}


def _toba_target_names(target: dict) -> list[str]:
    names = [str(target.get("original_name") or "")]
    names.extend(re.split(r"[|,]", str(target.get("aliases") or "")))
    names.extend(TOBA_SERIES_ALIASES.get(str(target.get("series_key") or ""), ()))
    return [name for name in names if name]


def _toba_target_keys(target: dict) -> set[str]:
    keys = set()
    for name in _toba_target_names(target):
        keys.add(_normalize_name(name))
        keys.add(_normalize_name(_toba_shape_key(name)))
    return {key for key in keys if key}


def _toba_core_name_compatible(target: dict, source: dict) -> bool:
    source_qualifiers = _toba_core_name_qualifiers(str(source.get("race_name") or ""))
    return any(
        _toba_core_name_qualifiers(name) == source_qualifiers
        for name in _toba_target_names(target)
    )


def _toba_shape_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", SPONSOR_RE.sub("", value or "")).upper()
    value = re.sub(r"\(\s*FORMERLY[^)]*\)", " ", value)
    value = re.split(r"\b(?:PRESENTED|SPONSORED)\s+BY\b", value, maxsplit=1)[0]
    value = re.sub(r"\b(?:STAKES|HANDICAP)\b", " ", value)
    value = re.sub(r"\b[SH]\.?\s*(?=PRESENTED\b|SPONSORED\b|$)", " ", value)
    value = re.sub(r"\bTHE\b", " ", value)
    return re.sub(r"[^A-Z0-9]+", "", value)


def _toba_name_shape_compatible(target: dict, source: dict) -> bool:
    source_key = _toba_shape_key(str(source.get("race_name") or ""))
    suffix_markers = ("PRESENTEDBY", "SPONSOREDBY", "INASSOCIATIONWITH")
    for target_name in _toba_target_names(target):
        target_key = _toba_shape_key(target_name)
        if not target_key:
            continue
        if target_key == source_key:
            return True
        if target_key in source_key:
            prefix, suffix = source_key.split(target_key, 1)
            if prefix and not suffix:
                return True
            if suffix.startswith(suffix_markers):
                return True
        if source_key in target_key:
            prefix, suffix = target_key.split(source_key, 1)
            if prefix and not suffix:
                return True
            if suffix.startswith(suffix_markers):
                return True
    return False


def _distance_with_unit(target: dict) -> str:
    value = str(target.get("distance_text") or "").strip()
    region = target.get("country_region")
    if re.fullmatch(r"\d+(?:\.\d+)?", value) and target.get("country_region") in {
        "france",
        "hong_kong",
        "japan",
    }:
        return f"{value}m"
    if re.fullmatch(r"\d+(?:\.\d+)?", value) and region == "united_states":
        return f"{value}f"
    if region == "united_kingdom":
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return f"{value}{'f' if float(value) >= 5 else 'm'}"
        compact = re.fullmatch(r"(?P<miles>\d+)m(?P<remainder>\d+(?:1/2)?|1/2)(?P<unit>[fy])", value)
        if compact:
            remainder = compact.group("remainder")
            if remainder.endswith("1/2"):
                whole = remainder[: -len("1/2")]
                remainder = f"{whole} 1/2" if whole else "1/2"
            return f"{compact.group('miles')}m {remainder}{compact.group('unit')}"
    return value


def _normalize_japanese_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").replace("ステークス", "S")
    value = re.sub(r"^(?:J\s*[・.]\s*)?G(?:I{1,3}|[ⅠⅡⅢ])\s*", "", value)
    return re.sub(r"[\s　・.（）()]+", "", value).upper()


def _source_result(url: str, *, provider: str, authority: str) -> dict:
    return {
        "result_url": {
            "url": url,
            "source_provider": provider,
            "source_authority": authority,
            "redirect_chain": [],
        }
    }


def parse_jra_english_schedule(body: bytes, *, year: int) -> list[dict]:
    soup = BeautifulSoup(body.decode("utf-8", errors="replace"), "html.parser")
    rows = []
    for heading in soup.find_all("th", colspan="7"):
        anchor = heading.find("a")
        date_node = heading.find("span")
        heading_row = heading.find_parent("tr")
        detail = heading_row.find_next_sibling("tr") if heading_row is not None else None
        if anchor is None or date_node is None or detail is None:
            continue
        result_anchor = next(
            (node for node in detail.find_all("a", href=True) if "doSubmit(" in node.get("href", "")),
            None,
        )
        if result_anchor is None:
            continue
        match = JRA_SUBMIT_RE.search(result_anchor["href"])
        if match is None or int(match.group("year")) != year:
            continue
        month_day = match.group("month_day")
        cells = detail.find_all(["td", "th"])
        rows.append(
            {
                "race_name": _collapse(anchor.get_text(" ", strip=True)),
                "race_key": _normalize_name(anchor.get_text(" ", strip=True)),
                "local_date": f"{year}-{month_day[:2]}-{month_day[2:]}",
                "racecourse": _collapse(cells[1].get_text(" ", strip=True)) if len(cells) > 1 else "",
                "distance": _collapse(cells[2].get_text(" ", strip=True)) if len(cells) > 2 else "",
            }
        )
    return rows


def parse_jra_history_records(body: bytes, *, year: int) -> list[dict]:
    text = body.decode("cp932", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    records = []
    for table in soup.find_all("table"):
        table_rows = table.find_all("tr")
        if not table_rows:
            continue
        headers = [_collapse(cell.get_text(" ", strip=True)) for cell in table_rows[0].find_all(["th", "td"])]
        if not {"月日", "レース名", "競馬場", "結果"} <= set(headers):
            continue
        date_index = headers.index("月日")
        name_index = headers.index("レース名")
        course_index = headers.index("競馬場")
        result_index = headers.index("結果")
        for tr in table_rows[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) <= max(date_index, course_index, result_index):
                continue
            date_match = re.search(r"(\d{1,2})月(\d{1,2})日", cells[date_index].get_text(" ", strip=True))
            result_link = cells[result_index].find("a", href=True)
            course = JRA_COURSES.get(_collapse(cells[course_index].get_text(" ", strip=True)), "")
            if date_match is None or result_link is None or not course:
                continue
            records.append(
                {
                    "local_date": f"{year}-{int(date_match.group(1)):02d}-{int(date_match.group(2)):02d}",
                    "race_name": _collapse(cells[name_index].get_text(" ", strip=True)),
                    "racecourse": course,
                    "result_url": urljoin(JRA_BASE_URL, result_link["href"]),
                }
            )
        if records:
            break
    return records


def build_jra_provider_rows(
    *, targets: list[dict], year: int, english_schedule_body: bytes, history_body: bytes
) -> dict:
    schedule = parse_jra_english_schedule(english_schedule_body, year=year)
    history_records = parse_jra_history_records(history_body, year=year)
    sources = [{**row, "result_url": ""} for row in schedule]
    group_keys = {(row["local_date"], row["racecourse"]) for row in sources}
    for group_key in group_keys:
        schedule_group = [row for row in sources if (row["local_date"], row["racecourse"]) == group_key]
        history_group = [
            row for row in history_records if (row["local_date"], row["racecourse"]) == group_key
        ]
        if len(schedule_group) == len(history_group):
            for schedule_row, history_row in zip(schedule_group, history_group, strict=True):
                schedule_row["result_url"] = history_row["result_url"]
            continue
        for schedule_row in schedule_group:
            words = [
                word.casefold()
                for word in re.findall(r"[A-Za-z]{4,}", schedule_row["race_name"])
                if word.upper() not in {"STAKES", "KINEN", "SHO", "JAPANESE"}
            ]
            matches = [
                row for row in history_group if any(word in row["result_url"].casefold() for word in words)
            ]
            if len(matches) == 1:
                schedule_row["result_url"] = matches[0]["result_url"]
    rows = []
    issues = []
    for target in targets:
        if target.get("country_region") != "japan" or int(target.get("year") or 0) != year:
            continue
        keys = _target_names(target)
        matches = _best_name_matches(keys, sources)
        if (
            (len(matches) != 1 or not matches[0].get("result_url"))
            and target.get("series_key") in JRA_OFFICIAL_NAME_ALIASES
        ):
            official_key = _normalize_japanese_name(JRA_OFFICIAL_NAME_ALIASES[target["series_key"]])
            official_matches = [
                source
                for source in history_records
                if _normalize_japanese_name(source.get("race_name") or "") == official_key
            ]
            if len(official_matches) == 1:
                official = official_matches[0]
                rows.append(
                    {
                        "adapter_key": "jra",
                        "series_key": target["series_key"],
                        "edition_year": year,
                        "local_date": official["local_date"],
                        "distance_text": _distance_with_unit(target),
                        "urls": _source_result(official["result_url"], provider="jra", authority="official"),
                    }
                )
                continue
        if len(matches) != 1:
            issues.append(
                {
                    "series_key": target.get("series_key") or "",
                    "edition_year": year,
                    "code": "source_match_not_unique",
                    "match_count": len(matches),
                }
            )
            continue
        match = matches[0]
        if not match["result_url"]:
            issues.append(
                {
                    "series_key": target.get("series_key") or "",
                    "edition_year": year,
                    "code": "source_result_not_unique",
                    "local_date": match["local_date"],
                    "racecourse": match["racecourse"],
                }
            )
            continue
        rows.append(
            {
                "adapter_key": "jra",
                "series_key": target["series_key"],
                "edition_year": year,
                "local_date": match["local_date"],
                "distance_text": _distance_with_unit(target),
                "urls": _source_result(match["result_url"], provider="jra", authority="official"),
            }
        )
    return {"rows": rows, "issues": issues}


def parse_toba_schedule(body: str, *, year: int) -> list[dict]:
    soup = BeautifulSoup(body, "html.parser")
    parsed = []
    for table in soup.find_all("table"):
        table_rows = table.find_all("tr")
        if not table_rows:
            continue
        headers = [_collapse(cell.get_text(" ", strip=True)).lower() for cell in table_rows[0].find_all(["th", "td"])]
        stake_index = next((i for i, value in enumerate(headers) if value in {"stake", "stakes"}), None)
        track_index = next((i for i, value in enumerate(headers) if value == "track"), None)
        winner_index = next((i for i, value in enumerate(headers) if value == "winner"), None)
        if stake_index is None or track_index is None or winner_index is None:
            continue
        for tr in table_rows[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) <= max(stake_index, track_index, winner_index):
                continue
            link = cells[winner_index].find("a", href=True) or tr.find("a", href=True)
            if link is None:
                continue
            query = parse_qs(urlparse(link["href"]).query)
            raw_date = (query.get("DT") or [""])[0]
            track = _collapse(cells[track_index].get_text(" ", strip=True)).upper()
            race_number = (query.get("RACE") or [""])[0]
            if not raw_date or not track or not race_number.isdigit():
                continue
            try:
                local_date = datetime.strptime(raw_date, "%m/%d/%Y").date()
            except ValueError:
                continue
            if local_date.year != year:
                continue
            parsed.append(
                {
                    "race_name": _collapse(cells[stake_index].get_text(" ", strip=True)),
                    "race_key": _normalize_name(cells[stake_index].get_text(" ", strip=True)),
                    "track": track,
                    "local_date": local_date.isoformat(),
                    "result_url": (
                        "https://www.equibase.com/yearbook/Result.cfm"
                        f"?cy=USA&de=D&rd={local_date.isoformat()}&rn={race_number}&tk={track}"
                    ),
                }
            )
        if parsed:
            break
    return parsed


def parse_toba_not_run_schedule(body: str) -> list[dict]:
    soup = BeautifulSoup(body, "html.parser")
    parsed = []
    for table in soup.find_all("table"):
        table_rows = table.find_all("tr")
        if not table_rows:
            continue
        headers = [
            _collapse(cell.get_text(" ", strip=True)).lower()
            for cell in table_rows[0].find_all(["th", "td"])
        ]
        stake_index = next((i for i, value in enumerate(headers) if value in {"stake", "stakes"}), None)
        track_index = next((i for i, value in enumerate(headers) if value == "track"), None)
        date_index = next((i for i, value in enumerate(headers) if value == "date"), None)
        if stake_index is None or track_index is None or date_index is None:
            continue
        for tr in table_rows[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) <= max(stake_index, track_index, date_index):
                continue
            source_status = _collapse(cells[date_index].get_text(" ", strip=True)).casefold()
            if source_status != "not run":
                continue
            race_name = _collapse(cells[stake_index].get_text(" ", strip=True))
            parsed.append(
                {
                    "race_name": race_name,
                    "race_key": _normalize_name(race_name),
                    "track": _collapse(cells[track_index].get_text(" ", strip=True)).upper(),
                    "source_status": source_status,
                }
            )
        if parsed:
            break
    return parsed


def build_toba_provider_rows(*, targets: list[dict], year: int, body: str) -> dict:
    sources = parse_toba_schedule(body, year=year)
    not_run_sources = parse_toba_not_run_schedule(body)
    rows = []
    issues = []
    for target in targets:
        if target.get("country_region") != "united_states" or int(target.get("year") or 0) != year:
            continue
        keys = _toba_target_keys(target)
        compatible_sources = [
            source
            for source in sources
            if _toba_core_name_compatible(target, source)
            and _toba_name_shape_compatible(target, source)
        ]
        name_matches = _best_name_matches(keys, compatible_sources)
        expected_tracks = TRACK_CODES.get(str(target.get("racecourse") or "").casefold(), set())
        track_sources = [
            source for source in compatible_sources if source["track"] in expected_tracks
        ]
        matches = _best_name_matches(keys, track_sources)
        # A unique annual-table name remains authoritative when a race was
        # temporarily moved, as happened during the Belmont reconstruction.
        if (
            not matches
            and len(name_matches) == 1
            and str(target.get("series_key") or "") in TOBA_REVIEWED_RELOCATIONS
        ):
            matches = name_matches
        not_run_track_sources = [
            source
            for source in not_run_sources
            if source["track"] in expected_tracks
            and _toba_core_name_compatible(target, source)
            and _toba_name_shape_compatible(target, source)
        ]
        not_run_matches = _best_name_matches(keys, not_run_track_sources)
        if len(matches) != 1 and len(not_run_matches) == 1:
            not_run_match = not_run_matches[0]
            issues.append(
                {
                    "series_key": target.get("series_key") or "",
                    "edition_year": year,
                    "code": "source_reports_not_run",
                    "source_name": not_run_match["race_name"],
                    "source_track": not_run_match["track"],
                    "source_status": not_run_match["source_status"],
                }
            )
            continue
        if len(matches) != 1:
            issues.append(
                {
                    "series_key": target.get("series_key") or "",
                    "edition_year": year,
                    "code": "source_match_not_unique",
                    "name_match_count": len(name_matches),
                    "track_match_count": len(matches),
                    "expected_track_codes": sorted(expected_tracks),
                }
            )
            continue
        match = matches[0]
        rows.append(
            {
                "adapter_key": "equibase",
                "series_key": target["series_key"],
                "edition_year": year,
                "local_date": match["local_date"],
                "distance_text": _distance_with_unit(target),
                "urls": _source_result(match["result_url"], provider="equibase", authority="third_party"),
            }
        )
    rows_by_url = defaultdict(list)
    for row in rows:
        rows_by_url[row["urls"]["result_url"]["url"]].append(row)
    duplicate_urls = {url for url, url_rows in rows_by_url.items() if len(url_rows) > 1}
    if duplicate_urls:
        duplicate_rows = [
            row for row in rows if row["urls"]["result_url"]["url"] in duplicate_urls
        ]
        rows = [row for row in rows if row["urls"]["result_url"]["url"] not in duplicate_urls]
        issues.extend(
            {
                "series_key": row["series_key"],
                "edition_year": year,
                "code": "duplicate_source_url",
                "source_url": row["urls"]["result_url"]["url"],
            }
            for row in duplicate_rows
        )
    return {"rows": rows, "issues": issues}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover direct JRA and Equibase sources for a fixed historical band batch.")
    parser.add_argument("--selection-snapshot", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--jra-english-schedule")
    parser.add_argument("--jra-history")
    parser.add_argument("--toba")
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--issues-json", required=True)
    args = parser.parse_args()

    snapshot = json.loads(Path(args.selection_snapshot).read_text(encoding="utf-8"))
    targets = snapshot.get("targets") or []
    rows = []
    issues = []
    if args.jra_english_schedule or args.jra_history:
        if not args.jra_english_schedule or not args.jra_history:
            parser.error("--jra-english-schedule and --jra-history must be supplied together")
        result = build_jra_provider_rows(
            targets=targets,
            year=args.year,
            english_schedule_body=Path(args.jra_english_schedule).read_bytes(),
            history_body=Path(args.jra_history).read_bytes(),
        )
        rows.extend(result["rows"])
        issues.extend(result["issues"])
    if args.toba:
        result = build_toba_provider_rows(
            targets=targets,
            year=args.year,
            body=Path(args.toba).read_text(encoding="utf-8", errors="replace"),
        )
        rows.extend(result["rows"])
        issues.extend(result["issues"])
    rows.sort(key=lambda row: (row["adapter_key"], row["series_key"], row["edition_year"]))
    issues.sort(key=lambda row: (row.get("series_key", ""), row.get("edition_year", 0)))
    _write_jsonl(Path(args.output_jsonl), rows)
    Path(args.issues_json).write_text(json.dumps(issues, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"row_count": len(rows), "issue_count": len(issues)}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
