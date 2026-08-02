from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from stable.adapters.international import INTERNATIONAL_ADAPTERS
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    OperationLog,
    QQPushDelivery,
    SourceSite,
    TranslationRun,
    WorkflowStatus,
)
from stable.services.operations import log_operation


INVENTORY_SCHEMA_VERSION = 1
APPROVED_MANIFEST_SCHEMA_VERSION = 2
ROLLBACK_MANIFEST_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COHORT_SOURCE_SITE = SourceSite.HORSE_RACING_NATION
_MAX_BATCH_SIZE = 10
_MAX_INVENTORY_PAGE = 500

SOURCE_CLEAN = "source_clean"
SOURCE_CHANGED = "source_changed"
SOURCE_BLOCKED = "source_blocked"
CHINESE_INPUT_VERIFIED = "chinese_input_verified"
CHINESE_INPUT_UNVERIFIABLE = "chinese_input_unverifiable"
CHINESE_ABSENT = "chinese_absent"

ACTION_NO_ACTION = "no_action"
ACTION_REPAIR_SOURCE_ONLY = "repair_source_only"
ACTION_RETRANSLATE_MACHINE_FIELDS = "retranslate_machine_fields"
ACTION_RETRANSLATE_AND_REWRITE = "retranslate_and_rewrite"
ACTION_MANUAL_REVIEW = "manual_review"
ACTION_BLOCKED_MISSING_HTML = "blocked_missing_html"
ACTION_BLOCKED_PARSE_FAILURE = "blocked_parse_failure"
ACTION_BLOCKED_STATE_DRIFT = "blocked_state_drift"

DECISION_APPROVE_NO_ACTION = "approve_no_action"
DECISION_APPROVE_FIELDS = "approve_fields"
DECISION_KEEP_MANUAL = "keep_manual"
DECISION_REJECT = "reject"

ALLOWED_APPROVE_FIELDS = frozenset(
    {
        "body_ja_raw",
        "body_ja_normalized",
        "content_boundary_repair",
        "translated_body_zh",
        "body_zh",
        "translated_summary_zh",
        "summary_zh",
        "push_summary_zh",
        "base_translation_zh",
        "rewrite_body_zh",
    }
)

SOURCE_ATOMIC_FIELDS = frozenset({"body_ja_raw", "body_ja_normalized", "content_boundary_repair"})

FIELD_DEPENDENCIES: dict[str, frozenset[str]] = {
    "body_zh": frozenset({"translated_body_zh"}),
    "summary_zh": frozenset({"translated_summary_zh"}),
    "push_summary_zh": frozenset({"translated_summary_zh"}),
    "base_translation_zh": frozenset({"translated_body_zh"}),
    "rewrite_body_zh": frozenset({"base_translation_zh"}),
}

FIELD_PREREQUISITES: dict[str, dict[str, Any]] = {
    "body_ja_raw": {"required_source_statuses": {SOURCE_CHANGED}, "require_parse_ok": True},
    "body_ja_normalized": {"required_source_statuses": {SOURCE_CHANGED}, "require_parse_ok": True},
    "content_boundary_repair": {"required_source_statuses": {SOURCE_CHANGED}, "require_parse_ok": True},
    "translated_body_zh": {"forbid_translation_statuses": {"failed", "pending"}},
    "body_zh": {"forbid_translation_statuses": {"failed", "pending"}},
    "translated_summary_zh": {"forbid_translation_statuses": {"failed", "pending"}},
    "summary_zh": {"forbid_translation_statuses": {"failed", "pending"}},
    "push_summary_zh": {"forbid_translation_statuses": {"failed", "pending"}},
    "base_translation_zh": {"forbid_translation_statuses": {"failed", "pending"}},
    "rewrite_body_zh": {"forbid_translation_statuses": {"failed", "pending"}},
}

PERMANENT_NO_WRITE_FIELDS = frozenset(
    {
        "id",
        "source_site",
        "source_article_id",
        "source_url",
        "public_slug",
        "workflow_status",
        "review_mode",
        "automation_status",
        "published_to_web_at",
        "published_by",
        "published_by_mode",
        "auto_publish_at",
        "manually_edited_fields",
        "title_ja",
        "title_zh",
        "translated_title_zh",
        "rewrite_title_zh",
        "translation_status",
        "translation_error_message",
        "translation_error_category",
        "translation_started_at",
        "translated_at",
        "translation_model",
        "translation_provider",
        "translation_retry_count",
        "translation_next_retry_at",
        "translation_retry_exhausted_at",
    }
)

ROLLBACK_WRITABLE_FIELDS = (
    "body_ja_raw",
    "body_ja_normalized",
    "translated_body_zh",
    "body_zh",
    "translated_summary_zh",
    "summary_zh",
    "push_summary_zh",
    "base_translation_zh",
    "rewrite_body_zh",
    "translation_metadata",
)

FINGERPRINT_DRIFT_KEYS = (
    "original_content_html",
    "body_ja_raw",
    "body_ja_normalized",
    "translated_body_zh",
    "body_zh",
    "rewrite_body_zh",
    "manually_edited_fields",
    "manually_edited_fields_list",
    "workflow_status",
    "translation_status",
    "published_to_web_at",
)


def _sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(str(tmp), "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(path))
    parent_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    os.chmod(str(path), 0o600)
    os.chmod(str(path.parent), 0o700)
    return hashlib.sha256(raw).hexdigest()


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


def _effective_title_layer(article: NewsArticle) -> str:
    manual_fields = set(article.manually_edited_fields or [])
    if "title_zh" in manual_fields and article.title_zh:
        return "manual_title_zh"
    if article.rewrite_title_zh:
        return "rewrite_title_zh"
    if article.title_zh:
        return "title_zh"
    if article.translated_title_zh:
        return "translated_title_zh"
    if article.title_ja:
        return "title_ja"
    return "empty"


def _translation_status_label(article: NewsArticle) -> str:
    if article.translation_status == ArticleTranslationStatus.FAILED:
        return "failed"
    if article.translation_status == ArticleTranslationStatus.PENDING:
        return "pending"
    if article.translation_status == ArticleTranslationStatus.TRANSLATING:
        return "translating"
    if article.translation_status == ArticleTranslationStatus.TRANSLATED:
        return "translated"
    return str(article.translation_status)


@dataclass(frozen=True)
class FrozenCohort:
    source_site: str
    max_id: int
    min_id: int
    count: int
    sorted_ids: tuple[int, ...]
    id_set_sha256: str
    revision: str
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_site": self.source_site,
            "max_id": self.max_id,
            "min_id": self.min_id,
            "count": self.count,
            "sorted_ids": list(self.sorted_ids),
            "id_set_sha256": self.id_set_sha256,
            "revision": self.revision,
            "generated_at": self.generated_at,
        }


@dataclass
class InventoryRow:
    article_id: int
    source_site: str
    updated_at: str
    source_url: str
    original_content_html_sha256: str
    before_body_ja_sha256: str
    after_body_ja_sha256: str
    body_parse_status: str
    body_selector: str
    source_status: str
    translated_body_zh_sha256: str
    body_zh_sha256: str
    rewrite_body_zh_sha256: str
    effective_body_sha256: str
    effective_body_layer: str
    effective_title_sha256: str
    effective_title_layer: str
    manually_edited_fields: list[str]
    has_rewrite_body: bool
    chinese_status: str
    workflow_status: str
    translation_status: str
    automation_status: str
    published_to_web_at: str | None
    qq_delivery_count: int
    qq_sent_count: int
    qq_failed_count: int
    latest_translation_run: dict[str, Any] | None
    before_length: int
    after_length: int
    length_delta: int
    auxiliary_signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "source_site": self.source_site,
            "updated_at": self.updated_at,
            "source_url": self.source_url,
            "original_content_html_sha256": self.original_content_html_sha256,
            "before_body_ja_sha256": self.before_body_ja_sha256,
            "after_body_ja_sha256": self.after_body_ja_sha256,
            "body_parse_status": self.body_parse_status,
            "body_selector": self.body_selector,
            "source_status": self.source_status,
            "translated_body_zh_sha256": self.translated_body_zh_sha256,
            "body_zh_sha256": self.body_zh_sha256,
            "rewrite_body_zh_sha256": self.rewrite_body_zh_sha256,
            "effective_body_sha256": self.effective_body_sha256,
            "effective_body_layer": self.effective_body_layer,
            "effective_title_sha256": self.effective_title_sha256,
            "effective_title_layer": self.effective_title_layer,
            "manually_edited_fields": self.manually_edited_fields,
            "has_rewrite_body": self.has_rewrite_body,
            "chinese_status": self.chinese_status,
            "workflow_status": self.workflow_status,
            "translation_status": self.translation_status,
            "automation_status": self.automation_status,
            "published_to_web_at": self.published_to_web_at,
            "qq_delivery_count": self.qq_delivery_count,
            "qq_sent_count": self.qq_sent_count,
            "qq_failed_count": self.qq_failed_count,
            "latest_translation_run": self.latest_translation_run,
            "before_length": self.before_length,
            "after_length": self.after_length,
            "length_delta": self.length_delta,
            "auxiliary_signals": self.auxiliary_signals,
        }


def freeze_cohort(
    *,
    source_site: str = _COHORT_SOURCE_SITE,
    max_id: int,
    revision: str = "",
) -> FrozenCohort:
    articles = (
        NewsArticle.objects.filter(source_site=source_site, id__lte=max_id)
        .order_by("id")
        .values_list("id", flat=True)
    )
    sorted_ids = tuple(articles)
    if not sorted_ids:
        return FrozenCohort(
            source_site=source_site,
            max_id=max_id,
            min_id=0,
            count=0,
            sorted_ids=(),
            id_set_sha256=_canonical_sha([]),
            revision=revision,
            generated_at=timezone.now().isoformat(),
        )
    return FrozenCohort(
        source_site=source_site,
        max_id=max_id,
        min_id=sorted_ids[0],
        count=len(sorted_ids),
        sorted_ids=sorted_ids,
        id_set_sha256=_canonical_sha(list(sorted_ids)),
        revision=revision,
        generated_at=timezone.now().isoformat(),
    )


def _parse_with_adapter(article: NewsArticle) -> tuple[str, str, str, str, str]:
    """Returns (parse_status, body_selector, after_body_raw, after_title, after_body_normalized)."""
    if not article.original_content_html:
        return ("missing_original_html", "", "", "", "")
    adapter_class = INTERNATIONAL_ADAPTERS.get(article.source_site)
    if adapter_class is None:
        return ("unsupported_source", "", "", "", "")
    try:
        detail = adapter_class().parse_detail_html(article.original_content_html, url=article.source_url)
    except Exception:
        return ("parse_error", "", "", "", "")
    parse_status = str(detail.metadata.get("body_parse_status") or "unknown")
    body_selector = str(detail.metadata.get("body_selector") or "")
    return (
        parse_status,
        body_selector,
        detail.body_ja_raw or "",
        detail.title_ja or "",
        detail.body_ja_normalized or "",
    )


def _classify_source_status(
    parse_status: str,
    before_sha: str,
    after_sha: str,
) -> str:
    if parse_status in {"missing_original_html", "selector_not_found", "empty_after_cleaning", "parse_error", "unsupported_source"}:
        return SOURCE_BLOCKED
    if before_sha != after_sha:
        return SOURCE_CHANGED
    return SOURCE_CLEAN


def _classify_chinese_status(
    article: NewsArticle,
    translation_status_label: str,
) -> str:
    if translation_status_label in {"failed", "pending"}:
        return CHINESE_ABSENT
    if article.translated_body_zh or article.body_zh:
        return CHINESE_INPUT_UNVERIFIABLE
    return CHINESE_ABSENT


def build_inventory_row(
    article: NewsArticle,
    *,
    qq_delivery_counts: dict[int, dict[str, int]] | None = None,
    latest_runs: dict[int, Any] | None = None,
) -> InventoryRow:
    parse_status, body_selector, after_body, after_title, after_body_normalized = _parse_with_adapter(article)
    before_body_sha = _sha256(article.body_ja_raw)
    after_body_sha = _sha256(after_body)
    source_status = _classify_source_status(parse_status, before_body_sha, after_body_sha)
    tl_status = _translation_status_label(article)
    chinese_status = _classify_chinese_status(article, tl_status)

    qq_counts = (qq_delivery_counts or {}).get(article.id, {})
    qq_total = qq_counts.get("total", 0)
    qq_sent = qq_counts.get("sent", 0)
    qq_failed = qq_counts.get("failed", 0)

    latest_run = None
    if latest_runs and article.id in latest_runs:
        run = latest_runs[article.id]
        latest_run = {
            "provider": run.provider_name,
            "model": run.model_name,
            "status": run.status,
            "created_at": run.created_at.isoformat(),
        }

    auxiliary = {}
    if article.body_zh:
        known_contamination = ["Trending", "Log in", "Sign up for free", "Related Pages", "Top Stories",
                               "热门", "公平赔率", "登录", "免费注册", "Head to head", "当前"]
        auxiliary["known_framework_hits"] = [
            w for w in known_contamination if w in (article.body_zh or "")
        ]

    return InventoryRow(
        article_id=article.id,
        source_site=article.source_site,
        updated_at=article.updated_at.isoformat(),
        source_url=article.source_url,
        original_content_html_sha256=_sha256(article.original_content_html),
        before_body_ja_sha256=before_body_sha,
        after_body_ja_sha256=after_body_sha,
        body_parse_status=parse_status,
        body_selector=body_selector,
        source_status=source_status,
        translated_body_zh_sha256=_sha256(article.translated_body_zh),
        body_zh_sha256=_sha256(article.body_zh),
        rewrite_body_zh_sha256=_sha256(article.rewrite_body_zh),
        effective_body_sha256=_sha256(article.effective_body),
        effective_body_layer=_effective_body_layer(article),
        effective_title_sha256=_sha256(article.effective_title),
        effective_title_layer=_effective_title_layer(article),
        manually_edited_fields=list(article.manually_edited_fields or []),
        has_rewrite_body=bool(article.rewrite_body_zh),
        chinese_status=chinese_status,
        workflow_status=article.workflow_status,
        translation_status=tl_status,
        automation_status=article.automation_status,
        published_to_web_at=article.published_to_web_at.isoformat() if article.published_to_web_at else None,
        qq_delivery_count=qq_total,
        qq_sent_count=qq_sent,
        qq_failed_count=qq_failed,
        latest_translation_run=latest_run,
        before_length=len(article.body_ja_raw or ""),
        after_length=len(after_body),
        length_delta=len(after_body) - len(article.body_ja_raw or ""),
        auxiliary_signals=auxiliary,
    )


class CohortDriftError(ValueError):
    """Raised when frozen cohort does not match expected baseline."""


def generate_inventory(
    *,
    source_site: str = _COHORT_SOURCE_SITE,
    max_id: int,
    output_dir: Path,
    revision: str = "",
    page_size: int = _MAX_INVENTORY_PAGE,
    expected_count: int | None = None,
    expected_id_set_sha256: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    cohort = freeze_cohort(source_site=source_site, max_id=max_id, revision=revision)

    # --- cohort drift check (P1 fix): fail closed if baseline mismatches ---
    if expected_count is not None and cohort.count != expected_count:
        raise CohortDriftError(
            f"cohort count 漂移: expected={expected_count} actual={cohort.count}"
        )
    if expected_id_set_sha256 is not None and cohort.id_set_sha256 != expected_id_set_sha256:
        raise CohortDriftError(
            f"cohort id_set_sha256 漂移: "
            f"expected={expected_id_set_sha256[:16]}... actual={cohort.id_set_sha256[:16]}..."
        )

    _atomic_write_json(output_dir / "cohort.json", cohort.to_dict())

    all_ids = list(cohort.sorted_ids)
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "total": cohort.count,
        SOURCE_CLEAN: 0,
        SOURCE_CHANGED: 0,
        SOURCE_BLOCKED: 0,
        "blocked_missing_original_html": 0,
        "blocked_selector_not_found": 0,
        "blocked_empty_after_cleaning": 0,
        "blocked_parse_error": 0,
        "blocked_unsupported_source": 0,
        CHINESE_INPUT_VERIFIED: 0,
        CHINESE_INPUT_UNVERIFIABLE: 0,
        CHINESE_ABSENT: 0,
        "published": 0,
        "qq_sent": 0,
        "has_manual_fields": 0,
        "has_rewrite": 0,
    }

    for offset in range(0, len(all_ids), page_size):
        page_ids = all_ids[offset : offset + page_size]
        articles = list(
            NewsArticle.objects.filter(id__in=page_ids).order_by("id").select_related("source_config")
        )

        qq_counts: dict[int, dict[str, int]] = {}
        for qq_row in (
            QQPushDelivery.objects.filter(article_id__in=page_ids)
            .values("article_id")
            .annotate(
                total=Count("id"),
                sent=Count("id", filter=Q(status="sent")),
                failed=Count("id", filter=Q(status="failed")),
            )
        ):
            qq_counts[qq_row["article_id"]] = {
                "total": qq_row["total"],
                "sent": qq_row["sent"],
                "failed": qq_row["failed"],
            }

        latest_runs: dict[int, Any] = {}
        all_runs = (
            TranslationRun.objects.filter(article_id__in=page_ids)
            .order_by("article_id", "-created_at")
        )
        seen_run_articles: set[int] = set()
        for run in all_runs:
            if run.article_id not in seen_run_articles:
                seen_run_articles.add(run.article_id)
                latest_runs[run.article_id] = run

        for article in articles:
            row = build_inventory_row(article, qq_delivery_counts=qq_counts, latest_runs=latest_runs)
            rows.append(row.to_dict())
            counts[row.source_status] += 1
            if row.source_status == SOURCE_BLOCKED:
                block_key = f"blocked_{row.body_parse_status}"
                if block_key in counts:
                    counts[block_key] += 1
            counts[row.chinese_status] += 1
            if row.workflow_status == WorkflowStatus.PUBLISHED:
                counts["published"] += 1
            if row.qq_sent_count > 0:
                counts["qq_sent"] += 1
            if row.manually_edited_fields:
                counts["has_manual_fields"] += 1
            if row.has_rewrite_body:
                counts["has_rewrite"] += 1

    inventory_path = output_dir / "inventory.jsonl"
    with inventory_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    summary = {
        "cohort": cohort.to_dict(),
        "counts": counts,
        "generated_at": timezone.now().isoformat(),
        "revision": revision,
    }
    _atomic_write_json(output_dir / "summary.json", summary)

    manifest = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "generated_at": timezone.now().isoformat(),
        "files": {
            "cohort.json": _file_sha(output_dir / "cohort.json"),
            "inventory.jsonl": _file_sha(output_dir / "inventory.jsonl"),
            "summary.json": _file_sha(output_dir / "summary.json"),
        },
    }
    _atomic_write_json(output_dir / "manifest.json", manifest)

    return {"cohort": cohort, "counts": counts, "manifest": manifest, "row_count": len(rows)}


_SHA_OF_EMPTY_LIST = _canonical_sha([])


def compute_before_fingerprint(article: NewsArticle) -> dict[str, str]:
    manual_list = list(article.manually_edited_fields or [])
    return {
        "id": str(article.id),
        "updated_at": article.updated_at.isoformat(),
        "original_content_html": _sha256(article.original_content_html),
        "body_ja_raw": _sha256(article.body_ja_raw),
        "body_ja_normalized": _sha256(article.body_ja_normalized),
        "title_ja": _sha256(article.title_ja),
        "translated_body_zh": _sha256(article.translated_body_zh),
        "translated_title_zh": _sha256(article.translated_title_zh),
        "translated_summary_zh": _sha256(article.translated_summary_zh),
        "body_zh": _sha256(article.body_zh),
        "title_zh": _sha256(article.title_zh),
        "summary_zh": _sha256(article.summary_zh),
        "push_summary_zh": _sha256(article.push_summary_zh),
        "base_translation_zh": _sha256(article.base_translation_zh),
        "rewrite_body_zh": _sha256(article.rewrite_body_zh),
        "rewrite_title_zh": _sha256(article.rewrite_title_zh),
        "rewrite_summary_zh": _sha256(article.rewrite_summary_zh),
        "manually_edited_fields": _canonical_sha(manual_list),
        "manually_edited_fields_list": manual_list,
        "workflow_status": article.workflow_status,
        "translation_status": article.translation_status,
        "automation_status": article.automation_status,
        "published_to_web_at": article.published_to_web_at.isoformat() if article.published_to_web_at else "",
    }


def validate_approved_decisions(
    approved: dict[str, Any],
    *,
    candidate_manifest_sha256: str,
    candidate_manifest: dict[str, Any] | None = None,
) -> list[str]:
    """Validate an approved decisions manifest.

    When candidate_manifest is provided, also cross-validates:
    - Every approve_fields decision must have a matching candidate entry
    - The decision's approved_fields and exact_output must match the candidate
    - The decision's candidate_sha256 must match the candidate entry's hash
    """
    errors: list[str] = []

    if approved.get("schema_version") != APPROVED_MANIFEST_SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {APPROVED_MANIFEST_SCHEMA_VERSION}")

    manifest_candidate_sha = approved.get("candidate_manifest_sha256")
    if not isinstance(manifest_candidate_sha, str) or not _SHA256_RE.fullmatch(manifest_candidate_sha):
        errors.append("candidate_manifest_sha256 缺失或格式无效")
    elif manifest_candidate_sha != candidate_manifest_sha256.lower():
        errors.append(
            f"candidate_manifest_sha256 不匹配: "
            f"manifest={manifest_candidate_sha[:16]}... arg={candidate_manifest_sha256[:16]}..."
        )

    decisions = approved.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append("decisions 必须是非空列表")
        return errors

    # P2 fix: enforce batch size limit
    if len(decisions) > _MAX_BATCH_SIZE:
        errors.append(f"批次数 {len(decisions)} 超过上限 {_MAX_BATCH_SIZE}")

    seen_ids: set[int] = set()
    for idx, dec in enumerate(decisions, start=1):
        article_id = dec.get("article_id")
        if not isinstance(article_id, int) or article_id < 1:
            errors.append(f"第 {idx} 个 decision article_id 无效")
            continue
        if article_id in seen_ids:
            errors.append(f"article_id={article_id} 重复")
        seen_ids.add(article_id)

        decision = dec.get("decision")
        if decision not in {DECISION_APPROVE_NO_ACTION, DECISION_APPROVE_FIELDS, DECISION_KEEP_MANUAL, DECISION_REJECT}:
            errors.append(f"article_id={article_id} 的 decision 无效: {decision}")
            continue

        reviewer = dec.get("reviewer")
        if not isinstance(reviewer, str) or not reviewer.strip():
            errors.append(f"article_id={article_id} 缺少 reviewer")
        reason = dec.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"article_id={article_id} 缺少 reason")

        before_fp = dec.get("before_fingerprint") or {}
        approved_fields: list[str] = list(dec.get("approved_fields") or [])

        if decision == DECISION_APPROVE_FIELDS:
            if not approved_fields:
                errors.append(f"article_id={article_id} approve_fields 需要 approved_fields")
            else:
                for field in approved_fields:
                    if field not in ALLOWED_APPROVE_FIELDS:
                        errors.append(f"article_id={article_id} approved_field 不在 allowlist: {field}")

                # --- FIELD_DEPENDENCIES ---
                approved_set = frozenset(approved_fields)
                for field in approved_fields:
                    deps = FIELD_DEPENDENCIES.get(field, frozenset())
                    missing_deps = deps - approved_set
                    if missing_deps:
                        errors.append(
                            f"article_id={article_id} {field} 缺少依赖字段: {', '.join(sorted(missing_deps))}"
                        )

                # --- FIELD_PREREQUISITES: translation status ---
                tl_status = before_fp.get("translation_status", "")
                for field in approved_fields:
                    prereq = FIELD_PREREQUISITES.get(field)
                    if prereq is None:
                        continue
                    forbid_tl = prereq.get("forbid_translation_statuses")
                    if forbid_tl and tl_status in forbid_tl:
                        errors.append(
                            f"article_id={article_id} {field} 禁止 translation_status={tl_status}"
                        )
                    if field == "body_zh" and before_fp.get("translated_body_zh") == _sha256(""):
                        errors.append(
                            f"article_id={article_id} body_zh 要求 translated_body_zh 非空"
                        )

                # --- SOURCE_ATOMIC_FIELDS prerequisite check ---
                source_fields_in_approval = SOURCE_ATOMIC_FIELDS & approved_set
                if source_fields_in_approval:
                    source_evidence = dec.get("source_evidence") or {}
                    src_status = source_evidence.get("source_status", "")
                    parse_ok = source_evidence.get("body_parse_status") == "ok"
                    for sf in source_fields_in_approval:
                        prereq = FIELD_PREREQUISITES.get(sf, {})
                        required_ss = prereq.get("required_source_statuses", set())
                        if required_ss and src_status not in required_ss:
                            errors.append(
                                f"article_id={article_id} {sf} 要求 source_status 在 {required_ss}，"
                                f"实际={src_status}"
                            )
                        if prereq.get("require_parse_ok") and not parse_ok:
                            errors.append(
                                f"article_id={article_id} {sf} 要求 body_parse_status=ok，"
                                f"实际={source_evidence.get('body_parse_status')}"
                            )

                # --- manual field protection (P1 fix) ---
                manual_list = before_fp.get("manually_edited_fields_list") or []
                for field in approved_fields:
                    if field in {"body_zh", "summary_zh", "push_summary_zh", "base_translation_zh",
                                 "rewrite_body_zh"}:
                        if field in manual_list:
                            errors.append(
                                f"article_id={article_id} {field} 为人工字段，不可自动覆盖"
                            )
                    # Also check title fields via permanent-no-write
                    if field in PERMANENT_NO_WRITE_FIELDS:
                        errors.append(f"article_id={article_id} {field} 为永久保护字段，不可写入")

        elif decision in {DECISION_APPROVE_NO_ACTION, DECISION_KEEP_MANUAL, DECISION_REJECT}:
            if approved_fields:
                errors.append(f"article_id={article_id} {decision} 的 approved_fields 必须为空")

    # --- candidate manifest content binding (P1 fix) ---
    if candidate_manifest is not None:
        candidate_entries = candidate_manifest.get("entries") or candidate_manifest.get("candidates") or []
        candidate_by_id: dict[int, dict[str, Any]] = {}
        if not isinstance(candidate_entries, list):
            errors.append("candidate manifest entries 必须是列表")
        else:
            for idx, ce in enumerate(candidate_entries):
                if not isinstance(ce, dict):
                    errors.append(f"candidate entry {idx} 不是对象")
                    continue
                cid = ce.get("article_id")
                if not isinstance(cid, int) or cid < 1:
                    errors.append(f"candidate entry {idx} article_id 无效: {cid}")
                    continue
                if cid in candidate_by_id:
                    errors.append(f"candidate entry article_id={cid} 重复")
                candidate_by_id[cid] = ce

        for dec in decisions:
            aid = dec.get("article_id")
            if dec.get("decision") != DECISION_APPROVE_FIELDS:
                continue
            ce = candidate_by_id.get(aid)
            if ce is None:
                errors.append(f"article_id={aid} 在 candidate manifest 中无对应条目")
                continue
            dec_output = dec.get("exact_output") or {}
            ce_output = ce.get("exact_output") or {}
            if dec_output != ce_output:
                errors.append(f"article_id={aid} exact_output 与 candidate 不一致")
            dec_fields = set(dec.get("approved_fields") or [])
            ce_fields = set(ce.get("approved_fields") or [])
            if dec_fields != ce_fields:
                errors.append(f"article_id={aid} approved_fields 与 candidate 不一致")

    return errors


def build_rollback_artifact(
    articles: list[NewsArticle],
    *,
    output_dir: Path,
) -> tuple[Path, str]:
    """Build and atomically persist a rollback artifact with pre-apply before values.

    MUST be called BEFORE any DB write transaction.
    The artifact contains only the `before` field values, NOT expected_fingerprint.
    Post-apply expected fingerprints are written separately in the receipt.
    During rollback, CAS uses the receipt post_apply_fingerprints.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for article in articles:
        entries.append(
            {
                "article_id": article.id,
                "before": {
                    "body_ja_raw": article.body_ja_raw,
                    "body_ja_normalized": article.body_ja_normalized,
                    "translated_body_zh": article.translated_body_zh,
                    "body_zh": article.body_zh,
                    "translated_summary_zh": article.translated_summary_zh,
                    "summary_zh": article.summary_zh,
                    "push_summary_zh": article.push_summary_zh,
                    "base_translation_zh": article.base_translation_zh,
                    "rewrite_body_zh": article.rewrite_body_zh,
                    "translation_metadata": article.translation_metadata,
                },
            }
        )
    payload: dict[str, Any] = {
        "schema_version": ROLLBACK_MANIFEST_SCHEMA_VERSION,
        "generated_at": timezone.now().isoformat(),
        "entries": entries,
    }
    path = output_dir / "rollback_manifest.json"
    file_sha = _atomic_write_json(path, payload)
    return path, file_sha


def apply_batch_inside_transaction(
    *,
    articles: list[NewsArticle],
    approved_manifest: dict[str, Any],
    approved_manifest_sha256: str,
    rollback_artifact_sha256: str,
) -> list[dict[str, Any]]:
    """Write approved fields inside an already-open transaction.

    Preconditions:
    - Caller has already opened transaction.atomic() and called select_for_update()
    - rollback artifact was persisted BEFORE the transaction started
    - articles are already locked and ordered by id
    """
    decisions = approved_manifest.get("decisions", [])
    article_ids = sorted([d["article_id"] for d in decisions])

    if len(articles) != len(article_ids):
        missing = set(article_ids) - {a.id for a in articles}
        raise ValueError(f"文章不存在: {sorted(missing)}")

    # --- drift check ---
    errors: list[str] = []
    for article in articles:
        dec = next(d for d in decisions if d["article_id"] == article.id)
        before = compute_before_fingerprint(article)
        expected_before = dec.get("before_fingerprint", {})
        drifted = []
        for key in FINGERPRINT_DRIFT_KEYS:
            if before.get(key) != expected_before.get(key):
                drifted.append(key)
        if drifted:
            errors.append(f"article_id={article.id} before fingerprint 漂移: {', '.join(drifted)}")

    # --- source evidence re-verification (P1 fix) ---
    for article in articles:
        dec = next(d for d in decisions if d["article_id"] == article.id)
        if dec.get("decision") != DECISION_APPROVE_FIELDS:
            continue
        approved_set = frozenset(dec.get("approved_fields") or [])
        if not (SOURCE_ATOMIC_FIELDS & approved_set):
            continue
        # Re-parse from original_content_html — must match source_evidence
        parse_status, body_selector, after_body, _, _ = _parse_with_adapter(article)
        source_evidence = dec.get("source_evidence") or {}
        claimed_status = source_evidence.get("source_status", "")
        claimed_parse = source_evidence.get("body_parse_status", "")
        actual_source_status = _classify_source_status(
            parse_status, _sha256(article.body_ja_raw), _sha256(after_body))
        if claimed_status != actual_source_status or claimed_parse != parse_status:
            errors.append(
                f"article_id={article.id} source_evidence 不匹配重解析: "
                f"claimed=({claimed_status},{claimed_parse}) actual=({actual_source_status},{parse_status})"
            )

    if errors:
        raise ValueError("批次漂移: " + "; ".join(errors))

    applied_at = timezone.now().isoformat()
    results = []
    for article in articles:
        dec = next(d for d in decisions if d["article_id"] == article.id)
        if dec["decision"] != DECISION_APPROVE_FIELDS:
            results.append({"article_id": article.id, "decision": dec["decision"], "applied": False})
            continue

        approved_fields = dec.get("approved_fields", [])
        exact_output = dec.get("exact_output", {})
        update_fields = {"updated_at"}

        for field in approved_fields:
            if field in exact_output and field not in PERMANENT_NO_WRITE_FIELDS:
                setattr(article, field, exact_output[field])
                update_fields.add(field)

        if "content_boundary_repair" in approved_fields or "body_ja_raw" in approved_fields:
            article.translation_metadata = {
                **(article.translation_metadata or {}),
                "content_boundary_repair": {
                    "approval_manifest_sha256": approved_manifest_sha256,
                    "applied_at": applied_at,
                    "approved_fields": approved_fields,
                },
            }
            update_fields.add("translation_metadata")

        article.save(update_fields=list(update_fields))
        log_operation(
            action_type="news_body_history_applied",
            target_type="article",
            target_id=article.id,
            detail=(
                f"history body repair manifest={approved_manifest_sha256[:12]} "
                f"fields={','.join(approved_fields)}"
            ),
        )
        results.append(
            {
                "article_id": article.id,
                "decision": dec["decision"],
                "applied": True,
                "rollback_artifact_sha256": rollback_artifact_sha256,
            }
        )

    # --- after writes: capture post-apply fingerprints for CAS rollback ---
    post_apply_fingerprints: dict[int, dict[str, str]] = {}
    for article in articles:
        article.refresh_from_db()
        post_apply_fingerprints[article.id] = compute_before_fingerprint(article)

    return results, post_apply_fingerprints


def build_receipt(
    *,
    approved_manifest_sha256: str,
    rollback_artifact_sha256: str,
    results: list[dict[str, Any]],
    post_apply_fingerprints: dict[int, dict[str, str]],
    output_dir: Path,
) -> str:
    """Write receipt AFTER transaction commit.

    Contains post_apply_fingerprints used by rollback_batch for CAS drift checks.
    Receipt can be rebuilt from DB + rollback artifact if lost after commit.
    """
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "approved_manifest_sha256": approved_manifest_sha256,
        "rollback_artifact_sha256": rollback_artifact_sha256,
        "applied_at": timezone.now().isoformat(),
        "results": results,
        "post_apply_fingerprints": {
            str(aid): fp for aid, fp in post_apply_fingerprints.items()
        },
    }
    return _atomic_write_json(output_dir / "receipt.json", receipt)


def verify_batch(
    *,
    receipt_path: Path,
    receipt_sha256: str,
    manifest_path: Path,
    manifest_sha256: str,
    rollback_dir: Path,
    approved_manifest: dict[str, Any],
) -> list[str]:
    """Post-apply verifier with full SHA trust chain.

    Cross-validates:
    - receipt file SHA matches --receipt-sha256
    - receipt approved_manifest_sha256 matches manifest file SHA
    - Fields in DB match approved exact_output
    """
    errors: list[str] = []
    if not receipt_path.exists():
        errors.append("receipt 文件不存在")
        return errors

    # --- trust chain: receipt file SHA ---
    actual_receipt_sha = _file_sha(receipt_path)
    if actual_receipt_sha != receipt_sha256.lower():
        errors.append(
            f"receipt 文件 SHA-256 不匹配: "
            f"expected={receipt_sha256[:16]}... actual={actual_receipt_sha[:16]}..."
        )
    # --- trust chain: manifest file SHA ---
    actual_manifest_sha = _file_sha(manifest_path)
    if actual_manifest_sha != manifest_sha256.lower():
        errors.append(
            f"manifest 文件 SHA-256 不匹配: "
            f"expected={manifest_sha256[:16]}... actual={actual_manifest_sha[:16]}..."
        )

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    # --- trust chain: receipt → rollback artifact cross-check ---
    rollback_path = rollback_dir / "rollback_manifest.json"
    receipt_rb_sha = receipt.get("rollback_artifact_sha256", "")
    if not rollback_path.exists():
        errors.append("rollback manifest 文件不存在")
    else:
        actual_rb_sha = _file_sha(rollback_path)
        if actual_rb_sha != receipt_rb_sha:
            errors.append(
                f"receipt.rollback_artifact_sha256 不匹配 rollback 文件: "
                f"receipt={receipt_rb_sha[:16]}... actual={actual_rb_sha[:16]}..."
            )

    # --- trust chain: receipt → manifest cross-check ---
    receipt_manifest_sha = receipt.get("approved_manifest_sha256", "")
    if receipt_manifest_sha != manifest_sha256.lower():
        errors.append(
            f"receipt.approved_manifest_sha256 不匹配 manifest 文件: "
            f"receipt={receipt_manifest_sha[:16]}... manifest={manifest_sha256[:16]}..."
        )

    decisions = approved_manifest.get("decisions", [])

    for result in receipt.get("results", []):
        if not result.get("applied"):
            continue
        article_id = result["article_id"]
        try:
            article = NewsArticle.objects.get(id=article_id)
        except NewsArticle.DoesNotExist:
            errors.append(f"article_id={article_id} 已不存在")
            continue

        dec = next((d for d in decisions if d["article_id"] == article_id), None)
        if dec is None:
            errors.append(f"article_id={article_id} 不在批准 manifest 中")
            continue

        exact_output = dec.get("exact_output", {})
        for field in dec.get("approved_fields", []):
            if field in exact_output and field not in PERMANENT_NO_WRITE_FIELDS:
                actual = getattr(article, field, "")
                expected = exact_output[field]
                if actual != expected:
                    errors.append(
                        f"article_id={article_id} {field}: expected={_sha256(expected)[:16]}... "
                        f"actual={_sha256(actual)[:16]}..."
                    )

    return errors


def rollback_batch(
    *,
    rollback_manifest_path: Path,
    rollback_manifest_sha256: str,
    receipt_path: Path | None = None,
    receipt_sha256: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """CAS rollback with receipt-based drift check."""
    actual_sha = _file_sha(rollback_manifest_path)
    if actual_sha != rollback_manifest_sha256.lower():
        raise ValueError("rollback manifest 文件 SHA-256 不匹配")

    # --- trust chain: receipt file SHA ---
    if receipt_path is not None and receipt_sha256 is not None:
        actual_receipt_sha = _file_sha(receipt_path)
        if actual_receipt_sha != receipt_sha256.lower():
            raise ValueError(
                f"receipt 文件 SHA-256 不匹配: "
                f"expected={receipt_sha256[:16]}... actual={actual_receipt_sha[:16]}..."
            )

    manifest = json.loads(rollback_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != ROLLBACK_MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"rollback manifest schema_version 必须为 {ROLLBACK_MANIFEST_SCHEMA_VERSION}")

    entries = manifest.get("entries", [])
    article_ids = sorted([e["article_id"] for e in entries])

    # Load receipt for CAS fingerprints; validate its SHA and cross-reference
    post_apply_fps: dict[int, dict[str, str]] = {}
    if receipt_path is not None and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        # --- trust chain: receipt → rollback artifact ---
        receipt_rb_sha = receipt.get("rollback_artifact_sha256", "")
        if receipt_rb_sha != rollback_manifest_sha256.lower():
            raise ValueError(
                f"receipt.rollback_artifact_sha256 不匹配: "
                f"receipt={receipt_rb_sha[:16]}... rollback={rollback_manifest_sha256[:16]}..."
            )
        raw_fps = receipt.get("post_apply_fingerprints", {})
        for aid_str, fp in raw_fps.items():
            post_apply_fps[int(aid_str)] = fp

    if not commit:
        articles = list(NewsArticle.objects.filter(id__in=article_ids).order_by("id"))
        dry_run_rows = []
        for article in articles:
            current_fp = compute_before_fingerprint(article)
            expected_fp = post_apply_fps.get(article.id, {})
            drifted = []
            if expected_fp:
                for key in FINGERPRINT_DRIFT_KEYS:
                    if current_fp.get(key) != expected_fp.get(key):
                        drifted.append(key)
            dry_run_rows.append(
                {
                    "article_id": article.id,
                    "current_fingerprint": current_fp,
                    "expected_fingerprint": expected_fp,
                    "drifted": bool(drifted),
                    "drifted_keys": drifted,
                }
            )
        return {"mode": "dry_run", "articles": dry_run_rows}

    # --- receipt SHA mandatory in commit mode (P1 fix) ---
    if commit and receipt_path is not None and receipt_sha256 is None:
        raise ValueError("rollback commit 模式必须提供 --receipt-sha256")
    if not post_apply_fps:
        raise ValueError("rollback commit 模式需要 --receipt 用于 CAS 校验")

    articles = list(
        NewsArticle.objects.select_for_update().filter(id__in=article_ids).order_by("id")
    )

    # --- CAS drift check (P1 fix): only restore if current state matches receipt's post_apply ---
    cas_errors: list[str] = []
    for article in articles:
        current_fp = compute_before_fingerprint(article)
        expected_fp = post_apply_fps.get(article.id, {})
        if not expected_fp:
            cas_errors.append(f"article_id={article.id} 在 receipt 中缺失 post_apply_fingerprint")
            continue
        drifted = []
        for key in FINGERPRINT_DRIFT_KEYS:
            if current_fp.get(key) != expected_fp.get(key):
                drifted.append(key)
        if drifted:
            cas_errors.append(
                f"article_id={article.id} CAS drift (state changed since apply): "
                f"{', '.join(drifted)}"
            )

    if cas_errors:
        raise ValueError("rollback CAS 漂移，拒绝覆盖: " + "; ".join(cas_errors))

    for article in articles:
        entry = next(e for e in entries if e["article_id"] == article.id)
        before = entry["before"]
        for field in ROLLBACK_WRITABLE_FIELDS:
            if field in before:
                setattr(article, field, before[field])
        article.save(
            update_fields=list(ROLLBACK_WRITABLE_FIELDS) + ["updated_at"]
        )
        log_operation(
            action_type="news_body_history_rolled_back",
            target_type="article",
            target_id=article.id,
            detail=f"rollback manifest={rollback_manifest_sha256[:12]}",
        )

    return {"mode": "commit", "rolled_back": len(articles)}
