#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from race_event_source_cache import write_source_cache


ROW_RE = re.compile(
    r"^\S+(?:\s+\S+)?\s+(?P<number>\d+[A-Za-z]?)\s+"
    r"(?P<horse>.+?)\s*\((?P<jockey>[^()]*)\)\s+(?P<weight>\d+)\s+(?P<rest>.+)$"
)

TRACK_NAMES = {
    "CD": "CHURCHILL DOWNS",
    "GP": "GULFSTREAM PARK",
}


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _person_from_equibase(value: str) -> str:
    parts = [part.strip() for part in (value or "").split(",") if part.strip()]
    if len(parts) == 2:
        family, given = parts
        return f"{given} {family}".strip()
    if len(parts) >= 3:
        family, suffix = parts[:2]
        given = " ".join(parts[2:])
        return f"{given} {family}, {suffix}".strip()
    return value.strip()


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text(x_tolerance=0.5) or "" for page in pdf.pages)


def _parse_trainers(text: str) -> dict[str, str]:
    match = re.search(r"Trainers:\s*(.*?)\nOwners:", text, flags=re.S)
    if not match:
        return {}
    trainers: dict[str, str] = {}
    for item in _collapse(match.group(1)).split(";"):
        if "-" not in item:
            continue
        number, name = item.split("-", 1)
        trainers[number.strip()] = _person_from_equibase(name)
    return trainers


def _post_position(rest: str) -> str:
    tokens = rest.split()
    for index, token in enumerate(tokens[1:], start=1):
        if token.isdigit():
            return token
    return ""


def _horse_sort_key(row: dict) -> tuple[int, str]:
    match = re.match(r"\d+", str(row.get("horse_number") or ""))
    return (int(match.group()) if match else 10**9, str(row.get("horse_number") or ""))


def _parse_metadata(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = lines[0] if lines else ""
    race_line = next((line for line in lines[1:8] if line.startswith(("STAKES", "ALLOWANCE"))), "")
    header_match = re.match(
        r"(?P<course>.+?)\s*-\s*(?P<date>[A-Za-z]+\s+\d{1,2},\s*\d{4})\s*-\s*Race\s*(?P<race>\d+)",
        header,
        flags=re.I,
    )
    return {
        "racecourse_compact": header_match.group("course") if header_match else "",
        "local_date_text": header_match.group("date") if header_match else "",
        "race_number": header_match.group("race") if header_match else "",
        "race_title_compact": race_line,
    }


def _compact_identity(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _validate_chart_identity(metadata: dict, mapping: dict) -> None:
    try:
        chart_date = datetime.strptime(metadata.get("local_date_text") or "", "%B %d, %Y").date().isoformat()
    except ValueError as exc:
        raise RuntimeError("Equibase chart date is missing or invalid") from exc
    expected_date = str(mapping.get("local_date") or "")
    if chart_date != expected_date:
        raise RuntimeError(f"Equibase chart date mismatch: expected {expected_date}, got {chart_date}")

    track_code = str(mapping.get("track_code") or "").upper()
    expected_course = TRACK_NAMES.get(track_code)
    if not expected_course:
        raise RuntimeError(f"unsupported Equibase track code: {track_code}")
    if _compact_identity(metadata.get("racecourse_compact")) != _compact_identity(expected_course):
        raise RuntimeError(
            f"Equibase chart racecourse mismatch: expected {expected_course}, got {metadata.get('racecourse_compact') or ''}"
        )

    expected_race = str(mapping.get("race_number") or "")
    if str(metadata.get("race_number") or "") != expected_race:
        raise RuntimeError(
            f"Equibase chart race number mismatch: expected {expected_race}, got {metadata.get('race_number') or ''}"
        )


def _parse_chart_text(text: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    header_match = re.search(r"Last\s*Raced\s+Pgm\s+Horse\s*Name\s*\(Jockey\).*?\n", text, flags=re.I)
    fractional_match = re.search(r"Fractional\s*Times:", text, flags=re.I)
    if not header_match:
        raise RuntimeError("Equibase chart missing runner table header")
    if not fractional_match:
        raise RuntimeError("Equibase chart missing Fractional Times marker")
    body = text[header_match.end() : fractional_match.start()]
    trainers = _parse_trainers(text)
    result_rows = []
    for line in body.splitlines():
        match = ROW_RE.match(_collapse(line))
        if not match:
            continue
        number = match.group("number")
        result_rows.append(
            {
                "horse_number": number,
                "barrier": _post_position(match.group("rest")),
                "horse_name": _collapse(match.group("horse")),
                "jockey_name": _person_from_equibase(match.group("jockey")),
                "trainer_name": trainers.get(number, ""),
                "carried_weight": match.group("weight"),
            }
        )
    if not result_rows:
        raise RuntimeError("Equibase chart produced no actual runners")

    runners = []
    results = []
    for finish_position, row in enumerate(result_rows, start=1):
        refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": "equibase_pdf_chart",
            "official_finish_position": finish_position,
        }
        runners.append(
            {
                **row,
                "odds_value": "",
                "running_status": "declared",
                "sort_order": 0,
                "source_refs": refs,
            }
        )
        results.append(
            {
                **row,
                "finish_position": finish_position,
                "finish_time": "",
                "margin": "",
                "odds_value": "",
                "running_status": "declared",
                "is_confirmed": True,
                "source_refs": refs,
            }
        )
    runners.sort(key=_horse_sort_key)
    for sort_order, runner in enumerate(runners, start=1):
        runner["sort_order"] = sort_order
    metadata = {
        **_parse_metadata(text),
        "runners_complete": len(runners) == len(result_rows),
        "results_complete": len(results) == len(result_rows),
        "row_count": len(result_rows),
    }
    return runners, results, metadata


def _parse_chart(path: Path, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    return _parse_chart_text(_pdf_text(path), source_url=source_url)


def _read_events(paths: list[Path]) -> dict[tuple[int, str], dict]:
    events: dict[tuple[int, str], dict] = {}
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (int(row["year"]), row["slug"])
                if key in events:
                    raise RuntimeError(f"duplicate event input: {key}")
                events[key] = row
    return events


def _approved_result_url(event: dict) -> str:
    try:
        refs = json.loads(event.get("source_refs") or "{}")
    except json.JSONDecodeError:
        return ""
    evidence = (((refs.get("detail_discovery") or {}).get("urls") or {}).get("result_url") or {})
    if evidence.get("source_provider") != "equibase":
        return ""
    return str(evidence.get("url") or "")


def _read_pdf_map(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("sources") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise RuntimeError("Equibase PDF map must be a list or contain sources")
    return rows


def _read_source_cache_identities(paths: list[Path]) -> dict[str, dict]:
    identities: dict[str, dict] = {}
    for manifest_path in paths:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = payload.get("files") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or not isinstance(files, dict):
            raise RuntimeError(f"date source cache manifest is invalid: {manifest_path}")
        root = manifest_path.parent.resolve()
        for identity in files.values():
            if not isinstance(identity, dict):
                raise RuntimeError(f"date source cache identity is invalid: {manifest_path}")
            source_url = str(identity.get("source_url") or "")
            source = (root / str(identity.get("path") or "")).resolve()
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(f"date source cache path escapes manifest directory: {source}") from exc
            if not source_url or not source.is_file():
                raise RuntimeError(f"date source cache file is missing: {source}")
            body = source.read_bytes()
            if len(body) != int(identity.get("size") or -1) or hashlib.sha256(body).hexdigest() != identity.get(
                "sha256"
            ):
                raise RuntimeError(f"date source cache identity changed: {source}")
            existing = identities.get(source_url)
            if existing and any(existing.get(field) != identity.get(field) for field in ("size", "sha256")):
                raise RuntimeError(f"date source URL has ambiguous cache identities: {source_url}")
            identities[source_url] = identity
    return identities


def _source_cache_manifest_is_approved(event: dict, paths: list[Path]) -> bool:
    try:
        refs = json.loads(event.get("source_refs") or "{}")
    except json.JSONDecodeError:
        return False
    if not isinstance(refs, dict):
        return False
    expected = (refs.get("detail_discovery") or {}).get("source_cache_manifest_identity")
    if not isinstance(expected, dict):
        return False
    try:
        expected_size = int(expected.get("size") or -1)
    except (TypeError, ValueError):
        return False
    for path in paths:
        try:
            body = path.read_bytes()
        except OSError:
            continue
        if len(body) == expected_size and hashlib.sha256(body).hexdigest() == expected.get(
            "sha256"
        ):
            return True
    return False


def _verified_pdf_body(path: Path, *, source_url: str, identities: dict[str, dict]) -> bytes:
    identity = identities.get(source_url)
    if identity is None:
        raise RuntimeError(f"Equibase source URL has no date source cache identity: {source_url}")
    body = path.read_bytes()
    if not body.startswith(b"%PDF-"):
        raise RuntimeError("Equibase source is not a PDF")
    if len(body) != int(identity.get("size") or -1) or hashlib.sha256(body).hexdigest() != identity.get("sha256"):
        raise RuntimeError(f"Equibase PDF differs from date source cache: {source_url}")
    return body


def prepare_candidates(args) -> dict:
    events = _read_events([Path(path) for path in args.events_csv])
    mappings = _read_pdf_map(Path(args.pdf_map_json))
    source_cache_manifest_paths = [Path(args.source_cache_manifest)]
    source_cache_identities = _read_source_cache_identities(source_cache_manifest_paths)
    output_dir = Path(args.output_dir)
    source_dir = output_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "us_equibase_archived_detail_candidates.jsonl"
    review_path = output_dir / "us_equibase_archived_detail_review.csv"
    summary = {
        "source": "equibase_pdf_chart",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events_requested": len(mappings),
        "events": 0,
        "runner_items": 0,
        "result_items": 0,
        "errors": [],
    }
    review_rows = []
    with candidate_path.open("w", encoding="utf-8") as handle:
        for mapping in mappings:
            key = (int(mapping.get("year") or 0), str(mapping.get("slug") or ""))
            event = events.get(key)
            if not event:
                summary["errors"].append({"key": key, "error": "missing_event"})
                continue
            if not _source_cache_manifest_is_approved(event, source_cache_manifest_paths):
                raise RuntimeError(f"Equibase date source cache manifest is not approved for event: {key}")
            source_url = str(mapping.get("source_url") or "")
            if source_url != _approved_result_url(event):
                raise RuntimeError(f"Equibase source URL is not approved for event: {key}")
            pdf_path = Path(mapping.get("pdf_path") or "")
            try:
                body = _verified_pdf_body(
                    pdf_path,
                    source_url=source_url,
                    identities=source_cache_identities,
                )
                cached = source_dir / f"equibase_{event['year']}_{event['slug']}.pdf"
                write_source_cache(cached, body, source_url=source_url)
                runners, results, metadata = _parse_chart(cached, source_url=source_url)
                _validate_chart_identity(metadata, mapping)
            except Exception as exc:
                summary["errors"].append({"key": key, "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            retrieval_url = str(mapping.get("retrieval_url") or mapping.get("archive_url") or "")
            for module_rows in (runners, results):
                for row in module_rows:
                    row["source_refs"]["retrieved_from_url"] = retrieval_url
            record = {
                "year": key[0],
                "slug": key[1],
                "source_name": "equibase_pdf_chart",
                "source_url": source_url,
                "modules": {
                    "runners": {"is_complete": True, "items": runners},
                    "results": {"is_complete": True, "items": results},
                },
                "metadata": {**metadata, "retrieved_from_url": retrieval_url},
            }
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["runner_items"] += len(runners)
            summary["result_items"] += len(results)
            review_rows.append(
                {
                    "year": key[0],
                    "slug": key[1],
                    "source_url": source_url,
                    "retrieval_url": retrieval_url,
                    "runners": len(runners),
                    "results": len(results),
                    "horse_number_1": next((row["horse_name"] for row in runners if row["horse_number"] == "1"), ""),
                    "winner": results[0]["horse_name"],
                }
            )
    fieldnames = ["year", "slug", "source_url", "retrieval_url", "runners", "results", "horse_number_1", "winner"]
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate complete US historical race details from archived Equibase chart PDFs.")
    parser.add_argument("--events-csv", action="append", required=True)
    parser.add_argument("--pdf-map-json", required=True)
    parser.add_argument("--source-cache-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
