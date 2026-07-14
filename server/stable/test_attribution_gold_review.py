from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from stable.models import NewsArticle, RacingRegion, SourceLanguage, SourceMode, SourceSite
from stable.services.attribution_gold_review import (
    GOLD_REGIONS,
    build_gold_review_package,
    finalize_gold_review_package,
    finalize_provisional_single_review_package,
)
from stable.services.attribution_quality import GoldLabel, evaluate_gold_set


NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)


def make_article(*, region: str, index: int, title: str) -> NewsArticle:
    return NewsArticle.objects.create(
        source_site=SourceSite.TDN,
        source_mode=SourceMode.LATEST,
        source_article_id=f"gold-review-{region}-{index}",
        source_url=f"https://example.com/{region}/{index}",
        racing_region=region,
        source_language=SourceLanguage.ENGLISH,
        title_ja=title,
        body_ja_raw=f"{title} Full story body.",
        body_ja_normalized=f"{title} Full story body.",
        title_zh=f"中文 {title}",
        body_zh="中文正文",
        published_at=NOW,
    )


def update_review_csv(path: Path, *, conflict_key: str = "", conflict_region: str = "") -> None:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    fieldnames = list(rows[0])
    for row in rows:
        row["reviewer_name"] = row["reviewer_role"]
        row["reviewed_at"] = "2026-07-13T10:00:00+00:00"
        row["review_status"] = "ready"
        row["expected_primary_region"] = row["sampled_article_region"]
        row["expected_related_regions"] = ""
        row["allow_source_fallback"] = "true"
        row["rationale"] = "正文没有更强赛事证据，使用来源回退。"
        if row["key"] == conflict_key:
            row["expected_primary_region"] = conflict_region
            row["allow_source_fallback"] = "false"
            row["rationale"] = "中心赛事位于另一个地区。"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class AttributionGoldReviewTests(TestCase):
    def setUp(self):
        for region in GOLD_REGIONS:
            make_article(
                region=region,
                index=1,
                title=f"{region} report: Prix de Diane at Chantilly and Breeders Cup at Keeneland",
            )
            make_article(region=region, index=2, title=f"Routine racing update for {region}")

    def test_build_package_is_blind_versioned_and_has_manifest_hashes(self):
        duplicate = make_article(
            region=RacingRegion.UNITED_KINGDOM,
            index=3,
            title="Duplicate placeholder",
        )
        original = NewsArticle.objects.filter(racing_region=RacingRegion.UNITED_KINGDOM).first()
        duplicate.title_ja = original.title_ja
        duplicate.body_ja_raw = original.body_ja_raw
        duplicate.body_ja_normalized = original.body_ja_normalized
        duplicate.save(update_fields=["title_ja", "body_ja_raw", "body_ja_normalized"])
        with TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "review"
            report = build_gold_review_package(
                output_dir=output_dir,
                version="multiregion-gold-v1-test",
                per_region=2,
                cross_candidate_target=5,
                seed="fixed",
            )

            self.assertEqual(report.selected_count, 10)
            self.assertEqual(report.region_counts, {region: 2 for region in GOLD_REGIONS})
            self.assertGreaterEqual(report.machine_cross_candidate_count, 5)
            with (output_dir / "source_snapshot.csv").open(newline="", encoding="utf-8-sig") as handle:
                snapshot_rows = list(csv.DictReader(handle))
            self.assertEqual(len({row["input_sha256"] for row in snapshot_rows}), 10)
            manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["selection"]["selected_count"], 10)
            review_text = (output_dir / "reviewer_a.csv").read_text(encoding="utf-8-sig")
            self.assertIn("title_original", review_text)
            self.assertNotIn("machine_cross_candidate", review_text)
            self.assertNotIn("primary_region\":", review_text)

    def test_finalize_requires_conflict_adjudication_before_gold_is_qualified(self):
        with TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "review"
            build_gold_review_package(
                output_dir=package_dir,
                version="multiregion-gold-v1-test",
                per_region=1,
                cross_candidate_target=0,
                seed="fixed",
            )
            snapshot_rows = list(csv.DictReader((package_dir / "source_snapshot.csv").open(encoding="utf-8-sig")))
            conflict_key = snapshot_rows[0]["key"]
            update_review_csv(package_dir / "reviewer_a.csv")
            update_review_csv(
                package_dir / "reviewer_b.csv",
                conflict_key=conflict_key,
                conflict_region=RacingRegion.FRANCE,
            )

            first_output = Path(tmp) / "first"
            first = finalize_gold_review_package(
                package_dir=package_dir,
                output_dir=first_output,
                minimum_total=5,
                minimum_per_region=0,
                minimum_cross_region=0,
            )

            self.assertEqual(first.conflict_count, 1)
            self.assertEqual(first.unresolved_count, 1)
            self.assertFalse(first.structurally_qualified)
            self.assertTrue(first.gold_labels_path.endswith("gold_labels_draft.csv"))

            adjudication_path = first_output / "adjudication.csv"
            with adjudication_path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0])
            rows[0].update(
                {
                    "adjudication_status": "resolved",
                    "expected_primary_region": RacingRegion.JAPAN,
                    "expected_related_regions": RacingRegion.FRANCE,
                    "rationale": "裁决认定日本对象赴法国参赛。",
                    "adjudicator_name": "adjudicator",
                    "adjudicated_at": "2026-07-13T11:00:00+00:00",
                }
            )
            with adjudication_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            second = finalize_gold_review_package(
                package_dir=package_dir,
                output_dir=Path(tmp) / "second",
                adjudication_path=adjudication_path,
                minimum_total=5,
                minimum_per_region=0,
                minimum_cross_region=1,
            )

            self.assertTrue(second.structurally_qualified)
            self.assertEqual(second.final_label_count, 5)
            self.assertEqual(second.cross_region_count, 1)
            self.assertTrue(second.gold_labels_path.endswith("gold_labels.csv"))

    def test_finalize_rejects_reviewer_identity_drift(self):
        with TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "review"
            build_gold_review_package(
                output_dir=package_dir,
                version="multiregion-gold-v1-test",
                per_region=1,
                cross_candidate_target=0,
            )
            update_review_csv(package_dir / "reviewer_a.csv")
            update_review_csv(package_dir / "reviewer_b.csv")
            path = package_dir / "reviewer_b.csv"
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0])
            rows[0]["input_sha256"] = "0" * 64
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaisesMessage(ValueError, "input_sha256 已漂移"):
                finalize_gold_review_package(package_dir=package_dir, output_dir=Path(tmp) / "out")

    def test_provisional_single_review_ignores_blank_rows_and_keeps_structural_gates(self):
        with TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "review"
            build_gold_review_package(
                output_dir=package_dir,
                version="multiregion-gold-v1-test",
                per_region=1,
                cross_candidate_target=0,
            )
            reviewer_path = package_dir / "reviewer_a.csv"
            with reviewer_path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
                fieldnames = list(rows[0])
            rows[0]["review_status"] = "exclude"
            rows[0]["rationale"] = "不是新闻。"
            rows[1]["expected_primary_region"] = "united_state"
            rows[2]["expected_primary_region"] = RacingRegion.OTHER
            rows[2]["expected_related_regions"] = "所有地区"
            rows[3]["expected_primary_region"] = RacingRegion.FRANCE
            # A note without any region selection is still unselected and must be ignored.
            rows[4]["rationale"] = "未选中，留给后续审核。"
            with reviewer_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            report = finalize_provisional_single_review_package(
                package_dir=package_dir,
                reviewer_path=reviewer_path,
                output_dir=Path(tmp) / "final",
            )

            self.assertEqual(report.review_mode, "provisional_single_review")
            self.assertEqual(report.final_label_count, 3)
            self.assertEqual(report.excluded_count, 1)
            self.assertEqual(report.ignored_count, 1)
            self.assertFalse(report.structurally_qualified)
            self.assertNotIn("provisional_single_review", report.no_go_reasons)
            self.assertIn("total_sample_count", report.no_go_reasons)
            with Path(report.gold_labels_path).open(newline="", encoding="utf-8-sig") as handle:
                labels = list(csv.DictReader(handle))
            self.assertEqual(labels[0]["expected_primary_region"], RacingRegion.UNITED_STATES)
            self.assertEqual(labels[1]["expected_primary_region"], RacingRegion.OTHER)
            self.assertEqual(set(labels[1]["expected_related_regions"].split(";")), set(GOLD_REGIONS))
            self.assertTrue(all(label["adjudicated"] == "false" for label in labels))

    def test_provisional_evaluation_reports_metrics_and_keeps_coverage_gates(self):
        label = GoldLabel(
            key="single-review-1",
            article_id=1,
            source_url="https://example.com/1",
            input_sha256="a" * 64,
            expected_primary_region=RacingRegion.FRANCE,
            expected_related_regions=[RacingRegion.UNITED_KINGDOM],
            reviewer_roles=["reviewer_a"],
            rationale="法国赛事有英国参赛马。",
            adjudicated=False,
        )
        actual = {
            label.key: {
                "input_sha256": label.input_sha256,
                "primary_region": RacingRegion.FRANCE,
                "related_regions": [RacingRegion.UNITED_KINGDOM],
            }
        }

        strict = evaluate_gold_set([label], actual)
        provisional = evaluate_gold_set([label], actual, allow_provisional=True)

        self.assertEqual(strict.valid_denominator, 0)
        self.assertEqual(strict.unresolved_count, 1)
        self.assertEqual(provisional.valid_denominator, 1)
        self.assertEqual(provisional.primary_accuracy, 1.0)
        self.assertEqual(provisional.review_mode, "single_review")
        self.assertFalse(provisional.qualified)
        self.assertNotIn("provisional_single_review", provisional.no_go_reasons)
        self.assertIn("total_sample_count", provisional.no_go_reasons)

    @override_settings(
        MULTIREGION_ATTRIBUTION_GOLD_MIN_TOTAL=5,
        MULTIREGION_ATTRIBUTION_GOLD_MIN_PER_REGION=1,
        MULTIREGION_ATTRIBUTION_GOLD_MIN_CROSS_REGION=0,
    )
    def test_single_review_finalizer_uses_configured_coverage_thresholds(self):
        with TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "review"
            build_gold_review_package(
                output_dir=package_dir,
                version="multiregion-gold-v1-test",
                per_region=1,
                cross_candidate_target=0,
            )
            reviewer_path = package_dir / "reviewer_a.csv"
            update_review_csv(reviewer_path)

            report = finalize_provisional_single_review_package(
                package_dir=package_dir,
                reviewer_path=reviewer_path,
                output_dir=Path(tmp) / "final",
            )

            self.assertEqual(report.final_label_count, 5)
            self.assertTrue(report.structurally_qualified)
            self.assertEqual(report.no_go_reasons, [])

    def test_current_159_single_review_shape_can_qualify(self):
        labels = []
        actual = {}
        region_counts = [
            (RacingRegion.JAPAN, 46),
            (RacingRegion.HONG_KONG, 50),
            (RacingRegion.UNITED_KINGDOM, 30),
            (RacingRegion.FRANCE, 11),
            (RacingRegion.UNITED_STATES, 17),
            (RacingRegion.OTHER, 5),
        ]
        for index, (region, count) in enumerate(region_counts):
            related_region = GOLD_REGIONS[(index + 1) % len(GOLD_REGIONS)]
            for offset in range(count):
                key = f"single-review-{index}-{offset}"
                expected_related = [related_region] if len(labels) < 24 else []
                article_id = len(labels) + 1
                label = GoldLabel(
                    key=key,
                    article_id=article_id,
                    source_url=f"https://example.com/{key}",
                    input_sha256=f"{article_id:064x}",
                    expected_primary_region=region,
                    expected_related_regions=expected_related,
                    reviewer_roles=["reviewer_a"],
                    rationale="单审完整覆盖测试。",
                    adjudicated=False,
                )
                labels.append(label)
                actual[key] = {
                    "input_sha256": label.input_sha256,
                    "primary_region": region,
                    "related_regions": expected_related,
                }

        report = evaluate_gold_set(labels, actual, allow_provisional=True)

        self.assertTrue(report.qualified)
        self.assertEqual(report.valid_denominator, 159)
        self.assertEqual(report.review_mode, "single_review")
        self.assertEqual(report.no_go_reasons, [])

    def test_source_term_patterns_are_reused_across_batch_articles(self):
        from stable.services.terms import _source_term_pattern

        _source_term_pattern.cache_clear()
        first = _source_term_pattern("Prix de Diane", SourceLanguage.ENGLISH)
        second = _source_term_pattern("Prix de Diane", SourceLanguage.ENGLISH)

        self.assertIs(first, second)
        self.assertEqual(_source_term_pattern.cache_info().hits, 1)
