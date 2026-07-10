#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber


GAP_PDFS = {
    "us-toba-2026-0501-110": "oaks_r13.pdf",
    "us-toba-2026-0501-116": "edgewood_r12.pdf",
    "us-toba-2026-0502-119": "derby_r12.pdf",
    "us-toba-2026-0502-126": "patday_r8.pdf",
}
ROW_RE = re.compile(r"^\S+\s+(?P<number>\d+)\s+(?P<horse>.+?)\((?P<jockey>[^()]*)\)\s+(?P<rest>.+)$")
ODDS_RE = re.compile(r"^\d+\.\d+\*?$")


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _person_from_equibase(value: str) -> str:
    parts = [part.strip() for part in (value or "").split(",") if part.strip()]
    if len(parts) == 2:
        family, given = parts
        return f"{given} {family}".strip()
    if len(parts) >= 3:
        family = parts[0]
        suffix = parts[1]
        given = " ".join(parts[2:])
        return f"{given} {family}, {suffix}".strip()
    return value or ""


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _read_events(path: Path) -> dict[str, dict]:
    events = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            events[row["slug"]] = row
    return events


def _read_runner_maps(path: Path) -> dict[str, dict[str, dict]]:
    maps: dict[str, dict[str, dict]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            runners = (record.get("modules") or {}).get("runners", {}).get("items", [])
            maps[record["slug"]] = {
                str(runner.get("horse_number") or ""): runner
                for runner in runners
                if runner.get("horse_number")
            }
    return maps


def _parse_trainers(text: str) -> dict[str, str]:
    match = re.search(r"Trainers:\s*(.*?)\nOwners:", text, flags=re.S)
    if not match:
        return {}
    raw = match.group(1).replace("\n", "")
    trainers = {}
    for item in raw.split(";"):
        item = item.strip()
        if not item or "-" not in item:
            continue
        number, value = item.split("-", 1)
        trainers[number.strip()] = _person_from_equibase(value)
    return trainers


def _finish_text_from_rest(rest: str) -> tuple[str, str]:
    tokens = rest.split()
    for index, token in enumerate(tokens):
        if ODDS_RE.match(token):
            fin_text = tokens[index - 1] if index > 0 else ""
            return fin_text, token.rstrip("*")
    return "", ""


def _parse_chart(path: Path) -> tuple[list[dict], dict[str, str]]:
    text = _pdf_text(path)
    trainers = _parse_trainers(text)
    if "FractionalTimes:" not in text:
        raise RuntimeError(f"Equibase chart missing FractionalTimes marker: {path}")
    body = text.split("LastRaced Pgm HorseName(Jockey)", 1)[-1].split("FractionalTimes:", 1)[0]
    rows = []
    for line in body.splitlines():
        line = _collapse(line)
        match = ROW_RE.match(line)
        if not match:
            continue
        fin_text, odds = _finish_text_from_rest(match.group("rest"))
        rows.append(
            {
                "horse_number": match.group("number"),
                "jockey_name": _person_from_equibase(match.group("jockey")),
                "trainer_name": trainers.get(match.group("number"), ""),
                "equibase_horse_name_compact": match.group("horse"),
                "equibase_fin_text": fin_text,
                "odds_value": odds,
            }
        )
    if not rows:
        raise RuntimeError(f"Equibase chart produced no result rows: {path}")
    return rows, trainers


def prepare_candidates(args) -> dict:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = Path(args.pdf_dir)
    events = _read_events(Path(args.events_csv))
    runner_maps = _read_runner_maps(Path(args.runner_jsonl))
    jsonl_path = output_dir / "us_equibase_gap_result_candidates_2026.jsonl"
    review_path = output_dir / "us_equibase_gap_result_review_2026.csv"
    summary = {
        "source": "equibase_pdf_chart",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": 0,
        "result_items": 0,
        "errors": [],
    }
    review_rows = []
    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for slug, filename in GAP_PDFS.items():
            event = events.get(slug)
            runner_map = runner_maps.get(slug) or {}
            if not event:
                summary["errors"].append({"slug": slug, "error": "missing_event_csv_row"})
                continue
            try:
                rows, _trainers = _parse_chart(pdf_dir / filename)
            except Exception as exc:
                summary["errors"].append({"slug": slug, "error": str(exc)})
                if args.fail_fast:
                    raise
                continue
            items = []
            for finish_position, row in enumerate(rows, start=1):
                runner = runner_map.get(row["horse_number"]) or {}
                horse_name = runner.get("horse_name") or row["equibase_horse_name_compact"]
                source_refs = {
                    **(runner.get("source_refs") or {}),
                    "primary": json.loads(event.get("source_refs") or "{}").get("chart_url", ""),
                    "source_language": "en",
                    "source_kind": "equibase_pdf_chart",
                    "official_finish_position": finish_position,
                    "equibase_pdf_file": filename,
                    "equibase_horse_name_compact": row["equibase_horse_name_compact"],
                    "equibase_fin_text": row["equibase_fin_text"],
                }
                items.append(
                    {
                        "finish_position": finish_position,
                        "horse_number": row["horse_number"],
                        "barrier": runner.get("barrier", ""),
                        "horse_name": horse_name,
                        "jockey_name": row["jockey_name"] or runner.get("jockey_name", ""),
                        "trainer_name": row["trainer_name"] or runner.get("trainer_name", ""),
                        "finish_time": "",
                        "margin": row["equibase_fin_text"],
                        "odds_value": row["odds_value"] or runner.get("odds_value", ""),
                        "running_status": "declared",
                        "is_confirmed": True,
                        "source_refs": source_refs,
                    }
                )
            record = {
                "year": int(event["year"]),
                "slug": slug,
                "source_name": "equibase_pdf_chart",
                "source_url": json.loads(event.get("source_refs") or "{}").get("chart_url", ""),
                "modules": {"results": {"items": items}},
                "metadata": {"pdf_file": filename, "row_count": len(items)},
            }
            jsonl.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary["events"] += 1
            summary["result_items"] += len(items)
            review_rows.append(
                {
                    "slug": slug,
                    "original_name": event["original_name"],
                    "pdf_file": filename,
                    "results": len(items),
                    "winner": items[0]["horse_name"] if items else "",
                    "winner_jockey": items[0]["jockey_name"] if items else "",
                    "winner_trainer": items[0]["trainer_name"] if items else "",
                }
            )
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["slug", "original_name", "pdf_file", "results", "winner", "winner_jockey", "winner_trainer"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate result candidates for US gap races from Equibase chart PDFs.")
    parser.add_argument("--events-csv", required=True)
    parser.add_argument("--runner-jsonl", required=True)
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare_candidates(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
