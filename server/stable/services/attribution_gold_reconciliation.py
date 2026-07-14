from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from stable.models import NewsArticle
from stable.services.attribution_quality import article_input_sha256, load_gold_labels
from stable.services.news_attribution import AttributionBatchContext, infer_article_attribution


SNAPSHOT_FIELDS = (
    "key",
    "article_id",
    "source_url",
    "input_sha256",
    "title_original",
    "body_original",
)
LABEL_FIELDS = (
    "key",
    "article_id",
    "source_url",
    "input_sha256",
    "expected_primary_region",
    "expected_related_regions",
    "reviewer_roles",
    "rationale",
    "adjudicated",
)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()


def _shingles(value: str, *, size: int = 3) -> set[str]:
    compact = re.sub(r"\s+", "", _normalize_text(value).casefold())
    return {compact[index : index + size] for index in range(max(0, len(compact) - size + 1))}


def _semantic_overlap(old_body: str, current_body: str) -> tuple[float, float]:
    old = _shingles(old_body)
    current = _shingles(current_body)
    overlap = len(old & current)
    return (
        overlap / len(old) if old else 0.0,
        overlap / len(current) if current else 0.0,
    )


def reconcile_gold_label_drift(
    *,
    labels_path: Path,
    review_snapshot_path: Path,
    output_dir: Path,
    minimum_overlap: float = 0.95,
    minimum_body_length: int = 100,
    minimum_length_ratio: float = 0.20,
) -> dict:
    if not 0 < minimum_overlap <= 1:
        raise ValueError("minimum_overlap 必须在 0 到 1 之间")
    if minimum_body_length < 1:
        raise ValueError("minimum_body_length 必须大于 0")
    if not 0 < minimum_length_ratio <= 1:
        raise ValueError("minimum_length_ratio 必须在 0 到 1 之间")
    if output_dir.exists():
        raise ValueError("输出目录已存在，拒绝覆盖既有对账证据")
    with labels_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing_fields = [field for field in LABEL_FIELDS if field not in (reader.fieldnames or [])]
        if missing_fields:
            raise ValueError(f"gold labels 缺少字段: {', '.join(missing_fields)}")
        label_fields = list(reader.fieldnames or [])
        label_rows = list(reader)
    labels = load_gold_labels(labels_path)
    if not labels:
        raise ValueError("gold labels 不能为空")
    with review_snapshot_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing_fields = [field for field in SNAPSHOT_FIELDS if field not in (reader.fieldnames or [])]
        if missing_fields:
            raise ValueError(f"review snapshot 缺少字段: {', '.join(missing_fields)}")
        snapshot_rows = list(reader)

    label_ids = [label.article_id for label in labels]
    label_keys = [label.key for label in labels]
    snapshot_ids = [int(row["article_id"]) for row in snapshot_rows]
    snapshot_keys = [row["key"] for row in snapshot_rows]
    if len(label_ids) != len(set(label_ids)) or len(label_keys) != len(set(label_keys)):
        raise ValueError("gold labels 存在重复 article_id 或 key")
    if len(snapshot_ids) != len(set(snapshot_ids)) or len(snapshot_keys) != len(set(snapshot_keys)):
        raise ValueError("review snapshot 存在重复 article_id 或 key")
    snapshots = {int(row["article_id"]): row for row in snapshot_rows}
    articles = list(
        NewsArticle.objects.filter(id__in=[label.article_id for label in labels]).select_related("source_config")
    )
    articles_by_id = {article.id: article for article in articles}
    context = AttributionBatchContext.build(articles)
    reconciliation_rows: list[dict] = []
    refreshed_sha_by_id: dict[int, str] = {}

    for label in labels:
        article = articles_by_id.get(label.article_id)
        snapshot = snapshots.get(label.article_id)
        current_sha = article_input_sha256(article) if article else ""
        if article and current_sha == label.input_sha256:
            reconciliation_rows.append(
                {
                    "key": label.key,
                    "article_id": label.article_id,
                    "status": "unchanged",
                    "reasons": "",
                    "old_input_sha256": label.input_sha256,
                    "current_input_sha256": current_sha,
                    "title_exact": True,
                    "source_url_exact": True,
                    "old_body_coverage": 1.0,
                    "current_body_coverage": 1.0,
                    "body_length_ratio": 1.0,
                    "inference_matches_label": True,
                }
            )
            continue

        reasons: list[str] = []
        if article is None:
            reasons.append("article_missing")
        if snapshot is None:
            reasons.append("review_snapshot_missing")
        title_exact = False
        source_url_exact = False
        old_coverage = 0.0
        current_coverage = 0.0
        body_length_ratio = 0.0
        inference_matches = False
        if article is not None and snapshot is not None:
            if snapshot["key"] != label.key:
                reasons.append("snapshot_key_mismatch")
            if snapshot["input_sha256"] != label.input_sha256:
                reasons.append("snapshot_sha_mismatch")
            source_url_exact = snapshot["source_url"] == label.source_url == article.source_url
            if not source_url_exact:
                reasons.append("source_url_changed")
            title_exact = _normalize_text(snapshot["title_original"]) == _normalize_text(article.title_ja or "")
            if not title_exact:
                reasons.append("title_changed")
            current_body = article.body_ja_normalized or article.body_ja_raw or ""
            old_body = snapshot["body_original"]
            old_body_length = len(_normalize_text(old_body))
            current_body_length = len(_normalize_text(current_body))
            old_coverage, current_coverage = _semantic_overlap(old_body, current_body)
            if min(old_body_length, current_body_length) < minimum_body_length:
                reasons.append("body_too_short")
            if max(old_body_length, current_body_length):
                body_length_ratio = min(old_body_length, current_body_length) / max(
                    old_body_length,
                    current_body_length,
                )
            if body_length_ratio < minimum_length_ratio:
                reasons.append("body_length_ratio_low")
            if max(old_coverage, current_coverage) < minimum_overlap:
                reasons.append("body_semantic_overlap_low")
            inferred = infer_article_attribution(article, batch_context=context)
            inference_matches = (
                inferred.primary_region == label.expected_primary_region
                and set(inferred.related_regions) == set(label.expected_related_regions)
            )
            if not inference_matches:
                reasons.append("inference_changed_from_label")

        status = "blocked"
        if not reasons:
            status = "auto_refreshed"
            refreshed_sha_by_id[label.article_id] = current_sha
        reconciliation_rows.append(
            {
                "key": label.key,
                "article_id": label.article_id,
                "status": status,
                "reasons": ";".join(reasons),
                "old_input_sha256": label.input_sha256,
                "current_input_sha256": current_sha,
                "title_exact": title_exact,
                "source_url_exact": source_url_exact,
                "old_body_coverage": round(old_coverage, 6),
                "current_body_coverage": round(current_coverage, 6),
                "body_length_ratio": round(body_length_ratio, 6),
                "inference_matches_label": inference_matches,
            }
        )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=False)
    labels_output = output_dir / "provisional_gold_labels_reconciled.csv"
    with labels_output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=label_fields)
        writer.writeheader()
        for row in label_rows:
            article_id = int(row["article_id"])
            if article_id in refreshed_sha_by_id:
                row = {**row, "input_sha256": refreshed_sha_by_id[article_id]}
            writer.writerow(row)

    reconciliation_output = output_dir / "gold_drift_reconciliation.csv"
    reconciliation_fields = list(reconciliation_rows[0]) if reconciliation_rows else ["key", "article_id", "status"]
    with reconciliation_output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=reconciliation_fields)
        writer.writeheader()
        writer.writerows(reconciliation_rows)

    labels_sha256 = hashlib.sha256(labels_output.read_bytes()).hexdigest()
    summary = {
        "label_count": len(labels),
        "unchanged_count": sum(row["status"] == "unchanged" for row in reconciliation_rows),
        "auto_refreshed_count": sum(row["status"] == "auto_refreshed" for row in reconciliation_rows),
        "blocked_count": sum(row["status"] == "blocked" for row in reconciliation_rows),
        "minimum_overlap": minimum_overlap,
        "minimum_body_length": minimum_body_length,
        "minimum_length_ratio": minimum_length_ratio,
        "labels_path": str(labels_output),
        "labels_sha256": labels_sha256,
        "reconciliation_path": str(reconciliation_output),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
