#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlparse

from race_event_request_budget import before_network_request
from race_event_safe_http import SafeHttpError, fetch_https
from race_event_source_cache import (
    SourceCacheBudgetExceeded,
    ensure_source_cache_manifest,
    write_source_cache,
)
from historical_race_calendar_common import (
    ADAPTER_ALLOWED_HOSTS,
    CalendarArtifactError,
    SHA256_RE,
    validate_source_url,
)



class DateSourceCacheError(RuntimeError):
    pass


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def require_network_gates(*, allow_network: bool, environ: Mapping[str, str]) -> None:
    if not allow_network:
        raise DateSourceCacheError("date source network access requires --allow-network")
    if not _enabled(environ.get("HISTORICAL_RACE_BACKFILL_ENABLED")):
        raise DateSourceCacheError("historical race backfill feature switch is disabled")
    if not _enabled(environ.get("HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK")):
        raise DateSourceCacheError("historical race backfill network switch is disabled")


def _source_filename(adapter_key: str, url: str) -> str:
    parsed = urlparse(url)
    extension = Path(parsed.path).suffix.lower()
    if extension not in {".html", ".htm", ".pdf", ".json", ".xml"}:
        extension = ".html"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    stem = re.sub(r"[^a-z0-9]+", "-", Path(parsed.path).stem.lower()).strip("-")[-60:] or "source"
    return f"{adapter_key}/{stem}-{digest}{extension}"


def request_headers(adapter_key: str) -> dict[str, str]:
    if adapter_key == "toba":
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
    return {
        "User-Agent": "UmaFansBot/1.0 (+https://umafans.run; historical race evidence)"
    }


def validate_source_body(url: str, body: bytes, headers: Mapping[str, str]) -> None:
    if not body:
        raise DateSourceCacheError("source response body is empty")
    content_type = str(
        next((value for key, value in headers.items() if str(key).lower() == "content-type"), "")
    ).lower()
    source_path = urlparse(url).path.lower()
    expects_pdf = source_path.endswith(".pdf") or source_path.endswith("/eqbpdfchartplus.cfm")
    if expects_pdf:
        if not body.startswith(b"%PDF-") or "pdf" not in content_type:
            raise DateSourceCacheError("source response is not a PDF")
        return
    sample = body[:100_000].lower()
    anti_bot_markers = (
        b"pardon our interruption",
        b"access denied",
        b"captcha",
        b"cf-chl-",
        b"incapsula incident id",
        b"_incapsula_resource",
        b"to regain access",
    )
    toba_sample = body[:2_000_000].lower()
    toba_yearbook_table = (
        urlparse(url).hostname in {"toba.org", "www.toba.org"}
        and b"<table" in toba_sample
        and b">stake</th>" in toba_sample
        and b">winner</th>" in toba_sample
    )
    if any(marker in sample for marker in anti_bot_markers) and not toba_yearbook_table:
        raise DateSourceCacheError("source response is an anti-bot page")
    if b"information not available" in sample:
        raise DateSourceCacheError("source response is an unavailable page")


def cache_provider_rows(
    provider_rows: Iterable[dict],
    *,
    output_root: Path,
    timeout: int,
) -> dict:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in provider_rows:
        adapter_key = str(row.get("adapter_key") or "").strip()
        if adapter_key not in ADAPTER_ALLOWED_HOSTS:
            raise DateSourceCacheError(f"unsupported date source adapter: {adapter_key}")
        raw_target_id = row.get("target_id")
        raw_year = row.get("edition_year")
        if (
            raw_target_id not in (None, "")
            and (not isinstance(raw_target_id, int) or isinstance(raw_target_id, bool))
        ) or (
            raw_year not in (None, "")
            and (not isinstance(raw_year, int) or isinstance(raw_year, bool))
        ):
            raise DateSourceCacheError("provider row target identity is invalid")
        target_id = None if raw_target_id in (None, "") else raw_target_id
        edition_year = None if raw_year in (None, "") else raw_year
        target_sha = str(row.get("target_sha256") or "")
        if (
            (target_id is not None and target_id <= 0)
            or (edition_year is not None and not 1800 <= edition_year <= 2200)
            or (target_sha and not SHA256_RE.fullmatch(target_sha))
        ):
            raise DateSourceCacheError("provider row target identity is invalid")
        urls = row.get("urls")
        if not isinstance(urls, dict) or not urls:
            raise DateSourceCacheError("provider row has no source URLs")
        for role, evidence in urls.items():
            if not isinstance(evidence, dict) or not str(evidence.get("url") or "").strip():
                raise DateSourceCacheError(f"provider row has invalid source URL: {role}")
            source_url = str(evidence["url"]).strip()
            try:
                validate_source_url(source_url, adapter_key)
            except CalendarArtifactError as exc:
                raise DateSourceCacheError(str(exc)) from exc
            grouped[(adapter_key, str(evidence["url"]).strip())].append(
                {
                    "target_id": target_id,
                    "target_sha256": target_sha,
                    "series_key": str(row.get("series_key") or ""),
                    "edition_year": edition_year,
                    "role": role,
                }
            )

    ledger: list[dict] = []
    failures = 0
    for adapter_key, url in sorted(grouped):
        requested_at = datetime.now(timezone.utc).isoformat()
        entry = {
            "adapter_key": adapter_key,
            "requested_at": requested_at,
            "source_url": url,
            "target_references": sorted(
                {
                    json.dumps(reference, ensure_ascii=False, sort_keys=True): reference
                    for reference in grouped[(adapter_key, url)]
                }.values(),
                key=lambda reference: (
                    int(reference.get("target_id") or 0),
                    reference.get("series_key") or "",
                    int(reference.get("edition_year") or 0),
                    reference.get("role") or "",
                ),
            ),
        }
        try:
            before_network_request(url)
            body, response = fetch_https(
                url,
                allowed_hosts=ADAPTER_ALLOWED_HOSTS[adapter_key],
                timeout=timeout,
                headers=request_headers(adapter_key),
            )
            entry.update(
                {
                    "http_status": response["status"],
                    "final_url": response["final_url"],
                    "redirect_chain": response["redirect_chain"],
                }
            )
            validate_source_body(url, body, response.get("headers") or {})
            relative_cache_path = _source_filename(adapter_key, url)
            identity = write_source_cache(
                output_root / relative_cache_path, body, source_url=url
            )
            entry.update(
                {
                    "status": "succeeded",
                    "source_cache_identity": identity,
                    "source_cache_relative_path": relative_cache_path,
                }
            )
        except (OSError, SafeHttpError, SourceCacheBudgetExceeded, RuntimeError) as exc:
            failures += 1
            entry.update({"status": "failed", "error": str(exc)})
        ledger.append(entry)
    failed_entries = [entry for entry in ledger if entry["status"] == "failed"]
    affected_target_ids = {
        int(reference["target_id"])
        for entry in failed_entries
        for reference in entry["target_references"]
        if reference.get("target_id") not in (None, "")
        and not isinstance(reference.get("target_id"), bool)
    }
    return {
        "request_count": len(ledger),
        "success_count": len(ledger) - failures,
        "failure_count": failures,
        "failed_urls": sorted(entry["source_url"] for entry in failed_entries),
        "affected_target_count": len(affected_target_ids),
        "request_ledger": ledger,
    }


def cache_command_exit_code(result: Mapping, *, allow_partial: bool) -> int:
    ledger = result.get("request_ledger")
    if not isinstance(ledger, list) or len(ledger) != result.get("request_count"):
        raise DateSourceCacheError("date source request ledger is incomplete")
    statuses = [entry.get("status") for entry in ledger if isinstance(entry, dict)]
    if len(statuses) != len(ledger) or any(status not in {"succeeded", "failed"} for status in statuses):
        raise DateSourceCacheError("date source request ledger is not terminal")
    success_count = statuses.count("succeeded")
    failure_count = statuses.count("failed")
    if success_count != result.get("success_count") or failure_count != result.get("failure_count"):
        raise DateSourceCacheError("date source request ledger counts are inconsistent")
    return 0 if not failure_count or allow_partial else 2


def _read_jsonl(paths: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise DateSourceCacheError(f"provider row must be an object: {path}:{line_number}")
                rows.append(payload)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="缓存历史赛事日期发现直接来源，并生成请求账本。")
    parser.add_argument("--provider-jsonl", action="append", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--request-ledger", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    try:
        require_network_gates(allow_network=args.allow_network, environ=os.environ)
        args.output_root.mkdir(parents=True, exist_ok=True)
        ensure_source_cache_manifest(args.output_root / ".calendar-cache")
        rows = _read_jsonl(args.provider_jsonl)
        result = cache_provider_rows(rows, output_root=args.output_root, timeout=args.timeout)
        args.request_ledger.parent.mkdir(parents=True, exist_ok=True)
        args.request_ledger.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in result["request_ledger"]),
            encoding="utf-8",
        )
        summary = {key: value for key, value in result.items() if key != "request_ledger"}
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return cache_command_exit_code(result, allow_partial=args.allow_partial)
    except (DateSourceCacheError, json.JSONDecodeError, OSError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
