from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

import django  # noqa: E402

django.setup()

from stable.models import RacingRegion  # noqa: E402
from stable.services.p0_horse_completion_adapters import (  # noqa: E402
    P0HorseCompletionRequest,
    summarize_p0_horse_race_record_counts,
)
from stable.services.p0_horse_completion_source_clients import (  # noqa: E402
    _HKJCClient,
    _SportingLifeClient,
    _dl_values,
    _field,
    _id_from_race_url,
    _iso_date,
    _normalized,
    _slug_from_name,
    _strong_label_values,
    _supplement_record_result_evidence,
    _supplement_record_start_evidence,
    _text,
    _year,
)


CANDIDATE_CSV = (
    ROOT
    / "runtime/p0_horse_candidates/"
    "production-reviewed-20260718-all-50-approved/"
    "p0_participant_sample_review.reviewed.csv"
)
JAPAN_JSONL = (
    ROOT
    / "runtime/horse_profile_completion/"
    "p0-reviewed-japan-authorized-offline-replay-20260718-100440/"
    "p0_horse_completion_candidates.jsonl"
)

FRANCE_SPORTING_LIFE_IDS = {
    "LOSANGE BLEU": "1055320",
    "LE PHILOSOPHE": "1055312",
    "DOUBLE MAJOR": "1094515",
    "KENTUCKY WOOD": "1137721",
    "TOSCANA DU BERLAIS": "1059738",
    "AVENTURE": "1119373",
    "SEVENNA'S KNIGHT": "1079049",
    "FIRST LOOK": "1124121",
    "HORIZON DORE": "1077939",
    "MARHABA YA SANAFI": "1080265",
}

US_EQUIBASE_EVENT_URLS = (
    "https://www.equibase.com/yearbook/Result.cfm"
    "?cy=USA&de=D&rd=2026-07-11&rn=8&tk=PRM",
    "https://www.equibase.com/yearbook/Result.cfm"
    "?cy=USA&de=D&rd=2026-07-11&rn=5&tk=SAR",
    "https://www.equibase.com/yearbook/Result.cfm"
    "?cy=USA&de=D&rd=2026-07-11&rn=10&tk=SAR",
)

US_HRN_SLUG_OVERRIDES = {
    "Cornishman": "Cornishman_1",
    "Gigante": "Gigante_1",
    "Movin' On Up": "Movin_On_Up_1",
}

US_OFFICIAL_PROFILE_OVERRIDES = {
    "Fort George": {
        "country": "GB",
        "breeder_name": "K. A. Bartlett & J. M. Beever",
        "source_url": (
            "https://prodv2.nyra.com/saratoga/racing/entries/"
            "?day=2026-07-11&limit=entries&race=10"
        ),
    },
}

US_EQUIBASE_PROFILE_EVIDENCE = (
    ROOT
    / "runtime/horse_profile_completion/"
    "manual-source-evidence-20260719/"
    "equibase_profile_evidence.json"
)
CAREER_RESULT_EVIDENCE = (
    ROOT
    / "runtime/horse_profile_completion/"
    "manual-source-evidence-20260719/"
    "career_result_evidence.json"
)
BASIC_PROFILE_EVIDENCE = (
    ROOT
    / "runtime/horse_profile_completion/"
    "manual-source-evidence-20260719/"
    "basic_profile_field_evidence.json"
)
_HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def _valid_http_url(value: Any) -> bool:
    try:
        _HTTP_URL_VALIDATOR(str(value or "").strip())
    except ValidationError:
        return False
    return True
CAREER_RECORD_EVIDENCE = (
    ROOT
    / "runtime/horse_profile_completion/"
    "manual-source-evidence-20260719/"
    "career_record_evidence.json"
)

FRANCE_GALOP_RESULT_EVIDENCE = {
    ("LE PHILOSOPHE", "2025-10-25"): {
        "canonical_value": "tbé",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2025-12/25obst22.pdf"
        ),
    },
    ("LE PHILOSOPHE", "2023-10-14"): {
        "canonical_value": "tbé",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2023-11/23obst21.pdf"
        ),
    },
    ("LE PHILOSOPHE", "2023-04-08"): {
        "canonical_value": "t.j",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2023-05/23obst08.pdf"
        ),
    },
    ("KENTUCKY WOOD", "2024-05-19"): {
        "canonical_value": "10",
        "result_status": "unplaced",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2024-06/24obst10.pdf"
        ),
    },
    ("TOSCANA DU BERLAIS", "2024-06-08"): {
        "canonical_value": "tbé",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2024-07/24obst12.pdf"
        ),
    },
    ("TOSCANA DU BERLAIS", "2024-05-19"): {
        "canonical_value": "tbé",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2024-06/24obst10.pdf"
        ),
    },
    ("TOSCANA DU BERLAIS", "2024-03-17"): {
        "canonical_value": "tbé",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2024-04/24obst06.pdf"
        ),
    },
    ("TOSCANA DU BERLAIS", "2023-12-02"): {
        "canonical_value": "t.j",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2024-01/23obst25.pdf"
        ),
    },
    ("TOSCANA DU BERLAIS", "2023-08-21"): {
        "canonical_value": "arr",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2023-09/23obst17.pdf"
        ),
    },
    ("TOSCANA DU BERLAIS", "2023-02-03"): {
        "canonical_value": "t.j",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2023-02/23obst03.pdf"
        ),
    },
    ("TOSCANA DU BERLAIS", "2022-09-16"): {
        "canonical_value": "t.j",
        "result_status": "did_not_finish",
        "source_url": (
            "https://www.france-galop.com/sites/default/files/"
            "2022-10/22obst19.pdf"
        ),
    },
}

PROFILE_FIELDS = (
    "country",
    "sex",
    "color",
    "birth_date",
    "owner_name",
    "trainer_name",
    "breeder_name",
)
PEDIGREE_FIELDS = (
    "sire",
    "dam",
    "sire_sire",
    "sire_dam",
    "dam_sire",
    "dam_dam",
)


class CachedTransport:
    user_agent = (
        "umanewsbot/1.0 (+https://umafans.run; "
        "low-frequency manual-review research)"
    )

    def __init__(self, cache_dir: Path, interval_seconds: float = 1.0):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = interval_seconds
        self.last_request_at: float | None = None
        self.session = requests.Session()

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        body_path = self.cache_dir / f"{cache_key}.html"
        meta_path = self.cache_dir / f"{cache_key}.json"
        if body_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            response = requests.Response()
            response.status_code = int(meta["status_code"])
            response.url = str(meta["url"])
            response._content = body_path.read_bytes()
            response.encoding = "utf-8"
            return response

        if self.last_request_at is not None:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.interval_seconds:
                time.sleep(self.interval_seconds - elapsed)
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("User-Agent", self.user_agent)
        response = self.session.get(url, headers=headers, **kwargs)
        self.last_request_at = time.monotonic()
        if response.status_code == 200:
            body_path.write_bytes(response.content)
            meta_path.write_text(
                json.dumps(
                    {
                        "status_code": response.status_code,
                        "url": response.url,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return response


def candidate_rows() -> list[dict[str, Any]]:
    with CANDIDATE_CSV.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in (
            "aliases",
            "identity_keys",
            "source_namespaces",
            "source_urls",
            "event_regions",
            "matched_profile_ids",
        ):
            row[key] = json.loads(row.get(key) or "[]")
        row["sample_rank"] = int(row["sample_rank"])
    return rows


def japan_candidates() -> dict[str, dict[str, Any]]:
    result = {}
    with JAPAN_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("region") == RacingRegion.JAPAN:
                result[row["candidate_key"]] = row
    return result


def make_request(
    row: dict[str, Any],
    *,
    region: str | None = None,
    source_name: str | None = None,
    external_horse_id: str | None = None,
) -> P0HorseCompletionRequest:
    return P0HorseCompletionRequest(
        candidate_key=row["candidate_key"],
        region=region or row["sample_region"],
        horse_name=row["horse_name"],
        source_url=(row["source_urls"] or [""])[0],
        external_horse_id=(
            external_horse_id
            if external_horse_id is not None
            else _candidate_external_id(row)
        ),
        candidate_source_name=source_name or row["source_namespace"],
        expected_sire_name=_text(row.get("sire_name")),
        expected_dam_name=_text(row.get("dam_name")),
        expected_birth_year=_year(row.get("birth_year")),
        allow_network=True,
        request_interval_seconds=0,
        request_budget=2,
        batch_limit=10,
    )


def _candidate_external_id(row: dict[str, Any]) -> str:
    prefix = f"{row['source_namespace']}:"
    return next(
        (
            value[len(prefix) :]
            for value in row["identity_keys"]
            if value.startswith(prefix)
        ),
        "",
    )


def compact_source_payload(
    payload: dict[str, Any],
    *,
    region: str | None = None,
    source_note: str,
) -> dict[str, Any]:
    payload = dict(payload)
    if region:
        payload["region"] = region
    payload["raw_payload"] = {"research_note": source_note}
    career = payload.get("career") if isinstance(payload.get("career"), dict) else {}
    career["source_start_count_quality"] = "source_declared"
    career["official_or_source_start_count"] = career.get(
        "source_start_count"
    )
    career["official_start_count_source"] = payload.get("source", {}).get(
        "name",
        "",
    )
    career["official_start_count_source_url"] = payload.get("source", {}).get(
        "url",
        "",
    )
    career["official_start_count_verified_at"] = payload.get("source", {}).get(
        "fetched_at",
    )
    career["record_authority_status"] = "source_records_verified"
    record_counts = summarize_p0_horse_race_record_counts(
        career.get("records") or []
    )
    career["career_collection_status"] = (
        "complete"
        if career.get("source_start_count")
        == record_counts["actual_start_count"]
        else "count_mismatch"
    )
    payload["career"] = career
    return payload


def apply_france_authoritative_evidence(
    payload: dict[str, Any],
    *,
    horse_name: str,
) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc).isoformat()
    career = payload.get("career") or {}
    unresolved_result_count = 0
    added_source_urls: set[str] = set()
    for record in career.get("records") or []:
        if record.get("result_evidence_status") != "requires_authoritative_supplement":
            continue
        evidence = FRANCE_GALOP_RESULT_EVIDENCE.get(
            (horse_name, record.get("race_date"))
        )
        if evidence is None:
            record["authority_supplement_status"] = "pending"
            record["authority_supplement_sources"] = [
                "france_galop",
                "ifce_sire",
            ]
            unresolved_result_count += 1
            continue
        _supplement_record_result_evidence(
            record,
            canonical_value=evidence["canonical_value"],
            normalized_result_status=evidence["result_status"],
            source_name="france_galop",
            source_url=evidence["source_url"],
            observed_at=observed_at,
            conversion_rule="france_galop_obstacle_result_map_v1",
        )
        record["authority_supplement_status"] = "verified"
        added_source_urls.add(evidence["source_url"])

    career["result_semantics_pending_count"] = unresolved_result_count
    if unresolved_result_count:
        career["career_collection_status"] = (
            "count_complete_result_semantics_partial"
        )
    payload["career"] = career
    source_evidence = list(payload.get("source_evidence") or [])
    source_evidence.extend(
        {
            "source_name": "france_galop",
            "source_url": source_url,
            "evidence_role": "canonical_result_supplement",
            "verification_method": "manual_official_bulletin_review",
            "verified_at": observed_at,
        }
        for source_url in sorted(added_source_urls)
    )
    payload["source_evidence"] = source_evidence
    payload.setdefault("raw_payload", {})[
        "france_result_evidence_policy"
    ] = (
        "Sporting Life direct values are retained. France Galop supplies "
        "canonical French result values. Internal status is normalized only "
        "when the official bulletin is explicit; no Class/Groupe or rounded "
        "imperial/metric inference is performed."
    )
    return payload


def parse_js_value(value: str) -> Any:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return (
            value[1:-1]
            .replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )
    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return float(value) if "." in value else int(value)
    if value in {"true", "false"}:
        return value == "true"
    return value


def parse_equibase_event(html: str, source_url: str) -> dict[str, dict[str, Any]]:
    starters: dict[int, dict[str, Any]] = {}
    assignment = re.compile(
        r'race\["starters"\]\[(\d+)\]((?:\["[^"]+"\])+)\s*=\s*(.+?);'
    )
    path_part = re.compile(r'\["([^"]+)"\]')
    for match in assignment.finditer(html):
        index = int(match.group(1))
        path = ".".join(path_part.findall(match.group(2)))
        starters.setdefault(index, {})[path] = parse_js_value(match.group(3))

    date_pattern = re.compile(
        r'race\["starters"\]\[(\d+)\]\["horse"\]\["foalingdate"\]'
        r"\s*=\s*new Date\((\d+),\s*(\d+),\s*(\d+),"
    )
    for match in date_pattern.finditer(html):
        index, year, month_zero, day = map(int, match.groups())
        starters.setdefault(index, {})["horse.foalingdate"] = (
            f"{year:04d}-{month_zero + 1:02d}-{day:02d}"
        )

    parsed = {}
    for values in starters.values():
        name = _text(values.get("horse.name"))
        if not name:
            continue
        owner = " ".join(
            part
            for part in (
                _text(values.get("owner.firstname")),
                _text(values.get("owner.middlename")),
                _text(values.get("owner.lastname")),
            )
            if part
        )
        trainer = " ".join(
            part
            for part in (
                _text(values.get("trainer.firstname")),
                _text(values.get("trainer.middlename")),
                _text(values.get("trainer.lastname")),
            )
            if part
        )
        refno = _text(values.get("horse.referencenumber"))
        parsed[_normalized(name)] = {
            "horse_name": name,
            "external_horse_id": refno,
            "source_url": (
                "https://www.equibase.com/profiles/Results.cfm"
                f"?type=Horse&refno={refno}&registry=T"
            ),
            "event_source_url": source_url,
            "birth_date": _text(values.get("horse.foalingdate")),
            "sex": _text(values.get("horse.sex")),
            "sire": _text(values.get("sirehorsename")),
            "dam": _text(values.get("damhorsename")),
            "owner_name": owner,
            "trainer_name": trainer,
            "breeder_name": _text(values.get("breedername")),
        }
    return parsed


def collect_equibase_identities(
    transport: CachedTransport,
) -> dict[str, dict[str, Any]]:
    identities = {}
    for url in US_EQUIBASE_EVENT_URLS:
        response = transport.get(url, timeout=30)
        response.raise_for_status()
        event_identities = parse_equibase_event(response.text, response.url)
        identities.update(event_identities)
        for identity in event_identities.values():
            without_country_suffix = re.sub(
                r"\s+\([A-Z]{2,3}\)$",
                "",
                identity["horse_name"],
            )
            identities[_normalized(without_country_suffix)] = identity
    return identities


def _identity_name(value: Any) -> str:
    return _normalized(re.sub(r"\s+\([A-Z]{2,3}\)$", "", _text(value)))


def _manual_evidence_source_key(
    source_name: Any,
    external_horse_id: Any,
) -> tuple[str, str, str] | None:
    normalized_source_name = _normalized(source_name)
    normalized_external_id = _normalized(external_horse_id)
    if bool(normalized_source_name) != bool(normalized_external_id):
        raise ValueError(
            "manual horse evidence source name and external ID must "
            "either both be present or both be absent"
        )
    if not normalized_source_name:
        return None
    return ("source", normalized_source_name, normalized_external_id)


def _manual_evidence_strong_identity_key(
    *,
    horse_name: Any,
    sire_name: Any,
    dam_name: Any,
    birth_year: Any,
) -> tuple[str, str, str, str, str]:
    values = (
        _identity_name(horse_name),
        _identity_name(sire_name),
        _identity_name(dam_name),
        _text(birth_year),
    )
    if not all(values):
        raise ValueError(
            "manual horse evidence requires horse name, sire, dam and "
            "birth year when source identity is unavailable"
        )
    return ("identity", *values)


def _manual_evidence_verification_key(
    verification: dict[str, Any],
) -> tuple[str, ...]:
    source_key = _manual_evidence_source_key(
        verification.get("expected_source_name"),
        verification.get("expected_external_horse_id"),
    )
    if source_key is not None:
        return source_key
    return _manual_evidence_strong_identity_key(
        horse_name=verification.get("horse_name"),
        sire_name=verification.get("expected_sire"),
        dam_name=verification.get("expected_dam"),
        birth_year=verification.get("expected_birth_year"),
    )


def _manual_evidence_horse_keys(
    horse: dict[str, Any],
) -> list[tuple[str, ...]]:
    candidate = horse.get("candidate") or {}
    identity = horse.get("identity") or {}
    pedigree = horse.get("pedigree") or {}
    source = horse.get("source") or {}
    source_key = _manual_evidence_source_key(
        source.get("name"),
        source.get("external_horse_id"),
    )
    if source_key is not None:
        return [source_key]
    strong_identity_values = (
        candidate.get("horse_name") or identity.get("horse_name"),
        identity.get("sire_name") or pedigree.get("sire"),
        identity.get("dam_name") or pedigree.get("dam"),
        identity.get("birth_year"),
    )
    if any(value in (None, "") for value in strong_identity_values):
        return []
    return [
        _manual_evidence_strong_identity_key(
            horse_name=strong_identity_values[0],
            sire_name=strong_identity_values[1],
            dam_name=strong_identity_values[2],
            birth_year=strong_identity_values[3],
        )
    ]


def _manual_evidence_horse_index(
    data: dict[str, Any],
) -> dict[tuple[str, ...], dict[str, Any]]:
    horses_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for horse in data.get("horses") or []:
        for key in _manual_evidence_horse_keys(horse):
            existing = horses_by_key.get(key)
            if existing is not None and existing is not horse:
                raise ValueError(
                    f"duplicate research horse evidence identity: {key}"
                )
            horses_by_key[key] = horse
    return horses_by_key


def _start_count_reconciliation(
    source_count: int | None,
    collected_start_count: int,
) -> dict[str, int | None]:
    if not isinstance(source_count, int) or isinstance(source_count, bool):
        return {
            "start_count_delta": None,
            "missing_start_count": None,
            "excess_start_count": None,
            "gap_count": None,
        }
    delta = collected_start_count - source_count
    missing_count = max(-delta, 0)
    excess_count = max(delta, 0)
    return {
        "start_count_delta": delta,
        "missing_start_count": missing_count,
        "excess_start_count": excess_count,
        "gap_count": missing_count + excess_count,
    }


def parse_basic_profile_verifications(
    content: bytes,
) -> list[dict[str, Any]]:
    document = json.loads(content.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("basic profile evidence must be an object")
    if document.get("schema_version") != "p0-horse-basic-profile-evidence.v1":
        raise ValueError("basic profile evidence has unsupported schema_version")
    for key in ("batch_id", "verified_at", "verification_method"):
        if not isinstance(document.get(key), str) or not document[key].strip():
            raise ValueError(f"basic profile evidence requires {key}")
    try:
        verified_at = datetime.fromisoformat(
            document["verified_at"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("basic profile evidence verified_at is invalid") from exc
    if verified_at.tzinfo is None:
        raise ValueError(
            "basic profile evidence verified_at must include timezone"
        )

    horses = document.get("horses")
    if not isinstance(horses, list):
        raise ValueError("basic profile evidence horses must be a list")
    required_identity_strings = (
        "horse_name",
        "region",
        "expected_sire",
        "expected_dam",
    )
    required_field_strings = (
        "field_name",
        "canonical_value",
        "direct_raw_value",
        "source_name",
        "source_url",
        "normalization_rule",
        "evidence_note",
    )
    allowed_fields = {"country", "birth_date", "breeder_name"}
    loaded: list[dict[str, Any]] = []
    seen_horses: set[tuple[str, ...]] = set()
    seen_fields: set[tuple[str, ...]] = set()
    for horse_index, horse in enumerate(horses):
        if not isinstance(horse, dict):
            raise ValueError(
                f"basic profile evidence horse {horse_index} is invalid"
            )
        for key in required_identity_strings:
            if not isinstance(horse.get(key), str) or not horse[key].strip():
                raise ValueError(
                    f"basic profile evidence horse {horse_index} requires {key}"
                )
        birth_year = horse.get("expected_birth_year")
        if (
            not isinstance(birth_year, int)
            or isinstance(birth_year, bool)
            or birth_year < 1800
        ):
            raise ValueError(
                f"basic profile evidence horse {horse_index} requires "
                "expected_birth_year"
            )
        source_key = _manual_evidence_source_key(
            horse.get("expected_source_name"),
            horse.get("expected_external_horse_id"),
        )
        if source_key is None:
            horse_key = _manual_evidence_strong_identity_key(
                horse_name=horse["horse_name"],
                sire_name=horse["expected_sire"],
                dam_name=horse["expected_dam"],
                birth_year=birth_year,
            )
        else:
            horse_key = source_key
        if horse_key in seen_horses:
            raise ValueError(
                f"duplicate basic profile evidence horse: {horse_key}"
            )
        seen_horses.add(horse_key)
        fields = horse.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError(
                f"basic profile evidence horse {horse_index} requires fields"
            )
        for field_index, field in enumerate(fields):
            if not isinstance(field, dict):
                raise ValueError(
                    "basic profile evidence field "
                    f"{horse_index}:{field_index} is invalid"
                )
            for key in required_field_strings:
                if not isinstance(field.get(key), str) or not field[key].strip():
                    raise ValueError(
                        "basic profile evidence field "
                        f"{horse_index}:{field_index} requires {key}"
                    )
            field_name = field["field_name"]
            if field_name not in allowed_fields:
                raise ValueError(
                    "basic profile evidence field "
                    f"{horse_index}:{field_index} is unsupported"
                )
            if not _valid_http_url(field["source_url"]):
                raise ValueError(
                    "basic profile evidence field "
                    f"{horse_index}:{field_index} has invalid source_url"
                )
            corroborating_urls = field.get("corroborating_source_urls") or []
            if (
                not isinstance(corroborating_urls, list)
                or not all(
                    isinstance(url, str) and _valid_http_url(url)
                    for url in corroborating_urls
                )
            ):
                raise ValueError(
                    "basic profile evidence field "
                    f"{horse_index}:{field_index} has invalid "
                    "corroborating_source_urls"
                )
            canonical_value = field["canonical_value"]
            if field_name == "country" and not re.fullmatch(
                r"[A-Z]{2,3}", canonical_value
            ):
                raise ValueError(
                    "basic profile country evidence must use an uppercase "
                    "ISO-style code"
                )
            if field_name == "birth_date":
                try:
                    parsed_birth_date = datetime.strptime(
                        canonical_value,
                        "%Y-%m-%d",
                    )
                except ValueError as exc:
                    raise ValueError(
                        "basic profile birth_date evidence must use YYYY-MM-DD"
                    ) from exc
                if parsed_birth_date.year != birth_year:
                    raise ValueError(
                        "basic profile birth_date evidence conflicts with "
                        f"expected_birth_year for {horse['horse_name']}"
                    )
            evidence_key = (
                *horse_key,
                field_name,
            )
            if evidence_key in seen_fields:
                raise ValueError(
                    f"duplicate basic profile field evidence: {evidence_key}"
                )
            seen_fields.add(evidence_key)
            loaded.append(
                {
                    **{
                        key: horse[key]
                        for key in required_identity_strings
                    },
                    "expected_source_name": _text(
                        horse.get("expected_source_name")
                    ),
                    "expected_external_horse_id": _text(
                        horse.get("expected_external_horse_id")
                    ),
                    "expected_birth_year": birth_year,
                    **field,
                    "corroborating_source_urls": corroborating_urls,
                    "batch_id": document["batch_id"],
                    "verified_at": document["verified_at"],
                    "verification_method": document["verification_method"],
                }
            )
    return loaded


def _validate_basic_profile_horse_identity(
    verification: dict[str, Any],
    horse: dict[str, Any],
) -> None:
    candidate = horse.get("candidate") or {}
    identity = horse.get("identity") or {}
    pedigree = horse.get("pedigree") or {}
    actual = {
        "horse_name": (
            candidate.get("horse_name") or identity.get("horse_name")
        ),
        "region": horse.get("region"),
        "expected_source_name": horse.get("source", {}).get("name"),
        "expected_external_horse_id": horse.get("source", {}).get(
            "external_horse_id"
        ),
        "expected_sire": identity.get("sire_name") or pedigree.get("sire"),
        "expected_dam": identity.get("dam_name") or pedigree.get("dam"),
        "expected_birth_year": identity.get("birth_year"),
    }
    for key, actual_value in actual.items():
        expected_value = (
            verification["horse_name"]
            if key == "horse_name"
            else verification.get(key)
        )
        if key in {
            "horse_name",
            "expected_source_name",
            "expected_sire",
            "expected_dam",
        }:
            matches = _identity_name(expected_value) == _identity_name(
                actual_value
            )
        else:
            matches = _text(expected_value) == _text(actual_value)
        if not matches:
            raise ValueError(
                f"basic profile evidence {key} mismatch for "
                f"{verification['horse_name']}: "
                f"{expected_value!r} != {actual_value!r}"
            )


def apply_basic_profile_verifications(
    data: dict[str, Any],
    verifications: list[dict[str, Any]],
) -> int:
    horses_by_key = _manual_evidence_horse_index(data)

    applied_count = 0
    applied_keys: set[tuple[str, ...]] = set()
    for verification in verifications:
        horse_key = _manual_evidence_verification_key(verification)
        horse = horses_by_key.get(horse_key)
        if horse is None:
            raise ValueError(
                "basic profile evidence horse not found: "
                f"{verification['region']} {verification['horse_name']}"
            )
        _validate_basic_profile_horse_identity(verification, horse)
        field_name = verification["field_name"]
        field_key = (*horse_key, field_name)
        basic_profile = horse.setdefault("basic_profile", {})
        current_value = basic_profile.get(field_name)
        canonical_value = verification["canonical_value"]
        existing_evidence = next(
            (
                item
                for item in horse.get("basic_profile_field_evidence") or []
                if item.get("field_name") == field_name
                and item.get("batch_id") == verification["batch_id"]
                and item.get("normalized_value") == canonical_value
                and item.get("source_url") == verification["source_url"]
            ),
            None,
        )
        if current_value not in ("", None):
            if _normalized(current_value) != _normalized(canonical_value):
                raise ValueError(
                    "basic profile evidence conflicts with collected value: "
                    f"{verification['horse_name']} {field_name}"
                )
            if existing_evidence is None:
                raise ValueError(
                    "basic profile evidence target is already populated "
                    "without matching evidence: "
                    f"{verification['horse_name']} {field_name}"
                )
            applied_keys.add(field_key)
            continue

        basic_profile[field_name] = canonical_value
        if field_name == "birth_date":
            horse.setdefault("identity", {})["birth_year"] = verification[
                "expected_birth_year"
            ]
        field_evidence = [
            item
            for item in horse.get("basic_profile_field_evidence") or []
            if item.get("field_name") != field_name
        ]
        field_evidence.append(
            {
                "field_name": field_name,
                "status": "manual_source_verified",
                "batch_id": verification["batch_id"],
                "source_name": verification["source_name"],
                "source_url": verification["source_url"],
                "corroborating_source_urls": verification[
                    "corroborating_source_urls"
                ],
                "direct_raw_value": verification["direct_raw_value"],
                "normalized_value": canonical_value,
                "normalization_rule": verification["normalization_rule"],
                "verified_at": verification["verified_at"],
                "verification_method": verification[
                    "verification_method"
                ],
                "evidence_note": verification["evidence_note"],
            }
        )
        horse["basic_profile_field_evidence"] = field_evidence
        evidence_id = "|".join(
            (
                verification["batch_id"],
                verification["region"],
                verification["expected_external_horse_id"],
                field_name,
            )
        )
        source_evidence = [
            item
            for item in horse.get("source_evidence") or []
            if item.get("evidence_id") != evidence_id
        ]
        source_evidence.append(
            {
                "evidence_id": evidence_id,
                "source_name": verification["source_name"],
                "source_url": verification["source_url"],
                "corroborating_source_urls": verification[
                    "corroborating_source_urls"
                ],
                "evidence_role": "basic_profile_field_manual_research",
                "field_name": field_name,
                "external_horse_id": verification[
                    "expected_external_horse_id"
                ],
                "verified_at": verification["verified_at"],
                "verification_method": verification[
                    "verification_method"
                ],
                "evidence_note": verification["evidence_note"],
            }
        )
        horse["source_evidence"] = source_evidence
        horse.setdefault("raw_payload", {})[
            "manual_basic_profile_evidence_policy"
        ] = (
            "A manually researched value may fill only an empty target after "
            "horse name, region, source ID, sire, dam and birth year are "
            "locked. Direct source text and normalized values remain separate."
        )
        horse["field_status"] = summarize_field_status(horse)
        applied_count += 1
        applied_keys.add(field_key)

    expected_keys = {
        (
            *_manual_evidence_verification_key(verification),
            verification["field_name"],
        )
        for verification in verifications
    }
    if applied_keys != expected_keys:
        raise ValueError(
            "basic profile evidence did not apply completely: "
            f"{sorted(expected_keys - applied_keys)}"
        )
    return applied_count


def parse_career_record_verifications(
    content: bytes,
) -> list[dict[str, Any]]:
    rows = json.loads(content.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("career record evidence must be a list")
    required_strings = (
        "horse_name",
        "region",
        "expected_sire",
        "expected_dam",
        "external_race_id",
        "external_result_id",
        "race_date",
        "race_name",
        "racecourse",
        "distance_text",
        "race_classification",
        "surface",
        "going",
        "source_name",
        "source_url",
        "verified_at",
        "verification_method",
        "evidence_note",
    )
    loaded: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"career record evidence row {index} is invalid")
        for key in required_strings:
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(
                    f"career record evidence row {index} requires {key}"
                )
        birth_year = row.get("expected_birth_year")
        finish_position = row.get("finish_position")
        if (
            not isinstance(birth_year, int)
            or isinstance(birth_year, bool)
            or birth_year < 1800
        ):
            raise ValueError(
                f"career record evidence row {index} requires "
                "expected_birth_year"
            )
        if (
            not isinstance(finish_position, int)
            or isinstance(finish_position, bool)
            or finish_position < 1
        ):
            raise ValueError(
                f"career record evidence row {index} requires "
                "finish_position"
            )
        try:
            datetime.strptime(row["race_date"], "%Y-%m-%d")
            verified_at = datetime.fromisoformat(
                row["verified_at"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"career record evidence row {index} has invalid date"
            ) from exc
        if verified_at.tzinfo is None:
            raise ValueError(
                f"career record evidence row {index} verified_at "
                "must include timezone"
            )
        if not _valid_http_url(row["source_url"]):
            raise ValueError(
                f"career record evidence row {index} has invalid source_url"
            )
        horse_key = _manual_evidence_verification_key(row)
        evidence_key = (
            *horse_key,
            row["external_race_id"],
            row["external_result_id"],
        )
        if evidence_key in seen_keys:
            raise ValueError(
                f"duplicate career record evidence: {evidence_key}"
            )
        seen_keys.add(evidence_key)
        loaded.append(row)
    return loaded


def _manual_record_field_evidence(
    *,
    field_name: str,
    value: str,
    source_name: str,
    source_url: str,
    observed_at: str,
    normalized_value: str | None = None,
    normalization_rule: str = "",
) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "direct_raw": {
            "value": value,
            "status": "observed",
            "source_name": source_name,
            "source_url": source_url,
            "observed_at": observed_at,
            "conversion_rule": "direct_result_page_value_v1",
        },
        "canonical_raw": {
            "value": None,
            "status": "not_collected",
            "source_name": "",
            "source_url": "",
            "observed_at": "",
            "conversion_rule": "",
        },
        "normalized": {
            "value": normalized_value,
            "status": "mapped" if normalized_value else "not_applied",
            "source_name": "umanews",
            "source_url": source_url,
            "observed_at": observed_at,
            "conversion_rule": normalization_rule,
        },
    }


def apply_career_record_verifications(
    data: dict[str, Any],
    verifications: list[dict[str, Any]],
) -> int:
    horses_by_key = _manual_evidence_horse_index(data)

    applied_count = 0
    touched_horses: set[tuple[str, ...]] = set()
    for verification in verifications:
        horse_key = _manual_evidence_verification_key(verification)
        horse = horses_by_key.get(horse_key)
        if horse is None:
            raise ValueError(
                "career record evidence horse not found: "
                f"{verification['horse_name']}"
            )
        _validate_basic_profile_horse_identity(verification, horse)
        career = horse.setdefault("career", {})
        records = career.setdefault("records", [])
        identity_matches = [
            record
            for record in records
            if (
                _text(record.get("external_race_id"))
                == verification["external_race_id"]
                or (
                    _text(record.get("race_date"))
                    == verification["race_date"]
                    and _normalized(record.get("racecourse"))
                    == _normalized(verification["racecourse"])
                    and _normalized(record.get("race_name"))
                    == _normalized(verification["race_name"])
                )
            )
        ]
        if identity_matches:
            if len(identity_matches) != 1:
                raise ValueError(
                    "career record evidence matched duplicate records: "
                    f"{verification['horse_name']} "
                    f"{verification['external_race_id']}"
                )
            existing = identity_matches[0]
            expected_existing = {
                "external_result_id": verification["external_result_id"],
                "finish": str(verification["finish_position"]),
                "source_url": verification["source_url"],
            }
            if not all(
                _text(existing.get(key)) == value
                for key, value in expected_existing.items()
            ):
                raise ValueError(
                    "career record evidence conflicts with an existing "
                    f"record: {verification['horse_name']} "
                    f"{verification['external_race_id']}"
                )
            touched_horses.add(horse_key)
            continue

        finish_position = verification["finish_position"]
        normalized_result = (
            "won"
            if finish_position == 1
            else "placed"
            if finish_position in {2, 3}
            else "unplaced"
        )
        record = {
            "external_race_id": verification["external_race_id"],
            "external_result_id": verification["external_result_id"],
            "race_date": verification["race_date"],
            "race_name": verification["race_name"],
            "racecourse": verification["racecourse"],
            "finish": str(finish_position),
            "official_result_code": "",
            "result_status": normalized_result,
            "start_status": "started",
            "result_evidence_status": "direct_position",
            "distance_text": verification["distance_text"],
            "race_classification": verification["race_classification"],
            "surface": verification["surface"],
            "going": verification["going"],
            "source_name": verification["source_name"],
            "source_url": verification["source_url"],
            "source_urls": [verification["source_url"]],
            "source_record_names": [verification["race_name"]],
            "field_evidence": [
                _manual_record_field_evidence(
                    field_name="result",
                    value=str(finish_position),
                    source_name=verification["source_name"],
                    source_url=verification["source_url"],
                    observed_at=verification["verified_at"],
                    normalized_value=normalized_result,
                    normalization_rule="numeric_finish_position_v1",
                ),
                _manual_record_field_evidence(
                    field_name="race_name",
                    value=verification["race_name"],
                    source_name=verification["source_name"],
                    source_url=verification["source_url"],
                    observed_at=verification["verified_at"],
                ),
                _manual_record_field_evidence(
                    field_name="distance_text",
                    value=verification["distance_text"],
                    source_name=verification["source_name"],
                    source_url=verification["source_url"],
                    observed_at=verification["verified_at"],
                ),
                _manual_record_field_evidence(
                    field_name="race_classification",
                    value=verification["race_classification"],
                    source_name=verification["source_name"],
                    source_url=verification["source_url"],
                    observed_at=verification["verified_at"],
                ),
            ],
            "manual_record_verification_method": verification[
                "verification_method"
            ],
            "manual_record_evidence_note": verification["evidence_note"],
        }
        records.append(record)
        evidence_id = "|".join(
            (
                "career-record",
                verification["expected_external_horse_id"],
                verification["external_race_id"],
                verification["external_result_id"],
            )
        )
        source_evidence = [
            item
            for item in horse.get("source_evidence") or []
            if item.get("evidence_id") != evidence_id
        ]
        source_evidence.append(
            {
                "evidence_id": evidence_id,
                "source_name": verification["source_name"],
                "source_url": verification["source_url"],
                "evidence_role": "manual_missing_career_record_research",
                "external_horse_id": verification[
                    "expected_external_horse_id"
                ],
                "external_race_id": verification["external_race_id"],
                "verified_at": verification["verified_at"],
                "verification_method": verification[
                    "verification_method"
                ],
                "evidence_note": verification["evidence_note"],
            }
        )
        horse["source_evidence"] = source_evidence
        applied_count += 1
        touched_horses.add(horse_key)

    for horse_key in touched_horses:
        horse = horses_by_key[horse_key]
        career = horse["career"]
        records = career["records"]
        records.sort(
            key=lambda record: (
                _text(record.get("race_date")),
                _text(record.get("external_race_id")),
            ),
            reverse=True,
        )
        record_counts = summarize_p0_horse_race_record_counts(records)
        actual_start_count = record_counts["actual_start_count"]
        official_start_count = career.get("official_or_source_start_count")
        if not isinstance(official_start_count, int):
            raise ValueError(
                "career record evidence requires an official/source count "
                f"for {horse_key}"
            )
        reconciliation = _start_count_reconciliation(
            official_start_count,
            actual_start_count,
        )
        gap_count = reconciliation["gap_count"]
        career.update(
            {
                "visible_source_record_count": len(records),
                "collected_start_count": actual_start_count,
                "nonstarter_count": record_counts["nonstarter_count"],
                **reconciliation,
                "record_authority_status": (
                    "count_aligned_records_unverified"
                    if gap_count == 0
                    else "source_blocked"
                ),
                "career_collection_status": (
                    "count_aligned_per_record_officiality_pending"
                    if gap_count == 0
                    else "count_mismatch"
                ),
            }
        )
        horse.setdefault("raw_payload", {})[
            "manual_missing_career_record_policy"
        ] = (
            "Missing visible rows may be added from a reviewed result page "
            "only after horse and race identity locks pass. An Equibase total "
            "count may reconcile quantity but does not make non-Equibase "
            "per-record evidence official."
        )
        horse["field_status"] = summarize_field_status(horse)
        finalize_career_collection_status(horse, horse["field_status"])
    return applied_count


def _normalized_record_value(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _text(value).casefold())


def deduplicate_us_visible_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    deduplicated: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str, str], int] = {}
    duplicate_count = 0
    for original in records:
        record = dict(original)
        key = (
            _text(record.get("race_date")),
            _normalized_record_value(record.get("racecourse")),
            _normalized_record_value(record.get("distance_text")),
            _normalized_record_value(record.get("finish")),
        )
        if not all(key):
            deduplicated.append(record)
            continue
        existing_index = by_key.get(key)
        if existing_index is None:
            source_urls = [
                _text(url) for url in record.get("source_urls") or []
            ]
            source_url = _text(record.get("source_url"))
            if source_url:
                source_urls.append(source_url)
            record["source_urls"] = list(
                dict.fromkeys(filter(None, source_urls))
            )
            source_record_names = [
                _text(name)
                for name in record.get("source_record_names") or []
            ]
            race_name = _text(record.get("race_name"))
            if race_name:
                source_record_names.append(race_name)
            record["source_record_names"] = list(
                dict.fromkeys(filter(None, source_record_names))
            )
            by_key[key] = len(deduplicated)
            deduplicated.append(record)
            continue

        duplicate_count += 1
        existing = deduplicated[existing_index]
        source_urls = list(existing.get("source_urls") or [])
        source_url = _text(record.get("source_url"))
        if source_url and source_url not in source_urls:
            source_urls.append(source_url)
        source_names = list(existing.get("source_record_names") or [])
        race_name = _text(record.get("race_name"))
        if race_name and race_name not in source_names:
            source_names.append(race_name)

        if record.get("external_race_id") and not existing.get(
            "external_race_id"
        ):
            preserved_urls = source_urls
            preserved_names = source_names
            existing = record
            existing["source_urls"] = preserved_urls
            existing["source_record_names"] = preserved_names
            deduplicated[existing_index] = existing
        else:
            existing["source_urls"] = source_urls
            existing["source_record_names"] = source_names
    return deduplicated, duplicate_count


def _apply_us_deduplicated_source_evidence(
    records: list[dict[str, Any]],
    verification: dict[str, Any],
) -> None:
    evidence = verification.get("deduplicated_record_source_evidence")
    if not evidence:
        return
    matches = [
        record
        for record in records
        if _text(record.get("race_date")) == evidence["expected_race_date"]
        and _text(record.get("external_race_id"))
        == evidence["expected_external_race_id"]
        and _normalized(record.get("race_name"))
        == _normalized(evidence["expected_race_name"])
    ]
    if len(matches) != 1:
        raise ValueError(
            "deduplicated source evidence must match exactly one record "
            f"for {verification['horse_name']}; matched {len(matches)}"
        )
    record = matches[0]
    source_urls = [
        _text(url) for url in record.get("source_urls") or []
    ]
    source_url = _text(record.get("source_url"))
    if source_url:
        source_urls.append(source_url)
    source_urls.append(evidence["additional_source_url"])
    record["source_urls"] = list(dict.fromkeys(filter(None, source_urls)))
    source_record_names = [
        _text(name) for name in record.get("source_record_names") or []
    ]
    source_record_names.append(evidence["additional_source_record_name"])
    record["source_record_names"] = list(
        dict.fromkeys(filter(None, source_record_names))
    )
    record["deduplicated_source_evidence_note"] = evidence["evidence_note"]


def parse_us_equibase_profile_verifications(
    content: bytes,
) -> dict[tuple[str, ...], dict[str, Any]]:
    rows = json.loads(content.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Equibase profile evidence must be a list")
    required_strings = (
        "horse_name",
        "expected_external_horse_id",
        "expected_sire",
        "expected_dam",
        "expected_birth_date",
        "color_raw",
        "color_normalized",
        "source_url",
        "source_as_of",
        "verified_at",
        "verification_method",
        "evidence_note",
    )
    loaded: dict[tuple[str, ...], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Equibase profile evidence row {index} is invalid")
        for key in required_strings:
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(
                    f"Equibase profile evidence row {index} requires {key}"
                )
        count = row.get("official_start_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(
                f"Equibase profile evidence row {index} requires "
                "official_start_count"
            )
        if (
            not _valid_http_url(row["source_url"])
            or urlparse(row["source_url"]).hostname != "www.equibase.com"
        ):
            raise ValueError(
                f"Equibase profile evidence row {index} has invalid source_url"
            )
        if row["expected_external_horse_id"] not in row["source_url"]:
            raise ValueError(
                f"Equibase profile evidence row {index} source_url does not "
                "match expected_external_horse_id"
            )
        duplicate_source_evidence = row.get(
            "deduplicated_record_source_evidence"
        )
        if duplicate_source_evidence is not None:
            if not isinstance(duplicate_source_evidence, dict):
                raise ValueError(
                    f"Equibase profile evidence row {index} has invalid "
                    "deduplicated_record_source_evidence"
                )
            for key in (
                "expected_race_date",
                "expected_external_race_id",
                "expected_race_name",
                "additional_source_url",
                "additional_source_record_name",
                "evidence_note",
            ):
                if (
                    not isinstance(duplicate_source_evidence.get(key), str)
                    or not duplicate_source_evidence[key].strip()
                ):
                    raise ValueError(
                        f"Equibase profile evidence row {index} requires "
                        f"deduplicated_record_source_evidence.{key}"
                    )
            additional_source_url = duplicate_source_evidence[
                "additional_source_url"
            ]
            parsed_additional_source_url = urlparse(additional_source_url)
            if (
                not _valid_http_url(additional_source_url)
                or parsed_additional_source_url.hostname
                != "www.horseracingnation.com"
                or not parsed_additional_source_url.path.startswith("/horse/")
            ):
                raise ValueError(
                    f"Equibase profile evidence row {index} has invalid "
                    "deduplicated_record_source_evidence.additional_source_url"
                )
        try:
            datetime.strptime(row["source_as_of"], "%Y-%m-%d")
            verified_at = datetime.fromisoformat(
                row["verified_at"].replace("Z", "+00:00")
            )
            datetime.strptime(row["expected_birth_date"], "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"Equibase profile evidence row {index} has invalid date"
            ) from exc
        if verified_at.tzinfo is None:
            raise ValueError(
                f"Equibase profile evidence row {index} verified_at "
                "must include timezone"
            )
        evidence_key = _manual_evidence_source_key(
            "equibase",
            row["expected_external_horse_id"],
        )
        if evidence_key is None:
            raise ValueError(
                f"Equibase profile evidence row {index} requires "
                "expected_external_horse_id"
            )
        if evidence_key in loaded:
            raise ValueError(
                f"duplicate Equibase profile evidence for {evidence_key}"
            )
        loaded[evidence_key] = row
    return loaded


def load_us_equibase_profile_verifications(
    path: Path,
) -> dict[tuple[str, ...], dict[str, Any]]:
    return parse_us_equibase_profile_verifications(path.read_bytes())


def validate_us_equibase_profile_verification(
    verification: dict[str, Any],
    equibase: dict[str, Any],
) -> None:
    expected = {
        "expected_external_horse_id": equibase.get("external_horse_id"),
        "expected_sire": equibase.get("sire"),
        "expected_dam": equibase.get("dam"),
        "expected_birth_date": equibase.get("birth_date"),
    }
    for key, actual_value in expected.items():
        expected_value = verification.get(key)
        if key in {"expected_sire", "expected_dam"}:
            matches = _identity_name(expected_value) == _identity_name(
                actual_value
            )
        else:
            matches = _text(expected_value) == _text(actual_value)
        if not matches:
            raise ValueError(
                f"Equibase manual evidence {key} mismatch for "
                f"{verification.get('horse_name')}: "
                f"{expected_value!r} != {actual_value!r}"
            )


def parse_career_result_verifications(
    content: bytes,
) -> list[dict[str, Any]]:
    rows = json.loads(content.decode("utf-8"))
    if not isinstance(rows, list):
        raise ValueError("career result evidence must be a list")
    required_strings = (
        "horse_name",
        "expected_source_name",
        "expected_external_horse_id",
        "expected_sire",
        "expected_dam",
        "race_date",
        "expected_external_race_id",
        "expected_external_result_id",
        "expected_race_name",
        "normalized_result_status",
        "normalized_start_status",
        "source_name",
        "source_url",
        "verified_at",
        "verification_method",
        "conversion_rule",
        "evidence_note",
    )
    valid_result_statuses = {
        "won",
        "placed",
        "unplaced",
        "finished",
        "scratched",
        "withdrawn",
        "did_not_finish",
        "disqualified",
        "unknown",
    }
    valid_start_statuses = {"started", "did_not_start"}
    loaded: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"career result evidence row {index} is invalid")
        for key in required_strings:
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(
                    f"career result evidence row {index} requires {key}"
                )
        birth_year = row.get("expected_birth_year")
        if (
            not isinstance(birth_year, int)
            or isinstance(birth_year, bool)
            or birth_year < 1800
        ):
            raise ValueError(
                f"career result evidence row {index} requires "
                "expected_birth_year"
            )
        if row["normalized_result_status"] not in valid_result_statuses:
            raise ValueError(
                f"career result evidence row {index} has invalid "
                "normalized_result_status"
            )
        if row["normalized_start_status"] not in valid_start_statuses:
            raise ValueError(
                f"career result evidence row {index} has invalid "
                "normalized_start_status"
            )
        canonical_value = row.get("canonical_value")
        if not isinstance(canonical_value, str):
            raise ValueError(
                f"career result evidence row {index} requires "
                "canonical_value"
            )
        if (
            row["normalized_start_status"] == "started"
            and row["normalized_result_status"] == "unknown"
        ):
            raise ValueError(
                f"career result evidence row {index} cannot leave an "
                "actual start result unknown"
            )
        if (
            row["normalized_start_status"] == "started"
            and not canonical_value.strip()
        ):
            raise ValueError(
                f"career result evidence row {index} requires "
                "canonical_value for an actual start"
            )
        participation_status_value = row.get(
            "participation_status_value"
        )
        if row["normalized_start_status"] == "did_not_start":
            if canonical_value:
                raise ValueError(
                    f"career result evidence row {index} cannot use "
                    "canonical_value for a non-start"
                )
            if (
                not isinstance(participation_status_value, str)
                or not participation_status_value.strip()
            ):
                raise ValueError(
                    f"career result evidence row {index} requires "
                    "participation_status_value for a non-start"
                )
        try:
            datetime.strptime(row["race_date"], "%Y-%m-%d")
            verified_at = datetime.fromisoformat(
                row["verified_at"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"career result evidence row {index} has invalid date"
            ) from exc
        if verified_at.tzinfo is None:
            raise ValueError(
                f"career result evidence row {index} verified_at "
                "must include timezone"
            )
        source_urls = [row["source_url"]] + list(
            row.get("corroborating_source_urls") or []
        )
        if not all(
            isinstance(url, str) and _valid_http_url(url)
            for url in source_urls
        ):
            raise ValueError(
                f"career result evidence row {index} has invalid source URL"
            )
        reconciled_count = row.get("official_or_source_start_count")
        if reconciled_count is not None and (
            not isinstance(reconciled_count, int)
            or isinstance(reconciled_count, bool)
            or reconciled_count < 0
        ):
            raise ValueError(
                f"career result evidence row {index} has invalid "
                "official_or_source_start_count"
            )
        count_source_url = row.get("count_source_url")
        if count_source_url is not None and (
            not isinstance(count_source_url, str)
            or not _valid_http_url(count_source_url)
        ):
            raise ValueError(
                f"career result evidence row {index} has invalid "
                "count_source_url"
            )
        if reconciled_count is not None and not count_source_url:
            raise ValueError(
                f"career result evidence row {index} with a reconciled "
                "count requires count_source_url"
            )
        evidence_key = (
            *_manual_evidence_verification_key(row),
            row["race_date"],
            row["expected_external_race_id"],
            row["expected_external_result_id"],
        )
        if evidence_key in seen_keys:
            raise ValueError(
                f"duplicate career result evidence for {evidence_key}"
            )
        seen_keys.add(evidence_key)
        loaded.append(row)
    return loaded


def load_career_result_verifications(
    path: Path,
) -> list[dict[str, Any]]:
    return parse_career_result_verifications(path.read_bytes())


def _validate_career_result_horse_identity(
    evidence: dict[str, Any],
    horse: dict[str, Any],
) -> None:
    identity = horse.get("identity") or {}
    pedigree = horse.get("pedigree") or {}
    expected = {
        "expected_source_name": horse.get("source", {}).get("name"),
        "expected_external_horse_id": horse.get("source", {}).get(
            "external_horse_id"
        ),
        "expected_sire": identity.get("sire_name") or pedigree.get("sire"),
        "expected_dam": identity.get("dam_name") or pedigree.get("dam"),
        "expected_birth_year": identity.get("birth_year"),
    }
    for key, actual_value in expected.items():
        expected_value = evidence.get(key)
        if key in {"expected_sire", "expected_dam"}:
            matches = _identity_name(expected_value) == _identity_name(
                actual_value
            )
        elif key == "expected_source_name":
            matches = _normalized(expected_value) == _normalized(actual_value)
        else:
            matches = _text(expected_value) == _text(actual_value)
        if not matches:
            raise ValueError(
                f"career result evidence {key} mismatch for "
                f"{evidence.get('horse_name')}: "
                f"{expected_value!r} != {actual_value!r}"
            )


def _career_result_record_matches(
    record: dict[str, Any],
    evidence: dict[str, Any],
) -> bool:
    return (
        _text(record.get("race_date")) == evidence["race_date"]
        and _text(record.get("external_race_id"))
        == evidence["expected_external_race_id"]
        and _text(record.get("external_result_id"))
        == evidence["expected_external_result_id"]
        and _normalized(record.get("race_name"))
        == _normalized(evidence["expected_race_name"])
    )


def apply_career_result_verifications(
    data: dict[str, Any],
    verifications: list[dict[str, Any]],
) -> int:
    horses_by_key = _manual_evidence_horse_index(data)
    by_horse: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for verification in verifications:
        by_horse.setdefault(
            _manual_evidence_verification_key(verification),
            [],
        ).append(
            verification
        )

    applied_count = 0
    applied_horses: set[tuple[str, ...]] = set()
    for horse_key, horse_verifications in by_horse.items():
        horse = horses_by_key.get(horse_key)
        if horse is None:
            continue
        horse_name = horse_verifications[0]["horse_name"]
        records = horse.setdefault("career", {}).setdefault("records", [])
        reconciled_counts: set[int] = set()
        for verification in horse_verifications:
            _validate_career_result_horse_identity(verification, horse)
            matched_records = [
                record
                for record in records
                if _career_result_record_matches(record, verification)
            ]
            if len(matched_records) != 1:
                raise ValueError(
                    "career result evidence must match exactly one record "
                    f"for {horse_name} {verification['race_date']}; "
                    f"matched {len(matched_records)}"
                )
            record = matched_records[0]
            if verification["normalized_start_status"] == "did_not_start":
                _supplement_record_start_evidence(
                    record,
                    canonical_value=verification[
                        "participation_status_value"
                    ],
                    normalized_start_status="did_not_start",
                    source_name=verification["source_name"],
                    source_url=verification["source_url"],
                    observed_at=verification["verified_at"],
                    conversion_rule=verification["conversion_rule"],
                )
            else:
                normalized_result_status = verification[
                    "normalized_result_status"
                ]
                if normalized_result_status == "finished":
                    normalized_result_status = "unplaced"
                _supplement_record_result_evidence(
                    record,
                    canonical_value=verification["canonical_value"],
                    normalized_result_status=normalized_result_status,
                    normalized_start_status="started",
                    source_name=verification["source_name"],
                    source_url=verification["source_url"],
                    observed_at=verification["verified_at"],
                    conversion_rule=verification["conversion_rule"],
                )
            record["authority_supplement_status"] = "verified"
            record["authority_supplement_sources"] = [
                verification["source_name"],
            ]
            record["result_verification_method"] = verification[
                "verification_method"
            ]
            record["result_evidence_note"] = verification["evidence_note"]
            record["corroborating_source_urls"] = list(
                verification.get("corroborating_source_urls") or []
            )
            reconciled_count = verification.get(
                "official_or_source_start_count"
            )
            if reconciled_count is not None:
                reconciled_counts.add(reconciled_count)

            evidence_id = "|".join(
                (
                    horse_name,
                    verification["race_date"],
                    verification["expected_external_race_id"],
                    verification["expected_external_result_id"],
                )
            )
            source_evidence = [
                item
                for item in horse.get("source_evidence") or []
                if item.get("evidence_id") != evidence_id
            ]
            source_evidence.append(
                {
                    "evidence_id": evidence_id,
                    "source_name": verification["source_name"],
                    "source_url": verification["source_url"],
                    "corroborating_source_urls": list(
                        verification.get("corroborating_source_urls") or []
                    ),
                    "evidence_role": (
                        "canonical_career_participation_review"
                        if verification["normalized_start_status"]
                        == "did_not_start"
                        else "canonical_career_result_review"
                    ),
                    "verified_at": verification["verified_at"],
                    "verification_method": verification[
                        "verification_method"
                    ],
                    "evidence_note": verification["evidence_note"],
                }
            )
            horse["source_evidence"] = source_evidence
            applied_count += 1

        if len(reconciled_counts) > 1:
            raise ValueError(
                f"conflicting reconciled career counts for {horse_name}: "
                f"{sorted(reconciled_counts)}"
            )
        career = horse["career"]
        career["visible_source_record_count"] = max(
            career.get("visible_source_record_count")
            if isinstance(career.get("visible_source_record_count"), int)
            else 0,
            len(records),
        )
        record_counts = summarize_p0_horse_race_record_counts(records)
        actual_start_count = record_counts["actual_start_count"]
        if reconciled_counts:
            reconciled_count = next(iter(reconciled_counts))
            if actual_start_count != reconciled_count:
                raise ValueError(
                    f"reconciled career count mismatch for {horse_name}: "
                    f"{reconciled_count} != {actual_start_count}"
                )
            career.update(
                {
                    "source_start_count": reconciled_count,
                    "official_or_source_start_count": reconciled_count,
                    "source_start_count_quality": "source_reconciled",
                    "official_start_count_source": (
                        "manual final-field and published career-count "
                        "reconciliation"
                    ),
                    "official_start_count_source_url": next(
                        (
                            item.get("count_source_url")
                            for item in horse_verifications
                            if item.get("count_source_url")
                        ),
                        horse_verifications[0]["source_url"],
                    ),
                    "official_start_count_verified_at": max(
                        item["verified_at"] for item in horse_verifications
                    ),
                }
            )
        career["collected_start_count"] = actual_start_count
        career["nonstarter_count"] = record_counts["nonstarter_count"]
        career["result_semantics_pending_count"] = sum(
            record.get("result_evidence_status")
            == "requires_authoritative_supplement"
            for record in records
        )
        career.update(
            _start_count_reconciliation(
                career.get("source_start_count"),
                actual_start_count,
            )
        )
        horse.setdefault("raw_payload", {})[
            "manual_career_result_evidence_policy"
        ] = (
            "A visible profile row is not automatically an actual start. "
            "Manual evidence may confirm a finish, an abnormal result, or a "
            "non-start. Result status and start status remain independent."
        )
        horse["field_status"] = summarize_field_status(horse)
        finalize_career_collection_status(horse, horse["field_status"])
        applied_horses.add(horse_key)

    unused_horses = sorted(repr(key) for key in set(by_horse) - applied_horses)
    if unused_horses:
        raise ValueError(
            "career result evidence did not match samples: "
            + ", ".join(unused_horses)
        )
    return applied_count


US_EQUIBASE_PROFILE_VERIFICATIONS = load_us_equibase_profile_verifications(
    US_EQUIBASE_PROFILE_EVIDENCE
)
CAREER_RESULT_VERIFICATIONS = load_career_result_verifications(
    CAREER_RESULT_EVIDENCE
)


def parse_hrn_profile(
    row: dict[str, Any],
    transport: CachedTransport,
    equibase: dict[str, Any],
) -> dict[str, Any]:
    official_override = US_OFFICIAL_PROFILE_OVERRIDES.get(
        row["horse_name"],
        {},
    )
    horse_id = US_HRN_SLUG_OVERRIDES.get(
        row["horse_name"],
        _slug_from_name(row["horse_name"]),
    )
    profile_url = f"https://www.horseracingnation.com/horse/{horse_id}"
    response = transport.get(profile_url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    horse_name = _text(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")

    stats_container = soup.select_one(".horse-stats")
    values = _dl_values(stats_container or soup)
    if stats_container is not None:
        for term in stats_container.find_all("dt"):
            description = term.find_next_sibling("dd")
            if description is not None:
                values[_normalized(term.get_text(" ", strip=True)).rstrip(":")] = _text(
                    description.get_text(" ", strip=True)
                )
    values.update(_strong_label_values(stats_container))
    pedigree_links = (
        stats_container.select('a.horse-name[href*="/horse/"]')
        if stats_container
        else []
    )
    sire = _field(values, "Sire")
    dam = _field(values, "Dam")
    dam_sire = _field(values, "Dam Sire")
    if len(pedigree_links) >= 3:
        sire = _text(pedigree_links[0].get_text(" ", strip=True))
        dam = _text(pedigree_links[1].get_text(" ", strip=True))
        dam_sire = _text(pedigree_links[2].get_text(" ", strip=True))

    hrn_birth_year = _year(_field(values, "Foaled"))
    for role, hrn_value, official_value in (
        ("horse_name", horse_name, row["horse_name"]),
        ("sire", sire, equibase.get("sire")),
        ("dam", dam, equibase.get("dam")),
        ("birth_year", hrn_birth_year, _year(equibase.get("birth_date"))),
    ):
        if hrn_value in ("", None) or official_value in ("", None):
            raise ValueError(
                f"HRN identity incomplete for {row['horse_name']}: {role}"
            )
        if role == "birth_year":
            matches = hrn_value == official_value
        else:
            matches = _identity_name(hrn_value) == _identity_name(official_value)
        if not matches:
            raise ValueError(
                f"HRN {role} mismatch for {row['horse_name']}: "
                f"{hrn_value!r} != {official_value!r}"
            )

    result_table = soup.select_one("table.horse-table, #all-results")
    records: list[dict[str, Any]] = []
    if result_table is not None:
        header_row = result_table.select_one("tr.horse-header")
        if header_row is None:
            header_row = next(
                (
                    item
                    for item in result_table.find_all("tr")
                    if item.find_all("th")
                    and any(
                        _normalized(cell.get_text(" ", strip=True)) == "date"
                        for cell in item.find_all("th")
                    )
                ),
                None,
            )
        headers = [
            _normalized(cell.get_text(" ", strip=True))
            for cell in header_row.find_all("th")
        ] if header_row else []
        for tr in result_table.find_all("tr"):
            if tr is header_row or tr.find("th"):
                continue
            cells = tr.find_all("td", recursive=False)
            if len(cells) < 4:
                continue
            by_header = {
                headers[index]: cell
                for index, cell in enumerate(cells)
                if index < len(headers)
            }
            date_cell = by_header.get("date", cells[0])
            date_node = date_cell.find("time")
            race_cell = next(
                (cell for label, cell in by_header.items() if label == "race"),
                cells[2] if len(cells) == 4 else cells[5],
            )
            track_cell = next(
                (
                    cell
                    for label, cell in by_header.items()
                    if label in {"trk", "track"}
                ),
                cells[1] if len(cells) == 4 else cells[2],
            )
            finish_cell = next(
                (
                    cell
                    for label, cell in by_header.items()
                    if label.startswith("finish")
                ),
                cells[3] if len(cells) == 4 else cells[1],
            )
            race_link = race_cell.find("a", href=re.compile(r"/race/"))
            race_url = (
                urljoin(profile_url, race_link["href"])
                if race_link
                else profile_url
            )
            finish_text = _text(finish_cell.get_text(" ", strip=True))
            ordinal = re.match(r"(\d+)(?:st|nd|rd|th)?", finish_text, re.I)
            records.append(
                {
                    "external_race_id": _text(tr.get("data-race-id"))
                    or _id_from_race_url(race_url),
                    "external_result_id": _text(tr.get("data-result-id")),
                    "race_date": _iso_date(
                        date_node.get("datetime")
                        if date_node and date_node.get("datetime")
                        else date_cell.get_text(" ", strip=True)
                    ),
                    "race_name": _text(race_cell.get_text(" ", strip=True)),
                    "racecourse": _text(
                        (
                            track_cell.find("a").get("title")
                            if track_cell.find("a")
                            else ""
                        )
                        or track_cell.get_text(" ", strip=True)
                    ),
                    "finish": ordinal.group(1) if ordinal else finish_text,
                    "distance_text": _text(
                        next(
                            (
                                cell.get_text(" ", strip=True)
                                for label, cell in by_header.items()
                                if label == "distance"
                            ),
                            "",
                        )
                    ),
                    "source_url": race_url,
                }
            )

    visible_source_record_count = len(records)
    records, deduplicated_record_count = deduplicate_us_visible_records(records)
    bred = _field(values, "Bred")
    bred_match = re.fullmatch(r"(.+?)\s+by\s+(.+)", bred, re.I)
    bred_location = _text(bred_match.group(1)) if bred_match else ""
    breeder = (
        _field(values, "Breeder")
        or (_text(bred_match.group(2)) if bred_match else "")
    )
    country = _field(values, "Country")
    if not country and bred_location:
        country = _text(bred_location.rsplit(",", 1)[-1])
    official_country_match = re.search(
        r"\(([A-Z]{2,3})\)$",
        _text(equibase.get("horse_name")),
    )
    country = (
        _text(official_override.get("country"))
        or (
            _text(official_country_match.group(1))
            if official_country_match
            else ""
        )
        or country
    )
    age_text = _field(values, "Age")
    age_match = re.search(r"\s+-\s+(.+)$", age_text)
    sex = _field(values, "Sex") or (
        _text(age_match.group(1)) if age_match else ""
    )

    birth_date = equibase.get("birth_date") or _iso_date(_field(values, "Foaled"))
    source_url = equibase.get("source_url") or profile_url
    profile_verification = US_EQUIBASE_PROFILE_VERIFICATIONS.get(
        _manual_evidence_source_key(
            "equibase",
            equibase.get("external_horse_id"),
        )
    )
    if profile_verification is None:
        raise ValueError(
            f"missing Equibase profile verification for {row['horse_name']}"
        )
    validate_us_equibase_profile_verification(
        profile_verification,
        equibase,
    )
    _apply_us_deduplicated_source_evidence(
        records,
        profile_verification,
    )
    official_start_count = profile_verification["official_start_count"]
    reconciliation = _start_count_reconciliation(
        official_start_count,
        len(records),
    )
    gap_count = reconciliation["gap_count"]
    count_aligned = gap_count == 0
    return {
        "schema_version": "p0-horse-research.v1",
        "adapter_key": "united_states_equibase_hrn_research",
        "region": RacingRegion.UNITED_STATES,
        "source": {
            "name": "equibase+hrn",
            "url": source_url,
            "external_horse_id": equibase.get("external_horse_id", horse_id),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "identity": {
            "horse_name": horse_name or row["horse_name"],
            "sire_name": equibase.get("sire") or sire,
            "dam_name": equibase.get("dam") or dam,
            "birth_year": _year(birth_date),
        },
        "basic_profile": {
            "country": country,
            "sex": equibase.get("sex") or sex,
            "color": profile_verification["color_normalized"],
            "birth_date": birth_date,
            "owner_name": equibase.get("owner_name", "")
            or _field(values, "Owner", "Owner(s)"),
            "trainer_name": equibase.get("trainer_name", "")
            or _field(values, "Trainer"),
            "breeder_name": _text(official_override.get("breeder_name"))
            or equibase.get("breeder_name", "")
            or breeder,
        },
        "basic_profile_field_evidence": [
            {
                "field_name": "color",
                "status": "official_manual_verified",
                "source_name": "equibase",
                "source_url": profile_verification["source_url"],
                "direct_raw_value": profile_verification["color_raw"],
                "normalized_value": profile_verification["color_normalized"],
                "verified_at": profile_verification["verified_at"],
                "verification_method": profile_verification[
                    "verification_method"
                ],
                "evidence_note": profile_verification["evidence_note"],
            }
        ],
        "pedigree": {
            "sire": equibase.get("sire") or sire,
            "dam": equibase.get("dam") or dam,
            "sire_sire": _field(values, "Sire Sire"),
            "sire_dam": _field(values, "Sire Dam"),
            "dam_sire": dam_sire,
            "dam_dam": _field(values, "Dam Dam"),
        },
        "aliases": [
            {
                "name": horse_name or row["horse_name"],
                "language": "en",
                "is_original": True,
            }
        ],
        "career": {
            "official_or_source_start_count": official_start_count,
            "source_start_count": official_start_count,
            "source_start_count_quality": "official_verified",
            "official_start_count_source": "equibase",
            "official_start_count_source_url": profile_verification[
                "source_url"
            ],
            "official_start_count_verified_at": profile_verification[
                "verified_at"
            ],
            "record_authority_status": (
                "count_aligned_records_unverified"
                if count_aligned
                else "source_blocked"
            ),
            "visible_source_record_count": visible_source_record_count,
            "deduplicated_record_count": deduplicated_record_count,
            "collected_start_count": len(records),
            **reconciliation,
            "career_collection_status": (
                "count_aligned_per_record_officiality_pending"
                if count_aligned
                else "count_mismatch"
            ),
            "records": records,
        },
        "source_evidence": [
            {
                    "source_name": "equibase",
                    "source_url": source_url,
                    "evidence_role": (
                        "identity_profile_color_and_official_start_count"
                    ),
                    "external_horse_id": equibase.get("external_horse_id", ""),
                    "verified_at": profile_verification["verified_at"],
                    "source_as_of": profile_verification["source_as_of"],
                    "verification_method": profile_verification[
                        "verification_method"
                    ],
                    "evidence_note": profile_verification["evidence_note"],
            },
            {
                "source_name": "hrn",
                "source_url": profile_url,
                "evidence_role": "profile_and_visible_career",
                "external_horse_id": horse_id,
            },
            *(
                [
                    {
                        "source_name": "nyra",
                        "source_url": official_override["source_url"],
                        "evidence_role": "official_entry_breeder_and_country",
                        "external_horse_id": equibase.get(
                            "external_horse_id",
                            "",
                        ),
                    }
                ]
                if official_override
                else []
            ),
        ],
        "raw_payload": {
            "research_note": (
                "Equibase profile is protected by Incapsula; exact refno and "
                "identity fields came from the official event result payload. "
                "HRN rows are not treated as official per-record results. "
                "The Equibase Career Starts count and profile color were "
                "manually verified, but per-record officiality remains pending."
            )
        },
    }


def from_japan_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    career = dict(candidate.get("career_history") or {})
    records = candidate.get("race_records") or []
    record_counts = summarize_p0_horse_race_record_counts(records)
    actual_start_count = record_counts["actual_start_count"]
    source_count = career.get("official_or_source_start_count")
    source_count_is_declared = (
        isinstance(source_count, int)
        and not isinstance(source_count, bool)
        and source_count >= 0
    )
    career["source_start_count"] = (
        source_count if source_count_is_declared else None
    )
    career["source_start_count_quality"] = "source_declared"
    source = next(
        (
            evidence
            for evidence in candidate.get("source_evidence") or []
            if evidence.get("evidence_role") != "reviewed_candidate"
        ),
        {},
    )
    career["official_start_count_source"] = source.get("source_name", "")
    career["official_start_count_source_url"] = source.get("source_url", "")
    career["official_start_count_verified_at"] = source.get("fetched_at")
    career["record_authority_status"] = "source_records_verified"
    career["career_collection_status"] = career.get("status")
    career["records"] = records
    reconciliation = _start_count_reconciliation(
        source_count if source_count_is_declared else None,
        actual_start_count,
    )
    career.update(
        {
            "career_record_count": len(records),
            "collected_start_count": actual_start_count,
            "nonstarter_count": record_counts["nonstarter_count"],
            "unconfirmed_count": record_counts["unconfirmed_count"],
            "abnormal_official_status_count": record_counts[
                "abnormal_official_status_count"
            ],
            "overseas_start_count": record_counts["overseas_start_count"],
            **reconciliation,
        }
    )
    return {
        "schema_version": "p0-horse-research.v1",
        "adapter_key": "japan_jbis",
        "region": RacingRegion.JAPAN,
        "source": {
            "name": source.get("source_name", ""),
            "url": source.get("source_url", ""),
            "external_horse_id": source.get("external_horse_id", ""),
            "fetched_at": source.get("fetched_at", ""),
        },
        "identity": candidate.get("identity") or {},
        "basic_profile": candidate.get("basic_profile") or {},
        "pedigree": candidate.get("pedigree") or {},
        "aliases": candidate.get("aliases") or [],
        "career": career,
        "source_evidence": candidate.get("source_evidence") or [],
        "major_wins": candidate.get("major_wins") or [],
        "raw_payload": {
            "research_note": "Reused from the authorized offline JBIS replay."
        },
    }


def attach_candidate_context(
    row: dict[str, Any],
    payload: dict[str, Any] | None,
    *,
    error: str = "",
) -> dict[str, Any]:
    payload = payload or {
        "region": row["sample_region"],
        "identity": {"horse_name": row["horse_name"]},
        "basic_profile": {},
        "pedigree": {},
        "aliases": [],
        "career": {"records": []},
        "source": {},
        "source_evidence": [],
        "raw_payload": {},
    }
    payload["candidate"] = {
        "sample_region": row["sample_region"],
        "sample_rank": row["sample_rank"],
        "candidate_key": row["candidate_key"],
        "horse_name": row["horse_name"],
        "aliases": row["aliases"],
        "identity_keys": row["identity_keys"],
        "source_namespace": row["source_namespace"],
        "source_urls": row["source_urls"],
        "evidence_count": int(row["evidence_count"]),
        "actual_start_evidence_count": int(
            row["actual_start_evidence_count"]
        ),
        "latest_event_name": row["latest_event_name"],
        "latest_event_grade": row["latest_event_grade"],
        "review_decision": row["review_decision"],
    }
    payload["research_error"] = error
    return payload


def summarize_field_status(payload: dict[str, Any]) -> dict[str, Any]:
    basic = payload.get("basic_profile") or {}
    pedigree = payload.get("pedigree") or {}
    career = payload.get("career") or {}
    missing_basic = [field for field in PROFILE_FIELDS if not basic.get(field)]
    missing_pedigree = [
        field for field in PEDIGREE_FIELDS if not pedigree.get(field)
    ]
    records = career.get("records") or []
    source_count = career.get("source_start_count")
    record_counts = summarize_p0_horse_race_record_counts(records)
    actual_start_count = record_counts["actual_start_count"]
    nonstarter_count = record_counts["nonstarter_count"]
    unknown_count = record_counts["unconfirmed_count"]
    abnormal_official_status_count = record_counts[
        "abnormal_official_status_count"
    ]
    overseas_start_count = record_counts["overseas_start_count"]
    source_count_is_declared = (
        career.get("source_start_count_quality")
        in {"source_declared", "source_reconciled", "official_verified"}
    )
    if (
        source_count_is_declared
        and isinstance(source_count, int)
        and source_count == len(records) - nonstarter_count
    ):
        # Sporting Life may omit a finish/casualty code for older starts, but
        # its declared run count still proves those rows were actual starts.
        actual_start_count = source_count
    count_reference = career.get("official_or_source_start_count")
    count_reference_is_declared = (
        isinstance(count_reference, int)
        and not isinstance(count_reference, bool)
    )
    if not count_reference_is_declared:
        count_reference = source_count
        count_reference_is_declared = source_count_is_declared
    reconciliation = _start_count_reconciliation(
        count_reference,
        actual_start_count,
    )
    return {
        "missing_basic_profile_fields": missing_basic,
        "missing_pedigree_fields": missing_pedigree,
        "career_record_count": len(records),
        "collected_actual_start_count": actual_start_count,
        "nonstarter_record_count": nonstarter_count,
        "unknown_record_count": unknown_count,
        "abnormal_official_status_count": abnormal_official_status_count,
        "overseas_start_count": overseas_start_count,
        "source_start_count": source_count,
        "official_or_source_start_count": career.get(
            "official_or_source_start_count",
            source_count,
        ),
        "official_start_count_source": career.get(
            "official_start_count_source",
            "",
        ),
        "official_start_count_source_url": career.get(
            "official_start_count_source_url",
            "",
        ),
        "official_start_count_verified_at": career.get(
            "official_start_count_verified_at",
        ),
        "record_authority_status": career.get(
            "record_authority_status",
            "",
        ),
        "career_gap_count": reconciliation["gap_count"],
        "career_missing_start_count": reconciliation[
            "missing_start_count"
        ],
        "career_excess_start_count": reconciliation[
            "excess_start_count"
        ],
        "career_start_count_delta": reconciliation["start_count_delta"],
        "career_count_matches": (
            count_reference_is_declared
            and isinstance(count_reference, int)
            and count_reference == actual_start_count
        ),
        "research_error": payload.get("research_error", ""),
    }


def refresh_research_career_counts(payload: dict[str, Any]) -> None:
    career = payload.setdefault("career", {})
    records = career.get("records") or []
    record_counts = summarize_p0_horse_race_record_counts(records)
    actual_start_count = record_counts["actual_start_count"]
    source_count = career.get("source_start_count")
    if (
        career.get("source_start_count_quality")
        in {"source_declared", "source_reconciled", "official_verified"}
        and isinstance(source_count, int)
        and not isinstance(source_count, bool)
        and source_count
        == len(records) - record_counts["nonstarter_count"]
    ):
        actual_start_count = source_count
    count_reference = career.get("official_or_source_start_count")
    if (
        not isinstance(count_reference, int)
        or isinstance(count_reference, bool)
    ):
        count_reference = source_count
    reconciliation = _start_count_reconciliation(
        count_reference,
        actual_start_count,
    )
    career.update(
        {
            "career_record_count": len(records),
            "collected_start_count": actual_start_count,
            "nonstarter_count": record_counts["nonstarter_count"],
            "unconfirmed_count": record_counts["unconfirmed_count"],
            "abnormal_official_status_count": record_counts[
                "abnormal_official_status_count"
            ],
            "overseas_start_count": record_counts[
                "overseas_start_count"
            ],
            **reconciliation,
        }
    )


def finalize_career_collection_status(
    payload: dict[str, Any],
    field_status: dict[str, Any],
) -> None:
    career = payload.get("career")
    if not isinstance(career, dict):
        return
    authority = career.get("record_authority_status")
    if authority == "count_aligned_records_unverified":
        career["career_collection_status"] = (
            "count_aligned_per_record_officiality_pending"
        )
        return
    if authority != "source_records_verified":
        if authority == "source_blocked":
            career["career_collection_status"] = "source_blocked"
        elif authority in {"", None, "unknown"}:
            career["career_collection_status"] = "record_authority_pending"
        else:
            career["career_collection_status"] = "record_authority_invalid"
        return
    if field_status.get("career_count_matches") is not True:
        if (
            career.get("source_start_count_quality")
            in {"source_declared", "source_reconciled", "official_verified"}
            and isinstance(career.get("source_start_count"), int)
        ):
            career["career_collection_status"] = "count_mismatch"
        return
    if (
        field_status.get("unknown_record_count", 0) > 0
        or career.get("result_semantics_pending_count", 0) > 0
    ):
        career["career_collection_status"] = (
            "count_complete_result_semantics_partial"
        )
        return
    career["career_collection_status"] = "complete"


def apply_us_equibase_profile_verifications(
    data: dict[str, Any],
    verifications: dict[tuple[str, ...], dict[str, Any]],
) -> int:
    applied_keys: set[tuple[str, ...]] = set()
    for horse in data.get("horses") or []:
        if horse.get("region") != RacingRegion.UNITED_STATES:
            continue
        horse_name = _text(
            horse.get("candidate", {}).get("horse_name")
            or horse.get("identity", {}).get("horse_name")
        )
        verification_key = _manual_evidence_source_key(
            "equibase",
            horse.get("source", {}).get("external_horse_id"),
        )
        verification = verifications.get(verification_key)
        if verification is None:
            raise ValueError(
                f"missing Equibase profile verification for {horse_name}"
            )
        basic_profile = horse.setdefault("basic_profile", {})
        pedigree = horse.get("pedigree") or {}
        identity = horse.get("identity") or {}
        validate_us_equibase_profile_verification(
            verification,
            {
                "external_horse_id": horse.get("source", {}).get(
                    "external_horse_id"
                ),
                "sire": identity.get("sire_name") or pedigree.get("sire"),
                "dam": identity.get("dam_name") or pedigree.get("dam"),
                "birth_date": basic_profile.get("birth_date"),
            },
        )
        basic_profile["color"] = verification["color_normalized"]
        color_evidence = [
            item
            for item in horse.get("basic_profile_field_evidence") or []
            if item.get("field_name") != "color"
        ]
        color_evidence.append(
            {
                "field_name": "color",
                "status": "official_manual_verified",
                "source_name": "equibase",
                "source_url": verification["source_url"],
                "direct_raw_value": verification["color_raw"],
                "normalized_value": verification["color_normalized"],
                "verified_at": verification["verified_at"],
                "verification_method": verification["verification_method"],
                "evidence_note": verification["evidence_note"],
            }
        )
        horse["basic_profile_field_evidence"] = color_evidence

        career = horse.setdefault("career", {})
        raw_records = list(career.get("records") or [])
        records, newly_deduplicated = deduplicate_us_visible_records(
            raw_records
        )
        _apply_us_deduplicated_source_evidence(records, verification)
        previous_visible_count = career.get("visible_source_record_count")
        visible_source_record_count = max(
            previous_visible_count
            if isinstance(previous_visible_count, int)
            else 0,
            len(raw_records),
        )
        previous_deduplicated_count = career.get(
            "deduplicated_record_count"
        )
        deduplicated_record_count = max(
            previous_deduplicated_count
            if isinstance(previous_deduplicated_count, int)
            else 0,
            newly_deduplicated,
            visible_source_record_count - len(records),
        )
        record_counts = summarize_p0_horse_race_record_counts(records)
        collected_start_count = record_counts["actual_start_count"]
        official_start_count = verification["official_start_count"]
        reconciliation = _start_count_reconciliation(
            official_start_count,
            collected_start_count,
        )
        gap_count = reconciliation["gap_count"]
        count_aligned = gap_count == 0
        career.update(
            {
                "official_or_source_start_count": official_start_count,
                "source_start_count": official_start_count,
                "source_start_count_quality": "official_verified",
                "official_start_count_source": "equibase",
                "official_start_count_source_url": verification["source_url"],
                "official_start_count_verified_at": verification[
                    "verified_at"
                ],
                "record_authority_status": (
                    "count_aligned_records_unverified"
                    if count_aligned
                    else "source_blocked"
                ),
                "visible_source_record_count": visible_source_record_count,
                "deduplicated_record_count": deduplicated_record_count,
                "collected_start_count": collected_start_count,
                **reconciliation,
                "career_collection_status": (
                    "count_aligned_per_record_officiality_pending"
                    if count_aligned
                    else "count_mismatch"
                ),
                "records": records,
            }
        )

        source_evidence = [
            item
            for item in horse.get("source_evidence") or []
            if not (
                item.get("source_name") == "equibase"
                and str(item.get("evidence_role") or "").startswith(
                    "identity"
                )
            )
        ]
        source_evidence.insert(
            0,
            {
                "source_name": "equibase",
                "source_url": verification["source_url"],
                "evidence_role": (
                    "identity_profile_color_and_official_start_count"
                ),
                "external_horse_id": verification[
                    "expected_external_horse_id"
                ],
                "verified_at": verification["verified_at"],
                "source_as_of": verification["source_as_of"],
                "verification_method": verification["verification_method"],
                "evidence_note": verification["evidence_note"],
            },
        )
        horse["source_evidence"] = source_evidence
        horse.setdefault("raw_payload", {})[
            "equibase_manual_verification_policy"
        ] = (
            "Career Starts and profile color were manually verified on the "
            "Equibase profile. HRN rows remain non-official per-record "
            "evidence; duplicate profile/race rows were collapsed only when "
            "date, racecourse, distance and finish all matched."
        )
        horse["field_status"] = summarize_field_status(horse)
        finalize_career_collection_status(
            horse,
            horse["field_status"],
        )
        if verification_key is None:
            raise ValueError(
                f"missing Equibase external ID for {horse_name}"
            )
        applied_keys.add(verification_key)

    unused = sorted(
        repr(key) for key in set(verifications) - applied_keys
    )
    if unused:
        raise ValueError(
            "Equibase profile evidence did not match US samples: "
            + ", ".join(unused)
        )
    return len(applied_keys)


def collect(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    transport = CachedTransport(output_dir / "http_cache")
    rows = candidate_rows()
    japan = japan_candidates()
    equibase = collect_equibase_identities(transport)
    hkjc_client = _HKJCClient(transport)
    france_sporting_life_client = _SportingLifeClient(transport)
    uk_sporting_life_client = _SportingLifeClient(transport)
    results = []

    for row in rows:
        region = row["sample_region"]
        payload: dict[str, Any] | None = None
        error = ""
        try:
            if region == RacingRegion.JAPAN:
                payload = from_japan_candidate(japan[row["candidate_key"]])
            elif region == RacingRegion.HONG_KONG:
                payload = compact_source_payload(
                    hkjc_client.fetch_source_payload(make_request(row)),
                    source_note=(
                        "Direct HKJC profile parse. Birth date and breeder are "
                        "not present on the public profile."
                    ),
                )
            elif region == RacingRegion.UNITED_KINGDOM:
                payload = compact_source_payload(
                    uk_sporting_life_client.fetch_source_payload(
                        make_request(row)
                    ),
                    source_note=(
                        "Direct Sporting Life __NEXT_DATA__ profile and full_form."
                    ),
                )
            elif region == RacingRegion.FRANCE:
                sporting_life_id = FRANCE_SPORTING_LIFE_IDS[row["horse_name"]]
                payload = compact_source_payload(
                    france_sporting_life_client.fetch_source_payload(
                        make_request(
                            row,
                            region=RacingRegion.UNITED_KINGDOM,
                            source_name="sporting_life",
                            external_horse_id=sporting_life_id,
                        )
                    ),
                    region=RacingRegion.FRANCE,
                    source_note=(
                        "Geny returned HTTP 429. Sporting Life was used as the "
                        "working career/profile source after exact identity "
                        "resolution from a matching graded-race entry."
                    ),
                )
                payload["adapter_key"] = "france_sporting_life_research"
                payload = apply_france_authoritative_evidence(
                    payload,
                    horse_name=row["horse_name"],
                )
            elif region == RacingRegion.UNITED_STATES:
                payload = parse_hrn_profile(
                    row,
                    transport,
                    equibase.get(_normalized(row["horse_name"]), {}),
                )
        except Exception as exc:  # Research output must retain every row.
            error = f"{type(exc).__name__}: {exc}"
        item = attach_candidate_context(row, payload, error=error)
        item["field_status"] = summarize_field_status(item)
        finalize_career_collection_status(item, item["field_status"])
        results.append(item)
        print(
            f"{len(results):02d}/50 {region:14s} "
            f"{row['horse_name']}: {'ok' if not error else error}",
            flush=True,
        )

    data = {
        "schema_version": "p0-horse-research.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_source": str(CANDIDATE_CSV),
        "horses": results,
    }
    apply_career_result_verifications(
        data,
        CAREER_RESULT_VERIFICATIONS,
    )
    output_path = output_dir / "p0_horse_research_50.json"
    output_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            ROOT
            / "runtime/horse_profile_completion/"
            "research-50-parsed-20260718"
        ),
    )
    args = parser.parse_args()
    print(collect(args.output_dir))


if __name__ == "__main__":
    main()
