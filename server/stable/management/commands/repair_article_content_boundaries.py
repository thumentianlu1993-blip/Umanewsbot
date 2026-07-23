from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from stable.adapters.international import INTERNATIONAL_ADAPTERS
from stable.models import NewsArticle, QQPushDelivery, SourceSite
from stable.services.operations import log_operation


_MANIFEST_SCHEMA_VERSION = 2
_MANIFEST_ROW_KEYS = {
    "article_id",
    "decision",
    "updated_at",
    "original_content_html_sha256",
    "before_body_sha256",
    "after_body_sha256",
    "after_title_sha256",
    "after_body_normalized_sha256",
    "after_parse_metadata_sha256",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCAN_SOURCE_SITE = SourceSite.HORSE_RACING_NATION
_SCAN_LIMIT_MAX = 500


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _persisted_parse_metadata(detail: Any) -> dict[str, Any]:
    return {
        "body_parse_status": detail.metadata.get("body_parse_status", ""),
        "body_selector": detail.metadata.get("body_selector", ""),
        "body_cleaning": detail.metadata.get("body_cleaning", {}),
    }


def _parse_metadata_sha256(detail: Any) -> str:
    canonical = json.dumps(
        _persisted_parse_metadata(detail),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(canonical)


def _effective_body_layer(article: NewsArticle) -> str:
    manual_fields = set(article.manually_edited_fields or [])
    if "body_zh" in manual_fields and article.body_zh:
        return "manual_body_zh"
    if article.rewrite_body_zh:
        return "rewrite_body_zh"
    if article.body_zh:
        return "body_zh"
    if article.translated_body_zh:
        return "translated_body_zh"
    if article.body_ja_normalized:
        return "body_ja_normalized"
    if article.body_ja_raw:
        return "body_ja_raw"
    return "empty"


class Command(BaseCommand):
    help = (
        "使用已保存 HTML 离线检查或修复国际新闻正文边界；"
        "显式文章 ID 默认 dry-run，HRN 来源扫描始终只读。"
    )

    def add_arguments(self, parser):
        parser.add_argument("--article-id", dest="article_ids", action="append", type=int)
        parser.add_argument("--source-site")
        parser.add_argument("--after-id", type=int)
        parser.add_argument("--max-id", type=int)
        parser.add_argument("--limit", type=int)
        parser.add_argument("--manifest")
        parser.add_argument("--manifest-sha256")
        parser.add_argument(
            "--commit",
            action="store_true",
            help="按批准 manifest 事务写回正文和审计元数据。",
        )

    def handle(self, *args, **options):
        article_ids = list(dict.fromkeys(options.get("article_ids") or []))
        source_site = options.get("source_site")

        if source_site:
            scan_options = {key: value for key, value in options.items() if key != "article_ids"}
            self._handle_scan(article_ids=article_ids, **scan_options)
            return

        scan_values = (options.get("after_id"), options.get("max_id"), options.get("limit"))
        if any(value is not None for value in scan_values):
            raise CommandError("--after-id、--max-id 和 --limit 只能与 --source-site 一起用于只读扫描")
        if not article_ids:
            raise CommandError("必须至少提供一个 --article-id")

        commit = bool(options.get("commit"))
        manifest_path = options.get("manifest")
        manifest_sha256 = options.get("manifest_sha256")
        if commit:
            if not manifest_path or not manifest_sha256:
                raise CommandError("--commit 必须同时提供 --manifest 和 --manifest-sha256")
            manifest = self._load_manifest(manifest_path, manifest_sha256)
            with transaction.atomic():
                articles = list(
                    NewsArticle.objects.select_for_update().filter(pk__in=article_ids).order_by("id")
                )
                prepared = self._prepare_articles(articles, requested_ids=article_ids)
                self._validate_manifest(
                    manifest,
                    articles=articles,
                    prepared=prepared,
                    requested_ids=article_ids,
                )
                payloads = self._write_prepared(
                    prepared,
                    approval_manifest_sha256=manifest_sha256.lower(),
                )
        else:
            if manifest_path or manifest_sha256:
                raise CommandError("批准 manifest 仅用于 --commit；普通 dry-run 只需显式 --article-id")
            articles = list(NewsArticle.objects.filter(pk__in=article_ids).order_by("id"))
            qq_delivery_counts = {
                article_id: count
                for article_id, count in (
                    QQPushDelivery.objects.filter(article_id__in=article_ids)
                    .values("article_id")
                    .annotate(count=Count("id"))
                    .values_list("article_id", "count")
                )
            }
            prepared = self._prepare_articles(
                articles,
                requested_ids=article_ids,
                dry_run_qq_delivery_counts=qq_delivery_counts,
            )
            payloads = [item[2] for item in prepared]

        self.stdout.write(
            json.dumps(
                {"mode": "commit" if commit else "dry_run", "articles": payloads},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    def _handle_scan(self, *, article_ids: list[int], **options):
        if article_ids:
            raise CommandError("只读来源扫描不能同时提供 --article-id")
        if options.get("commit"):
            raise CommandError("来源扫描始终只读，禁止 --commit")
        if options.get("manifest") or options.get("manifest_sha256"):
            raise CommandError("来源扫描不接受批准 manifest")

        source_site = options.get("source_site")
        after_id = options.get("after_id")
        max_id = options.get("max_id")
        limit = options.get("limit")
        if after_id is None or max_id is None or limit is None:
            raise CommandError("来源扫描必须显式提供 --after-id、--max-id 和 --limit")
        if source_site != _SCAN_SOURCE_SITE:
            raise CommandError(f"只支持 {_SCAN_SOURCE_SITE} 的历史正文边界扫描")
        if after_id < 0 or max_id < 1 or after_id > max_id:
            raise CommandError("扫描范围必须满足 0 <= after-id <= max-id 且 max-id >= 1")
        if not 1 <= limit <= _SCAN_LIMIT_MAX:
            raise CommandError(f"--limit 必须在 1..{_SCAN_LIMIT_MAX} 之间")

        articles = list(
            NewsArticle.objects.filter(
                source_site=source_site,
                id__gt=after_id,
                id__lte=max_id,
            )
            .annotate(qq_delivery_count=Count("qq_push_deliveries"))
            .order_by("id")[:limit]
        )
        counts = {
            "total": len(articles),
            "missing_original_html": 0,
            "selector_not_found": 0,
            "empty_after_cleaning": 0,
            "parse_error": 0,
            "changed": 0,
            "unchanged": 0,
        }
        rows = []
        for article in articles:
            row, category = self._scan_article(article)
            rows.append(row)
            counts[category] += 1

        next_after_id = rows[-1]["article_id"] if rows else after_id
        payload = {
            "mode": "scan",
            "scope": {
                "source_site": source_site,
                "after_id": after_id,
                "max_id": max_id,
                "limit": limit,
            },
            "counts": counts,
            "next_after_id": next_after_id,
            "has_more": bool(
                next_after_id < max_id
                and NewsArticle.objects.filter(
                    source_site=source_site,
                    id__gt=next_after_id,
                    id__lte=max_id,
                ).exists()
            ),
            "articles": rows,
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    def _scan_article(self, article: NewsArticle) -> tuple[dict[str, Any], str]:
        effective_layer = _effective_body_layer(article)
        before_length = len(article.body_ja_raw or "")
        row: dict[str, Any] = {
            "article_id": article.id,
            "source_site": article.source_site,
            "updated_at": article.updated_at.isoformat(),
            "original_content_html_sha256": _sha256(article.original_content_html),
            "before_body_sha256": _sha256(article.body_ja_raw),
            "after_body_sha256": _sha256(""),
            "effective_body_sha256": _sha256(article.effective_body),
            "effective_body_layer": effective_layer,
            "manually_edited_fields": list(article.manually_edited_fields or []),
            "has_rewrite_body": bool(article.rewrite_body_zh),
            "workflow_status": article.workflow_status,
            "translation_status": article.translation_status,
            "automation_status": article.automation_status,
            "qq_delivery_count": int(article.qq_delivery_count),
            "body_parse_status": "",
            "body_selector": "",
            "status": "",
            "before_length": before_length,
            "after_length": 0,
            "length_delta": -before_length,
        }
        if not article.original_content_html:
            row.update(body_parse_status="missing_original_html", status="missing_original_html")
            return row, "missing_original_html"

        adapter_class = INTERNATIONAL_ADAPTERS.get(article.source_site)
        if adapter_class is None:
            row.update(body_parse_status="unsupported_source", status="parse_error")
            return row, "parse_error"
        try:
            detail = adapter_class().parse_detail_html(article.original_content_html, url=article.source_url)
        except Exception as exc:  # noqa: BLE001 - 批量只读审计必须保留其他文章的 scope
            row.update(
                body_parse_status="parse_error",
                status="parse_error",
                error_type=type(exc).__name__,
            )
            return row, "parse_error"

        parse_status = str(detail.metadata.get("body_parse_status") or "unknown")
        row["body_parse_status"] = parse_status
        row["body_selector"] = detail.metadata.get("body_selector", "")
        row["after_body_sha256"] = _sha256(detail.body_ja_raw)
        row["after_length"] = len(detail.body_ja_raw or "")
        row["length_delta"] = row["after_length"] - before_length
        if parse_status != "ok" or not detail.body_ja_normalized:
            if parse_status in {"selector_not_found", "empty_after_cleaning"}:
                category = parse_status
            else:
                category = "parse_error"
            row["status"] = category
            return row, category

        category = "changed" if row["before_body_sha256"] != row["after_body_sha256"] else "unchanged"
        row["status"] = category
        return row, category

    def _load_manifest(self, manifest_path: str, expected_sha256: str) -> dict[str, Any]:
        if not _SHA256_RE.fullmatch((expected_sha256 or "").lower()):
            raise CommandError("--manifest-sha256 必须是 64 位十六进制 SHA-256")
        path = Path(manifest_path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CommandError(f"无法读取批准 manifest: {exc}") from exc
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != expected_sha256.lower():
            raise CommandError("批准 manifest 文件 SHA-256 不匹配")
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError("批准 manifest 不是有效 UTF-8 JSON") from exc
        if not isinstance(manifest, dict):
            raise CommandError("批准 manifest 顶层必须是对象")
        return manifest

    def _validate_manifest(
        self,
        manifest: dict[str, Any],
        *,
        articles: list[NewsArticle],
        prepared: list[tuple[NewsArticle, Any, dict[str, Any]]],
        requested_ids: list[int],
    ) -> None:
        if set(manifest) != {"schema_version", "source_site", "articles"}:
            raise CommandError("批准 manifest 顶层 schema 不匹配")
        if manifest.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
            raise CommandError(f"批准 manifest schema_version 必须为 {_MANIFEST_SCHEMA_VERSION}")
        source_site = manifest.get("source_site")
        if not isinstance(source_site, str) or not source_site:
            raise CommandError("批准 manifest source_site 无效")
        rows = manifest.get("articles")
        if not isinstance(rows, list) or not rows:
            raise CommandError("批准 manifest articles 必须是非空列表")

        row_by_id: dict[int, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != _MANIFEST_ROW_KEYS:
                raise CommandError("批准 manifest 文章行 schema 不匹配")
            article_id = row.get("article_id")
            if not isinstance(article_id, int) or isinstance(article_id, bool) or article_id < 1:
                raise CommandError("批准 manifest article_id 无效")
            if article_id in row_by_id:
                raise CommandError(f"批准 manifest 含重复文章 ID: {article_id}")
            if row.get("decision") != "repair_source_body":
                raise CommandError(f"文章 {article_id} 的批准决定无效")
            if not isinstance(row.get("updated_at"), str) or not row["updated_at"]:
                raise CommandError(f"文章 {article_id} 的 updated_at 无效")
            for key in (
                "original_content_html_sha256",
                "before_body_sha256",
                "after_body_sha256",
                "after_title_sha256",
                "after_body_normalized_sha256",
                "after_parse_metadata_sha256",
            ):
                if not isinstance(row.get(key), str) or not _SHA256_RE.fullmatch(row[key]):
                    raise CommandError(f"文章 {article_id} 的 {key} 无效")
            row_by_id[article_id] = row

        requested_set = set(requested_ids)
        if len(requested_set) != len(requested_ids):
            raise CommandError("--article-id 不得重复")
        if set(row_by_id) != requested_set:
            raise CommandError("批准 manifest 文章集合与 --article-id 精确集合不匹配")
        if len(articles) != len(requested_set):
            missing = sorted(requested_set - {article.id for article in articles})
            raise CommandError(f"文章不存在: {missing}")

        prepared_by_id = {article.id: payload for article, _detail, payload in prepared}
        for article in articles:
            row = row_by_id[article.id]
            payload = prepared_by_id[article.id]
            if article.source_site != source_site:
                raise CommandError(f"文章 {article.id} 的来源与批准 manifest 不匹配")
            expected = {
                "updated_at": article.updated_at.isoformat(),
                "original_content_html_sha256": _sha256(article.original_content_html),
                "before_body_sha256": payload["before_sha256"],
                "after_body_sha256": payload["after_sha256"],
                "after_title_sha256": payload["after_title_sha256"],
                "after_body_normalized_sha256": payload["after_body_normalized_sha256"],
                "after_parse_metadata_sha256": payload["after_parse_metadata_sha256"],
            }
            drifted = [key for key, value in expected.items() if row.get(key) != value]
            if drifted:
                raise CommandError(f"文章 {article.id} 批准输入/输出已漂移: {', '.join(drifted)}")

    def _prepare_articles(
        self,
        articles: list[NewsArticle],
        *,
        requested_ids: list[int],
        dry_run_qq_delivery_counts: dict[int, int] | None = None,
    ) -> list[tuple[NewsArticle, Any, dict[str, Any]]]:
        found_ids = {article.id for article in articles}
        missing_ids = [article_id for article_id in requested_ids if article_id not in found_ids]
        if missing_ids:
            raise CommandError(f"文章不存在: {missing_ids}")

        prepared = []
        for article in articles:
            adapter_class = INTERNATIONAL_ADAPTERS.get(article.source_site)
            if adapter_class is None:
                raise CommandError(
                    f"文章 {article.id} 的来源 {article.source_site} 不支持国际正文重解析"
                )
            if not article.original_content_html:
                raise CommandError(f"文章 {article.id} 缺少 original_content_html")

            detail = adapter_class().parse_detail_html(article.original_content_html, url=article.source_url)
            parse_status = detail.metadata.get("body_parse_status")
            if parse_status != "ok" or not detail.body_ja_normalized:
                raise CommandError(f"文章 {article.id} 正文重解析失败: {parse_status or 'unknown'}")
            if not detail.title_ja:
                raise CommandError(f"文章 {article.id} 标题重解析失败")

            before_sha = _sha256(article.body_ja_raw)
            after_sha = _sha256(detail.body_ja_raw)
            before_title_sha = _sha256(article.title_ja)
            after_title_sha = _sha256(detail.title_ja)
            payload = {
                "article_id": article.id,
                "source_site": article.source_site,
                "updated_at": article.updated_at.isoformat(),
                "body_parse_status": parse_status,
                "body_selector": detail.metadata.get("body_selector", ""),
                "body_cleaning": detail.metadata.get("body_cleaning", {}),
                "before_sha256": before_sha,
                "after_sha256": after_sha,
                "before_body_sha256": before_sha,
                "after_body_sha256": after_sha,
                "after_body_normalized_sha256": _sha256(detail.body_ja_normalized),
                "original_content_html_sha256": _sha256(article.original_content_html),
                "before_length": len(article.body_ja_raw or ""),
                "after_length": len(detail.body_ja_raw or ""),
                "length_delta": len(detail.body_ja_raw or "") - len(article.body_ja_raw or ""),
                "before_title": article.title_ja,
                "after_title": detail.title_ja,
                "before_title_sha256": before_title_sha,
                "after_title_sha256": after_title_sha,
                "after_parse_metadata_sha256": _parse_metadata_sha256(detail),
                "body_changed": before_sha != after_sha,
                "title_changed": before_title_sha != after_title_sha,
                "changed": before_sha != after_sha or before_title_sha != after_title_sha,
            }
            if dry_run_qq_delivery_counts is not None:
                effective_body = article.effective_body
                before_body = article.body_ja_raw or ""
                after_body = detail.body_ja_raw or ""
                payload.update(
                    workflow_status=article.workflow_status,
                    translation_status=article.translation_status,
                    automation_status=article.automation_status,
                    effective_body_layer=_effective_body_layer(article),
                    effective_body_sha256=_sha256(effective_body),
                    manually_edited_fields=list(article.manually_edited_fields or []),
                    has_rewrite_body=bool(article.rewrite_body_zh),
                    qq_delivery_count=int(dry_run_qq_delivery_counts.get(article.id, 0)),
                    published_to_web_at=(
                        article.published_to_web_at.isoformat()
                        if article.published_to_web_at
                        else None
                    ),
                    before_body_start_excerpt=before_body[:160],
                    before_body_end_excerpt=before_body[-160:],
                    after_body_start_excerpt=after_body[:160],
                    after_body_end_excerpt=after_body[-160:],
                )
            prepared.append((article, detail, payload))
        return prepared

    def _write_prepared(
        self,
        prepared: list[tuple[NewsArticle, Any, dict[str, Any]]],
        *,
        approval_manifest_sha256: str,
    ) -> list[dict[str, Any]]:
        payloads = []
        repaired_at = timezone.now().isoformat()
        for article, detail, payload in prepared:
            repair_metadata = {
                **payload,
                "approval_manifest_sha256": approval_manifest_sha256,
                "repaired_at": repaired_at,
            }
            article.title_ja = detail.title_ja
            article.body_ja_raw = detail.body_ja_raw
            article.body_ja_normalized = detail.body_ja_normalized
            article.translation_metadata = {
                **(article.translation_metadata or {}),
                "body_parse_status": payload["body_parse_status"],
                "body_selector": payload["body_selector"],
                "body_cleaning": payload["body_cleaning"],
                "content_boundary_repair": repair_metadata,
            }
            article.save(
                update_fields=[
                    "title_ja",
                    "body_ja_raw",
                    "body_ja_normalized",
                    "translation_metadata",
                    "updated_at",
                ]
            )
            log_operation(
                action_type="article_content_boundary_repaired",
                target_type="article",
                target_id=article.id,
                detail=(
                    f"离线正文边界修复 manifest={approval_manifest_sha256[:12]} "
                    f"title={payload['before_title_sha256'][:12]}->{payload['after_title_sha256'][:12]} "
                    f"body={payload['before_sha256'][:12]}->{payload['after_sha256'][:12]}"
                ),
            )
            payloads.append(payload)
        return payloads
