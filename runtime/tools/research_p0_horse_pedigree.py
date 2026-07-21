from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    ROOT
    / "runtime/horse_profile_completion/research-50-parsed-20260718/"
    "p0_horse_research_50.json"
)
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "runtime/horse_profile_completion/pedigree-research-20260719"
)
DEFAULT_MANUAL_EVIDENCE = DEFAULT_OUTPUT_DIR / "manual_pedigree_evidence.json"
NETKEIBA_SEARCH_URL = "https://en.netkeiba.com/db/horse/horse_list.html"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
)
_HTTP_URL_VALIDATOR = URLValidator(schemes=["http", "https"])
_NETKEIBA_PROFILE_PATH_RE = re.compile(
    r"^/db/horse/([0-9A-Za-z_-]+)/$"
)


def valid_http_url(value: Any) -> bool:
    try:
        _HTTP_URL_VALIDATOR(str(value or "").strip())
    except ValidationError:
        return False
    return True


def netkeiba_profile_external_id(value: Any) -> str | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.netloc != "en.netkeiba.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = _NETKEIBA_PROFILE_PATH_RE.fullmatch(parsed.path)
    return match.group(1) if match else None


def normalized_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def horse_identity_key(horse: dict[str, Any]) -> str:
    identity = horse.get("identity") or {}
    pedigree = horse.get("pedigree") or {}
    horse_name = identity.get("horse_name") or horse.get("candidate", {}).get(
        "horse_name"
    )
    birth_year = identity.get("birth_year") or str(
        horse.get("basic_profile", {}).get("birth_date") or ""
    )[:4]
    return " | ".join(
        str(value or "").strip()
        for value in (
            horse_name,
            pedigree.get("sire"),
            pedigree.get("dam"),
            birth_year,
        )
    )


def normalized_identity_key(value: Any) -> tuple[str, str, str, str] | None:
    parts = [part.strip() for part in str(value or "").split("|")]
    if len(parts) != 4 or not all(parts):
        return None
    return (
        normalized_name(parts[0]),
        normalized_name(parts[1]),
        normalized_name(parts[2]),
        parts[3],
    )


def manual_evidence_source_key(
    source_name: Any,
    external_horse_id: Any,
) -> tuple[str, str, str] | None:
    normalized_source_name = normalized_name(source_name)
    if external_horse_id in (None, ""):
        external_id = ""
    elif not isinstance(external_horse_id, str):
        raise ValueError("manual pedigree evidence external ID must be a string")
    else:
        external_id = external_horse_id.strip()
    if bool(normalized_source_name) != bool(external_id):
        raise ValueError(
            "manual pedigree evidence source name and external ID must "
            "either both be present or both be absent"
        )
    if not normalized_source_name:
        return None
    return (
        "source",
        normalized_source_name,
        external_id,
    )


def parse_search_candidates(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for row in soup.select("ul.BreederList > li"):
        link = row.select_one('a[href*="/db/horse/"]')
        name_node = row.select_one("h2")
        if link is None or name_node is None:
            continue
        labels = {}
        for node in row.select(".DataBox_01 p"):
            text = node.get_text(" ", strip=True)
            if ":" not in text:
                continue
            label, value = text.split(":", 1)
            labels[label.strip().lower()] = value.strip()
        profile_url_value = link.get("href", "")
        profile_url = (
            profile_url_value
            if isinstance(profile_url_value, str)
            else ""
        )
        horse_id = netkeiba_profile_external_id(profile_url)
        birth_year = ""
        for node in row.select(".DataBox_01 p"):
            year_match = re.search(r"\b((?:18|19|20)\d{2})\b", node.get_text(" ", strip=True))
            if year_match:
                birth_year = year_match.group(1)
                break
        candidates.append(
            {
                "horse_id": horse_id or "",
                "name": name_node.get_text(" ", strip=True),
                "sire": labels.get("sire", ""),
                "dam": labels.get("dam", ""),
                "birth_year": birth_year,
                "profile_url": profile_url,
            }
        )
    return candidates


def _candidate_has_complete_source_identity(candidate: dict[str, str]) -> bool:
    external_id_value = candidate.get("horse_id")
    profile_url = candidate.get("profile_url")
    if (
        not isinstance(external_id_value, str)
        or external_id_value != external_id_value.strip()
        or not isinstance(profile_url, str)
    ):
        return False
    external_id = external_id_value
    birth_year = str(candidate.get("birth_year") or "").strip()
    if not all(
        (
            external_id,
            str(candidate.get("name") or "").strip(),
            str(candidate.get("sire") or "").strip(),
            str(candidate.get("dam") or "").strip(),
            re.fullmatch(r"(?:18|19|20)\d{2}", birth_year),
        )
    ):
        return False
    return netkeiba_profile_external_id(profile_url) == external_id


def select_parent_candidate(
    candidates: list[dict[str, str]],
    *,
    parent_name: str,
    expected_sire: str = "",
    expected_external_id: str = "",
) -> tuple[dict[str, str] | None, str]:
    normalized_parent_name = normalized_name(parent_name)
    if not normalized_parent_name:
        return None, "empty_normalized_parent_name"
    exact_name = [
        candidate
        for candidate in candidates
        if normalized_name(candidate["name"]) == normalized_parent_name
    ]
    if not exact_name:
        return None, "no_identity_matched_candidate"
    if expected_external_id in (None, ""):
        exact_external_id = ""
    elif (
        not isinstance(expected_external_id, str)
        or expected_external_id != expected_external_id.strip()
    ):
        return None, "no_identity_matched_candidate"
    else:
        exact_external_id = expected_external_id
    if exact_external_id:
        exact_name = [
            candidate
            for candidate in exact_name
            if candidate.get("horse_id") == exact_external_id
        ]
        verification_method = "parent_source_external_id_match"
    elif expected_sire:
        exact_name = [
            candidate
            for candidate in exact_name
            if normalized_name(candidate["sire"]) == normalized_name(expected_sire)
        ]
        verification_method = "parent_complete_identity_and_known_sire_match"
    else:
        return None, "insufficient_parent_identity_evidence"
    if len(exact_name) == 1:
        if not _candidate_has_complete_source_identity(exact_name[0]):
            return None, "incomplete_parent_source_identity"
        selected = dict(exact_name[0])
        selected["identity_verification_method"] = verification_method
        return selected, ""
    if not exact_name:
        return None, "no_identity_matched_candidate"
    return None, "ambiguous_identity_matched_candidates"


def apply_parent_evidence(
    horse: dict[str, Any],
    *,
    role: str,
    candidate: dict[str, str],
    verified_at: str,
) -> list[dict[str, str]]:
    if not _candidate_has_complete_source_identity(candidate):
        raise ValueError("parent candidate requires complete source identity")
    verification_method = str(
        candidate.get("identity_verification_method") or ""
    ).strip()
    if verification_method not in {
        "parent_source_external_id_match",
        "parent_complete_identity_and_known_sire_match",
    }:
        raise ValueError("parent candidate requires a reviewed identity match method")
    pedigree = horse.setdefault("pedigree", {})
    evidence = []
    fields = (
        (("sire_sire", candidate["sire"]), ("sire_dam", candidate["dam"]))
        if role == "sire"
        else (("dam_sire", candidate["sire"]), ("dam_dam", candidate["dam"]))
    )
    for field_name, value in fields:
        if not value:
            continue
        existing_value = str(pedigree.get(field_name) or "").strip()
        if existing_value and normalized_name(existing_value) != normalized_name(value):
            evidence.append(
                {
                    "field_name": field_name,
                    "value": existing_value,
                    "source_value": value,
                    "status": "conflict",
                    "source_name": "netkeiba_en",
                    "source_url": candidate["profile_url"],
                    "source_external_horse_id": candidate["horse_id"],
                    "source_identity": {
                        "horse_name": candidate["name"],
                        "sire_name": candidate["sire"],
                        "dam_name": candidate["dam"],
                        "birth_year": candidate["birth_year"],
                    },
                    "verified_at": verified_at,
                    "verification_method": verification_method,
                }
            )
            continue
        if not existing_value:
            pedigree[field_name] = value
        evidence.append(
            {
                "field_name": field_name,
                "value": value,
                "status": "verified_secondary_source",
                "source_name": "netkeiba_en",
                "source_url": candidate["profile_url"],
                "source_external_horse_id": candidate["horse_id"],
                "source_identity": {
                    "horse_name": candidate["name"],
                    "sire_name": candidate["sire"],
                    "dam_name": candidate["dam"],
                    "birth_year": candidate["birth_year"],
                },
                "verified_at": verified_at,
                "verification_method": verification_method,
            }
        )
    return evidence


def refresh_missing_pedigree_fields(horse: dict[str, Any]) -> None:
    field_status = horse.get("field_status")
    if not isinstance(field_status, dict):
        return
    field_status["missing_pedigree_fields"] = [
        key
        for key in (
            "sire",
            "dam",
            "sire_sire",
            "sire_dam",
            "dam_sire",
            "dam_dam",
        )
        if not horse.get("pedigree", {}).get(key)
    ]


def apply_manual_evidence(
    data: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> tuple[int, list[dict[str, str]]]:
    horses_by_identity = {}
    for horse in data.get("horses") or []:
        identity = horse.get("identity") or {}
        horse_name = identity.get("horse_name") or horse.get("candidate", {}).get(
            "horse_name"
        )
        normalized_horse_name = normalized_name(horse_name)
        pedigree = horse.get("pedigree") or {}
        normalized_sire = normalized_name(pedigree.get("sire"))
        normalized_dam = normalized_name(pedigree.get("dam"))
        birth_year = str(
            identity.get("birth_year")
            or str(horse.get("basic_profile", {}).get("birth_date") or "")[:4]
        ).strip()
        source = horse.get("source") or {}
        key = manual_evidence_source_key(
            source.get("name"),
            source.get("external_horse_id"),
        )
        if key is None:
            if not all(
                (
                    normalized_horse_name,
                    normalized_sire,
                    normalized_dam,
                    birth_year,
                )
            ):
                continue
            key = (
                "identity",
                normalized_horse_name,
                normalized_sire,
                normalized_dam,
                birth_year,
            )
        if key in horses_by_identity:
            raise ValueError(f"duplicate horse identity for manual evidence: {key}")
        horses_by_identity[key] = horse

    filled_count = 0
    applied_rows = []
    for row in evidence_rows:
        horse_name = str(row.get("horse_name") or "").strip()
        identity_parts = [
            part.strip()
            for part in str(row.get("expected_identity_key") or "").split("|")
        ]
        if (
            len(identity_parts) != 4
            or not all(identity_parts)
            or normalized_name(identity_parts[0]) != normalized_name(horse_name)
        ):
            raise ValueError(
                "manual evidence requires horse_name and a matching four-part "
                "expected_identity_key"
            )
        _, expected_sire, expected_dam, expected_birth_year = identity_parts
        for expected_key, identity_value in (
            ("expected_sire", expected_sire),
            ("expected_dam", expected_dam),
        ):
            row_value = str(row.get(expected_key) or "").strip()
            if row_value and normalized_name(row_value) != normalized_name(identity_value):
                raise ValueError(
                    f"manual evidence {expected_key} conflicts with expected_identity_key"
                )
        key = manual_evidence_source_key(
            row.get("expected_source_name"),
            row.get("expected_external_horse_id"),
        )
        if key is None:
            key = (
                "identity",
                normalized_name(row.get("horse_name")),
                normalized_name(expected_sire),
                normalized_name(expected_dam),
                expected_birth_year,
            )
        horse = horses_by_identity.get(key)
        if horse is None:
            raise ValueError(f"manual evidence horse not found: {key}")
        field_name = str(row.get("field_name") or "")
        if field_name not in {"sire_sire", "sire_dam", "dam_sire", "dam_dam"}:
            raise ValueError(f"unsupported manual pedigree field: {field_name}")
        value = str(row.get("value") or "").strip()
        if not value:
            raise ValueError(f"manual pedigree value is empty: {key} {field_name}")

        pedigree = horse.setdefault("pedigree", {})
        if field_name in {"sire_sire", "sire_dam"}:
            required_identity_fields = ("expected_sire",)
            identity_checks = (("sire", "expected_sire"),)
        else:
            required_identity_fields = ("expected_dam", "expected_dam_sire")
            identity_checks = (("dam", "expected_dam"),)
            if field_name == "dam_dam":
                identity_checks += (("dam_sire", "expected_dam_sire"),)
        for required_key in required_identity_fields:
            if not str(row.get(required_key) or "").strip():
                raise ValueError(
                    f"manual evidence requires {required_key}: {key} {field_name}"
                )
        if field_name == "dam_sire" and normalized_name(
            row.get("expected_dam_sire")
        ) != normalized_name(value):
            raise ValueError(
                "manual evidence expected_dam_sire must match the dam_sire value"
            )
        for pedigree_key, evidence_key in identity_checks:
            expected_value = str(row.get(evidence_key) or "").strip()
            actual_value = str(pedigree.get(pedigree_key) or "").strip()
            if normalized_name(actual_value) != normalized_name(expected_value):
                raise ValueError(
                    "manual evidence identity mismatch: "
                    f"{key} expected {pedigree_key}={expected_value!r}, "
                    f"actual={actual_value!r}"
                )

        audit_values = {}
        for audit_key in (
            "source_name",
            "source_url",
            "verified_at",
            "verification_method",
            "evidence_note",
        ):
            raw_audit_value = row.get(audit_key)
            if not isinstance(raw_audit_value, str):
                raise ValueError(
                    f"manual evidence {audit_key} must be a string: "
                    f"{key} {field_name}"
                )
            audit_values[audit_key] = raw_audit_value.strip()
        for audit_key, audit_value in audit_values.items():
            if not audit_value:
                raise ValueError(
                    f"manual evidence requires non-empty {audit_key}: "
                    f"{key} {field_name}"
                )
        if not valid_http_url(audit_values["source_url"]):
            raise ValueError(
                f"manual evidence source_url is invalid: {audit_values['source_url']!r}"
            )
        try:
            parsed_verified_at = datetime.fromisoformat(
                audit_values["verified_at"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                "manual evidence verified_at must be a valid ISO-8601 timestamp"
            ) from exc
        if parsed_verified_at.tzinfo is None:
            raise ValueError(
                "manual evidence verified_at must include a timezone offset"
            )

        existing_value = str(pedigree.get(field_name) or "").strip()
        if existing_value and normalized_name(existing_value) != normalized_name(value):
            raise ValueError(
                "manual evidence conflicts with collected pedigree: "
                f"{key} {field_name}={existing_value!r}, evidence={value!r}"
            )
        if not existing_value:
            pedigree[field_name] = value
            filled_count += 1

        evidence = {
            "field_name": field_name,
            "value": value,
            "status": "verified_secondary_manual_source",
            "source_name": audit_values["source_name"],
            "source_url": audit_values["source_url"],
            "verified_at": audit_values["verified_at"],
            "verification_method": audit_values["verification_method"],
            "evidence_note": audit_values["evidence_note"],
        }
        horse.setdefault("pedigree_field_evidence", []).append(evidence)
        applied_rows.append(evidence | {"region": key[0], "horse_name": key[1]})
        refresh_missing_pedigree_fields(horse)
    return filled_count, applied_rows


class NetkeibaParentResearchClient:
    def __init__(self, *, request_interval_seconds: float = 0.8):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.request_interval_seconds = request_interval_seconds
        self._last_request_at = 0.0
        self._cache: dict[str, list[dict[str, str]]] = {}

    def search(self, parent_name: str) -> list[dict[str, str]]:
        cache_key = normalized_name(parent_name)
        if not cache_key:
            raise ValueError("parent name normalizes to an empty cache key")
        if cache_key in self._cache:
            return self._cache[cache_key]
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.request_interval_seconds:
            time.sleep(self.request_interval_seconds - elapsed)
        response = self.session.post(
            NETKEIBA_SEARCH_URL,
            data={
                "type": "db",
                "word": parent_name,
                "match": "1",
            },
            timeout=30,
        )
        self._last_request_at = time.monotonic()
        response.raise_for_status()
        candidates = parse_search_candidates(response.text)
        self._cache[cache_key] = candidates
        return candidates


def research(
    data: dict[str, Any],
    client: NetkeibaParentResearchClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched = deepcopy(data)
    verified_at = datetime.now(timezone.utc).isoformat()
    unresolved = []
    evidence_count = 0
    filled_fields = 0

    for horse in enriched.get("horses") or []:
        pedigree = horse.get("pedigree") or {}
        horse_evidence = list(horse.get("pedigree_field_evidence") or [])
        identity_key = horse_identity_key(horse)
        parent_queries = []
        missing_sire_fields = [
            field_name
            for field_name in ("sire_sire", "sire_dam")
            if not pedigree.get(field_name)
        ]
        if missing_sire_fields:
            parent_queries.append(
                ("sire", pedigree.get("sire", ""), "", missing_sire_fields)
            )
        missing_dam_fields = [
            field_name
            for field_name in ("dam_sire", "dam_dam")
            if not pedigree.get(field_name)
        ]
        if missing_dam_fields:
            parent_queries.append(
                (
                    "dam",
                    pedigree.get("dam", ""),
                    pedigree.get("dam_sire", ""),
                    missing_dam_fields,
                )
            )

        for role, parent_name, expected_sire, target_fields in parent_queries:
            if not parent_name:
                unresolved.append(
                    {
                        "horse_name": horse.get("candidate", {}).get("horse_name", ""),
                        "region": horse.get("region", ""),
                        "identity_key": identity_key,
                        "parent_role": role,
                        "target_fields": target_fields,
                        "parent_name": "",
                        "expected_parent_sire": expected_sire,
                        "reason": "missing_parent_name",
                    }
                )
                continue
            candidates = client.search(parent_name)
            candidate, reason = select_parent_candidate(
                candidates,
                parent_name=parent_name,
                expected_sire=expected_sire,
            )
            if candidate is None:
                unresolved.append(
                    {
                        "horse_name": horse.get("candidate", {}).get("horse_name", ""),
                        "region": horse.get("region", ""),
                        "identity_key": identity_key,
                        "parent_role": role,
                        "target_fields": target_fields,
                        "parent_name": parent_name,
                        "expected_parent_sire": expected_sire,
                        "reason": reason,
                        "candidate_count": len(candidates),
                    }
                )
                continue
            before = {
                key: pedigree.get(key)
                for key in ("sire_sire", "sire_dam", "dam_sire", "dam_dam")
            }
            new_evidence = apply_parent_evidence(
                horse,
                role=role,
                candidate=candidate,
                verified_at=verified_at,
            )
            horse_evidence.extend(new_evidence)
            evidence_count += len(new_evidence)
            filled_fields += sum(
                1
                for key in before
                if not before[key] and horse["pedigree"].get(key)
            )

        horse["pedigree_field_evidence"] = horse_evidence
        refresh_missing_pedigree_fields(horse)

    report = {
        "schema_version": "p0-horse-pedigree-research.v1",
        "source_name": "netkeiba_en",
        "source_search_url": NETKEIBA_SEARCH_URL,
        "verified_at": verified_at,
        "horse_count": len(enriched.get("horses") or []),
        "filled_field_count": filled_fields,
        "evidence_count": evidence_count,
        "automatic_unresolved_query_count": len(unresolved),
        "automatic_unresolved_queries": unresolved,
    }
    enriched["pedigree_research"] = report
    return enriched, report


def finalize_automatic_unresolved_queries(
    data: dict[str, Any],
    unresolved_queries: list[dict[str, Any]],
) -> None:
    horses_by_identity = {}
    for horse in data.get("horses") or []:
        key = normalized_identity_key(horse_identity_key(horse))
        if key is None:
            continue
        horses_by_identity[(str(horse.get("region") or ""), key)] = horse

    fields_by_role = {
        "sire": ("sire_sire", "sire_dam"),
        "dam": ("dam_sire", "dam_dam"),
    }
    for query in unresolved_queries:
        role = str(query.get("parent_role") or "")
        role_fields = fields_by_role.get(role)
        if role_fields is None:
            raise ValueError(
                f"automatic unresolved query has invalid parent_role: {role!r}"
            )
        target_fields = query.get("target_fields")
        if (
            not isinstance(target_fields, list)
            or not target_fields
            or any(field_name not in role_fields for field_name in target_fields)
        ):
            raise ValueError(
                "automatic unresolved query has invalid target_fields: "
                f"{target_fields!r} for role {role!r}"
            )
        identity = normalized_identity_key(query.get("identity_key"))
        horse = horses_by_identity.get(
            (str(query.get("region") or ""), identity)
        )
        missing_fields = [
            field_name
            for field_name in target_fields
            if horse is None or not horse.get("pedigree", {}).get(field_name)
        ]
        query["final_missing_fields"] = missing_fields
        query["final_disposition"] = (
            "still_missing"
            if missing_fields
            else "resolved_by_manual_evidence"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--manual-evidence",
        type=Path,
        default=DEFAULT_MANUAL_EVIDENCE,
    )
    parser.add_argument("--request-interval", type=float, default=0.8)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    enriched, report = research(
        data,
        NetkeibaParentResearchClient(
            request_interval_seconds=args.request_interval,
        ),
    )
    manual_rows = []
    if args.manual_evidence.exists():
        manual_rows = json.loads(args.manual_evidence.read_text(encoding="utf-8"))
    manual_filled_count, manual_applied_rows = apply_manual_evidence(
        enriched,
        manual_rows,
    )
    remaining_missing = [
        {
            "region": horse.get("region", ""),
            "horse_name": horse.get("identity", {}).get("horse_name", ""),
            "missing_fields": horse.get("field_status", {}).get(
                "missing_pedigree_fields",
                [],
            ),
        }
        for horse in enriched.get("horses") or []
        if horse.get("field_status", {}).get("missing_pedigree_fields")
    ]
    report["manual_evidence_row_count"] = len(manual_applied_rows)
    report["manual_filled_field_count"] = manual_filled_count
    report["total_filled_field_count"] = (
        report["filled_field_count"] + manual_filled_count
    )
    report["remaining_missing_horse_count"] = len(remaining_missing)
    report["remaining_missing"] = remaining_missing
    report["unresolved_count"] = len(remaining_missing)
    report["unresolved"] = remaining_missing
    finalize_automatic_unresolved_queries(
        enriched,
        report["automatic_unresolved_queries"],
    )
    enriched["pedigree_research"] = report
    args.output_dir.mkdir(parents=True, exist_ok=True)
    enriched_path = args.output_dir / "p0_horse_research_50_enriched.json"
    report_path = args.output_dir / "p0_horse_pedigree_research_report.json"
    enriched_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    print(enriched_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
