from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import time
import unicodedata
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from stable.models import HorseCareerRecordAuthorityStatus, RacingRegion
from stable.services.p0_horse_completion_adapters import (
    REGION_ADAPTERS,
    REQUIRED_BASIC_PROFILE_FIELDS,
    REQUIRED_PEDIGREE_FIELDS,
    SOURCE_CACHE_SCHEMA_VERSION,
    P0HorseCompletionNetworkDisabled,
    P0HorseCompletionRequest,
)


class P0HorseSourceBlocked(ValueError):
    """A stable, fail-closed source retrieval or completeness failure.

    ``status_code`` carries the HTTP status when applicable; ``transient``
    marks failures eligible for bounded retry (timeout, connection errors,
    HTTP 429 and 5xx); ``retry_after`` carries the Retry-After hint seconds.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        transient: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient
        self.retry_after = retry_after


RETRY_AFTER_CAP_SECONDS = 300.0
NETKEIBA_PARSER_VERSION = "netkeiba-parser.v2"


MANUAL_SUPPLEMENT_CSV_FIELDS = (
    "candidate_key",
    "region",
    "horse_name",
    "field_group",
    "field_name",
    "current_value",
    "proposed_value",
    "source_name",
    "source_url",
    "source_external_horse_id",
    "evidence_note",
    "entered_by",
    "reviewer",
    "review_status",
    "reviewed_at",
    "review_notes",
)
MANUAL_SUPPLEMENT_FIELDS = {
    "identity": frozenset({"sire_name", "dam_name", "birth_year"}),
    "basic_profile": frozenset(REQUIRED_BASIC_PROFILE_FIELDS),
    "pedigree": frozenset(REQUIRED_PEDIGREE_FIELDS),
}
MANUAL_SUPPLEMENT_REVIEW_STATUSES = frozenset(
    {"pending", "approved", "rejected", "needs_more_evidence"}
)
CANONICAL_JSON_MAX_DEPTH = 100
_HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


class P0HorseTransport(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any:
        ...


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalized(value: Any) -> str:
    return unicodedata.normalize("NFKC", _text(value)).casefold()


def _adjacent_search_summary(link: Any) -> str:
    for sibling in link.next_siblings:
        name = getattr(sibling, "name", None)
        if name is None and not _text(sibling):
            continue
        if name == "span":
            return _text(sibling.get_text(" ", strip=True))
        break
    return ""


def _parse_search_identity_summary(
    summary: Any,
    *,
    jbis_metadata: bool = False,
) -> dict[str, Any]:
    text = unicodedata.normalize("NFKC", _text(summary))
    match = re.fullmatch(
        r"(?P<birth_year>(?:19|20)\d{2})\s*[,，]?\s*"
        r"(?P<sire>.+?)\s+-\s+(?P<dam>.+)",
        text,
    )
    if not match:
        raise P0HorseSourceBlocked(
            "identity_incomplete: search_result birth_year, sire_name, or dam_name"
        )
    sire = _text(match.group("sire"))
    if jbis_metadata:
        tokens = sire.split()
        metadata = {
            "牡",
            "牝",
            "騸",
            "鹿毛",
            "黒鹿毛",
            "青鹿毛",
            "青毛",
            "栗毛",
            "栃栗毛",
            "芦毛",
            "白毛",
        }
        while tokens and tokens[0] in metadata:
            tokens.pop(0)
        sire = " ".join(tokens)
    parsed = {
        "birth_year": int(match.group("birth_year")),
        "sire_name": sire,
        "dam_name": _text(match.group("dam")),
    }
    if not parsed["sire_name"] or not parsed["dam_name"]:
        raise P0HorseSourceBlocked(
            "identity_incomplete: search_result sire_name or dam_name"
        )
    return parsed


def _require_names_in_profile_aliases(
    *,
    request_name: Any,
    search_name: Any,
    profile_aliases: list[Any],
) -> None:
    aliases = {_normalized(alias) for alias in profile_aliases if _normalized(alias)}
    if not aliases or not _normalized(request_name) or not _normalized(search_name):
        raise P0HorseSourceBlocked(
            "identity_incomplete: request, search_result, or profile horse_name"
        )
    for evidence, name in (
        ("request", request_name),
        ("search_result", search_name),
    ):
        if _normalized(name) not in aliases:
            raise P0HorseSourceBlocked(f"identity_mismatch: {evidence} horse_name")


def _require_search_identity_matches_profile(
    search_identity: dict[str, Any],
    *,
    sire_name: Any,
    dam_name: Any,
    birth_year: Any,
) -> None:
    profile_identity = {
        "birth_year": birth_year,
        "sire_name": sire_name,
        "dam_name": dam_name,
    }
    for field in ("birth_year", "sire_name", "dam_name"):
        search_value = search_identity.get(field)
        profile_value = profile_identity.get(field)
        if search_value in ("", None) or profile_value in ("", None):
            raise P0HorseSourceBlocked(
                f"identity_incomplete: search_result or profile {field}"
            )
        if _normalized(search_value) != _normalized(profile_value):
            raise P0HorseSourceBlocked(
                f"identity_mismatch: search_result {field}"
            )


def _require_complete_identity(
    *,
    horse_name: Any,
    sire_name: Any,
    dam_name: Any,
    birth_year: Any,
) -> None:
    if (
        not _text(horse_name)
        or not _text(sire_name)
        or not _text(dam_name)
        or birth_year is None
    ):
        raise P0HorseSourceBlocked(
            "identity_incomplete: horse_name, sire_name, dam_name, or birth_year"
        )


def _require_request_identity_matches_profile(
    request: P0HorseCompletionRequest,
    *,
    horse_name: Any,
    sire_name: Any,
    dam_name: Any,
    birth_year: Any,
) -> None:
    expected = {
        "horse_name": request.horse_name,
        "sire_name": request.expected_sire_name,
        "dam_name": request.expected_dam_name,
        "birth_year": request.expected_birth_year,
    }
    profile = {
        "horse_name": horse_name,
        "sire_name": sire_name,
        "dam_name": dam_name,
        "birth_year": birth_year,
    }
    if any(expected[field] in ("", None) for field in expected):
        raise P0HorseSourceBlocked(
            "identity_incomplete: request horse_name, sire_name, dam_name, "
            "or birth_year"
        )
    for field, expected_value in expected.items():
        profile_value = profile[field]
        if profile_value in ("", None):
            raise P0HorseSourceBlocked(f"identity_incomplete: profile {field}")
        if _normalized(expected_value) != _normalized(profile_value):
            raise P0HorseSourceBlocked(f"identity_mismatch: request {field}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_url(value: Any) -> bool:
    try:
        _HTTP_URL_VALIDATOR(_text(value))
    except ValidationError:
        return False
    return True


def _year(value: Any) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", _text(value))
    return int(match.group(0)) if match else None


def _iso_date(value: Any) -> str:
    text = _text(value)
    for pattern, order in (
        (r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", "ymd"),
        (r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", "dmy"),
    ):
        match = (
            re.search(pattern, text)
            if order == "ymd"
            else re.fullmatch(pattern, text)
        )
        if not match:
            continue
        first, second, third = (int(part) for part in match.groups())
        if order == "ymd":
            year, month, day = first, second, third
        else:
            day, month, year = first, second, third
            if year < 100:
                year += 2000
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""
    japanese = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if japanese:
        try:
            return datetime(
                int(japanese.group(1)),
                int(japanese.group(2)),
                int(japanese.group(3)),
            ).date().isoformat()
        except ValueError:
            return ""
    return ""


def _dl_values(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for term in soup.find_all("dt"):
        description = term.find_next_sibling("dd")
        if description is not None:
            values[_normalized(term.get_text(" ", strip=True))] = _text(
                description.get_text(" ", strip=True)
            )
    return values


def _table_values(table: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    if table is None:
        return values
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            values[_normalized(cells[0].get_text(" ", strip=True))] = _text(
                cells[-1].get_text(" ", strip=True)
            )
    return values


def _field(values: dict[str, str], *labels: str) -> str:
    for label in labels:
        value = values.get(_normalized(label), "")
        if value:
            return value
    return ""


def _pedigree_from_roles(soup: BeautifulSoup) -> dict[str, str]:
    return {
        field: _text(
            node.get_text(" ", strip=True)
            if (node := soup.select_one(f'[data-role="{role}"]'))
            else ""
        )
        for field, role in (
            ("sire", "sire"),
            ("dam", "dam"),
            ("sire_sire", "sire-sire"),
            ("sire_dam", "sire-dam"),
            ("dam_sire", "dam-sire"),
            ("dam_dam", "dam-dam"),
        )
    }


def _strong_label_values(container: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    if container is None:
        return values
    for strong in container.find_all("strong"):
        label = _normalized(strong.get_text(" ", strip=True)).rstrip(":")
        parent = strong.parent
        text = _text(parent.get_text(" ", strip=True)) if parent else ""
        value = re.sub(
            rf"^{re.escape(_text(strong.get_text(' ', strip=True)))}\s*",
            "",
            text,
        )
        if label and value:
            values[label] = value
    return values


def _slug_from_name(value: Any) -> str:
    ascii_name = unicodedata.normalize("NFKD", _text(value)).encode(
        "ascii", "ignore"
    ).decode("ascii")
    ascii_name = re.sub(r"['’]", "", ascii_name)
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_")


def _id_from_race_url(value: Any) -> str:
    path = urlparse(_text(value)).path.rstrip("/")
    if "/race/result/" in path:
        return "-".join(path.split("/")[-3:])
    match = re.search(r"/race/([^/?#]+)", path)
    return match.group(1) if match else ""


def _stable_source_record_id(prefix: str, *parts: Any) -> str:
    normalized_parts = [
        _normalized(part)
        for part in parts
        if _text(part)
    ]
    encoded = "|".join((prefix, *normalized_parts)).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _field_evidence_layer(
    *,
    value: Any = None,
    status: str,
    source_name: str = "",
    source_url: str = "",
    observed_at: str = "",
    conversion_rule: str = "",
) -> dict[str, Any]:
    return {
        "value": deepcopy(value),
        "status": status,
        "source_name": source_name,
        "source_url": source_url,
        "observed_at": observed_at,
        "conversion_rule": conversion_rule,
    }


SPORTING_LIFE_CASUALTY_RESULTS = {
    "fell": ("F", "did_not_finish"),
    "unseatedrider": ("UR", "did_not_finish"),
    "broughtdown": ("BD", "did_not_finish"),
    "pulledup": ("PU", "did_not_finish"),
    "refused": ("REF", "did_not_finish"),
    "ranout": ("RO", "did_not_finish"),
    "slippedup": ("SU", "did_not_finish"),
}


def _sporting_life_result_evidence(
    *,
    position: Any,
    casualty_reason: Any,
    source_url: str,
    observed_at: str,
) -> tuple[str, str, str, list[dict[str, Any]]]:
    position_text = _text(position)
    casualty_text = _text(casualty_reason)
    casualty_mapping = SPORTING_LIFE_CASUALTY_RESULTS.get(
        _normalized(casualty_text).replace(" ", "")
    )
    if casualty_mapping:
        official_code, result_status = casualty_mapping
        evidence_status = "normalized_from_source_reason"
        direct_value = casualty_text
        normalized_value = result_status
        normalized_status = "mapped"
        conversion_rule = "sporting_life_casualty_reason_map_v1"
    elif position_text:
        official_code = ""
        result_status = ""
        evidence_status = "direct_position"
        direct_value = position_text
        normalized_value = None
        normalized_status = "not_applied"
        conversion_rule = ""
    else:
        official_code = ""
        result_status = ""
        evidence_status = "requires_authoritative_supplement"
        direct_value = "N/A"
        normalized_value = None
        normalized_status = "blocked"
        conversion_rule = "authoritative_result_required_v1"

    field_evidence = [
        {
            "field_name": "result",
            "direct_raw": _field_evidence_layer(
                value=direct_value,
                status="observed",
                source_name="sporting_life",
                source_url=source_url,
                observed_at=observed_at,
                conversion_rule="sporting_life_display_value_v1",
            ),
            "canonical_raw": _field_evidence_layer(
                status="not_collected",
            ),
            "normalized": _field_evidence_layer(
                value=normalized_value,
                status=normalized_status,
                source_name="umanews",
                source_url=source_url,
                observed_at=observed_at,
                conversion_rule=conversion_rule,
            ),
        }
    ]
    return official_code, result_status, evidence_status, field_evidence


def _sporting_life_semantic_field_evidence(
    *,
    field_name: str,
    value: Any,
    source_url: str,
    observed_at: str,
) -> dict[str, Any]:
    direct_value = _text(value)
    return {
        "field_name": field_name,
        "direct_raw": _field_evidence_layer(
            value=direct_value or None,
            status="observed" if direct_value else "not_collected",
            source_name="sporting_life",
            source_url=source_url,
            observed_at=observed_at,
            conversion_rule="sporting_life_display_value_v1",
        ),
        "canonical_raw": _field_evidence_layer(status="not_collected"),
        "normalized": _field_evidence_layer(
            status="blocked",
            source_name="umanews",
            source_url=source_url,
            observed_at=observed_at,
            conversion_rule="authoritative_local_semantics_required_v1",
        ),
    }


def _supplement_record_result_evidence(
    record: dict[str, Any],
    *,
    canonical_value: Any,
    normalized_result_status: str,
    normalized_start_status: str = "",
    source_name: str,
    source_url: str,
    observed_at: str,
    conversion_rule: str,
) -> dict[str, Any]:
    existing_evidence = list(record.get("field_evidence") or [])
    result_evidence = next(
        (
            item
            for item in existing_evidence
            if item.get("field_name") == "result"
        ),
        {},
    )
    direct_raw = deepcopy(result_evidence.get("direct_raw") or {})
    if not direct_raw:
        direct_raw = _field_evidence_layer(
            value=record.get("finish"),
            status="observed",
            source_name="sporting_life",
            source_url=record.get("source_url", ""),
        )
    supplemented_result = {
        "field_name": "result",
        "direct_raw": direct_raw,
        "canonical_raw": _field_evidence_layer(
            value=canonical_value,
            status="observed",
            source_name=source_name,
            source_url=source_url,
            observed_at=observed_at,
            conversion_rule="authoritative_source_display_value_v1",
        ),
        "normalized": _field_evidence_layer(
            value=normalized_result_status,
            status="mapped",
            source_name="umanews",
            source_url=source_url,
            observed_at=observed_at,
            conversion_rule=conversion_rule,
        ),
    }
    record["direct_result_value"] = direct_raw.get("value")
    record["finish"] = _text(canonical_value)
    record["official_result_code"] = _text(canonical_value)
    record["result_status"] = normalized_result_status
    if normalized_start_status:
        record["start_status"] = normalized_start_status
    record["result_evidence_status"] = "canonical_verified"
    record["field_evidence"] = [
        item
        for item in existing_evidence
        if item.get("field_name") != "result"
    ] + [supplemented_result]
    return record


def _supplement_record_start_evidence(
    record: dict[str, Any],
    *,
    canonical_value: str,
    normalized_start_status: str,
    source_name: str,
    source_url: str,
    observed_at: str,
    conversion_rule: str,
) -> dict[str, Any]:
    existing_evidence = list(record.get("field_evidence") or [])
    start_evidence = {
        "field_name": "start_status",
        "direct_raw": _field_evidence_layer(status="not_collected"),
        "canonical_raw": _field_evidence_layer(
            value=canonical_value,
            status="observed",
            source_name=source_name,
            source_url=source_url,
            observed_at=observed_at,
            conversion_rule="authoritative_participation_status_v1",
        ),
        "normalized": _field_evidence_layer(
            value=normalized_start_status,
            status="mapped",
            source_name="umanews",
            source_url=source_url,
            observed_at=observed_at,
            conversion_rule=conversion_rule,
        ),
    }
    record["finish"] = ""
    record["official_result_code"] = ""
    record["result_status"] = "unknown"
    record["start_status"] = normalized_start_status
    record["participation_status"] = canonical_value
    record["result_evidence_status"] = (
        "not_applicable_nonstart_verified"
    )
    adjusted_evidence: list[dict[str, Any]] = []
    supplemented_result: dict[str, Any] | None = None
    for item in existing_evidence:
        if item.get("field_name") == "start_status":
            continue
        if item.get("field_name") == "result":
            supplemented_result = deepcopy(item)
            supplemented_result["canonical_raw"] = _field_evidence_layer(
                status="not_applicable",
                source_name="umanews",
                source_url=source_url,
                observed_at=observed_at,
                conversion_rule="verified_nonstart_has_no_result_v1",
            )
            supplemented_result["normalized"] = _field_evidence_layer(
                status="not_applicable",
                source_name="umanews",
                source_url=source_url,
                observed_at=observed_at,
                conversion_rule="verified_nonstart_has_no_result_v1",
            )
            continue
        adjusted_evidence.append(item)
    if supplemented_result is None:
        supplemented_result = {
            "field_name": "result",
            "direct_raw": _field_evidence_layer(status="not_collected"),
            "canonical_raw": _field_evidence_layer(
                status="not_applicable",
                source_name="umanews",
                source_url=source_url,
                observed_at=observed_at,
                conversion_rule="verified_nonstart_has_no_result_v1",
            ),
            "normalized": _field_evidence_layer(
                status="not_applicable",
                source_name="umanews",
                source_url=source_url,
                observed_at=observed_at,
                conversion_rule="verified_nonstart_has_no_result_v1",
            ),
        }
    record["field_evidence"] = adjusted_evidence + [
        supplemented_result,
        start_evidence,
    ]
    return record


def _row_records(
    table: Any,
    *,
    source_url: str,
    is_overseas: bool = False,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if table is None:
        return records
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        link = row.find("a", href=True)
        race_url = urljoin(source_url, link["href"]) if link else source_url
        records.append(
            {
                "external_race_id": _text(row.get("data-race-id")),
                "external_result_id": _text(row.get("data-result-id")),
                "race_date": _text(cells[0].get_text(" ", strip=True)),
                "race_name": _text(cells[1].get_text(" ", strip=True)),
                "racecourse": _text(cells[2].get_text(" ", strip=True)),
                "finish": _text(cells[3].get_text(" ", strip=True)),
                "source_url": race_url,
                "is_overseas": is_overseas,
            }
        )
    return records


def _is_actual_start(finish: Any) -> bool:
    return _normalized(finish).replace(".", "") not in {
        "",
        "scr",
        "scratched",
        "nr",
        "non runner",
        "non-runner",
        "wv",
        "wd",
        "withdrawn",
    }


def _source_provenance(source: dict[str, Any]) -> dict[str, Any]:
    return {
        output_key: deepcopy(source.get(source_key))
        for source_key, output_key in (
            ("name", "source_name"),
            ("url", "source_url"),
            ("external_horse_id", "external_horse_id"),
            ("fetched_at", "fetched_at"),
        )
        if source.get(source_key) not in ("", None)
    }


def _utc_datetime(value: Any, *, field: str) -> datetime:
    text = _text(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise P0HorseSourceBlocked(
            f"invalid_manual_supplement: {field} must be UTC"
        ) from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise P0HorseSourceBlocked(
            f"invalid_manual_supplement: {field} must be UTC"
        )
    return parsed


def manual_supplement_evidence_fingerprint(row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        raise P0HorseSourceBlocked(
            "invalid_manual_supplement: evidence row must be an object"
        )
    evidence = {
        "field_group": deepcopy(row.get("field_group")),
        "field_name": deepcopy(row.get("field_name")),
        "current_value": deepcopy(row.get("current_value")),
        "proposed_value": deepcopy(row.get("proposed_value")),
        "source": deepcopy(row.get("source")),
    }
    encoded = json.dumps(
        evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contains_manual_supplement_marker(value: Any) -> bool:
    if isinstance(value, dict):
        if (
            "manual_supplements" in value
            or "manual_supplement_outcomes" in value
            or value.get("entry_method") == "manual_review"
            or value.get("evidence_role") == "manual_supplement"
        ):
            return True
        return any(
            _contains_manual_supplement_marker(item)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_manual_supplement_marker(item) for item in value)
    return False


def _validate_canonical_json_value(value: Any) -> None:
    active_container_ids: set[int] = set()
    stack: list[tuple[str, Any, str, int]] = [
        ("enter", value, "$", 0)
    ]
    while stack:
        action, current, path, depth = stack.pop()
        if action == "exit":
            active_container_ids.remove(id(current))
            continue
        if type(current) in (dict, list):
            if depth > CANONICAL_JSON_MAX_DEPTH:
                raise P0HorseSourceBlocked(
                    "invalid_cache: canonical source payload exceeds "
                    f"maximum depth at {path}"
                )
            container_id = id(current)
            if container_id in active_container_ids:
                raise P0HorseSourceBlocked(
                    "invalid_cache: canonical source payload contains "
                    f"a circular reference at {path}"
                )
            active_container_ids.add(container_id)
            stack.append(("exit", current, path, depth))
            if type(current) is dict:
                for key, item in reversed(list(current.items())):
                    if not isinstance(key, str):
                        raise P0HorseSourceBlocked(
                            "invalid_cache: canonical source payload has a "
                            f"non-string object key at {path}"
                        )
                    stack.append(
                        ("enter", item, f"{path}.{key}", depth + 1)
                    )
            else:
                for index in range(len(current) - 1, -1, -1):
                    stack.append(
                        (
                            "enter",
                            current[index],
                            f"{path}[{index}]",
                            depth + 1,
                        )
                    )
            continue
        if current is None or isinstance(current, (str, bool, int)):
            continue
        if isinstance(current, float) and math.isfinite(current):
            continue
        raise P0HorseSourceBlocked(
            "invalid_cache: canonical source payload contains a non-JSON "
            f"value at {path}"
        )


def _copy_canonical_json_value(value: Any) -> Any:
    _validate_canonical_json_value(value)
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise P0HorseSourceBlocked(
            "invalid_cache: canonical source payload cannot be normalized"
        ) from exc


def reject_manual_supplements_from_canonical_source_payload(
    payload: dict[str, Any],
) -> None:
    if type(payload) is not dict:
        raise P0HorseSourceBlocked("invalid_cache: payload must be an object")
    _validate_canonical_json_value(payload)
    checked = _copy_canonical_json_value(payload)
    if (
        _contains_manual_supplement_marker(payload)
        or _contains_manual_supplement_marker(checked)
    ):
        raise P0HorseSourceBlocked(
            "invalid_cache: canonical source cache contains manual supplements"
        )


def load_reviewed_manual_supplements(
    manual_supplements_csv: str | Path,
    *,
    reviewed_candidates: list[dict[str, Any]],
    captured_bytes: bytes | None = None,
) -> dict[str, list[dict[str, Any]]]:
    path = Path(manual_supplements_csv)
    candidate_index = {
        _text(candidate.get("candidate_key")): candidate
        for candidate in reviewed_candidates
        if _text(candidate.get("candidate_key"))
    }
    try:
        source_bytes = (
            bytes(captured_bytes)
            if captured_bytes is not None
            else path.read_bytes()
        )
        input_file = io.StringIO(
            source_bytes.decode("utf-8-sig"),
            newline="",
        )
        reader = csv.DictReader(input_file)
        if tuple(reader.fieldnames or ()) != MANUAL_SUPPLEMENT_CSV_FIELDS:
            raise P0HorseSourceBlocked(
                "invalid_manual_supplement: CSV header mismatch"
            )
        raw_rows = list(reader)
    except (OSError, UnicodeDecodeError) as exc:
        raise P0HorseSourceBlocked(
            f"invalid_manual_supplement: CSV is unreadable: {path}"
        ) from exc

    output: dict[str, list[dict[str, Any]]] = {}
    approved_fields: set[tuple[str, str, str]] = set()
    for row_number, raw_row in enumerate(raw_rows, start=2):
        row = {
            field: _text(raw_row.get(field))
            for field in MANUAL_SUPPLEMENT_CSV_FIELDS
        }
        review_status = row["review_status"].casefold()
        if review_status not in MANUAL_SUPPLEMENT_REVIEW_STATUSES:
            raise P0HorseSourceBlocked(
                f"invalid_manual_supplement: row {row_number} review_status"
            )
        if review_status != "approved":
            continue

        candidate_key = row["candidate_key"]
        candidate = candidate_index.get(candidate_key)
        if candidate is None:
            raise P0HorseSourceBlocked(
                f"invalid_manual_supplement: row {row_number} unknown candidate_key"
            )
        if (
            row["region"] != _text(candidate.get("sample_region"))
            or _normalized(row["horse_name"])
            != _normalized(candidate.get("horse_name"))
        ):
            raise P0HorseSourceBlocked(
                f"invalid_manual_supplement: row {row_number} candidate mismatch"
            )
        field_group = row["field_group"]
        field_name = row["field_name"]
        if field_name not in MANUAL_SUPPLEMENT_FIELDS.get(
            field_group,
            frozenset(),
        ):
            raise P0HorseSourceBlocked(
                "invalid_manual_supplement: "
                f"row {row_number} unsupported field_group or field_name"
            )
        field_key = (candidate_key, field_group, field_name)
        if field_key in approved_fields:
            raise P0HorseSourceBlocked(
                f"invalid_manual_supplement: row {row_number} duplicate field"
            )
        approved_fields.add(field_key)
        if not row["proposed_value"]:
            raise P0HorseSourceBlocked(
                f"invalid_manual_supplement: row {row_number} proposed_value"
            )
        if (
            not row["source_name"]
            or not _http_url(row["source_url"])
        ):
            raise P0HorseSourceBlocked(
                f"invalid_manual_supplement: row {row_number} source"
            )
        if not row["entered_by"] or not row["reviewer"]:
            raise P0HorseSourceBlocked(
                f"invalid_manual_supplement: row {row_number} audit users"
            )
        if _normalized(row["entered_by"]) == _normalized(row["reviewer"]):
            raise P0HorseSourceBlocked(
                "invalid_manual_supplement: "
                f"row {row_number} entered_by and reviewer must be different"
            )
        _utc_datetime(row["reviewed_at"], field="reviewed_at")
        proposed_value: Any = row["proposed_value"]
        if field_group == "identity" and field_name == "birth_year":
            try:
                proposed_value = int(proposed_value)
            except ValueError as exc:
                raise P0HorseSourceBlocked(
                    f"invalid_manual_supplement: row {row_number} birth_year"
                ) from exc

        output.setdefault(candidate_key, []).append(
            {
                "field_group": field_group,
                "field_name": field_name,
                "current_value": row["current_value"],
                "proposed_value": proposed_value,
                "source": {
                    "name": row["source_name"],
                    "url": row["source_url"],
                    "external_horse_id": row["source_external_horse_id"],
                    "fetched_at": row["reviewed_at"],
                    "entry_method": "manual_review",
                    "entered_by": row["entered_by"],
                    "reviewer": row["reviewer"],
                    "field_group": field_group,
                    "field_name": field_name,
                    "evidence_role": "manual_supplement",
                    "evidence_note": row["evidence_note"],
                    "review_notes": row["review_notes"],
                },
            }
        )
    return output


def merge_reviewed_manual_supplements(
    primary_payload: dict[str, Any],
    manual_supplements: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = _copy_canonical_json_value(primary_payload)
    normalized_supplements = _copy_canonical_json_value(
        manual_supplements
    )
    if type(merged) is not dict:
        raise P0HorseSourceBlocked(
            "invalid_cache: primary payload must be an object"
        )
    if type(normalized_supplements) is not list:
        raise P0HorseSourceBlocked(
            "invalid_manual_supplement: rows must be an array"
        )
    primary_source = merged.get("source")
    if not isinstance(primary_source, dict):
        raise P0HorseSourceBlocked(
            "missing_source: primary source must be an object"
        )
    primary_provenance = _source_provenance(primary_source)
    provenance = (
        deepcopy(merged.get("field_provenance"))
        if isinstance(merged.get("field_provenance"), dict)
        else {}
    )
    for group_name in ("identity", "basic_profile", "pedigree"):
        group = merged.get(group_name)
        if not isinstance(group, dict):
            group = {}
            merged[group_name] = group
        for field, value in group.items():
            if value not in ("", None):
                provenance.setdefault(
                    f"{group_name}.{field}",
                    deepcopy(primary_provenance),
                )

    supplemental_sources = (
        deepcopy(merged.get("supplemental_sources"))
        if isinstance(merged.get("supplemental_sources"), list)
        else []
    )
    manual_raw_rows: list[dict[str, Any]] = []
    for supplement in normalized_supplements:
        if not isinstance(supplement, dict):
            raise P0HorseSourceBlocked(
                "invalid_manual_supplement: row must be an object"
            )
        field_group = _text(supplement.get("field_group"))
        field_name = _text(supplement.get("field_name"))
        if field_name not in MANUAL_SUPPLEMENT_FIELDS.get(
            field_group,
            frozenset(),
        ):
            raise P0HorseSourceBlocked(
                "invalid_manual_supplement: unsupported field_group or field_name"
            )
        source = supplement.get("source")
        if (
            not isinstance(source, dict)
            or source.get("entry_method") != "manual_review"
            or source.get("evidence_role") != "manual_supplement"
            or not _http_url(source.get("url"))
            or not _text(source.get("name"))
            or not _text(source.get("entered_by"))
            or not _text(source.get("reviewer"))
            or _normalized(source.get("entered_by"))
            == _normalized(source.get("reviewer"))
            or source.get("field_group") != field_group
            or source.get("field_name") != field_name
        ):
            raise P0HorseSourceBlocked(
                "invalid_manual_supplement: audit metadata"
            )
        _utc_datetime(source.get("fetched_at"), field="reviewed_at")
        proposed_value = supplement.get("proposed_value")
        if proposed_value in ("", None):
            raise P0HorseSourceBlocked(
                "invalid_manual_supplement: proposed_value"
            )
        group = merged[field_group]
        field_path = f"{field_group}.{field_name}"
        current_value = group.get(field_name)
        recorded_current_value = supplement.get("current_value")
        if (
            recorded_current_value not in ("", None)
            and _normalized(recorded_current_value)
            != _normalized(current_value)
        ):
            raise P0HorseSourceBlocked(
                f"stale_manual_supplement: {field_path}"
            )
        if current_value not in ("", None):
            if _normalized(current_value) != _normalized(proposed_value):
                raise P0HorseSourceBlocked(
                    f"source_conflict: {field_path}"
                )
            existing_source = provenance.get(field_path)
            audit_keys = (
                "name",
                "url",
                "external_horse_id",
                "fetched_at",
                "entry_method",
                "entered_by",
                "reviewer",
                "field_group",
                "field_name",
                "evidence_role",
                "evidence_note",
                "review_notes",
            )
            if (
                isinstance(existing_source, dict)
                and all(
                    _normalized(existing_source.get(key))
                    == _normalized(source.get(key))
                    for key in audit_keys
                )
            ):
                manual_raw_rows.append(
                    {
                        "field_group": field_group,
                        "field_name": field_name,
                        "current_value": deepcopy(current_value),
                        "proposed_value": deepcopy(proposed_value),
                        "status": "already_applied",
                        "reason": "",
                        "source": deepcopy(source),
                    }
                )
                continue
            raise P0HorseSourceBlocked(
                f"manual_target_not_empty: {field_path}"
            )
        group[field_name] = deepcopy(proposed_value)
        provenance[field_path] = deepcopy(source)
        supplemental_sources.append(deepcopy(source))
        manual_raw_rows.append(
            {
                "field_group": field_group,
                "field_name": field_name,
                "current_value": deepcopy(recorded_current_value),
                "proposed_value": deepcopy(proposed_value),
                "status": "applied",
                "reason": "",
                "source": deepcopy(source),
            }
        )

    merged["field_provenance"] = provenance
    merged["supplemental_sources"] = supplemental_sources
    raw_payload = (
        deepcopy(merged.get("raw_payload"))
        if isinstance(merged.get("raw_payload"), dict)
        else {}
    )
    raw_payload["manual_supplements"] = deepcopy(manual_raw_rows)
    merged["raw_payload"] = raw_payload
    merged["manual_supplement_outcomes"] = deepcopy(manual_raw_rows)
    return validate_p0_horse_source_cache(
        merged,
        allow_manual_supplements=True,
    )


def _require_supplemental_source(
    source: Any,
    *,
    allowed_source_names: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise P0HorseSourceBlocked(
            "invalid_supplemental_source: source must be an object"
        )
    source_name = _text(source.get("name"))
    if source_name not in allowed_source_names:
        raise P0HorseSourceBlocked(
            f"supplemental_provider_not_allowed: {source_name}"
        )
    if not _http_url(source.get("url")):
        raise P0HorseSourceBlocked(
            "invalid_supplemental_source: source URL"
        )
    fetched_at = _text(source.get("fetched_at"))
    try:
        fetched_time = datetime.fromisoformat(
            fetched_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise P0HorseSourceBlocked(
            "invalid_supplemental_source: fetched_at"
        ) from exc
    if fetched_time.utcoffset() != timezone.utc.utcoffset(fetched_time):
        raise P0HorseSourceBlocked(
            "invalid_supplemental_source: fetched_at"
        )
    return {
        key: deepcopy(source.get(key))
        for key in (
            "name",
            "url",
            "external_horse_id",
            "fetched_at",
        )
        if source.get(key) not in ("", None)
    }


def _merge_missing_source_group(
    target: dict[str, Any],
    incoming: Any,
    *,
    group_name: str,
    provenance: dict[str, dict[str, Any]],
    source: dict[str, Any],
) -> None:
    if incoming in (None, {}):
        return
    if not isinstance(incoming, dict):
        raise P0HorseSourceBlocked(
            f"invalid_supplemental_source: {group_name}"
        )
    for field, incoming_value in incoming.items():
        if incoming_value in ("", None):
            continue
        field_path = f"{group_name}.{field}"
        current_value = target.get(field)
        if current_value not in ("", None):
            if _normalized(current_value) != _normalized(incoming_value):
                raise P0HorseSourceBlocked(
                    f"source_conflict: {field_path}"
                )
            continue
        target[field] = deepcopy(incoming_value)
        provenance[field_path] = deepcopy(source)


def _require_supplemental_identity_matches_primary(
    *,
    primary_source: dict[str, Any],
    primary_identity: dict[str, Any],
    supplemental_source: dict[str, Any],
    supplemental_identity: dict[str, Any],
) -> None:
    same_provider = _normalized(primary_source.get("name")) == _normalized(
        supplemental_source.get("name")
    )
    primary_external_id = _text(primary_source.get("external_horse_id"))
    supplemental_external_id = _text(
        supplemental_source.get("external_horse_id")
    )
    if (
        same_provider
        and primary_external_id
        and supplemental_external_id
        and primary_external_id == supplemental_external_id
    ):
        return

    fields = ("horse_name", "sire_name", "dam_name", "birth_year")
    if any(
        primary_identity.get(field) in ("", None)
        or supplemental_identity.get(field) in ("", None)
        for field in fields
    ):
        raise P0HorseSourceBlocked(
            "supplemental_identity_incomplete: provider external ID or "
            "complete four-field identity required"
        )
    for field in fields:
        if _normalized(primary_identity[field]) != _normalized(
            supplemental_identity[field]
        ):
            raise P0HorseSourceBlocked(
                f"supplemental_identity_mismatch: {field}"
            )


def merge_p0_horse_source_payloads(
    primary_payload: dict[str, Any],
    supplemental_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = _copy_canonical_json_value(primary_payload)
    normalized_supplements = _copy_canonical_json_value(
        supplemental_payloads
    )
    if type(merged) is not dict:
        raise P0HorseSourceBlocked(
            "invalid_cache: primary payload must be an object"
        )
    if type(normalized_supplements) is not list:
        raise P0HorseSourceBlocked(
            "invalid_supplemental_source: payloads must be an array"
        )
    if (
        _contains_manual_supplement_marker(merged)
        or _contains_manual_supplement_marker(normalized_supplements)
    ):
        raise P0HorseSourceBlocked(
            "invalid_cache: automatic source merge contains manual supplements"
        )
    region = merged.get("region")
    adapter = REGION_ADAPTERS.get(region)
    if adapter is None:
        raise P0HorseSourceBlocked(
            "invalid_cache: unsupported primary region"
        )
    primary_source = merged.get("source")
    if not isinstance(primary_source, dict):
        raise P0HorseSourceBlocked(
            "missing_source: primary source must be an object"
        )
    primary_provenance = _source_provenance(primary_source)
    provenance: dict[str, dict[str, Any]] = {}
    for group_name in ("identity", "basic_profile", "pedigree"):
        group = merged.get(group_name)
        if not isinstance(group, dict):
            group = {}
            merged[group_name] = group
        for field, value in group.items():
            if value not in ("", None):
                provenance[f"{group_name}.{field}"] = deepcopy(
                    primary_provenance
                )

    supplemental_sources: list[dict[str, Any]] = []
    supplemental_raw_payloads: list[dict[str, Any]] = []
    for supplement in normalized_supplements:
        if not isinstance(supplement, dict):
            raise P0HorseSourceBlocked(
                "invalid_supplemental_source: payload must be an object"
            )
        if supplement.get("career") not in (None, {}):
            raise P0HorseSourceBlocked(
                "supplemental_career_not_allowed"
            )
        if supplement.get("region") not in (None, "", region):
            raise P0HorseSourceBlocked(
                "invalid_supplemental_source: region mismatch"
            )
        source = _require_supplemental_source(
            supplement.get("source"),
            allowed_source_names=adapter.source_names,
        )
        incoming_identity = supplement.get("identity")
        if (
            not isinstance(incoming_identity, dict)
            or not _text(incoming_identity.get("horse_name"))
        ):
            raise P0HorseSourceBlocked(
                "identity_incomplete: supplemental horse_name"
            )
        _require_supplemental_identity_matches_primary(
            primary_source=primary_source,
            primary_identity=merged["identity"],
            supplemental_source=source,
            supplemental_identity=incoming_identity,
        )
        _merge_missing_source_group(
            merged["identity"],
            incoming_identity,
            group_name="identity",
            provenance=provenance,
            source=_source_provenance(source),
        )
        _merge_missing_source_group(
            merged["basic_profile"],
            supplement.get("basic_profile"),
            group_name="basic_profile",
            provenance=provenance,
            source=_source_provenance(source),
        )
        _merge_missing_source_group(
            merged["pedigree"],
            supplement.get("pedigree"),
            group_name="pedigree",
            provenance=provenance,
            source=_source_provenance(source),
        )
        aliases = supplement.get("aliases")
        if aliases not in (None, []):
            if not isinstance(aliases, list):
                raise P0HorseSourceBlocked(
                    "invalid_supplemental_source: aliases"
                )
            merged.setdefault("aliases", []).extend(deepcopy(aliases))
        supplemental_sources.append(source)
        supplemental_raw_payloads.append(
            {
                "source": deepcopy(source),
                "raw_payload": deepcopy(supplement.get("raw_payload", {})),
            }
        )

    aliases = [
        alias
        for alias in merged.get("aliases", [])
        if isinstance(alias, dict) and _text(alias.get("name"))
    ]
    deduplicated_aliases: list[dict[str, Any]] = []
    seen_aliases: set[tuple[str, str]] = set()
    for alias in aliases:
        key = (
            _normalized(alias.get("name")),
            _normalized(alias.get("language")),
        )
        if key in seen_aliases:
            continue
        seen_aliases.add(key)
        deduplicated_aliases.append(deepcopy(alias))
    merged["aliases"] = deduplicated_aliases
    merged["field_provenance"] = provenance
    merged["supplemental_sources"] = supplemental_sources
    raw_payload = (
        deepcopy(merged.get("raw_payload"))
        if isinstance(merged.get("raw_payload"), dict)
        else {}
    )
    raw_payload["supplemental_sources"] = supplemental_raw_payloads
    merged["raw_payload"] = raw_payload
    return validate_p0_horse_source_cache(merged)


def validate_p0_horse_source_cache(
    payload: dict[str, Any],
    *,
    allow_manual_supplements: bool = False,
) -> dict[str, Any]:
    if type(payload) is not dict:
        raise P0HorseSourceBlocked("invalid_cache: payload must be an object")
    _validate_canonical_json_value(payload)
    if (
        not allow_manual_supplements
        and _contains_manual_supplement_marker(payload)
    ):
        raise P0HorseSourceBlocked(
            "invalid_cache: canonical source cache contains manual supplements"
        )
    checked = _copy_canonical_json_value(payload)
    if (
        not allow_manual_supplements
        and _contains_manual_supplement_marker(checked)
    ):
        raise P0HorseSourceBlocked(
            "invalid_cache: canonical source cache contains manual supplements"
        )
    if checked.get("schema_version") != SOURCE_CACHE_SCHEMA_VERSION:
        raise P0HorseSourceBlocked("invalid_cache: unsupported schema_version")
    region = checked.get("region")
    adapter = REGION_ADAPTERS.get(region)
    if adapter is None or checked.get("adapter_key") != adapter.key:
        raise P0HorseSourceBlocked("invalid_cache: region or adapter_key mismatch")

    source = checked.get("source")
    if not isinstance(source, dict):
        raise P0HorseSourceBlocked("missing_source: source must be an object")
    fetched_at = _text(source.get("fetched_at"))
    try:
        fetched_time = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise P0HorseSourceBlocked("missing_source: fetched_at is not UTC") from exc
    if (
        source.get("name") not in adapter.source_names
        or not _http_url(source.get("url"))
        or fetched_time.utcoffset() != timezone.utc.utcoffset(fetched_time)
    ):
        raise P0HorseSourceBlocked("missing_source: provider identity or provenance")

    identity = checked.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    external_horse_id = source.get("external_horse_id")
    has_provider_identity = (
        isinstance(external_horse_id, str)
        and bool(external_horse_id.strip())
    )
    identity_text_fields = ("horse_name", "sire_name", "dam_name")
    for field in identity_text_fields:
        value = identity.get(field)
        if value not in ("", None) and (
            not isinstance(value, str) or not value.strip()
        ):
            raise P0HorseSourceBlocked(
                f"identity_incomplete: {field} is invalid"
            )
    birth_year = identity.get("birth_year")
    if birth_year not in ("", None) and (
        isinstance(birth_year, bool)
        or not isinstance(birth_year, int)
        or not 1800 <= birth_year <= datetime.now(timezone.utc).year
    ):
        raise P0HorseSourceBlocked("identity_incomplete: birth_year is invalid")
    complete_identity = all(
        isinstance(identity.get(field), str)
        and bool(identity[field].strip())
        for field in identity_text_fields
    ) and isinstance(birth_year, int)
    if not has_provider_identity and not complete_identity:
        raise P0HorseSourceBlocked(
            "identity_incomplete: provider external ID or complete four-field identity"
        )

    basic_profile = checked.get("basic_profile")
    if not isinstance(basic_profile, dict):
        raise P0HorseSourceBlocked("missing_hard_fields: basic_profile")
    missing_basic = [
        field
        for field in REQUIRED_BASIC_PROFILE_FIELDS
        if not isinstance(basic_profile.get(field), str)
        or not basic_profile[field].strip()
    ]
    if missing_basic:
        raise P0HorseSourceBlocked(
            f"missing_hard_fields: {','.join(missing_basic)}"
        )
    try:
        parsed_birth_date = date.fromisoformat(
            basic_profile["birth_date"].strip()
        )
    except ValueError as exc:
        raise P0HorseSourceBlocked(
            "invalid_hard_field_format: birth_date"
        ) from exc
    if isinstance(birth_year, int) and parsed_birth_date.year != birth_year:
        raise P0HorseSourceBlocked(
            "identity_mismatch: birth_date and birth_year"
        )

    pedigree = checked.get("pedigree")
    if not isinstance(pedigree, dict):
        raise P0HorseSourceBlocked("missing_two_generation_pedigree")
    missing_pedigree = [
        field
        for field in REQUIRED_PEDIGREE_FIELDS
        if not isinstance(pedigree.get(field), str)
        or not pedigree[field].strip()
    ]
    if missing_pedigree:
        raise P0HorseSourceBlocked(
            f"missing_two_generation_pedigree: {','.join(missing_pedigree)}"
        )

    aliases = checked.get("aliases")
    if not isinstance(aliases, list) or not any(
        isinstance(alias, dict)
        and isinstance(alias.get("name"), str)
        and bool(alias["name"].strip())
        for alias in aliases
    ):
        raise P0HorseSourceBlocked("missing_aliases")

    career = checked.get("career")
    if not isinstance(career, dict) or "source_start_count" not in career:
        raise P0HorseSourceBlocked("missing_source_start_count")
    source_start_count = career.get("source_start_count")
    if (
        isinstance(source_start_count, bool)
        or not isinstance(source_start_count, int)
        or source_start_count < 0
    ):
        raise P0HorseSourceBlocked("invalid_source_start_count")
    if (
        career.get("record_authority_status")
        not in HorseCareerRecordAuthorityStatus.values
    ):
        raise P0HorseSourceBlocked("invalid_record_authority_status")
    if not _text(career.get("official_start_count_source")):
        raise P0HorseSourceBlocked("missing_official_start_count_source")
    if not _http_url(career.get("official_start_count_source_url")):
        raise P0HorseSourceBlocked("missing_official_start_count_source_url")
    verified_at = _text(career.get("official_start_count_verified_at"))
    try:
        verified_time = datetime.fromisoformat(
            verified_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise P0HorseSourceBlocked(
            "missing_official_start_count_verified_at"
        ) from exc
    if verified_time.utcoffset() is None:
        raise P0HorseSourceBlocked(
            "missing_official_start_count_verified_at"
        )
    records = career.get("records")
    if not isinstance(records, list) or (
        source_start_count > 0 and not records
    ):
        raise P0HorseSourceBlocked("partial_career: complete records are missing")
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or any(
            not isinstance(record.get(field), str)
            or not record[field].strip()
            for field in (
                "race_name",
                "race_date",
                "racecourse",
                "finish",
            )
        ) or not _http_url(record.get("source_url")):
            raise P0HorseSourceBlocked(
                f"partial_career: record {index} lacks core evidence"
            )
        race_date_text = record["race_date"].strip()
        if not re.fullmatch(r"\d{4}", race_date_text):
            try:
                date.fromisoformat(race_date_text)
            except ValueError as exc:
                raise P0HorseSourceBlocked(
                    f"partial_career: record {index} has invalid race_date"
                ) from exc
        if _text(record.get("finish")) == "**":
            raise P0HorseSourceBlocked(
                f"partial_career: record {index} has an unknown finish marker"
            )
    collected_start_count = sum(
        _is_actual_start(record.get("finish")) for record in records
    )
    if collected_start_count != source_start_count:
        raise P0HorseSourceBlocked(
            "partial_career: source_start_count does not match complete records"
        )
    return checked


class _BaseSourceClient:
    record_authority_status = "unknown"

    region = ""
    provider_name = ""
    allowed_hosts: frozenset[str] = frozenset()
    user_agent = "umanewsbot/1.0 (+https://umafans.run; low-frequency data import)"

    def __init__(
        self,
        transport: P0HorseTransport,
        *,
        manual_supplements_by_candidate: (
            dict[str, list[dict[str, Any]]] | None
        ) = None,
        budget_hook: Any = None,
        retry_max_attempts: int | None = None,
        retry_backoff_base_seconds: float | None = None,
        sleep_func: Any = None,
    ):
        if transport is None or not callable(getattr(transport, "get", None)):
            raise P0HorseSourceBlocked("transport_required")
        self.transport = transport
        self.manual_supplements_by_candidate = deepcopy(
            manual_supplements_by_candidate or {}
        )
        self.budget_hook = budget_hook
        self._retry_max_attempts = retry_max_attempts
        self._retry_backoff_base_seconds = retry_backoff_base_seconds
        self._sleep_func = sleep_func or time.sleep
        self._candidate_keys: set[str] = set()
        self._request_count = 0
        self._budgeted_urls: set[str] = set()
        self._last_request_at: float | None = None
        self.last_request_count = 0

    def _effective_retry_max_attempts(self) -> int:
        if self._retry_max_attempts is not None:
            return max(1, int(self._retry_max_attempts))
        from django.conf import settings

        return max(
            1,
            int(getattr(settings, "HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS", 3)),
        )

    def _effective_retry_backoff_base(self) -> float:
        if self._retry_backoff_base_seconds is not None:
            return max(0.0, float(self._retry_backoff_base_seconds))
        from django.conf import settings

        return max(
            0.0,
            float(
                getattr(
                    settings,
                    "HORSE_PROFILE_COMPLETION_RETRY_BACKOFF_BASE_SECONDS",
                    30.0,
                )
            ),
        )

    def fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        payload = self.fetch_source_payload(request)
        reject_manual_supplements_from_canonical_source_payload(
            payload
        )
        payload = self.apply_manual_supplements(payload, request)
        return validate_p0_horse_source_cache(
            payload,
            allow_manual_supplements=bool(
                self.manual_supplements_by_candidate.get(
                    request.candidate_key
                )
            ),
        )

    def has_manual_supplements(
        self,
        request: P0HorseCompletionRequest,
    ) -> bool:
        return bool(
            self.manual_supplements_by_candidate.get(
                request.candidate_key
            )
        )

    def fetch_source_payload(
        self,
        request: P0HorseCompletionRequest,
    ) -> dict[str, Any]:
        if not request.allow_network:
            raise P0HorseCompletionNetworkDisabled(
                "P0 horse completion network access is disabled"
            )
        provider = _normalized(request.candidate_source_name)
        external_id = _text(request.external_horse_id)
        candidate_key = (
            f"{provider}:{external_id}"
            if provider and external_id
            else _text(request.candidate_key) or _normalized(request.horse_name)
        )
        if (
            candidate_key not in self._candidate_keys
            and len(self._candidate_keys) >= request.batch_limit
        ):
            raise P0HorseSourceBlocked("batch_limit_exceeded")
        self._candidate_keys.add(candidate_key)
        self._request_count = 0
        self._budgeted_urls = set()
        try:
            return self._fetch(request)
        finally:
            self.last_request_count = self._request_count

    def apply_manual_supplements(
        self,
        payload: dict[str, Any],
        request: P0HorseCompletionRequest,
    ) -> dict[str, Any]:
        manual_supplements = self.manual_supplements_by_candidate.get(
            request.candidate_key,
            [],
        )
        if not manual_supplements:
            return payload
        return merge_reviewed_manual_supplements(
            payload,
            manual_supplements,
        )

    def _validated_source_url(self, value: Any) -> str:
        source_url = _text(value)
        parsed = urlparse(source_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise P0HorseSourceBlocked("unapproved_source_url") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname.casefold() not in self.allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise P0HorseSourceBlocked("unapproved_source_url")
        return source_url

    def _get(self, url: str, request: P0HorseCompletionRequest) -> Any:
        max_attempts = self._effective_retry_max_attempts()
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._get_once(url, request)
            except P0HorseSourceBlocked as exc:
                if not exc.transient or attempt >= max_attempts:
                    raise
                backoff = self._effective_retry_backoff_base() * (2 ** (attempt - 1))
                if exc.retry_after is not None:
                    backoff = max(
                        backoff,
                        min(float(exc.retry_after), RETRY_AFTER_CAP_SECONDS),
                    )
                if backoff > 0:
                    self._sleep_func(backoff)

    def _get_once(self, url: str, request: P0HorseCompletionRequest) -> Any:
        current_url = self._validated_source_url(url)
        for _redirect_count in range(5):
            if current_url not in self._budgeted_urls:
                if self._request_count >= request.request_budget:
                    raise P0HorseSourceBlocked("request_budget_exceeded")
                self._request_count += 1
                self._budgeted_urls.add(current_url)
            if (
                self._last_request_at is not None
                and request.request_interval_seconds > 0
            ):
                elapsed = time.monotonic() - self._last_request_at
                delay = max(0.0, request.request_interval_seconds - elapsed)
                if delay:
                    time.sleep(delay)
            self._last_request_at = time.monotonic()
            if self.budget_hook is not None:
                self.budget_hook(current_url)
            try:
                response = self.transport.get(
                    current_url,
                    timeout=20,
                    headers={"User-Agent": self.user_agent},
                    allow_redirects=False,
                )
            except P0HorseSourceBlocked:
                raise
            except Exception as exc:
                raise P0HorseSourceBlocked(
                    f"transport_error: {exc}", transient=True
                ) from exc
            response_url = _text(getattr(response, "url", "")) or current_url
            response_url = self._validated_source_url(response_url)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if 300 <= status_code < 400:
                headers = getattr(response, "headers", None)
                header_get = getattr(headers, "get", None)
                location = header_get("Location") if callable(header_get) else ""
                if not location:
                    raise P0HorseSourceBlocked(
                        f"http_error: HTTP {status_code} without Location",
                        status_code=status_code,
                    )
                current_url = self._validated_source_url(
                    urljoin(response_url, _text(location))
                )
                continue
            if status_code == 429:
                headers = getattr(response, "headers", None)
                header_get = getattr(headers, "get", None)
                retry_after_text = header_get("Retry-After") if callable(header_get) else ""
                try:
                    retry_after = float(retry_after_text) if retry_after_text else None
                except (TypeError, ValueError):
                    retry_after = None
                raise P0HorseSourceBlocked(
                    "rate_limited: HTTP 429",
                    status_code=429,
                    transient=True,
                    retry_after=retry_after,
                )
            if status_code >= 400 or status_code == 0:
                raise P0HorseSourceBlocked(
                    f"http_error: HTTP {status_code}",
                    status_code=status_code or None,
                    transient=status_code >= 500 or status_code == 0,
                )
            response_text = str(getattr(response, "text", "") or "")
            if re.search(
                r"<(?:form|input)\b[^>]*(?:id=[\"']?login|name=[\"']password[\"']?)",
                response_text,
                re.IGNORECASE,
            ):
                raise P0HorseSourceBlocked("login_wall")
            return response
        raise P0HorseSourceBlocked("too_many_redirects")

    def _payload(
        self,
        *,
        request: P0HorseCompletionRequest,
        source_url: str,
        external_horse_id: str,
        horse_name: str,
        identity: dict[str, Any],
        basic_profile: dict[str, Any],
        pedigree: dict[str, Any],
        records: list[dict[str, Any]],
        source_start_count: int,
        raw_payload: dict[str, Any],
        aliases: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fetched_at = _utc_now()
        return {
            "schema_version": SOURCE_CACHE_SCHEMA_VERSION,
            "adapter_key": REGION_ADAPTERS[self.region].key,
            "region": self.region,
            "source": {
                "name": self.provider_name,
                "url": source_url,
                "external_horse_id": external_horse_id,
                "fetched_at": fetched_at,
            },
            "identity": {
                "horse_name": horse_name,
                "sire_name": pedigree.get("sire", ""),
                "dam_name": pedigree.get("dam", ""),
                "birth_year": identity.get("birth_year"),
            },
            "basic_profile": basic_profile,
            "pedigree": pedigree,
            "aliases": aliases
            or [{"name": horse_name, "language": "", "is_original": True}],
            "career": {
                "source_start_count": source_start_count,
                "official_or_source_start_count": source_start_count,
                "official_start_count_source": self.provider_name,
                "official_start_count_source_url": source_url,
                "official_start_count_verified_at": fetched_at,
                "record_authority_status": self.record_authority_status,
                "records": records,
            },
            "raw_payload": raw_payload,
        }

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        raise NotImplementedError


class _JBISClient(_BaseSourceClient):
    region = RacingRegion.JAPAN
    provider_name = "jbis"
    record_authority_status = "source_records_verified"
    allowed_hosts = frozenset({"www.jbis.or.jp"})
    base_url = "https://www.jbis.or.jp"

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        search_url = (
            f"{self.base_url}/horse/result/"
            f"?keyword={quote_plus(request.horse_name)}&match=exact"
        )
        search = self._get(search_url, request)
        search_soup = BeautifulSoup(search.text, "html.parser")
        results = [
            link
            for link in search_soup.select(
                '.search-result a[href], '
                '.data-6-1 tr td:first-child a[href*="/horse/"], '
                '.data-6-1 .jc-between > a[href*="/horse/"]'
            )
            if re.fullmatch(r"/horse/[^/]+/?", _text(link.get("href")))
        ]
        if len(results) != 1:
            reason = "identity_not_found" if not results else "ambiguous_identity"
            raise P0HorseSourceBlocked(reason)
        result_link = results[0]
        search_name = _text(result_link.get_text(" ", strip=True))
        search_summary = _adjacent_search_summary(result_link)
        search_identity: dict[str, Any]
        if search_summary:
            search_identity = _parse_search_identity_summary(
                search_summary,
                jbis_metadata=True,
            )
        else:
            row = result_link.find_parent("tr")
            if row is not None:
                cells = [
                    _text(cell.get_text(" ", strip=True))
                    for cell in row.find_all(["th", "td"])
                ]
            else:
                container = result_link
                while (
                    container.parent is not None
                    and "data-6-1" not in container.parent.get("class", [])
                ):
                    container = container.parent
                cells = [
                    _text(child.get_text(" ", strip=True))
                    for child in container.find_all("div", recursive=False)
                ]
            if len(cells) < 6:
                raise P0HorseSourceBlocked(
                    "identity_incomplete: JBIS search result columns"
                )
            search_identity = {
                "birth_year": _year(cells[1]),
                "sire_name": cells[-3] if row is None else cells[4],
                "dam_name": cells[-2] if row is None else cells[5],
            }
        profile_url = urljoin(self.base_url, result_link["href"])
        match = re.search(r"/horse/([^/]+)/?", profile_url)
        external_id = match.group(1) if match else ""
        if not external_id:
            raise P0HorseSourceBlocked("identity_not_found: missing JBIS ID")

        profile = self._get(profile_url, request)
        profile_soup = BeautifulSoup(profile.text, "html.parser")
        values = _dl_values(profile_soup)
        pedigree = _pedigree_from_roles(profile_soup)
        pedigree_grid = profile_soup.select_one(".data-3-2")
        pedigree_rows = (
            pedigree_grid.select(".data-3__items") if pedigree_grid else []
        )
        if len(pedigree_rows) >= 2:
            sire_links = pedigree_rows[0].select('a[href*="/horse/"]')
            dam_links = pedigree_rows[1].select('a[href*="/horse/"]')
            if len(sire_links) >= 3 and len(dam_links) >= 3:
                pedigree = {
                    "sire": _text(sire_links[0].get_text(" ", strip=True)),
                    "dam": _text(dam_links[0].get_text(" ", strip=True)),
                    "sire_sire": _text(sire_links[1].get_text(" ", strip=True)),
                    "sire_dam": _text(sire_links[2].get_text(" ", strip=True)),
                    "dam_sire": _text(dam_links[1].get_text(" ", strip=True)),
                    "dam_dam": _text(dam_links[2].get_text(" ", strip=True)),
                }
        name = _text(
            profile_soup.find("h1").get_text(" ", strip=True)
            if profile_soup.find("h1")
            else ""
        )
        english_name = _field(values, "英字表記") or _text(
            profile_soup.select_one(".hdg1-search__sub").get_text(" ", strip=True)
            if profile_soup.select_one(".hdg1-search__sub")
            else ""
        )
        _require_names_in_profile_aliases(
            request_name=request.horse_name,
            search_name=search_name,
            profile_aliases=[name, english_name],
        )
        birth_text = _field(values, "生年月日")
        birth_date = _iso_date(birth_text)
        _require_complete_identity(
            horse_name=name,
            sire_name=pedigree.get("sire"),
            dam_name=pedigree.get("dam"),
            birth_year=_year(birth_text),
        )
        _require_search_identity_matches_profile(
            search_identity,
            sire_name=pedigree.get("sire"),
            dam_name=pedigree.get("dam"),
            birth_year=_year(birth_text),
        )
        record_link = profile_soup.select_one('a[href*="/record/"]')
        record_url = (
            urljoin(profile_url, record_link["href"])
            if record_link
            else urljoin(profile_url.rstrip("/") + "/", "record/")
        )
        record = self._get(record_url, request)
        record_soup = BeautifulSoup(record.text, "html.parser")
        summary = _text(
            record_soup.select_one(".record-summary").get_text(" ", strip=True)
            if record_soup.select_one(".record-summary")
            else record_soup.find("h2").get_text(" ", strip=True)
            if record_soup.find("h2")
            else ""
        )
        count_match = re.search(
            r"(?:出走\s*(\d+)\s*回|(\d+)\s*戦中\s*(\d+)\s*戦)",
            summary,
        )
        if not count_match:
            raise P0HorseSourceBlocked("missing_source_start_count")
        records: list[dict[str, Any]] = []
        for html_row in record_soup.select("#career-records tr[data-race-id]"):
            cells = html_row.find_all("td")
            if len(cells) < 5:
                continue
            link = html_row.find("a", href=True)
            records.append(
                {
                    "external_race_id": _text(html_row.get("data-race-id")),
                    "external_result_id": _text(html_row.get("data-result-id")),
                    "race_date": _text(cells[0].get_text(" ", strip=True)),
                    "racecourse": _text(cells[1].get_text(" ", strip=True)),
                    "race_name": _text(cells[2].get_text(" ", strip=True)),
                    "finish": _text(cells[3].get_text(" ", strip=True)),
                    "distance_text": _text(cells[4].get_text(" ", strip=True)),
                    "source_url": (
                        urljoin(getattr(record, "url", record_url), link["href"])
                        if link
                        else getattr(record, "url", record_url)
                    ),
                }
            )
        for html_row in record_soup.select(".data-18-1 .record-row"):
            link = html_row.select_one('.race-name a[href], a[href*="/race/"]')
            race_url = (
                urljoin(getattr(record, "url", record_url), link["href"])
                if link
                else getattr(record, "url", record_url)
            )
            records.append(
                {
                    "external_race_id": _text(
                        html_row.get("data-race-id")
                    ) or _id_from_race_url(race_url),
                    "external_result_id": _text(
                        html_row.get("data-result-id")
                    ),
                    "race_date": _iso_date(
                        html_row.select_one(".date").get_text(" ", strip=True)
                        if html_row.select_one(".date")
                        else ""
                    ),
                    "racecourse": _text(
                        html_row.select_one(".racecourse").get_text(" ", strip=True)
                        if html_row.select_one(".racecourse")
                        else ""
                    ),
                    "race_name": _text(
                        html_row.select_one(".race-name").get_text(" ", strip=True)
                        if html_row.select_one(".race-name")
                        else ""
                    ),
                    "finish": _text(
                        html_row.select_one(".finish").get_text(" ", strip=True)
                        if html_row.select_one(".finish")
                        else ""
                    ),
                    "distance_text": _text(
                        html_row.select_one(".distance").get_text(" ", strip=True)
                        if html_row.select_one(".distance")
                        else ""
                    ),
                    "source_url": race_url,
                }
            )
        grid = record_soup.select_one(".data-6-5")
        if grid is not None:
            for html_row in grid.find_all("div", recursive=False)[1:]:
                cells = html_row.find_all("div", recursive=False)
                if len(cells) < 6:
                    continue
                link = html_row.select_one('a[href*="/race/result/"]')
                race_url = (
                    urljoin(getattr(record, "url", record_url), link["href"])
                    if link
                    else getattr(record, "url", record_url)
                )
                finish = _text(cells[3].get_text(" ", strip=True))
                if finish == "**" and len(cells) >= 13:
                    status = unicodedata.normalize(
                        "NFKC",
                        _text(cells[12].get_text(" ", strip=True)),
                    )
                    if status == "除外":
                        finish = "withdrawn"
                    elif status == "取消":
                        finish = "scratched"
                records.append(
                    {
                        "external_race_id": _id_from_race_url(race_url),
                        "external_result_id": "",
                        "race_date": _iso_date(cells[0].get_text(" ", strip=True)),
                        "racecourse": _text(cells[1].get_text(" ", strip=True)),
                        "race_name": _text(cells[2].get_text(" ", strip=True)),
                        "finish": finish,
                        "distance_text": _text(cells[5].get_text(" ", strip=True)),
                        "source_url": race_url,
                    }
                )
        source_start_count = next(
            int(value)
            for value in count_match.groups()
            if value is not None
        )
        return self._payload(
            request=request,
            source_url=getattr(profile, "url", profile_url),
            external_horse_id=external_id,
            horse_name=name,
            identity={"birth_year": _year(birth_text)},
            basic_profile={
                "country": (
                    _field(values, "生産国")
                    or ("日本" if _field(values, "産地") else "")
                ),
                "sex": _field(values, "性別"),
                "color": _field(values, "毛色"),
                "birth_date": birth_date,
                "owner_name": _field(values, "馬主"),
                "trainer_name": _field(values, "調教師"),
                "breeder_name": _field(values, "生産牧場"),
            },
            pedigree=pedigree,
            records=records,
            source_start_count=source_start_count,
            raw_payload={
                "search_html": search.text,
                "profile_html": profile.text,
                "record_html": record.text,
            },
            aliases=[
                {"name": name, "language": "ja", "is_original": True},
                {
                    "name": english_name,
                    "language": "en",
                    "is_original": False,
                },
            ],
        )


_NETKEIBA_COUNTRY_BY_MARK = {
    "米": "美国",
    "英": "英国",
    "愛": "爱尔兰",
    "仏": "法国",
    "豪": "澳大利亚",
    "新": "新西兰",
    "独": "德国",
    "加": "加拿大",
    "伊": "意大利",
    "韓": "韩国",
    "日": "日本",
}
_NETKEIBA_STATUS_MAP = {
    "取消": "scratched",
    "取": "scratched",
    "除外": "withdrawn",
    "除": "withdrawn",
    "中止": "did_not_finish",
    "中": "did_not_finish",
    "失格": "disqualified",
    "失": "disqualified",
}
_NETKEIBA_NONSTART_STATUSES = {"scratched", "withdrawn"}
_NETKEIBA_COLORS = (
    "黒鹿毛", "青鹿毛", "栃栗毛", "尾花栗毛",
    "鹿毛", "青毛", "芦毛", "栗毛", "白毛",
)
_NETKEIBA_JRA_VENUE_RE = re.compile(
    r"^\d*(?:東京|中山|京都|阪神|新潟|中京|札幌|函館|福島|小倉)\d*$"
)
_NETKEIBA_NAR_VENUE_RE = re.compile(
    r"^\d*(?:大井|川崎|船橋|浦和|盛岡|水沢|金沢|笠松|名古屋|園田|姫路|高知|佐賀|帯広|門別)\d*$"
)
_NETKEIBA_PEDIGREE_CELLS = {
    "sire": (0, 0),
    "sire_sire": (0, 1),
    "sire_dam": (8, 0),
    "dam": (16, 0),
    "dam_sire": (16, 1),
    "dam_dam": (24, 0),
}


def _netkeiba_pedigree_name(value: Any) -> str:
    """Strip country marks, year, color and [血統]/[産駒] markers."""
    text = _text(value)
    text = re.split(r"[\[（(]|\d{4}", text, maxsplit=1)[0]
    return text.strip(" 　")


def _netkeiba_japanese_date(value: Any) -> str:
    text = _text(value)
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if not match:
        return _iso_date(text)
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _netkeiba_page_text(response: Any) -> str:
    """netkeiba serves EUC-JP without a charset header; requests defaults to
    ISO-8859-1, so ``.text`` is mojibake. Decode the raw bytes explicitly."""
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return content.decode("euc-jp", errors="replace")
    return str(getattr(response, "text", "") or "")


class _NetkeibaClient(_BaseSourceClient):
    """Fetch horses by netkeiba ID directly — no name search, no ambiguity."""

    region = RacingRegion.JAPAN
    provider_name = "netkeiba"
    record_authority_status = "source_records_verified"
    allowed_hosts = frozenset({"db.netkeiba.com"})
    base_url = "https://db.netkeiba.com"

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        if (
            _normalized(request.candidate_source_name) != "netkeiba"
            or not _text(request.external_horse_id)
        ):
            raise P0HorseSourceBlocked("provider_bound_identity_required: netkeiba")
        horse_id = _text(request.external_horse_id)
        if not horse_id.isdigit():
            raise P0HorseSourceBlocked("provider_bound_identity_required: netkeiba")
        profile_url = f"{self.base_url}/horse/{horse_id}/"
        result_url = f"{self.base_url}/horse/result/{horse_id}/"
        pedigree_url = f"{self.base_url}/horse/ped/{horse_id}/"
        profile = self._get(profile_url, request)
        result = self._get(result_url, request)
        pedigree_page = self._get(pedigree_url, request)

        profile_soup = BeautifulSoup(_netkeiba_page_text(profile), "html.parser")
        name, english_name, sex, color = self._parse_title(profile_soup)
        if not name:
            raise P0HorseSourceBlocked("netkeiba_profile_structure: title")
        values = self._parse_profile_table(profile_soup)
        birth_date = _netkeiba_japanese_date(values.get("生年月日"))
        if not birth_date:
            raise P0HorseSourceBlocked("netkeiba_profile_structure: birth_date")
        source_start_count = self._parse_career_total(values.get("通算成績"))
        pedigree = self._parse_pedigree(
            BeautifulSoup(_netkeiba_page_text(pedigree_page), "html.parser")
        )
        records = self._parse_records(
            BeautifulSoup(_netkeiba_page_text(result), "html.parser"),
            result_url=result_url,
        )
        payload = self._payload(
            request=request,
            source_url=getattr(profile, "url", profile_url),
            external_horse_id=horse_id,
            horse_name=name,
            identity={"birth_year": _year(birth_date)},
            basic_profile={
                "country": self._parse_country(values.get("産地")),
                "sex": sex,
                "color": color,
                "birth_date": birth_date,
                "owner_name": _text(values.get("馬主")),
                "trainer_name": re.sub(
                    r"[（(][^）)]*[）)]", "", _text(values.get("調教師"))
                ).strip(),
                "breeder_name": _text(values.get("生産者")),
            },
            pedigree=pedigree,
            records=records,
            source_start_count=source_start_count,
            raw_payload={
                "profile_html": _netkeiba_page_text(profile),
                "result_html": _netkeiba_page_text(result),
                "pedigree_html": _netkeiba_page_text(pedigree_page),
            },
            aliases=[
                {"name": name, "language": "ja", "is_original": True},
                *(
                    [{"name": english_name, "language": "en", "is_original": False}]
                    if english_name
                    else []
                ),
            ],
        )
        payload["source"]["parser_version"] = NETKEIBA_PARSER_VERSION
        return payload

    def _parse_title(self, soup) -> tuple[str, str, str, str]:
        title = soup.select_one(".horse_title")
        if title is None:
            return "", "", "", ""
        heading = title.select_one("h1")
        name = re.sub(r"[（(][^）)]*[）)]", "", _text(heading.get_text() if heading else "")).strip()
        line = _text(title.get_text(" ", strip=True))
        heading_text = _text(heading.get_text(" ", strip=True)) if heading else ""
        remainder = line[len(heading_text):].strip(" 　") if heading_text else line
        color_alternation = "|".join(_NETKEIBA_COLORS)
        color_match = re.search(rf"(?P<color>{color_alternation})$", remainder)
        if not color_match:
            raise P0HorseSourceBlocked("netkeiba_profile_structure: title_color")
        color = color_match.group("color")
        before_color = remainder[: color_match.start()].strip(" 　")
        sex_match = re.search(r"(?P<sex>セン|牡|牝|セ)(?:\d+歳)?$", before_color)
        if not sex_match:
            raise P0HorseSourceBlocked("netkeiba_profile_structure: title_sex")
        sex = sex_match.group("sex")
        before_sex = before_color[: sex_match.start()].strip(" 　")
        status_match = re.search(
            r"(?P<status>登録抹消|現役|引退|繁殖|抹消)$", before_sex
        )
        if not status_match:
            raise P0HorseSourceBlocked("netkeiba_profile_structure: title_status")
        english_name = before_sex[: status_match.start()].strip(" 　")
        return name, english_name, sex, color

    def _parse_profile_table(self, soup) -> dict[str, str]:
        table = soup.select_one("table.db_prof_table")
        if table is None:
            raise P0HorseSourceBlocked("netkeiba_profile_structure: db_prof_table")
        values: dict[str, str] = {}
        for row in table.select("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                values[_text(cells[0].get_text(" ", strip=True))] = _text(
                    cells[1].get_text(" ", strip=True)
                )
        return values

    def _parse_country(self, mark: Any) -> str:
        text = _text(mark)
        if not text:
            raise P0HorseSourceBlocked("netkeiba_profile_structure: country")
        mapped = _NETKEIBA_COUNTRY_BY_MARK.get(text)
        if mapped:
            return mapped
        # multi-character values are domestic prefectures/regions (e.g. 北海道);
        # an unknown single-character country mark must fail closed, not be
        # silently mislabeled 日本
        if len(text) == 1:
            raise P0HorseSourceBlocked(
                f"netkeiba_profile_structure: unknown country mark {text}"
            )
        return "日本"

    def _parse_career_total(self, value: Any) -> int:
        match = re.search(r"(\d+)\s*戦", _text(value))
        if not match:
            raise P0HorseSourceBlocked("missing_source_start_count")
        return int(match.group(1))

    def _parse_pedigree(self, soup) -> dict[str, str]:
        table = soup.select_one("table.blood_table")
        if table is None:
            raise P0HorseSourceBlocked("netkeiba_pedigree_structure: blood_table")
        rows = table.select("tr")
        pedigree: dict[str, str] = {}
        for field, (row_index, cell_index) in _NETKEIBA_PEDIGREE_CELLS.items():
            if row_index >= len(rows):
                raise P0HorseSourceBlocked(
                    f"netkeiba_pedigree_structure: row {row_index}"
                )
            cells = rows[row_index].find_all(["th", "td"])
            if cell_index >= len(cells):
                raise P0HorseSourceBlocked(
                    f"netkeiba_pedigree_structure: cell {row_index}/{cell_index}"
                )
            pedigree[field] = _netkeiba_pedigree_name(
                cells[cell_index].get_text(" ", strip=True)
            )
        return pedigree

    def _parse_records(self, soup, *, result_url: str) -> list[dict[str, Any]]:
        table = soup.select_one("table.db_h_race_results")
        if table is None:
            raise P0HorseSourceBlocked("netkeiba_result_structure: db_h_race_results")
        records: list[dict[str, Any]] = []
        for row in table.select("tr"):
            cells = row.find_all("td")
            if len(cells) < 19:
                continue
            race_date = _iso_date(cells[0].get_text(" ", strip=True))
            venue = _text(cells[1].get_text(" ", strip=True))
            race_name = _text(cells[4].get_text(" ", strip=True))
            finish_raw = _text(cells[11].get_text(" ", strip=True))
            result_status = _NETKEIBA_STATUS_MAP.get(finish_raw, "")
            overseas = not (
                _NETKEIBA_JRA_VENUE_RE.match(venue)
                or _NETKEIBA_NAR_VENUE_RE.match(venue)
            )
            link = cells[4].find("a", href=True)
            records.append(
                {
                    "external_race_id": "",
                    "external_result_id": "",
                    "race_date": race_date,
                    "racecourse": venue,
                    "race_name": race_name,
                    "finish": result_status or finish_raw,
                    "result_status": result_status,
                    "distance_text": _text(cells[14].get_text(" ", strip=True)),
                    "horse_number": _text(cells[8].get_text(" ", strip=True)),
                    "jockey_name": _text(cells[12].get_text(" ", strip=True)),
                    "carried_weight": _text(cells[13].get_text(" ", strip=True)),
                    "going": _text(cells[16].get_text(" ", strip=True)),
                    "finish_time": _text(cells[18].get_text(" ", strip=True)),
                    "is_overseas": overseas,
                    "source_url": (
                        urljoin(result_url, link["href"]) if link else result_url
                    ),
                }
            )
        return records


class _JapanDispatcherClient(_BaseSourceClient):
    """Dispatch japan candidates: netkeiba ID fetch when the candidate carries
    a netkeiba identity, JBIS name search otherwise. The dispatcher's own
    fetch_source_payload enforces the region batch_limit once per run, so the
    region cap stays 1x total; sub-client caps are unreachable in practice.
    """

    region = RacingRegion.JAPAN
    provider_name = "japan_dispatch"
    allowed_hosts = frozenset({"www.jbis.or.jp", "db.netkeiba.com"})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._netkeiba = _NetkeibaClient(*args, **kwargs)
        self._jbis = _JBISClient(*args, **kwargs)
        self._active: _BaseSourceClient = self._jbis

    def has_manual_supplements(self, request: P0HorseCompletionRequest) -> bool:
        if _normalized(request.candidate_source_name) == "netkeiba":
            return self._netkeiba.has_manual_supplements(request)
        return self._jbis.has_manual_supplements(request)

    def apply_manual_supplements(self, payload, request):
        return self._active.apply_manual_supplements(payload, request)

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        self._active = (
            self._netkeiba
            if _normalized(request.candidate_source_name) == "netkeiba"
            else self._jbis
        )
        try:
            return self._active.fetch_source_payload(request)
        finally:
            # the base wrapper overwrites last_request_count from
            # self._request_count after _fetch returns, so mirror both
            self._request_count = self._active._request_count
            self.last_request_count = self._active.last_request_count


class _HKJCClient(_BaseSourceClient):
    region = RacingRegion.HONG_KONG
    provider_name = "hkjc"
    record_authority_status = "source_records_verified"
    allowed_hosts = frozenset({"racing.hkjc.com"})

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        if (
            _normalized(request.candidate_source_name) != "hkjc"
            or not _text(request.external_horse_id)
        ):
            raise P0HorseSourceBlocked("provider_bound_identity_required: hkjc")
        horse_id = _text(request.external_horse_id)
        profile_url = (
            "https://racing.hkjc.com/racing/information/English/Horse/"
            f"Horse.aspx?HorseId={quote_plus(horse_id)}"
        )
        response = self._get(profile_url, request)
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.select_one("form#login input[name=password]"):
            raise P0HorseSourceBlocked("login_wall")
        profile_table = soup.select_one("#profile, table.horseProfile")
        values: dict[str, str] = {}
        if profile_table is not None:
            for row in profile_table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                if len(cells) >= 2:
                    label = _normalized(cells[0].get_text(" ", strip=True))
                    value = _text(cells[-1].get_text(" ", strip=True))
                    if label and value and label != value:
                        values[label] = value
        heading = _text(
            soup.select_one(".title_text").get_text(" ", strip=True)
            if soup.select_one(".title_text")
            else soup.find("h1").get_text(" ", strip=True)
            if soup.find("h1")
            else _field(values, "Horse Name")
        )
        horse_name = re.sub(
            r"\s*\([^)]*\)(?:\s*\([^)]*\))*\s*$", "", heading
        )
        origin_age = _field(
            values,
            "Country of Origin / Age",
            "Country of Origin",
        )
        colour_sex = _field(values, "Colour / Sex")
        origin_parts = [_text(part) for part in origin_age.split("/")]
        colour_parts = [_text(part) for part in colour_sex.split("/")]
        birth_date = _iso_date(_field(values, "Date of Birth"))
        pedigree = {
            "sire": _field(values, "Sire"),
            "dam": _field(values, "Dam"),
            "sire_sire": _field(values, "Sire's Sire"),
            "sire_dam": _field(values, "Sire's Dam"),
            "dam_sire": _field(values, "Dam's Sire"),
            "dam_dam": _field(values, "Dam's Dam"),
        }
        records = []
        legacy_tables = (
            (soup.select_one("#local-records"), False),
            (soup.select_one("#overseas-records"), True),
        )
        for table, is_overseas in legacy_tables:
            records.extend(
                _row_records(
                    table,
                    source_url=getattr(response, "url", profile_url),
                    is_overseas=is_overseas,
                )
            )
        trainers_by_date: list[tuple[str, str]] = []
        seen_record_keys: set[str] = set()
        for table in soup.select("table.bigborder"):
            header_row = next(
                (
                    row
                    for row in table.find_all("tr")
                    if row.find_all("th")
                    or row.select("td.hsubheader")
                ),
                None,
            )
            if header_row is None:
                continue
            headers = [
                re.sub(
                    r"\s*/\s*",
                    "/",
                    _normalized(cell.get_text(" ", strip=True)).rstrip("."),
                )
                for cell in header_row.find_all(["th", "td"])
            ]
            for row in header_row.find_next_siblings("tr"):
                cells = row.find_all("td", recursive=False)
                if not cells or len(cells) < 4:
                    continue
                values_by_header = {
                    headers[index]: _text(cell.get_text(" ", strip=True))
                    for index, cell in enumerate(cells)
                    if index < len(headers)
                }
                race_index = (
                    values_by_header.get("race index", "")
                    or _text(cells[0].get_text(" ", strip=True))
                )
                normalized_race_index = _normalized(race_index)
                is_overseas = normalized_race_index == "overseas"
                if not race_index or (
                    not is_overseas
                    and not re.search(r"\d", race_index)
                ):
                    continue
                date_text = (
                    values_by_header.get("date", "")
                    or (_text(cells[2].get_text(" ", strip=True)) if len(cells) > 2 else "")
                )
                placing = (
                    values_by_header.get("pla", "")
                    or values_by_header.get("placing", "")
                    or (_text(cells[1].get_text(" ", strip=True)) if len(cells) > 1 else "")
                )
                course_parts = [
                    values_by_header.get(label, "")
                    for label in ("rc", "track", "course", "rc/track/course")
                ]
                course = " / ".join(
                    part for part in course_parts if part
                ) or _text(cells[3].get_text(" ", strip=True))
                distance_text = (
                    values_by_header.get("dist", "")
                    or values_by_header.get("distance", "")
                )
                race_class = values_by_header.get("race class", "")
                parsed_race_date = _iso_date(date_text)
                external_race_id = (
                    _stable_source_record_id(
                        "hkjc-overseas",
                        parsed_race_date,
                        course,
                        distance_text,
                        race_class,
                    )
                    if is_overseas
                    else race_index
                )
                race_name = _text(row.get("data-race-name"))
                if not race_name:
                    named = row.select_one(
                        '[data-race-name], .race-name, [class*="race_name"]'
                    )
                    race_name = _text(
                        named.get("data-race-name")
                        or named.get_text(" ", strip=True)
                    ) if named else ""
                link = cells[0].find("a", href=True)
                race_url = (
                    urljoin(getattr(response, "url", profile_url), link["href"])
                    if link
                    else getattr(response, "url", profile_url)
                )
                trainer_name = values_by_header.get("trainer", "")
                if trainer_name and parsed_race_date:
                    trainers_by_date.append(
                        (parsed_race_date, trainer_name)
                    )
                record_key = _stable_source_record_id(
                    "hkjc-record",
                    external_race_id,
                    parsed_race_date,
                    course,
                    distance_text,
                    placing,
                )
                if record_key in seen_record_keys:
                    continue
                seen_record_keys.add(record_key)
                records.append(
                    {
                        "external_race_id": external_race_id,
                        "external_result_id": "",
                        "race_date": parsed_race_date,
                        "race_name": race_name,
                        "racecourse": course,
                        "finish": placing,
                        "distance_text": distance_text,
                        "source_url": race_url,
                        "is_overseas": is_overseas,
                        "source_record_key": record_key,
                    }
                )
        latest_form_trainer = (
            max(trainers_by_date, key=lambda item: item[0])[1]
            if trainers_by_date
            else ""
        )
        starts_text = _field(values, "No. of 1-2-3-Starts*")
        starts_match = re.search(r"(\d+)\s*$", starts_text.replace(" ", ""))
        if not starts_match:
            raise P0HorseSourceBlocked("missing_source_start_count")
        return self._payload(
            request=request,
            source_url=getattr(response, "url", profile_url),
            external_horse_id=horse_id,
            horse_name=horse_name,
            identity={"birth_year": _year(birth_date)},
            basic_profile={
                "country": origin_parts[0] if origin_parts else "",
                "sex": colour_parts[1] if len(colour_parts) > 1 else "",
                "color": colour_parts[0] if colour_parts else "",
                "birth_date": birth_date,
                "owner_name": _field(values, "Owner"),
                "trainer_name": (
                    _field(values, "Trainer")
                    or latest_form_trainer
                ),
                "breeder_name": _field(values, "Breeder"),
            },
            pedigree=pedigree,
            records=records,
            source_start_count=int(starts_match.group(1)),
            raw_payload={"profile_html": response.text},
            aliases=[
                {"name": horse_name, "language": "en", "is_original": True}
            ],
        )


class _SportingLifeClient(_BaseSourceClient):
    region = RacingRegion.UNITED_KINGDOM
    provider_name = "sporting_life"
    record_authority_status = "source_records_verified"
    allowed_hosts = frozenset({"www.sportinglife.com"})

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        if (
            _normalized(request.candidate_source_name) != "sporting_life"
            or not _text(request.external_horse_id)
        ):
            raise P0HorseSourceBlocked(
                "provider_bound_identity_required: sporting_life"
            )
        horse_id = _text(request.external_horse_id)
        profile_url = (
            f"https://www.sportinglife.com/racing/profiles/horse/{quote_plus(horse_id)}"
        )
        response = self._get(profile_url, request)
        soup = BeautifulSoup(response.text, "html.parser")
        script = soup.select_one("script#__NEXT_DATA__")
        if script is None:
            raise P0HorseSourceBlocked("missing_next_data")
        try:
            next_data = json.loads(script.string or script.get_text())
            page_props = next_data["props"]["pageProps"]
            horse = page_props.get("horse") or page_props.get("profile")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise P0HorseSourceBlocked("invalid_next_data") from exc
        if not isinstance(horse, dict):
            raise P0HorseSourceBlocked("invalid_next_data")
        horse_reference = (
            horse.get("horse_reference")
            if isinstance(horse.get("horse_reference"), dict)
            else {}
        )
        payload_horse_id = _text(horse.get("id") or horse_reference.get("id"))
        if payload_horse_id != horse_id:
            raise P0HorseSourceBlocked("provider_identity_mismatch")
        stats = horse.get("stats") if isinstance(horse.get("stats"), dict) else {}
        total_stats = (
            stats.get("total") if isinstance(stats.get("total"), dict) else stats
        )
        runs = (
            horse.get("full_form")
            if isinstance(horse.get("full_form"), list)
            else horse.get("previous_results")
        )
        if not isinstance(runs, list):
            runs = page_props.get("previous_results")
        if not isinstance(runs, list):
            raise P0HorseSourceBlocked("partial_career: form records missing")
        records = []
        observed_at = _utc_now()
        source_url = getattr(response, "url", profile_url)
        for run in runs:
            if not isinstance(run, dict):
                continue
            race_reference = (
                run.get("race_reference")
                if isinstance(run.get("race_reference"), dict)
                else {}
            )
            result_reference = (
                run.get("result_reference")
                if isinstance(run.get("result_reference"), dict)
                else {}
            )
            course = (
                run.get("course")
                if isinstance(run.get("course"), dict)
                else {}
            )
            casualty = run.get("casualty")
            casualty_reason = casualty
            if isinstance(casualty, dict):
                casualty_reason = next(
                    (
                        casualty.get(key)
                        for key in (
                            "reason",
                            "type",
                            "name",
                            "code",
                            "description",
                        )
                        if casualty.get(key)
                    ),
                    "",
                )
            (
                official_result_code,
                normalized_result_status,
                result_evidence_status,
                field_evidence,
            ) = _sporting_life_result_evidence(
                position=run.get("position"),
                casualty_reason=casualty_reason,
                source_url=source_url,
                observed_at=observed_at,
            )
            race_name = _text(
                run.get("race_name") or race_reference.get("name")
            )
            distance_text = _text(run.get("distance"))
            race_classification = next(
                (
                    _text(run.get(key))
                    for key in (
                        "race_classification",
                        "race_class",
                        "race_grade",
                        "grade",
                    )
                    if _text(run.get(key))
                ),
                "",
            )
            field_evidence.extend(
                [
                    _sporting_life_semantic_field_evidence(
                        field_name="race_name",
                        value=race_name,
                        source_url=source_url,
                        observed_at=observed_at,
                    ),
                    _sporting_life_semantic_field_evidence(
                        field_name="distance_text",
                        value=distance_text,
                        source_url=source_url,
                        observed_at=observed_at,
                    ),
                    _sporting_life_semantic_field_evidence(
                        field_name="race_classification",
                        value=race_classification,
                        source_url=source_url,
                        observed_at=observed_at,
                    ),
                ]
            )
            finish = (
                _text(run.get("position"))
                or official_result_code
                or "N/A"
            )
            records.append(
                {
                    "external_race_id": _text(
                        run.get("race_id") or race_reference.get("id")
                    ),
                    "external_result_id": _text(
                        run.get("ride_id")
                        or run.get("result_id")
                        or result_reference.get("id")
                    ),
                    "race_date": _iso_date(run.get("date")),
                    "race_name": race_name,
                    "racecourse": _text(
                        run.get("course_name")
                        or course.get("name")
                        or (
                            run.get("course")
                            if not isinstance(run.get("course"), dict)
                            else ""
                        )
                    ),
                    "finish": finish,
                    "casualty": _text(casualty_reason),
                    "casualty_reason_raw": _text(casualty_reason),
                    "official_result_code": official_result_code,
                    "result_status": normalized_result_status,
                    "result_evidence_status": result_evidence_status,
                    "field_evidence": field_evidence,
                    "distance_text": distance_text,
                    "source_url": source_url,
                }
            )
        pedigree = (
            deepcopy(horse.get("pedigree"))
            if isinstance(horse.get("pedigree"), dict)
            else {}
        )
        if not pedigree:
            pedigree = {
                "sire": _text(
                    horse.get("sire", {}).get("name")
                    if isinstance(horse.get("sire"), dict)
                    else horse.get("sire")
                ),
                "dam": _text(
                    horse.get("dam", {}).get("name")
                    if isinstance(horse.get("dam"), dict)
                    else horse.get("dam")
                ),
                "dam_sire": _text(
                    horse.get("damsire", {}).get("name")
                    if isinstance(horse.get("damsire"), dict)
                    else horse.get("damsire")
                ),
            }
        birth_date = _iso_date(horse.get("date_of_birth") or horse.get("foaled"))
        sex = horse.get("sex")
        trainer = horse.get("trainer")
        horse_name = _text(
            horse.get("name") or horse_reference.get("name")
        )
        return self._payload(
            request=request,
            source_url=getattr(response, "url", profile_url),
            external_horse_id=horse_id,
            horse_name=horse_name,
            identity={"birth_year": _year(birth_date)},
            basic_profile={
                "country": _text(horse.get("country")),
                "sex": _text(
                    sex.get("type") if isinstance(sex, dict) else sex
                ),
                "color": _text(horse.get("colour")),
                "birth_date": birth_date,
                "owner_name": _text(horse.get("owner")),
                "trainer_name": _text(
                    trainer.get("name")
                    if isinstance(trainer, dict)
                    else trainer
                ),
                "breeder_name": _text(horse.get("breeder")),
            },
            pedigree=pedigree,
            records=records,
            source_start_count=total_stats.get("runs"),
            raw_payload={
                "profile_html_kind": "__NEXT_DATA__ full_form/stats",
                "next_data": next_data,
            },
            aliases=[
                {
                    "name": horse_name,
                    "language": "en",
                    "is_original": True,
                }
            ],
        )


class _GenyClient(_BaseSourceClient):
    region = RacingRegion.FRANCE
    record_authority_status = "source_records_verified"
    provider_name = "geny"
    allowed_hosts = frozenset({"www.geny.com"})
    base_url = "https://www.geny.com"

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        search_url = f"{self.base_url}/recherche?query={quote_plus(request.horse_name)}"
        search = self._get(search_url, request)
        search_soup = BeautifulSoup(search.text, "html.parser")
        results = search_soup.select('.search-results a[href*="/cheval/"]')
        if len(results) != 1:
            reason = "identity_not_found" if not results else "ambiguous_identity"
            raise P0HorseSourceBlocked(reason)
        search_name = results[0].get_text(" ", strip=True)
        search_summary = _adjacent_search_summary(results[0])
        profile_url = urljoin(self.base_url, results[0]["href"])
        match = re.search(r"/cheval/[^/?#]*_(c\d+_h\d+)", profile_url)
        geny_id = match.group(1) if match else ""
        if not geny_id:
            raise P0HorseSourceBlocked("identity_not_found: missing Geny ID")
        response = self._get(profile_url, request)
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.select_one("form#login input[name=password]") or soup.select_one(
            'input[name="password"]'
        ):
            raise P0HorseSourceBlocked("login_wall")
        values = _dl_values(soup)
        identity_text = _text(
            soup.select_one(".identite").get_text(" ", strip=True)
            if soup.select_one(".identite")
            else ""
        )
        parents = re.search(r"\bpar\s+(.+?)\s+et\s+(.+)$", identity_text, re.I)
        pedigree = {
            "sire": _text(parents.group(1)) if parents else "",
            "dam": _text(parents.group(2)) if parents else "",
            "sire_sire": _field(values, "Père du père"),
            "sire_dam": _field(values, "Mère du père"),
            "dam_sire": _field(values, "Père de la mère"),
            "dam_dam": _field(values, "Mère de la mère"),
        }
        count_text = _field(values, "Nombre de courses")
        if not count_text.isdigit():
            raise P0HorseSourceBlocked("missing_source_start_count")
        records = _row_records(
            soup.select_one("#carriere"),
            source_url=getattr(response, "url", profile_url),
        )
        for record in records:
            if _normalized(record.get("finish")) == "np":
                record["finish"] = "unplaced"
        horse_name = _text(
            soup.find("h1").get_text(" ", strip=True)
            if soup.find("h1")
            else ""
        )
        _require_names_in_profile_aliases(
            request_name=request.horse_name,
            search_name=search_name,
            profile_aliases=[horse_name],
        )
        birth_date = _field(values, "Date de naissance")
        _require_complete_identity(
            horse_name=horse_name,
            sire_name=pedigree.get("sire"),
            dam_name=pedigree.get("dam"),
            birth_year=_year(birth_date),
        )
        _require_search_identity_matches_profile(
            _parse_search_identity_summary(search_summary),
            sire_name=pedigree.get("sire"),
            dam_name=pedigree.get("dam"),
            birth_year=_year(birth_date),
        )
        sex = "gelding" if re.search(r"\bhongre\b", identity_text, re.I) else ""
        color_match = re.search(r"\b(?:ans|an),\s*([^,]+),\s*par\b", identity_text, re.I)
        return self._payload(
            request=request,
            source_url=getattr(response, "url", profile_url),
            external_horse_id=geny_id,
            horse_name=horse_name,
            identity={"birth_year": _year(birth_date)},
            basic_profile={
                "country": _field(values, "Pays"),
                "sex": sex,
                "color": _text(color_match.group(1)) if color_match else "",
                "birth_date": birth_date,
                "owner_name": _field(values, "Propriétaire"),
                "trainer_name": _field(values, "Entraîneur"),
                "breeder_name": _field(values, "Éleveur"),
            },
            pedigree=pedigree,
            records=records,
            source_start_count=int(count_text),
            raw_payload={
                "search_html": search.text,
                "career_html": response.text,
            },
            aliases=[
                {"name": horse_name, "language": "fr", "is_original": True}
            ],
        )


class _HRNClient(_BaseSourceClient):
    region = RacingRegion.UNITED_STATES
    provider_name = "hrn"
    record_authority_status = "source_blocked"
    allowed_hosts = frozenset({"www.horseracingnation.com"})
    base_url = "https://www.horseracingnation.com"

    def _fetch(self, request: P0HorseCompletionRequest) -> dict[str, Any]:
        horse_id = _slug_from_name(request.horse_name)
        if not horse_id:
            raise P0HorseSourceBlocked("identity_not_found: missing HRN slug")
        profile_url = f"{self.base_url}/horse/{horse_id}"
        first_response = self._get(profile_url, request)
        first_soup = BeautifulSoup(first_response.text, "html.parser")
        first_heading = _text(
            first_soup.find("h1").get_text(" ", strip=True)
            if first_soup.find("h1")
            else ""
        )
        search_identity: dict[str, Any] | None = None
        search_name = ""
        if _normalized(first_heading) == _normalized(request.horse_name):
            profile = first_response
            profile_soup = first_soup
        else:
            results = first_soup.select(
                '.search-results a[href*="/horse/"]'
            )
            if len(results) != 1:
                reason = "identity_not_found" if not results else "ambiguous_identity"
                raise P0HorseSourceBlocked(reason)
            search_name = _text(results[0].get_text(" ", strip=True))
            search_identity = _parse_search_identity_summary(
                _adjacent_search_summary(results[0])
            )
            profile_url = urljoin(self.base_url, results[0]["href"])
            match = re.search(r"/horse/([^/?#]+)", profile_url)
            horse_id = match.group(1) if match else ""
            if not horse_id:
                raise P0HorseSourceBlocked(
                    "identity_not_found: missing HRN ID"
                )
            profile = self._get(profile_url, request)
            profile_soup = BeautifulSoup(profile.text, "html.parser")
        horse_name = _text(
            profile_soup.find("h1").get_text(" ", strip=True)
            if profile_soup.find("h1")
            else ""
        )
        if _normalized(horse_name) != _normalized(request.horse_name):
            raise P0HorseSourceBlocked("identity_mismatch: profile horse_name")
        if search_name and _normalized(search_name) != _normalized(horse_name):
            raise P0HorseSourceBlocked("identity_mismatch: search_result horse_name")

        stats_container = profile_soup.select_one(".horse-stats")
        values = _dl_values(stats_container or profile_soup)
        if stats_container is not None:
            for term in stats_container.find_all("dt"):
                description = term.find_next_sibling("dd")
                if description is not None:
                    values[
                        _normalized(term.get_text(" ", strip=True)).rstrip(":")
                    ] = _text(description.get_text(" ", strip=True))
        values.update(_strong_label_values(stats_container))
        pedigree_text = _field(values, "Pedigree")
        pedigree_links = (
            stats_container.select('a.horse-name[href*="/horse/"]')
            if stats_container
            else []
        )
        sire = _field(values, "Sire")
        dam = _field(values, "Dam")
        dam_sire = _field(values, "Dam Sire")
        if pedigree_text and len(pedigree_links) >= 3:
            sire = _text(pedigree_links[0].get_text(" ", strip=True))
            dam = _text(pedigree_links[1].get_text(" ", strip=True))
            dam_sire = _text(pedigree_links[2].get_text(" ", strip=True))
        birth_date = _iso_date(_field(values, "Foaled"))
        birth_year = _year(_field(values, "Foaled"))
        _require_request_identity_matches_profile(
            request,
            horse_name=horse_name,
            sire_name=sire,
            dam_name=dam,
            birth_year=birth_year,
        )
        if search_identity is not None:
            _require_search_identity_matches_profile(
                search_identity,
                sire_name=sire,
                dam_name=dam,
                birth_year=birth_year,
            )

        results_soup = profile_soup
        results_response = profile
        result_table = profile_soup.select_one(
            "table.horse-table, #all-results"
        )
        if result_table is None:
            results_link = profile_soup.select_one('a[href*="/results"]')
            if results_link is None:
                raise P0HorseSourceBlocked(
                    "partial_career: results table missing"
                )
            results_url = urljoin(profile_url, results_link["href"])
            results_response = self._get(results_url, request)
            results_soup = BeautifulSoup(results_response.text, "html.parser")
            result_table = results_soup.select_one(
                "table.horse-table, #all-results"
            )
        records: list[dict[str, Any]] = []
        if result_table is not None and result_table.get("id") == "all-results":
            records = _row_records(
                result_table,
                source_url=getattr(results_response, "url", profile_url),
            )
        elif result_table is not None:
            header_row = result_table.select_one("tr.horse-header")
            if header_row is None:
                header_row = next(
                    (
                        row
                        for row in result_table.find_all("tr")
                        if row.find_all("th")
                        and any(
                            _normalized(cell.get_text(" ", strip=True)) == "date"
                            for cell in row.find_all("th")
                        )
                    ),
                    None,
                )
            headers = [
                _normalized(cell.get_text(" ", strip=True))
                for cell in header_row.find_all("th")
            ] if header_row else []
            for row in result_table.find_all("tr"):
                if row is header_row or row.find("th"):
                    continue
                cells = row.find_all("td", recursive=False)
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
                    (
                        cell
                        for label, cell in by_header.items()
                        if label == "race"
                    ),
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
                race_link = race_cell.find('a', href=re.compile(r"/race/"))
                race_url = (
                    urljoin(profile_url, race_link["href"])
                    if race_link
                    else getattr(profile, "url", profile_url)
                )
                finish_text = _text(finish_cell.get_text(" ", strip=True))
                ordinal = re.match(r"(\d+)(?:st|nd|rd|th)?", finish_text, re.I)
                records.append(
                    {
                        "external_race_id": _text(
                            row.get("data-race-id")
                        ) or _id_from_race_url(race_url),
                        "external_result_id": _text(
                            row.get("data-result-id")
                        ),
                        "race_date": _iso_date(
                            date_node.get("datetime")
                            if date_node and date_node.get("datetime")
                            else date_cell.get_text(" ", strip=True)
                        ),
                        "race_name": _text(
                            race_cell.get_text(" ", strip=True)
                        ),
                        "racecourse": _text(
                            (
                                track_cell.find("a").get("title")
                                if track_cell.find("a")
                                else ""
                            )
                            or track_cell.get_text(" ", strip=True)
                        ),
                        "finish": (
                            ordinal.group(1) if ordinal else finish_text
                        ),
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

        starts_text = _field(values, "Starts")
        if not starts_text.isdigit():
            raise P0HorseSourceBlocked("missing_source_start_count")
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
        sex = _field(values, "Sex")
        if not sex:
            age_text = _field(values, "Age")
            age_match = re.search(r"\s+-\s+(.+)$", age_text)
            sex = _text(age_match.group(1)) if age_match else ""
        pedigree = {
            "sire": sire,
            "dam": dam,
            "sire_sire": _field(values, "Sire Sire"),
            "sire_dam": _field(values, "Sire Dam"),
            "dam_sire": dam_sire,
            "dam_dam": _field(values, "Dam Dam"),
        }
        return self._payload(
            request=request,
            source_url=getattr(profile, "url", profile_url),
            external_horse_id=horse_id,
            horse_name=horse_name,
            identity={"birth_year": birth_year},
            basic_profile={
                "country": country,
                "sex": sex,
                "color": _field(values, "Color"),
                "birth_date": birth_date,
                "owner_name": _field(values, "Owner", "Owner(s)"),
                "trainer_name": _field(values, "Trainer"),
                "breeder_name": breeder,
            },
            pedigree=pedigree,
            records=records,
            source_start_count=int(starts_text),
            raw_payload={
                "profile_html": profile.text,
                "results_html": results_response.text,
            },
            aliases=[
                {"name": horse_name, "language": "en", "is_original": True}
            ],
        )


_CLIENTS = {
    RacingRegion.JAPAN: _JapanDispatcherClient,
    RacingRegion.HONG_KONG: _HKJCClient,
    RacingRegion.UNITED_KINGDOM: _SportingLifeClient,
    RacingRegion.FRANCE: _GenyClient,
    RacingRegion.UNITED_STATES: _HRNClient,
}


def build_p0_horse_completion_source_client(
    region: str,
    transport: P0HorseTransport,
    *,
    manual_supplements_by_candidate: (
        dict[str, list[dict[str, Any]]] | None
    ) = None,
    **client_kwargs: Any,
) -> _BaseSourceClient:
    client_class = _CLIENTS.get(region)
    if client_class is None:
        raise P0HorseSourceBlocked(f"unsupported_region: {region}")
    return client_class(
        transport,
        manual_supplements_by_candidate=manual_supplements_by_candidate,
        **client_kwargs,
    )
