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
from race_event_source_cache import SourceCacheBudgetExceeded, write_source_cache


ADAPTER_ALLOWED_HOSTS = {
    "jra": ("jra.go.jp",),
    "netkeiba": ("netkeiba.com",),
    "jbis": ("jbis.or.jp",),
    "hkjc": ("hkjc.com",),
    "uk_racingpost": ("racingpost.com",),
    "uk_skysports": ("skysports.com",),
    "uk_sportinglife": ("sportinglife.com",),
    "uk_irishracing": ("irishracing.com",),
    "uk_bha": ("britishhorseracing.com",),
    "france_galop": ("france-galop.com",),
    "pmu": ("pmu.fr",),
    "france_irishracing": ("irishracing.com",),
    "equibase": ("equibase.com",),
    "brisnet": ("brisnet.com",),
    "drf": ("drf.com",),
    "bloodhorse": ("bloodhorse.com",),
    "nsa": ("nationalsteeplechase.com",),
    "us_hrn": ("horseracingnation.com",),
}


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
    if any(marker in sample for marker in anti_bot_markers):
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
        urls = row.get("urls")
        if not isinstance(urls, dict) or not urls:
            raise DateSourceCacheError("provider row has no source URLs")
        for role, evidence in urls.items():
            if not isinstance(evidence, dict) or not str(evidence.get("url") or "").strip():
                raise DateSourceCacheError(f"provider row has invalid source URL: {role}")
            grouped[(adapter_key, str(evidence["url"]).strip())].append(
                {
                    "series_key": str(row.get("series_key") or ""),
                    "edition_year": row.get("edition_year"),
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
            "target_references": grouped[(adapter_key, url)],
        }
        try:
            before_network_request(url)
            body, response = fetch_https(
                url,
                allowed_hosts=ADAPTER_ALLOWED_HOSTS[adapter_key],
                timeout=timeout,
                headers={"User-Agent": "UmaFansBot/1.0 (+https://umafans.run; historical race evidence)"},
            )
            entry.update(
                {
                    "http_status": response["status"],
                    "final_url": response["final_url"],
                    "redirect_chain": response["redirect_chain"],
                }
            )
            validate_source_body(url, body, response.get("headers") or {})
            identity = write_source_cache(output_root / _source_filename(adapter_key, url), body, source_url=url)
            entry.update(
                {
                    "status": "succeeded",
                    "source_cache_identity": identity,
                }
            )
        except (OSError, SafeHttpError, SourceCacheBudgetExceeded, RuntimeError) as exc:
            failures += 1
            entry.update({"status": "failed", "error": str(exc)})
        ledger.append(entry)
    return {
        "request_count": len(ledger),
        "success_count": len(ledger) - failures,
        "failure_count": failures,
        "request_ledger": ledger,
    }


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
    args = parser.parse_args()
    try:
        require_network_gates(allow_network=args.allow_network, environ=os.environ)
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
        return 0 if not result["failure_count"] else 2
    except (DateSourceCacheError, json.JSONDecodeError, OSError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
