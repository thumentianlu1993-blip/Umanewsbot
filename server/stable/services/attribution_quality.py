from __future__ import annotations

import math
import csv
import hashlib
import resource
import time
from dataclasses import dataclass, field

from django.conf import settings

from stable.models import RacingRegion
from stable.services.news_attribution import AttributionBatchContext, infer_article_attribution


DEFAULT_GOLD_MIN_TOTAL = 150
DEFAULT_GOLD_MIN_PER_REGION = 10
DEFAULT_GOLD_MIN_CROSS_REGION = 20


def gold_coverage_thresholds() -> tuple[int, int, int]:
    return (
        max(1, int(getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_MIN_TOTAL", DEFAULT_GOLD_MIN_TOTAL))),
        max(
            0,
            int(getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_MIN_PER_REGION", DEFAULT_GOLD_MIN_PER_REGION)),
        ),
        max(
            0,
            int(getattr(settings, "MULTIREGION_ATTRIBUTION_GOLD_MIN_CROSS_REGION", DEFAULT_GOLD_MIN_CROSS_REGION)),
        ),
    )


@dataclass(frozen=True)
class GoldLabel:
    key: str
    article_id: int
    source_url: str
    input_sha256: str
    expected_primary_region: str
    expected_related_regions: list[str]
    reviewer_roles: list[str]
    rationale: str
    adjudicated: bool


@dataclass(frozen=True)
class GoldQualityReport:
    total_labels: int
    valid_denominator: int
    unresolved_count: int
    drifted_count: int
    region_valid_counts: dict[str, int]
    primary_accuracy: float
    region_primary_accuracy: dict[str, float]
    related_precision: float
    related_recall: float
    unsupported_primary_change_rate: float
    over_expansion_rate: float
    locked_override_count: int
    wilson_intervals: dict[str, tuple[float, float]]
    review_mode: str
    qualified: bool
    no_go_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AttributionBenchmarkReport:
    elapsed_seconds: float
    rss_delta_bytes: int
    preload_counts: dict[str, int]


def wilson_interval(successes: int, total: int, *, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def load_gold_labels(path) -> list[GoldLabel]:
    labels: list[GoldLabel] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            labels.append(
                GoldLabel(
                    key=row["key"].strip(),
                    article_id=int(row["article_id"]),
                    source_url=row["source_url"].strip(),
                    input_sha256=row["input_sha256"].strip(),
                    expected_primary_region=row["expected_primary_region"].strip(),
                    expected_related_regions=[item.strip() for item in row.get("expected_related_regions", "").split(";") if item.strip()],
                    reviewer_roles=[item.strip() for item in row.get("reviewer_roles", "").split(";") if item.strip()],
                    rationale=row.get("rationale", "").strip(),
                    adjudicated=row.get("adjudicated", "").strip().lower() in {"1", "true", "yes"},
                )
            )
    return labels


def article_input_sha256(article) -> str:
    text = "\n".join([article.title_ja or "", article.body_ja_normalized or article.body_ja_raw or ""])
    return hashlib.sha256(text.encode()).hexdigest()


def evaluate_gold_labels_against_database(
    labels: list[GoldLabel],
    *,
    allow_provisional: bool = False,
) -> GoldQualityReport:
    from stable.models import NewsArticle

    articles = list(
        NewsArticle.objects.filter(id__in=[label.article_id for label in labels])
        .select_related("source_config")
        .prefetch_related("related_region_links")
    )
    by_id = {article.id: article for article in articles}
    context = AttributionBatchContext.build(articles)
    actual: dict[str, dict] = {}
    for label in labels:
        article = by_id.get(label.article_id)
        if article is None:
            continue
        result = infer_article_attribution(article, batch_context=context)
        actual[label.key] = {
            "input_sha256": article_input_sha256(article),
            "primary_region": result.primary_region,
            "related_regions": result.related_regions,
            "unsupported_primary_change": result.primary_region != article.racing_region and result.confidence_band == "low",
            "over_expansion": len(result.related_regions) > 2 and not label.expected_related_regions,
            "locked_override": article.attribution_locked and result.primary_region != article.racing_region,
        }
    return evaluate_gold_set(labels, actual, allow_provisional=allow_provisional)


def evaluate_gold_set(
    labels: list[GoldLabel],
    actual: dict[str, dict],
    *,
    allow_provisional: bool = False,
) -> GoldQualityReport:
    valid: list[tuple[GoldLabel, dict]] = []
    unresolved_count = 0
    drifted_count = 0
    for label in labels:
        review_is_valid = bool(label.reviewer_roles) if allow_provisional else (
            label.adjudicated and len(set(label.reviewer_roles)) >= 2
        )
        if not review_is_valid:
            unresolved_count += 1
            continue
        outcome = actual.get(label.key)
        if not outcome or outcome.get("input_sha256") != label.input_sha256:
            drifted_count += 1
            continue
        valid.append((label, outcome))

    regions = [
        RacingRegion.JAPAN,
        RacingRegion.HONG_KONG,
        RacingRegion.UNITED_KINGDOM,
        RacingRegion.FRANCE,
        RacingRegion.UNITED_STATES,
    ]
    region_counts = {region: 0 for region in regions}
    region_correct = {region: 0 for region in regions}
    primary_correct = 0
    related_tp = 0
    related_fp = 0
    related_fn = 0
    unsupported_changes = 0
    over_expansions = 0
    locked_overrides = 0
    for label, outcome in valid:
        region_counts[label.expected_primary_region] = region_counts.get(label.expected_primary_region, 0) + 1
        is_primary_correct = outcome.get("primary_region") == label.expected_primary_region
        primary_correct += int(is_primary_correct)
        region_correct[label.expected_primary_region] = region_correct.get(label.expected_primary_region, 0) + int(
            is_primary_correct
        )
        expected_related = set(label.expected_related_regions)
        actual_related = set(outcome.get("related_regions") or [])
        related_tp += len(expected_related & actual_related)
        related_fp += len(actual_related - expected_related)
        related_fn += len(expected_related - actual_related)
        unsupported_changes += int(bool(outcome.get("unsupported_primary_change")))
        over_expansions += int(bool(outcome.get("over_expansion")) or len(actual_related - expected_related) > 2)
        locked_overrides += int(bool(outcome.get("locked_override")))

    denominator = len(valid)
    primary_accuracy = primary_correct / denominator if denominator else 0.0
    region_accuracy = {
        region: region_correct.get(region, 0) / count if count else 0.0
        for region, count in region_counts.items()
    }
    related_precision = related_tp / (related_tp + related_fp) if related_tp + related_fp else 1.0
    related_recall = related_tp / (related_tp + related_fn) if related_tp + related_fn else 1.0
    unsupported_rate = unsupported_changes / denominator if denominator else 0.0
    expansion_rate = over_expansions / denominator if denominator else 0.0
    cross_region_count = sum(bool(label.expected_related_regions) for label, _outcome in valid)
    no_go: list[str] = []
    minimum_total, minimum_per_region, minimum_cross_region = gold_coverage_thresholds()
    if denominator < minimum_total:
        no_go.append("total_sample_count")
    if any(region_counts.get(region, 0) < minimum_per_region for region in regions):
        no_go.append("region_sample_count")
    if cross_region_count < minimum_cross_region:
        no_go.append("cross_region_sample_count")
    if primary_accuracy < float(getattr(settings, "MULTIREGION_ATTRIBUTION_OVERALL_ACCURACY_MIN", 0.95)):
        no_go.append("overall_primary_accuracy")
    if any(
        region_accuracy.get(region, 0.0)
        < float(getattr(settings, "MULTIREGION_ATTRIBUTION_REGION_ACCURACY_MIN", 0.90))
        for region in regions
    ):
        no_go.append("region_accuracy")
    if related_precision < float(getattr(settings, "MULTIREGION_ATTRIBUTION_RELATED_PRECISION_MIN", 0.95)):
        no_go.append("related_precision")
    if related_recall < float(getattr(settings, "MULTIREGION_ATTRIBUTION_RELATED_RECALL_MIN", 0.50)):
        no_go.append("related_recall")
    if unsupported_rate > 0.02:
        no_go.append("unsupported_primary_change")
    if expansion_rate > 0.01:
        no_go.append("over_expansion")
    if locked_overrides:
        no_go.append("locked_override")
    return GoldQualityReport(
        total_labels=len(labels),
        valid_denominator=denominator,
        unresolved_count=unresolved_count,
        drifted_count=drifted_count,
        region_valid_counts=region_counts,
        primary_accuracy=primary_accuracy,
        region_primary_accuracy=region_accuracy,
        related_precision=related_precision,
        related_recall=related_recall,
        unsupported_primary_change_rate=unsupported_rate,
        over_expansion_rate=expansion_rate,
        locked_override_count=locked_overrides,
        wilson_intervals={"primary_accuracy": wilson_interval(primary_correct, denominator)},
        review_mode="single_review" if allow_provisional else "dual_review",
        qualified=not no_go,
        no_go_reasons=no_go,
    )


def benchmark_attribution_batch(articles) -> AttributionBenchmarkReport:
    article_rows = list(articles)
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.monotonic()
    context = AttributionBatchContext.build(article_rows)
    for article in article_rows:
        infer_article_attribution(article, batch_context=context)
    elapsed = time.monotonic() - started
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    multiplier = 1 if __import__("sys").platform == "darwin" else 1024
    return AttributionBenchmarkReport(
        elapsed_seconds=elapsed,
        rss_delta_bytes=max(0, (rss_after - rss_before) * multiplier),
        preload_counts=context.preload_counts,
    )


def build_stratified_review_sample(outcomes: list[dict], *, per_region: int = 10) -> list[dict]:
    selected: dict[int, dict] = {}
    for outcome in outcomes:
        if outcome.get("primary_changed") or outcome.get("status") == "needs_review":
            selected[int(outcome["article_id"])] = outcome
    grouped: dict[str, list[dict]] = {}
    for outcome in outcomes:
        grouped.setdefault(str(outcome.get("primary_region") or ""), []).append(outcome)
    for rows in grouped.values():
        for outcome in sorted(rows, key=lambda item: int(item["article_id"]))[: max(0, per_region)]:
            selected[int(outcome["article_id"])] = outcome
    return [selected[key] for key in sorted(selected)]
