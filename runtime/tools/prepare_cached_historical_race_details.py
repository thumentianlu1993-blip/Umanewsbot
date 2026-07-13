#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_jra_race_detail_candidates import _parse_detail_page as parse_jra_detail


ASSIGNMENT_RE = re.compile(
    r'^race\["(?P<group>starters|scratches)"\]\[(?P<index>\d+)\]'
    r'(?P<path>(?:\["[^"]+"\])+?)\s*=\s*(?P<value>.+);$'
)


def _js_value(raw: str):
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace(r"\'", "'").replace(r'\"', '"').replace(r"\\", "\\")
    if value in {"true", "false"}:
        return value == "true"
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def _person(row: dict, role: str) -> str:
    return " ".join(
        str(row.get(f"{role}.{part}") or "").strip()
        for part in ("firstname", "middlename", "lastname")
        if str(row.get(f"{role}.{part}") or "").strip()
    )


def _horse_sort_key(row: dict) -> tuple[int, str]:
    match = re.match(r"\d+", str(row.get("horse_number") or ""))
    return (int(match.group()) if match else 10**9, str(row.get("horse_number") or ""))


def parse_equibase_yearbook(html: str, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    groups: dict[str, dict[int, dict]] = {"starters": {}, "scratches": {}}
    for raw_line in html.splitlines():
        match = ASSIGNMENT_RE.match(raw_line.strip())
        if match is None:
            continue
        path = ".".join(re.findall(r'\["([^"]+)"\]', match.group("path")))
        groups[match.group("group")].setdefault(int(match.group("index")), {})[path] = _js_value(
            match.group("value")
        )
    if not groups["starters"]:
        raise RuntimeError("Equibase yearbook page has no starters")

    runners = []
    results = []
    for group_name in ("starters", "scratches"):
        for group_index, row in groups[group_name].items():
            horse_name = str(row.get("horse.name") or "").strip()
            if not horse_name:
                continue
            scratched = group_name == "scratches" or bool(row.get("scratchindicator"))
            refs = {
                "primary": source_url,
                "source_language": "en",
                "source_kind": "equibase_yearbook",
            }
            horse_number = str(row.get("programnumber") or "")
            if group_name == "scratches" and (not horse_number or horse_number.upper() == "SCR"):
                horse_number = f"SCR-{group_index + 1}"
            runner = {
                "sort_order": 0,
                "horse_number": horse_number,
                "barrier": str(row.get("postposition") or ""),
                "horse_name": horse_name,
                "jockey_name": _person(row, "jockey"),
                "trainer_name": _person(row, "trainer"),
                "carried_weight": str(row.get("weightcarried") or ""),
                "odds_value": str(float(row["odds"]) / 100) if row.get("odds") not in (None, "") else "",
                "running_status": "scratched" if scratched else "declared",
                "source_refs": {**refs, "scratch_reason": str(row.get("scratchreason") or "")},
            }
            runners.append(runner)
            position = row.get("officialposition")
            if scratched or not isinstance(position, (int, float)) or int(position) <= 0:
                continue
            results.append(
                {
                    **{key: runner[key] for key in (
                        "horse_number", "barrier", "horse_name", "jockey_name", "trainer_name",
                        "carried_weight", "odds_value", "running_status", "source_refs"
                    )},
                    "finish_position": int(position),
                    "official_finish_position": int(position),
                    "finish_time": "",
                    "margin": "",
                    "is_confirmed": True,
                }
            )
    runners.sort(key=_horse_sort_key)
    for index, row in enumerate(runners, start=1):
        row["sort_order"] = index
    results.sort(key=lambda row: row["official_finish_position"])
    for storage_position, row in enumerate(results, start=1):
        row["finish_position"] = storage_position
    if not results:
        raise RuntimeError("Equibase yearbook page has no official results")
    return runners, results, {
        "runner_count": len(runners),
        "result_count": len(results),
        "scratch_count": sum(row["running_status"] == "scratched" for row in runners),
    }


def _comma_person(value: str) -> str:
    parts = [part.strip() for part in value.split(",", 1)]
    return f"{parts[1]} {parts[0]}".strip() if len(parts) == 2 else value.strip()


def parse_nsa_words(words: list[dict], *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    lines: dict[float, list[dict]] = {}
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        top = float(word["top"])
        line = next((value for value in lines if abs(value - top) <= 1.0), None)
        lines.setdefault(top if line is None else line, []).append(word)
    runners = []
    results = []
    for line in sorted(lines):
        row = sorted(lines[line], key=lambda item: float(item["x0"]))
        order_tokens = [item["text"] for item in row if float(item["x0"]) < 40]
        if len(order_tokens) != 1 or not re.fullmatch(r"\d{2}|F|UR|PU|RO|BD", order_tokens[0]):
            continue
        order_text = order_tokens[0]
        horse_name = " ".join(item["text"] for item in row if 40 <= float(item["x0"]) < 190).strip()
        weights = [item["text"] for item in row if 190 <= float(item["x0"]) < 212]
        rider = " ".join(item["text"] for item in row if 212 <= float(item["x0"]) < 290).strip()
        trainer = " ".join(item["text"] for item in row if 415 <= float(item["x0"]) < 535).strip()
        if not horse_name or not weights or not rider:
            continue
        finished = order_text.isdigit()
        refs = {
            "primary": source_url,
            "source_language": "en",
            "source_kind": "nsa_official_result_pdf",
            "official_order_text": order_text,
        }
        runner = {
            "sort_order": len(runners) + 1,
            "horse_number": "",
            "barrier": "",
            "horse_name": horse_name,
            "jockey_name": _comma_person(rider),
            "trainer_name": trainer,
            "carried_weight": weights[0],
            "odds_value": "",
            "running_status": "declared" if finished else "unknown",
            "source_refs": refs,
        }
        runners.append(runner)
        if finished:
            official_position = int(order_text)
            results.append(
                {
                    **{key: runner[key] for key in (
                        "horse_number", "barrier", "horse_name", "jockey_name", "trainer_name",
                        "carried_weight", "odds_value", "running_status", "source_refs"
                    )},
                    "finish_position": len(results) + 1,
                    "official_finish_position": official_position,
                    "finish_time": "",
                    "margin": "",
                    "is_confirmed": True,
                }
            )
    if not runners or not results:
        raise RuntimeError("NSA result PDF has no complete race rows")
    return runners, results, {
        "runner_count": len(runners),
        "result_count": len(results),
        "non_finish_count": len(runners) - len(results),
    }


def parse_nsa_pdf(path: Path, *, source_url: str) -> tuple[list[dict], list[dict], dict]:
    with pdfplumber.open(path) as pdf:
        words = [word for page in pdf.pages for word in page.extract_words(x_tolerance=1, y_tolerance=3)]
    return parse_nsa_words(words, source_url=source_url)


def _events(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def _cache(manifest_path: Path) -> dict[str, tuple[dict, Path]]:
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent.resolve()
    result = {}
    for identity in manifest["files"].values():
        path = (root / identity["path"]).resolve()
        path.relative_to(root)
        body = path.read_bytes()
        if len(body) != int(identity["size"]) or hashlib.sha256(body).hexdigest() != identity["sha256"]:
            raise RuntimeError(f"source cache identity mismatch: {path}")
        result[identity["source_url"]] = (identity, path)
    return result


def prepare(*, event_paths: list[Path], manifest_path: Path) -> dict:
    cache = _cache(manifest_path)
    records = []
    gaps = []
    for event in _events(event_paths):
        refs = json.loads(event["source_refs"])
        evidence = (((refs.get("detail_discovery") or {}).get("urls") or {}).get("result_url") or {})
        provider = evidence.get("source_provider")
        source_url = str(evidence.get("url") or "")
        cached = cache.get(source_url)
        if cached is None:
            gaps.append({"slug": event["slug"], "reason": "source_not_cached", "source_url": source_url})
            continue
        _identity, source_path = cached
        try:
            if provider == "jra":
                runners, results, metadata = parse_jra_detail(source_path.read_bytes(), source_url=source_url)
                source_name = "jra_official_result_page"
            elif provider == "equibase":
                runners, results, metadata = parse_equibase_yearbook(
                    source_path.read_text(encoding="utf-8", errors="replace"), source_url=source_url
                )
                source_name = "equibase_yearbook"
            elif provider == "nsa":
                runners, results, metadata = parse_nsa_pdf(source_path, source_url=source_url)
                source_name = "nsa_official_result_pdf"
            else:
                gaps.append({"slug": event["slug"], "reason": "unsupported_provider", "provider": provider})
                continue
        except Exception as exc:
            gaps.append({"slug": event["slug"], "reason": "parse_failed", "error": str(exc)})
            continue
        records.append(
            {
                "year": int(event["year"]),
                "slug": event["slug"],
                "source_name": source_name,
                "source_url": source_url,
                "modules": {
                    "runners": {"is_complete": True, "items": runners},
                    "results": {"is_complete": True, "items": results},
                },
                "metadata": metadata,
            }
        )
    return {"records": records, "gaps": gaps}


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse approved historical detail pages from immutable cache.")
    parser.add_argument("--events-csv", action="append", required=True, type=Path)
    parser.add_argument("--source-cache-manifest", required=True, type=Path)
    parser.add_argument("--output-jsonl", required=True, type=Path)
    parser.add_argument("--gap-json", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(event_paths=args.events_csv, manifest_path=args.source_cache_manifest)
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.output_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in result["records"]),
        encoding="utf-8",
    )
    args.gap_json.write_text(json.dumps(result["gaps"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "event_count": len(result["records"]),
        "gap_count": len(result["gaps"]),
        "runner_count": sum(len(row["modules"]["runners"]["items"]) for row in result["records"]),
        "result_count": sum(len(row["modules"]["results"]["items"]) for row in result["records"]),
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
