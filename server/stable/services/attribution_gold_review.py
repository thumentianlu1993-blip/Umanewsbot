from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from django.db.models import QuerySet

from stable.models import NewsArticle, RacingRegion
from stable.services.attribution_quality import (
    article_input_sha256,
    gold_coverage_thresholds,
)
from stable.services.news_attribution import REGION_KEYWORDS


GOLD_REGIONS = (
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
)
SNAPSHOT_FIELDS = (
    "key",
    "article_id",
    "source_url",
    "input_sha256",
    "source_name",
    "source_default_region",
    "sampled_article_region",
    "source_language",
    "published_at",
    "title_original",
    "body_original",
    "title_zh",
    "summary_zh",
    "body_zh",
)
REVIEW_FIELDS = SNAPSHOT_FIELDS + (
    "reviewer_role",
    "reviewer_name",
    "reviewed_at",
    "review_status",
    "expected_primary_region",
    "expected_related_regions",
    "allow_source_fallback",
    "rationale",
)
GOLD_FIELDS = (
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
PROVISIONAL_AUDIT_FIELDS = (
    "key",
    "article_id",
    "source_url",
    "input_sha256",
    "action",
    "review_status_raw",
    "review_status_normalized",
    "primary_region_raw",
    "primary_region_normalized",
    "related_regions_raw",
    "related_regions_normalized",
    "allow_source_fallback_raw",
    "rationale",
    "normalization_notes",
)
SUPPORTED_REVIEW_REGIONS = GOLD_REGIONS + (RacingRegion.OTHER,)
REGION_ALIASES = {
    "united_state": RacingRegion.UNITED_STATES,
}
ALL_SUPPORTED_REGION_MARKERS = {"所有地区", "all", "all_regions", "all_supported_regions"}


@dataclass(frozen=True)
class GoldReviewPackageReport:
    output_dir: str
    version: str
    selected_count: int
    region_counts: dict[str, int]
    machine_cross_candidate_count: int
    manifest_sha256: str


@dataclass(frozen=True)
class GoldReviewFinalizeReport:
    output_dir: str
    agreed_count: int
    conflict_count: int
    excluded_count: int
    unresolved_count: int
    final_label_count: int
    primary_region_counts: dict[str, int]
    cross_region_count: int
    structurally_qualified: bool
    no_go_reasons: list[str]
    gold_labels_path: str
    review_mode: str = "dual_review"
    ignored_count: int = 0
    normalization_count: int = 0


def eligible_gold_articles() -> QuerySet[NewsArticle]:
    return (
        NewsArticle.objects.filter(
            racing_region__in=GOLD_REGIONS,
            withdrawn_at__isnull=True,
        )
        .exclude(title_ja="")
        .exclude(body_ja_normalized="", body_ja_raw="")
        .select_related("source_config")
        .order_by("-published_at", "-id")
    )


def stratified_gold_candidate_pool(*, per_source: int = 100) -> list[NewsArticle]:
    if per_source <= 0:
        raise ValueError("per_source 必须大于 0")
    base = eligible_gold_articles()
    rows: list[NewsArticle] = []
    for region in GOLD_REGIONS:
        source_ids = list(
            base.filter(racing_region=region)
            .order_by()
            .values_list("source_config_id", flat=True)
            .distinct()
        )
        for source_id in source_ids:
            source_rows = base.filter(racing_region=region, source_config_id=source_id)[:per_source]
            rows.extend(source_rows)
    return rows


def _stable_rank(article: NewsArticle, seed: str) -> str:
    return hashlib.sha256(f"{seed}:{article.id}".encode()).hexdigest()


def _round_robin_by_source(articles: Iterable[NewsArticle], *, seed: str) -> list[NewsArticle]:
    buckets: dict[str, list[NewsArticle]] = defaultdict(list)
    for article in articles:
        source_key = str(article.source_config_id or f"site:{article.source_site}:{article.source_mode}")
        buckets[source_key].append(article)
    for rows in buckets.values():
        rows.sort(key=lambda item: _stable_rank(item, seed))
    ordered: list[NewsArticle] = []
    source_keys = sorted(buckets)
    while source_keys:
        remaining: list[str] = []
        for source_key in source_keys:
            rows = buckets[source_key]
            if rows:
                ordered.append(rows.pop(0))
            if rows:
                remaining.append(source_key)
        source_keys = remaining
    return ordered


def select_gold_candidates(
    queryset: QuerySet[NewsArticle] | Iterable[NewsArticle],
    *,
    per_region: int = 50,
    cross_candidate_target: int = 75,
    seed: str = "20260713",
) -> tuple[list[NewsArticle], dict[int, dict]]:
    if per_region <= 0:
        raise ValueError("per_region 必须大于 0")
    ranked_articles = sorted(list(queryset), key=lambda item: _stable_rank(item, seed))
    unique_by_input: dict[str, NewsArticle] = {}
    for article in ranked_articles:
        unique_by_input.setdefault(article_input_sha256(article), article)
    articles = list(unique_by_input.values())
    grouped: dict[str, list[NewsArticle]] = defaultdict(list)
    for article in articles:
        grouped[article.racing_region].append(article)
    shortages = {region: per_region - len(grouped.get(region, [])) for region in GOLD_REGIONS if len(grouped.get(region, [])) < per_region}
    if shortages:
        details = ", ".join(f"{region} 缺 {count}" for region, count in shortages.items())
        raise ValueError(f"Gold Set 可用文章不足：{details}")

    predictions: dict[int, dict] = {}
    for article in articles:
        text = "\n".join(
            [article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or ""]
        ).casefold()
        candidate_regions = [
            region
            for region, keywords in REGION_KEYWORDS.items()
            if any(keyword.casefold() in text for keyword in keywords)
        ]
        predictions[article.id] = {
            "candidate_regions": candidate_regions,
            "machine_cross_candidate": any(region != article.racing_region for region in candidate_regions),
        }

    selected: list[NewsArticle] = []
    selected_ids: set[int] = set()
    cross_per_region = max(0, (cross_candidate_target + len(GOLD_REGIONS) - 1) // len(GOLD_REGIONS))
    for region in GOLD_REGIONS:
        region_rows = grouped[region]
        cross_rows = [row for row in region_rows if predictions[row.id]["machine_cross_candidate"]]
        cross_ordered = _round_robin_by_source(cross_rows, seed=f"{seed}:cross:{region}")
        for article in cross_ordered[: min(per_region, cross_per_region)]:
            selected.append(article)
            selected_ids.add(article.id)
        fill_rows = [row for row in region_rows if row.id not in selected_ids]
        fill_ordered = _round_robin_by_source(fill_rows, seed=f"{seed}:fill:{region}")
        need = per_region - sum(row.racing_region == region for row in selected)
        for article in fill_ordered[:need]:
            selected.append(article)
            selected_ids.add(article.id)

    selected.sort(key=lambda item: (GOLD_REGIONS.index(item.racing_region), _stable_rank(item, seed)))
    cross_count = sum(predictions[item.id]["machine_cross_candidate"] for item in selected)
    if cross_count < cross_candidate_target:
        raise ValueError(
            f"仅选出 {cross_count} 篇疑似跨地区样本，低于目标 {cross_candidate_target}；"
            "请扩大候选池或降低抽样目标，但不得降低正式 Gold Set 的 50 篇跨地区硬门槛。"
        )
    return selected, predictions


def _source_name(article: NewsArticle) -> str:
    if article.source_config_id and article.source_config:
        return article.source_config.name
    return f"{article.source_site}/{article.source_mode}"


def _source_region(article: NewsArticle) -> str:
    if article.source_config_id and article.source_config:
        return article.source_config.racing_region
    return article.racing_region


def _snapshot_row(article: NewsArticle, *, version: str) -> dict[str, str | int]:
    body_original = article.body_ja_normalized or article.body_ja_raw or ""
    return {
        "key": f"{version}-article-{article.id}",
        "article_id": article.id,
        "source_url": article.source_url,
        "input_sha256": article_input_sha256(article),
        "source_name": _source_name(article),
        "source_default_region": _source_region(article),
        "sampled_article_region": article.racing_region,
        "source_language": article.source_language,
        "published_at": article.published_at.astimezone(timezone.utc).isoformat(),
        "title_original": article.title_ja,
        "body_original": body_original,
        "title_zh": article.effective_title,
        "summary_zh": article.effective_summary,
        "body_zh": article.effective_body,
    }


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: Iterable[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_review_readme(path: Path, *, version: str) -> None:
    path.write_text(
        f"""# 多地区归属 Gold Set 双人标注包

- Gold 版本：`{version}`
- `reviewer_a.csv` 与 `reviewer_b.csv` 必须由两位不同审核人独立填写，完成前不要互看答案。
- 只编辑以下字段：`reviewer_name`、`reviewed_at`、`review_status`、`expected_primary_region`、`expected_related_regions`、`allow_source_fallback`、`rationale`。
- `review_status` 只允许 `ready` 或 `exclude`；正文足够判断时使用 `ready`，输入损坏或无法判断时才使用 `exclude`。
- `reviewed_at` 必须填写带时区的 ISO-8601 时间；`allow_source_fallback` 必须明确填写 `true` 或 `false`，不能留空。
- 地区值只允许：`japan`、`hong_kong`、`united_kingdom`、`france`、`united_states`；多个相关地区用英文分号 `;` 分隔。
- 主地区按文章中心事件决定；核心马匹、骑师或机构真实涉及但不是中心事件时列为相关地区。
- 普通地名、历史履历、血统背景和来源备注不能单独决定地区。
- 没有可信内容证据或证据冲突时，允许以 `source_default_region` 回退，并把 `allow_source_fallback` 填为 `true`。
- `rationale` 必须用一句话说明中心事件和关键实体依据，不能只写“看起来像”。
- 两份表完成后运行合并命令；不一致项会进入 `adjudication.csv`，裁决完成前不会生成正式 Gold Labels。

`source_snapshot.csv` 是不可变输入，不要编辑；它包含第三方正文，仅作为内部审核材料，不得提交到 Git。
""",
        encoding="utf-8",
    )


def build_gold_review_package(
    *,
    output_dir: Path,
    version: str,
    queryset: QuerySet[NewsArticle] | Iterable[NewsArticle] | None = None,
    per_region: int = 50,
    cross_candidate_target: int = 75,
    seed: str = "20260713",
) -> GoldReviewPackageReport:
    if not version.strip():
        raise ValueError("version 不能为空")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"输出目录非空，拒绝覆盖：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    selected, predictions = select_gold_candidates(
        queryset if queryset is not None else stratified_gold_candidate_pool(),
        per_region=per_region,
        cross_candidate_target=cross_candidate_target,
        seed=seed,
    )
    snapshot_rows = [_snapshot_row(article, version=version) for article in selected]
    snapshot_path = output_dir / "source_snapshot.csv"
    _write_csv(snapshot_path, SNAPSHOT_FIELDS, snapshot_rows)
    for role in ("reviewer_a", "reviewer_b"):
        review_rows = [{**row, "reviewer_role": role} for row in snapshot_rows]
        _write_csv(output_dir / f"{role}.csv", REVIEW_FIELDS, review_rows)
    _write_review_readme(output_dir / "README.md", version=version)

    region_counts = Counter(article.racing_region for article in selected)
    source_counts = Counter(_source_name(article) for article in selected)
    machine_cross_count = sum(predictions[article.id]["machine_cross_candidate"] for article in selected)
    manifest = {
        "schema_version": 1,
        "gold_version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection": {
            "seed": seed,
            "per_region": per_region,
            "cross_candidate_target": cross_candidate_target,
            "selected_count": len(selected),
            "sampled_region_counts": dict(sorted(region_counts.items())),
            "source_counts": dict(sorted(source_counts.items())),
            "machine_cross_candidate_count": machine_cross_count,
            "note": "独立宽关键词信号仅用于抽样，不调用待测归属算法，不写入盲标表，也不等于人工 Gold 标签。",
        },
        "files": {
            name: _file_sha256(output_dir / name)
            for name in ("source_snapshot.csv", "reviewer_a.csv", "reviewer_b.csv", "README.md")
        },
    }
    manifest_path = output_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    return GoldReviewPackageReport(
        output_dir=str(output_dir),
        version=version,
        selected_count=len(selected),
        region_counts=dict(region_counts),
        machine_cross_candidate_count=machine_cross_count,
        manifest_sha256=_file_sha256(manifest_path),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _normalize_regions(value: str) -> list[str]:
    result: list[str] = []
    for item in (value or "").split(";"):
        region = item.strip()
        if not region:
            continue
        if region not in GOLD_REGIONS:
            raise ValueError(f"不支持的地区：{region}")
        if region not in result:
            result.append(region)
    return result


def _normalize_provisional_region(value: str) -> tuple[str, list[str]]:
    raw = (value or "").strip()
    normalized = REGION_ALIASES.get(raw, raw)
    notes: list[str] = []
    if normalized != raw:
        notes.append(f"{raw}->{normalized}")
    if normalized not in SUPPORTED_REVIEW_REGIONS:
        raise ValueError(f"不支持的地区：{raw}")
    return normalized, notes


def _normalize_provisional_related(value: str, *, primary: str) -> tuple[list[str], list[str]]:
    raw = (value or "").strip()
    if not raw:
        return [], []
    tokens = [item.strip() for item in re.split(r"[;,，；]", raw) if item.strip()]
    result: list[str] = []
    notes: list[str] = []
    for token in tokens:
        if token.casefold() in ALL_SUPPORTED_REGION_MARKERS or token in ALL_SUPPORTED_REGION_MARKERS:
            expanded = list(GOLD_REGIONS)
            notes.append(f"{token}->" + ";".join(expanded))
        else:
            normalized, token_notes = _normalize_provisional_region(token)
            expanded = [normalized]
            notes.extend(token_notes)
        for region in expanded:
            if region != primary and region not in result:
                result.append(region)
    return result, notes


def finalize_provisional_single_review_package(
    *,
    package_dir: Path,
    reviewer_path: Path,
    output_dir: Path,
    reviewer_role: str = "reviewer_a",
    minimum_total: int | None = None,
    minimum_per_region: int | None = None,
    minimum_cross_region: int | None = None,
) -> GoldReviewFinalizeReport:
    """Build auditable single-review labels while preserving production quality gates."""
    configured_total, configured_per_region, configured_cross_region = gold_coverage_thresholds()
    minimum_total = configured_total if minimum_total is None else minimum_total
    minimum_per_region = configured_per_region if minimum_per_region is None else minimum_per_region
    minimum_cross_region = configured_cross_region if minimum_cross_region is None else minimum_cross_region
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"输出目录非空，拒绝覆盖：{output_dir}")
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in ("source_snapshot.csv", "README.md"):
        if _file_sha256(package_dir / name) != manifest["files"][name]:
            raise ValueError(f"{name} 已漂移，拒绝合并标注")

    snapshot_rows = _read_csv(package_dir / "source_snapshot.csv")
    snapshot_by_key = {row["key"]: row for row in snapshot_rows}
    if len(snapshot_by_key) != len(snapshot_rows):
        raise ValueError("source_snapshot.csv 存在重复 key")
    review_rows = _read_csv(reviewer_path)
    if {row.get("key") for row in review_rows} != set(snapshot_by_key):
        raise ValueError("单审文件的 key 集合与快照不一致")

    output_dir.mkdir(parents=True, exist_ok=True)
    gold_rows: list[dict] = []
    audit_rows: list[dict] = []
    excluded_rows: list[dict] = []
    ignored_rows: list[dict] = []
    normalization_count = 0
    for row in review_rows:
        key = row["key"]
        snapshot = snapshot_by_key[key]
        for field in SNAPSHOT_FIELDS:
            if row.get(field, "") != snapshot.get(field, ""):
                raise ValueError(f"{key}: 单审文件的 {field} 已漂移")

        status_raw = (row.get("review_status", "") or "").strip().lower()
        primary_raw = (row.get("expected_primary_region", "") or "").strip()
        related_raw = (row.get("expected_related_regions", "") or "").strip()
        rationale = (row.get("rationale", "") or "").strip()
        fallback_raw = (row.get("allow_source_fallback", "") or "").strip()
        audit = {
            **{field: snapshot[field] for field in ("key", "article_id", "source_url", "input_sha256")},
            "review_status_raw": status_raw,
            "primary_region_raw": primary_raw,
            "related_regions_raw": related_raw,
            "allow_source_fallback_raw": fallback_raw,
            "rationale": rationale,
            "normalization_notes": "",
        }
        if status_raw == "exclude":
            audit.update(
                action="excluded",
                review_status_normalized="exclude",
                primary_region_normalized="",
                related_regions_normalized="",
            )
            audit_rows.append(audit)
            excluded_rows.append(audit)
            continue
        if not primary_raw and not related_raw:
            audit.update(
                action="ignored_unselected",
                review_status_normalized="",
                primary_region_normalized="",
                related_regions_normalized="",
            )
            audit_rows.append(audit)
            ignored_rows.append(audit)
            continue
        if status_raw not in {"", "ready"}:
            raise ValueError(f"{key}: 单审 review_status 只允许留空、ready 或 exclude")
        if not primary_raw:
            raise ValueError(f"{key}: 已填写审核内容但没有期望主地区")

        primary, primary_notes = _normalize_provisional_region(primary_raw)
        related, related_notes = _normalize_provisional_related(related_raw, primary=primary)
        notes = primary_notes + related_notes
        normalization_count += int(bool(notes))
        audit.update(
            action="included_provisional",
            review_status_normalized="ready",
            primary_region_normalized=primary,
            related_regions_normalized=";".join(related),
            normalization_notes=" | ".join(notes),
        )
        audit_rows.append(audit)
        gold_rows.append(
            {
                "key": key,
                "article_id": snapshot["article_id"],
                "source_url": snapshot["source_url"],
                "input_sha256": snapshot["input_sha256"],
                "expected_primary_region": primary,
                "expected_related_regions": ";".join(related),
                "reviewer_roles": reviewer_role,
                "rationale": rationale,
                "adjudicated": "false",
            }
        )

    _write_csv(output_dir / "normalization_audit.csv", PROVISIONAL_AUDIT_FIELDS, audit_rows)
    _write_csv(output_dir / "excluded_rows.csv", PROVISIONAL_AUDIT_FIELDS, excluded_rows)
    _write_csv(output_dir / "ignored_unselected_rows.csv", PROVISIONAL_AUDIT_FIELDS, ignored_rows)
    gold_path = output_dir / "provisional_gold_labels.csv"
    _write_csv(gold_path, GOLD_FIELDS, gold_rows)
    primary_counts = Counter(row["expected_primary_region"] for row in gold_rows)
    cross_count = sum(bool(row["expected_related_regions"]) for row in gold_rows)
    no_go: list[str] = []
    if len(gold_rows) < minimum_total:
        no_go.append("total_sample_count")
    if any(primary_counts.get(region, 0) < minimum_per_region for region in GOLD_REGIONS):
        no_go.append("region_sample_count")
    if cross_count < minimum_cross_region:
        no_go.append("cross_region_sample_count")
    report_payload = {
        "schema_version": 1,
        "gold_version": manifest["gold_version"],
        "review_mode": "provisional_single_review",
        "source_manifest_sha256": _file_sha256(manifest_path),
        "selected_input_count": len(snapshot_rows),
        "final_label_count": len(gold_rows),
        "excluded_count": len(excluded_rows),
        "ignored_count": len(ignored_rows),
        "normalization_count": normalization_count,
        "primary_region_counts": dict(sorted(primary_counts.items())),
        "cross_region_count": cross_count,
        "structurally_qualified": not no_go,
        "no_go_reasons": no_go,
        "gold_labels_file": gold_path.name,
        "gold_labels_sha256": _file_sha256(gold_path),
        "normalization_audit_sha256": _file_sha256(output_dir / "normalization_audit.csv"),
    }
    _write_json(output_dir / "finalize_report.json", report_payload)
    return GoldReviewFinalizeReport(
        output_dir=str(output_dir),
        agreed_count=len(gold_rows),
        conflict_count=0,
        excluded_count=len(excluded_rows),
        unresolved_count=0,
        final_label_count=len(gold_rows),
        primary_region_counts=dict(primary_counts),
        cross_region_count=cross_count,
        structurally_qualified=not no_go,
        no_go_reasons=no_go,
        gold_labels_path=str(gold_path),
        review_mode="provisional_single_review",
        ignored_count=len(ignored_rows),
        normalization_count=normalization_count,
    )


def _validated_review_row(row: dict[str, str], *, expected_role: str) -> dict:
    if row.get("reviewer_role", "").strip() != expected_role:
        raise ValueError(f"{row.get('key')}: reviewer_role 必须是 {expected_role}")
    status = row.get("review_status", "").strip().lower()
    if status not in {"ready", "exclude"}:
        raise ValueError(f"{row.get('key')}: review_status 必须是 ready 或 exclude")
    reviewer_name = row.get("reviewer_name", "").strip()
    reviewed_at = row.get("reviewed_at", "").strip()
    if not reviewer_name or not reviewed_at:
        raise ValueError(f"{row.get('key')}: reviewer_name 和 reviewed_at 必填")
    try:
        parsed_reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{row.get('key')}: reviewed_at 必须是 ISO-8601 时间") from exc
    if parsed_reviewed_at.tzinfo is None:
        raise ValueError(f"{row.get('key')}: reviewed_at 必须包含时区")
    if status == "exclude":
        return {"status": status, "reviewer_name": reviewer_name, "reviewed_at": reviewed_at}
    primary = row.get("expected_primary_region", "").strip()
    if primary not in GOLD_REGIONS:
        raise ValueError(f"{row.get('key')}: expected_primary_region 无效")
    related = _normalize_regions(row.get("expected_related_regions", ""))
    if primary in related:
        raise ValueError(f"{row.get('key')}: 相关地区不能包含主地区")
    rationale = row.get("rationale", "").strip()
    if not rationale:
        raise ValueError(f"{row.get('key')}: rationale 必填")
    fallback_value = row.get("allow_source_fallback", "").strip().lower()
    if fallback_value not in {"1", "0", "true", "false", "yes", "no"}:
        raise ValueError(f"{row.get('key')}: allow_source_fallback 必须明确填写 true 或 false")
    return {
        "status": status,
        "primary": primary,
        "related": related,
        "allow_source_fallback": fallback_value in {"1", "true", "yes"},
        "rationale": rationale,
        "reviewer_name": reviewer_name,
        "reviewed_at": reviewed_at,
    }


def _labels_match(first: dict, second: dict) -> bool:
    return (
        first["status"] == second["status"] == "ready"
        and first["primary"] == second["primary"]
        and set(first["related"]) == set(second["related"])
        and first["allow_source_fallback"] == second["allow_source_fallback"]
    )


def finalize_gold_review_package(
    *,
    package_dir: Path,
    output_dir: Path,
    adjudication_path: Path | None = None,
    minimum_total: int | None = None,
    minimum_per_region: int | None = None,
    minimum_cross_region: int | None = None,
) -> GoldReviewFinalizeReport:
    configured_total, configured_per_region, configured_cross_region = gold_coverage_thresholds()
    minimum_total = configured_total if minimum_total is None else minimum_total
    minimum_per_region = configured_per_region if minimum_per_region is None else minimum_per_region
    minimum_cross_region = configured_cross_region if minimum_cross_region is None else minimum_cross_region
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"输出目录非空，拒绝覆盖：{output_dir}")
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, expected_sha in manifest["files"].items():
        actual_sha = _file_sha256(package_dir / name)
        if actual_sha != expected_sha and name in {"source_snapshot.csv", "README.md"}:
            raise ValueError(f"{name} 已漂移，拒绝合并标注")

    snapshot_rows = _read_csv(package_dir / "source_snapshot.csv")
    snapshot_by_key = {row["key"]: row for row in snapshot_rows}
    if len(snapshot_by_key) != len(snapshot_rows):
        raise ValueError("source_snapshot.csv 存在重复 key")
    reviews: dict[str, dict[str, dict]] = {"reviewer_a": {}, "reviewer_b": {}}
    for role in reviews:
        rows = _read_csv(package_dir / f"{role}.csv")
        if {row.get("key") for row in rows} != set(snapshot_by_key):
            raise ValueError(f"{role}.csv 的 key 集合与快照不一致")
        for row in rows:
            snapshot = snapshot_by_key[row["key"]]
            for field in SNAPSHOT_FIELDS:
                if row.get(field, "") != snapshot.get(field, ""):
                    raise ValueError(f"{row['key']}: {role}.csv 的 {field} 已漂移")
            reviews[role][row["key"]] = _validated_review_row(row, expected_role=role)

    for key in snapshot_by_key:
        first_name = reviews["reviewer_a"][key]["reviewer_name"].casefold()
        second_name = reviews["reviewer_b"][key]["reviewer_name"].casefold()
        if first_name == second_name:
            raise ValueError(f"{key}: 两次标注必须由不同审核人独立完成")

    adjudicated_by_key: dict[str, dict[str, str]] = {}
    if adjudication_path:
        for row in _read_csv(adjudication_path):
            if row.get("key") in adjudicated_by_key:
                raise ValueError(f"裁决表存在重复 key：{row.get('key')}")
            key = row.get("key", "")
            if key not in snapshot_by_key:
                raise ValueError(f"裁决表包含未知 key：{key}")
            snapshot = snapshot_by_key[key]
            for field in ("article_id", "source_url", "input_sha256"):
                if row.get(field, "") != snapshot.get(field, ""):
                    raise ValueError(f"{key}: 裁决表的 {field} 已漂移")
            adjudicated_by_key[row.get("key", "")] = row

    output_dir.mkdir(parents=True, exist_ok=True)
    conflict_rows: list[dict] = []
    gold_rows: list[dict] = []
    excluded_count = 0
    agreed_count = 0
    unresolved_count = 0
    for key, snapshot in snapshot_by_key.items():
        first = reviews["reviewer_a"][key]
        second = reviews["reviewer_b"][key]
        if first["status"] == "exclude" or second["status"] == "exclude":
            excluded_count += 1
            unresolved_count += 1
            continue
        roles = ["reviewer_a", "reviewer_b"]
        if _labels_match(first, second):
            agreed_count += 1
            primary = first["primary"]
            related = first["related"]
            rationale = f"A: {first['rationale']} | B: {second['rationale']}"
        else:
            conflict = {
                **{field: snapshot[field] for field in ("key", "article_id", "source_url", "input_sha256")},
                "reviewer_a_primary": first["primary"],
                "reviewer_a_related": ";".join(first["related"]),
                "reviewer_a_rationale": first["rationale"],
                "reviewer_b_primary": second["primary"],
                "reviewer_b_related": ";".join(second["related"]),
                "reviewer_b_rationale": second["rationale"],
                "adjudication_status": "",
                "expected_primary_region": "",
                "expected_related_regions": "",
                "rationale": "",
                "adjudicator_name": "",
                "adjudicated_at": "",
            }
            conflict_rows.append(conflict)
            resolution = adjudicated_by_key.get(key)
            if not resolution or resolution.get("adjudication_status", "").strip().lower() != "resolved":
                unresolved_count += 1
                continue
            primary = resolution.get("expected_primary_region", "").strip()
            if primary not in GOLD_REGIONS:
                raise ValueError(f"{key}: 裁决主地区无效")
            related = _normalize_regions(resolution.get("expected_related_regions", ""))
            if primary in related:
                raise ValueError(f"{key}: 裁决相关地区包含主地区")
            rationale = resolution.get("rationale", "").strip()
            adjudicated_at = resolution.get("adjudicated_at", "").strip()
            if not rationale or not resolution.get("adjudicator_name", "").strip() or not adjudicated_at:
                raise ValueError(f"{key}: 裁决理由、裁决人和时间必填")
            try:
                parsed_adjudicated_at = datetime.fromisoformat(adjudicated_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{key}: adjudicated_at 必须是 ISO-8601 时间") from exc
            if parsed_adjudicated_at.tzinfo is None:
                raise ValueError(f"{key}: adjudicated_at 必须包含时区")
            roles.append("adjudicator")
        gold_rows.append(
            {
                "key": key,
                "article_id": snapshot["article_id"],
                "source_url": snapshot["source_url"],
                "input_sha256": snapshot["input_sha256"],
                "expected_primary_region": primary,
                "expected_related_regions": ";".join(related),
                "reviewer_roles": ";".join(roles),
                "rationale": rationale,
                "adjudicated": "true",
            }
        )

    conflict_fields = (
        "key", "article_id", "source_url", "input_sha256",
        "reviewer_a_primary", "reviewer_a_related", "reviewer_a_rationale",
        "reviewer_b_primary", "reviewer_b_related", "reviewer_b_rationale",
        "adjudication_status", "expected_primary_region", "expected_related_regions",
        "rationale", "adjudicator_name", "adjudicated_at",
    )
    _write_csv(output_dir / "adjudication.csv", conflict_fields, conflict_rows)
    primary_counts = Counter(row["expected_primary_region"] for row in gold_rows)
    cross_count = sum(bool(row["expected_related_regions"]) for row in gold_rows)
    no_go: list[str] = []
    if unresolved_count:
        no_go.append("unresolved_labels")
    if len(gold_rows) < minimum_total:
        no_go.append("total_sample_count")
    if any(primary_counts.get(region, 0) < minimum_per_region for region in GOLD_REGIONS):
        no_go.append("region_sample_count")
    if cross_count < minimum_cross_region:
        no_go.append("cross_region_sample_count")
    qualified = not no_go
    gold_path = output_dir / ("gold_labels.csv" if qualified else "gold_labels_draft.csv")
    _write_csv(gold_path, GOLD_FIELDS, gold_rows)
    report_payload = {
        "schema_version": 1,
        "gold_version": manifest["gold_version"],
        "source_manifest_sha256": _file_sha256(manifest_path),
        "agreed_count": agreed_count,
        "conflict_count": len(conflict_rows),
        "excluded_count": excluded_count,
        "unresolved_count": unresolved_count,
        "final_label_count": len(gold_rows),
        "primary_region_counts": dict(sorted(primary_counts.items())),
        "cross_region_count": cross_count,
        "structurally_qualified": qualified,
        "no_go_reasons": no_go,
        "gold_labels_file": gold_path.name,
        "gold_labels_sha256": _file_sha256(gold_path),
    }
    _write_json(output_dir / "finalize_report.json", report_payload)
    return GoldReviewFinalizeReport(
        output_dir=str(output_dir),
        agreed_count=agreed_count,
        conflict_count=len(conflict_rows),
        excluded_count=excluded_count,
        unresolved_count=unresolved_count,
        final_label_count=len(gold_rows),
        primary_region_counts=dict(primary_counts),
        cross_region_count=cross_count,
        structurally_qualified=qualified,
        no_go_reasons=no_go,
        gold_labels_path=str(gold_path),
    )
