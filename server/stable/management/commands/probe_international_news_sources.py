from __future__ import annotations

import hashlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import NewsArticle, SourceMode
from stable.services.production_windows import classify_source_error
from stable.adapters.international import (
    FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS,
    FIRST_VERSION_INTERNATIONAL_PROBES,
    INTERNATIONAL_ADAPTERS,
)


def _status_code_from_exception(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        try:
            return int(status_code)
        except (TypeError, ValueError):
            pass
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        return None
    try:
        return int(status_code)
    except (TypeError, ValueError):
        return None


def _deferred_reason(*, error: str = "", status_code: int | None = None, list_count: int = 0, detail_body_length: int = 0) -> str:
    category = classify_source_error(status_code=status_code, message=error, empty_success=not error and list_count == 0)
    if category in {"http_403", "http_429", "captcha_or_blocked"}:
        return "access_limited"
    if error:
        return "probe_failed"
    if list_count == 0:
        return "empty_sample"
    if detail_body_length <= 0:
        return "parse_failed"
    return ""


def _duplicate_count(stubs) -> int:
    count = 0
    for stub in stubs:
        if NewsArticle.objects.filter(source_url=stub.source_url).exists():
            count += 1
            continue
        if NewsArticle.objects.filter(source_site=stub.source_site, source_article_id=stub.source_article_id).exists():
            count += 1
    return count


def _probe_http_status(adapter) -> int | None:
    value = getattr(adapter, "last_listing_http_status", None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _probe_final_url(adapter) -> str:
    return str(getattr(adapter, "last_listing_final_url", "") or "")


def _apply_probe_http_metadata(source_result: dict, adapter) -> None:
    status_code = _probe_http_status(adapter)
    if status_code is not None:
        source_result["http_status"] = status_code
    final_url = _probe_final_url(adapter)
    if final_url:
        source_result["final_url"] = final_url


def _apply_probe_query_errors(source_result: dict, adapter) -> None:
    query_errors = getattr(adapter, "last_listing_query_errors", []) or []
    source_result["query_errors"] = [
        {
            "query": str(item.get("query", "")),
            "error": str(item.get("error", "")),
        }
        for item in query_errors
        if isinstance(item, dict)
    ]


def _apply_probe_adapter_metadata(source_result: dict, adapter) -> None:
    _apply_probe_http_metadata(source_result, adapter)
    _apply_probe_query_errors(source_result, adapter)


def _finalize_probe_contract(source_result: dict, adapter) -> None:
    legacy_status = str(source_result.get("status") or "deferred")
    if legacy_status == "accepted":
        technical_status = "accepted"
    elif source_result.get("deferred_reason") == "access_limited":
        technical_status = "blocked"
    else:
        technical_status = "deferred"
    permission = str(
        getattr(adapter, "automation_permission_status", "unknown") or "unknown"
    ).strip().lower()
    if permission not in {"approved", "unknown", "blocked", "expired"}:
        permission = "unknown"
    source_result["source_key"] = source_result["source"]
    source_result["technical_status"] = technical_status
    source_result["automation_permission_status"] = permission
    source_result["effective_production_status"] = (
        "eligible"
        if technical_status == "accepted" and permission == "approved"
        else "production_blocked"
    )
    source_result["adapter_version"] = str(
        getattr(adapter, "adapter_version", adapter.__class__.__name__) or adapter.__class__.__name__
    )
    source_result["parser_version"] = str(
        getattr(adapter, "parser_version", source_result["adapter_version"])
        or source_result["adapter_version"]
    )
    source_result["reviewed_at"] = timezone.now().isoformat()
    canonical = json.dumps(
        source_result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    source_result["artifact_sha256"] = hashlib.sha256(canonical).hexdigest()


class Command(BaseCommand):
    help = "Dry-run probe international news adapters without writing articles."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            action="append",
            choices=sorted(INTERNATIONAL_ADAPTERS.keys()),
            help="只探测指定来源；可重复传入。默认探测第一版最终国际来源。",
        )
        parser.add_argument(
            "--mode",
            choices=[SourceMode.LATEST, SourceMode.ACCESS, SourceMode.ATTENTION, SourceMode.OFFICIAL],
            help="探测指定来源模式；不传时按第一版来源矩阵使用各自默认/榜单 mode。",
        )
        parser.add_argument("--limit", type=int, default=2, help="每个来源解析的真实新闻数量，默认 2。")
        parser.add_argument("--json", action="store_true", help="以 JSON 输出探测结果。")

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if limit < 1 or limit > 2:
            raise CommandError("--limit 必须在 1-2 之间；每来源详情探测最多 2 篇。")
        requested_mode = options.get("mode")
        if options.get("source"):
            probe_targets = []
            for key in options["source"]:
                adapter_cls = INTERNATIONAL_ADAPTERS.get(key)
                if adapter_cls is None:
                    raise CommandError(f"Unknown source: {key}")
                mode = requested_mode or adapter_cls.source_mode
                probe_targets.append((key, mode))
        elif requested_mode:
            probe_targets = [(key, requested_mode) for key in FIRST_VERSION_INTERNATIONAL_ADAPTER_KEYS]
        else:
            probe_targets = list(FIRST_VERSION_INTERNATIONAL_PROBES)
        results = []
        for key, mode in probe_targets:
            adapter_cls = INTERNATIONAL_ADAPTERS.get(key)
            if adapter_cls is None:
                raise CommandError(f"Unknown source: {key}")
            adapter = adapter_cls()
            source_result = {
                "source": key,
                "region": adapter.racing_region,
                "source_language": adapter.source_language,
                "source_mode": mode,
                "listing_url": adapter.listing_url(1, mode=mode),
                "status": "deferred",
                "deferred_reason": "",
                "http_status": None,
                "final_url": "",
                "parse_quality": {
                    "list_count": 0,
                    "detail_sample_count": 0,
                    "detail_error_count": 0,
                    "detail_body_length": 0,
                    "duplicate_count": 0,
                    "duplicate_ratio": 0.0,
                    "verified_time_count": 0,
                    "missing_time_count": 0,
                },
                "articles": [],
                "query_errors": [],
                "sample_errors": [],
                "error": "",
            }
            try:
                stubs = adapter.fetch_listing(mode, 1)
                _apply_probe_adapter_metadata(source_result, adapter)
                duplicate_count = _duplicate_count(stubs)
                source_result["parse_quality"]["list_count"] = len(stubs)
                source_result["parse_quality"]["duplicate_count"] = duplicate_count
                source_result["parse_quality"]["duplicate_ratio"] = round(duplicate_count / len(stubs), 4) if stubs else 0.0
                stubs = stubs[:limit]
                for stub in stubs:
                    try:
                        detail = adapter.fetch_detail(stub.source_url)
                    except Exception as exc:
                        source_result["parse_quality"]["detail_error_count"] += 1
                        source_result["sample_errors"].append(
                            {
                                "url": stub.source_url,
                                "error": str(exc),
                            }
                        )
                        continue
                    published_at = detail.published_at or stub.published_at
                    published_evidence = (detail.metadata or {}).get("published_at_evidence") or {}
                    published_verified = (detail.metadata or {}).get("published_at_verified")
                    if published_verified is None:
                        published_verified = detail.published_at is not None
                    if published_verified:
                        source_result["parse_quality"]["verified_time_count"] += 1
                    else:
                        source_result["parse_quality"]["missing_time_count"] += 1
                    body_length = len(detail.body_ja_normalized or detail.body_ja_raw or "")
                    source_result["parse_quality"]["detail_sample_count"] += 1
                    source_result["parse_quality"]["detail_body_length"] = max(
                        source_result["parse_quality"]["detail_body_length"],
                        body_length,
                    )
                    source_result["articles"].append(
                        {
                            "title": detail.title_ja or stub.title_ja,
                            "url": stub.source_url,
                            "published_at": published_at.isoformat() if published_at else "",
                            "published_at_verified": bool(published_verified),
                            "published_at_evidence": published_evidence,
                            "body_length": body_length,
                            "has_html": bool(detail.original_content_html),
                            "rank": stub.rank,
                        }
                    )
                reason = _deferred_reason(
                    list_count=source_result["parse_quality"]["list_count"],
                    detail_body_length=source_result["parse_quality"]["detail_body_length"],
                )
                if reason:
                    source_result["status"] = "deferred"
                    source_result["deferred_reason"] = reason
                else:
                    source_result["status"] = "accepted"
            except Exception as exc:  # pragma: no cover - live network probe.
                source_result["error"] = str(exc)
                _apply_probe_adapter_metadata(source_result, adapter)
                status_code = _status_code_from_exception(exc) or source_result["http_status"]
                source_result["http_status"] = status_code
                final_url = _probe_final_url(adapter)
                if final_url:
                    source_result["final_url"] = final_url
                source_result["deferred_reason"] = _deferred_reason(error=str(exc), status_code=status_code)
            _finalize_probe_contract(source_result, adapter)
            results.append(source_result)

        if options["json"]:
            self.stdout.write(json.dumps(results, ensure_ascii=False, indent=2))
            return

        for item in results:
            self.stdout.write(
                f"[{item['source']}] {item['region']} / {item['source_language']} / {item['source_mode']} / {item['listing_url']}"
            )
            self.stdout.write(
                "  CONTRACT "
                f"technical_status={item['technical_status']} "
                f"automation_permission_status={item['automation_permission_status']} "
                f"effective_production_status={item['effective_production_status']} "
                f"adapter_version={item['adapter_version']} "
                f"parser_version={item['parser_version']} "
                f"reviewed_at={item['reviewed_at']} "
                f"artifact_sha256={item['artifact_sha256']}"
            )
            if item["error"]:
                self.stdout.write(f"  ERROR: {item['error']}")
                for query_error in item.get("query_errors", []):
                    self.stdout.write(f"  QUERY ERROR: {query_error['query']} | {query_error['error']}")
                continue
            for query_error in item.get("query_errors", []):
                self.stdout.write(f"  QUERY ERROR: {query_error['query']} | {query_error['error']}")
            for article in item["articles"]:
                rank_text = f"rank={article['rank']} | " if article.get("rank") else ""
                self.stdout.write(f"  - {rank_text}{article['title']} | body={article['body_length']} | {article['url']}")
