from __future__ import annotations

import json
from pathlib import Path


def canonical(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def provider_source_url(row: dict) -> str:
    return str(((row.get("urls") or {}).get("calendar_source") or {}).get("url") or "")


def expected_source_urls(provider_path: Path) -> set[str]:
    urls = {provider_source_url(row) for row in read_jsonl(provider_path)}
    if "" in urls or not urls:
        raise RuntimeError("provider rows contain an invalid source URL")
    return urls


def cache_is_complete(cache: Path, provider_path: Path) -> bool:
    try:
        summary = json.loads((cache / "summary.json").read_text())
    except (OSError, json.JSONDecodeError):
        return False
    rows = read_jsonl(cache / "request-ledger.jsonl")
    latest = {str(row.get("source_url") or ""): row for row in rows}
    expected = expected_source_urls(provider_path)
    return (
        summary.get("failure_count") == 0
        and set(latest) == expected
        and all(latest[url].get("status") == "succeeded" for url in expected)
    )


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def begin_cache_retry(cache: Path, provider_path: Path) -> tuple[Path, list[dict]]:
    provider_rows = read_jsonl(provider_path)
    expected = expected_source_urls(provider_path)
    previous_by_url = {
        str(row.get("source_url") or ""): row
        for row in [
            *read_jsonl(cache / "request-attempt-ledger.jsonl"),
            *read_jsonl(cache / "request-ledger.jsonl"),
        ]
        if str(row.get("source_url") or "") in expected
    }
    previous_rows = [previous_by_url[url] for url in sorted(previous_by_url)]
    successful = {
        str(row.get("source_url") or "")
        for row in previous_rows
        if row.get("status") == "succeeded"
    }
    retry_rows = [row for row in provider_rows if provider_source_url(row) not in successful]
    if not retry_rows:
        raise RuntimeError("cache summary is incomplete but no failed source URL is retryable")
    retry_path = cache / "retry-provider-rows.jsonl"
    retry_path.parent.mkdir(parents=True, exist_ok=True)
    retry_path.write_bytes(b"".join(canonical(row) for row in retry_rows))
    append_jsonl(cache / "request-attempt-ledger.jsonl", previous_rows)
    summary_path = cache / "summary.json"
    if summary_path.is_file():
        append_jsonl(
            cache / "request-attempt-summaries.jsonl",
            [{"phase": "before_retry", "summary": json.loads(summary_path.read_text())}],
        )
    return retry_path, previous_rows


def finish_cache_retry(
    cache: Path,
    provider_path: Path,
    previous_rows: list[dict],
) -> None:
    retry_rows = read_jsonl(cache / "request-ledger.jsonl")
    retry_summary = json.loads((cache / "summary.json").read_text())
    append_jsonl(cache / "request-attempt-ledger.jsonl", retry_rows)
    append_jsonl(
        cache / "request-attempt-summaries.jsonl",
        [{"phase": "retry", "summary": retry_summary}],
    )
    latest = {
        str(row.get("source_url") or ""): row
        for row in [*previous_rows, *retry_rows]
    }
    expected = expected_source_urls(provider_path)
    if set(latest) != expected:
        raise RuntimeError("retry ledger does not account for every expected source URL")
    final_rows = [latest[url] for url in sorted(expected)]
    (cache / "request-ledger.jsonl").write_bytes(
        b"".join(canonical(row) for row in final_rows)
    )
    failed = [row for row in final_rows if row.get("status") != "succeeded"]
    affected = {
        reference.get("target_id")
        for row in failed
        for reference in row.get("target_references") or []
        if reference.get("target_id") not in (None, "")
    }
    summary = {
        "request_count": len(final_rows),
        "success_count": len(final_rows) - len(failed),
        "failure_count": len(failed),
        "failed_urls": sorted(str(row.get("source_url") or "") for row in failed),
        "affected_target_count": len(affected),
    }
    (cache / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
