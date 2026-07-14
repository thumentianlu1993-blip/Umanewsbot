from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from stable.adapters.base import CanonicalNewsDraft, SourceArticleDetail, SourceArticleStub
from stable.adapters.international import (
    FranceGalopEnglishNewsAdapter,
    TDNFranceBroadKeywordAdapter,
    TDNFranceKeywordAdapter,
)
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    NewsSnapshot,
    QQPushDelivery,
    RacingRegion,
    SourceKind,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)
from stable.services.ingestion import upsert_article_from_draft


UTC = dt_timezone.utc
NOW = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)


class FakeJSONResponse:
    status_code = 200

    def __init__(self, payload, url="https://www.thoroughbreddailynews.com/wp-json/wp/v2/posts"):
        self.payload = payload
        self.url = url

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def tdn_post(post_id: int, slug: str, published_at: datetime) -> dict:
    return {
        "id": post_id,
        "link": f"https://www.thoroughbreddailynews.com/{slug}/",
        "title": {"rendered": slug.replace("-", " ").title()},
        "date_gmt": published_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
    }


def draft_for(
    *,
    source_article_id: str = "france-1",
    published_at: datetime = NOW,
    verified: bool | None = True,
    evidence_source: str = "detail",
) -> CanonicalNewsDraft:
    return CanonicalNewsDraft(
        source_site=SourceSite.FRANCE_GALOP_NEWS,
        source_mode=SourceMode.OFFICIAL,
        source_article_id=source_article_id,
        source_url=f"https://www.france-galop.com/en/content/{source_article_id}",
        title_ja="France Galop official update",
        body_ja_raw="Official racing body with enough content.",
        body_ja_normalized="Official racing body with enough content.",
        published_at=published_at,
        images=[],
        racing_region=RacingRegion.FRANCE,
        source_language=SourceLanguage.ENGLISH,
        source_kind=SourceKind.OFFICIAL,
        metadata={
            "published_at_verified": verified,
            "published_at_evidence": {
                "source": evidence_source,
                "raw": published_at.isoformat(),
                "timezone": "Europe/Paris" if evidence_source == "detail" else "UTC",
                "verified": verified,
            },
        },
    )


class TDNFrancePostsSearchTests(TestCase):
    def test_keyword_adapter_uses_posts_date_order_and_utc_after(self):
        adapter = TDNFranceKeywordAdapter()
        response = FakeJSONResponse([tdn_post(1, "grand-prix-de-paris", NOW - timedelta(hours=2))])

        with (
            patch("stable.adapters.international.timezone.now", return_value=NOW),
            patch("stable.adapters.international.requests.get", return_value=response) as request_get,
        ):
            stubs = adapter.fetch_listing(SourceMode.LATEST, 1)

        self.assertEqual(len(stubs), 1)
        called_url = request_get.call_args.args[0]
        self.assertEqual(urlsplit(called_url).path, "/wp-json/wp/v2/posts")
        params = request_get.call_args.kwargs.get("params") or parse_qs(urlsplit(called_url).query)
        self.assertEqual(params["orderby"], "date" if isinstance(params["orderby"], str) else ["date"])
        self.assertEqual(params["order"], "desc" if isinstance(params["order"], str) else ["desc"])
        self.assertIn("search", params)
        self.assertIn("after", params)
        self.assertIn("_fields", params)
        after = params["after"] if isinstance(params["after"], str) else params["after"][0]
        self.assertEqual(datetime.fromisoformat(after.replace("Z", "+00:00")), NOW - timedelta(days=3))

    def test_posts_response_does_not_trigger_per_post_date_requests(self):
        adapter = TDNFranceKeywordAdapter()
        response = FakeJSONResponse(
            [
                tdn_post(1, "first-france-story", NOW - timedelta(hours=1)),
                tdn_post(2, "second-france-story", NOW - timedelta(hours=2)),
            ]
        )

        with (
            patch("stable.adapters.international.timezone.now", return_value=NOW),
            patch("stable.adapters.international.requests.get", return_value=response) as request_get,
        ):
            stubs = adapter.fetch_listing(SourceMode.LATEST, 1)

        self.assertEqual(len(stubs), 2)
        self.assertEqual(request_get.call_count, 1)

    def test_three_day_boundary_is_inclusive_and_older_article_is_rejected(self):
        adapter = TDNFranceKeywordAdapter()
        response = FakeJSONResponse(
            [
                tdn_post(1, "boundary-story", NOW - timedelta(days=3)),
                tdn_post(2, "old-story", NOW - timedelta(days=3, seconds=1)),
            ]
        )

        with (
            patch("stable.adapters.international.timezone.now", return_value=NOW),
            patch("stable.adapters.international.requests.get", return_value=response),
        ):
            stubs = adapter.fetch_listing(SourceMode.LATEST, 1)

        self.assertEqual(len(stubs), 1)
        self.assertIn("boundary-story", stubs[0].source_url)
        self.assertTrue(any("stale_published_at" in item for item in adapter.skipped_items))

    def test_broad_queries_dedupe_by_canonical_identity_and_sort_newest_first(self):
        adapter = TDNFranceBroadKeywordAdapter()
        adapter.search_queries = ("France Galop", "ParisLongchamp")
        newer = tdn_post(2, "newer-story", NOW - timedelta(minutes=10))
        older = tdn_post(1, "shared-story", NOW - timedelta(hours=2))
        duplicate = {**older, "title": {"rendered": "Shared Story Duplicate"}}

        with (
            patch("stable.adapters.international.timezone.now", return_value=NOW),
            patch(
                "stable.adapters.international.requests.get",
                side_effect=[FakeJSONResponse([older, newer]), FakeJSONResponse([duplicate])],
            ),
        ):
            stubs = adapter.fetch_listing(SourceMode.ACCESS, 1)

        self.assertEqual([stub.source_url for stub in stubs], [newer["link"], older["link"]])
        self.assertEqual(len(stubs), 2)
        self.assertEqual(stubs[1].metadata["listing_queries"], ["France Galop", "ParisLongchamp"])

    def test_broad_query_keeps_successes_and_audits_partial_failure(self):
        adapter = TDNFranceBroadKeywordAdapter()
        adapter.search_queries = ("France Galop", "ParisLongchamp")
        error_response = Mock(status_code=503)
        error = requests.HTTPError("503 provider unavailable", response=error_response)

        with (
            patch("stable.adapters.international.timezone.now", return_value=NOW),
            patch(
                "stable.adapters.international.requests.get",
                side_effect=[FakeJSONResponse([tdn_post(1, "good-story", NOW)]), error],
            ),
        ):
            stubs = adapter.fetch_listing(SourceMode.ACCESS, 1)

        self.assertEqual(len(stubs), 1)
        self.assertEqual(adapter.last_listing_query_errors[0]["query"], "ParisLongchamp")
        self.assertIn("503", adapter.last_listing_query_errors[0]["error"])

    def test_tdn_stub_preserves_query_url_date_and_verified_evidence(self):
        adapter = TDNFranceKeywordAdapter()
        response = FakeJSONResponse([tdn_post(1, "evidence-story", NOW - timedelta(hours=1))])

        with (
            patch("stable.adapters.international.timezone.now", return_value=NOW),
            patch("stable.adapters.international.requests.get", return_value=response),
        ):
            stub = adapter.fetch_listing(SourceMode.LATEST, 1)[0]

        evidence = stub.metadata["published_at_evidence"]
        self.assertEqual(evidence["source"], "api")
        self.assertEqual(evidence["raw"], "2026-07-12T23:00:00")
        self.assertTrue(evidence["verified"])
        self.assertIn("listing_query", stub.metadata)
        self.assertIn("request_url", stub.metadata)


class FranceGalopPublishedEvidenceTests(TestCase):
    def test_detail_iso_datetime_is_converted_from_paris_to_utc(self):
        adapter = FranceGalopEnglishNewsAdapter()
        detail = adapter.parse_detail_html(
            """
            <article>
              <h1>Official update</h1>
              <time datetime="2026-07-12T15:30:00">12 July 2026</time>
              <p>Official racing body.</p>
            </article>
            """,
            url="https://www.france-galop.com/en/content/official-update",
        )

        self.assertEqual(detail.published_at, datetime(2026, 7, 12, 13, 30, tzinfo=UTC))
        self.assertEqual(detail.metadata["published_at_evidence"]["timezone"], "Europe/Paris")
        self.assertTrue(detail.metadata["published_at_evidence"]["verified"])

    def test_detail_textual_english_date_is_parsed(self):
        adapter = FranceGalopEnglishNewsAdapter()
        detail = adapter.parse_detail_html(
            """
            <main><h1>Official update</h1><div class="date">12 July 2026 - 15:30</div>
            <p>Official racing body.</p></main>
            """,
            url="https://www.france-galop.com/en/content/official-update",
        )

        self.assertEqual(detail.published_at, datetime(2026, 7, 12, 13, 30, tzinfo=UTC))

    def test_detail_weekday_prefixed_date_is_parsed(self):
        adapter = FranceGalopEnglishNewsAdapter()
        detail = adapter.parse_detail_html(
            """
            <main><h1>Official update</h1><p class="date">Sunday, July 12, 2026 - 19:04</p>
            <p>Official racing body.</p></main>
            """,
            url="https://www.france-galop.com/en/content/official-update",
        )

        self.assertEqual(detail.published_at, datetime(2026, 7, 12, 17, 4, tzinfo=UTC))
        self.assertTrue(detail.metadata["published_at_verified"])

    def test_winter_date_uses_paris_standard_time(self):
        adapter = FranceGalopEnglishNewsAdapter()
        detail = adapter.parse_detail_html(
            """
            <article><h1>Winter update</h1><time datetime="2026-01-12T15:30:00">12 January 2026</time>
            <p>Official racing body.</p></article>
            """,
            url="https://www.france-galop.com/en/content/winter-update",
        )

        self.assertEqual(detail.published_at, datetime(2026, 1, 12, 14, 30, tzinfo=UTC))

    def test_missing_detail_date_is_explicit_unverified_fallback(self):
        adapter = FranceGalopEnglishNewsAdapter()
        stub = SourceArticleStub(
            source_site=SourceSite.FRANCE_GALOP_NEWS,
            source_mode=SourceMode.OFFICIAL,
            source_article_id="missing-date",
            source_url="https://www.france-galop.com/en/content/missing-date",
            title_ja="Missing date",
            published_at=NOW,
            metadata={"published_at_evidence": {"source": "listing", "verified": False}},
        )
        detail = adapter.parse_detail_html(
            "<article><h1>Missing date</h1><p>Official racing body.</p></article>",
            url=stub.source_url,
        )

        draft = adapter.normalize_source_payload(stub, detail)

        self.assertEqual(draft.published_at, NOW)
        self.assertFalse(draft.metadata["published_at_verified"])
        self.assertEqual(draft.metadata["published_at_evidence"]["source"], "listing")


class PublishedAtUpsertContractTests(TestCase):
    def test_new_article_persists_structured_published_evidence(self):
        result = upsert_article_from_draft(draft_for())

        self.assertTrue(result.created)
        self.assertTrue(result.article.published_at_verified)
        self.assertEqual(result.article.published_at_evidence["source"], "detail")

    def test_repeated_fallback_never_overwrites_existing_verified_time(self):
        verified_time = NOW - timedelta(days=1)
        article = upsert_article_from_draft(draft_for(published_at=verified_time)).article

        upsert_article_from_draft(
            draft_for(
                published_at=NOW,
                verified=False,
                evidence_source="fallback",
            )
        )

        article.refresh_from_db()
        self.assertEqual(article.published_at, verified_time)
        self.assertTrue(article.published_at_verified)
        self.assertEqual(article.published_at_evidence["source"], "detail")

    def test_verified_detail_can_correct_previous_fallback_time(self):
        article = upsert_article_from_draft(
            draft_for(published_at=NOW, verified=False, evidence_source="fallback")
        ).article
        corrected = NOW - timedelta(days=1)

        upsert_article_from_draft(draft_for(published_at=corrected, verified=True))

        article.refresh_from_db()
        self.assertEqual(article.published_at, corrected)
        self.assertTrue(article.published_at_verified)
        self.assertEqual(article.published_at_evidence["previous_published_at"], NOW.isoformat())

    def test_legacy_null_is_not_treated_as_explicitly_unverified(self):
        field = NewsArticle._meta.get_field("published_at_verified")

        self.assertTrue(field.null)
        self.assertIsNone(field.default)

    def test_re_crawled_legacy_null_becomes_explicitly_unverified_without_changing_time(self):
        original_time = NOW - timedelta(days=2)
        article = upsert_article_from_draft(
            draft_for(published_at=original_time, verified=None, evidence_source="legacy")
        ).article

        upsert_article_from_draft(
            draft_for(published_at=NOW, verified=False, evidence_source="fallback")
        )

        article.refresh_from_db()
        self.assertEqual(article.published_at, original_time)
        self.assertFalse(article.published_at_verified)
        self.assertEqual(article.published_at_evidence["source"], "fallback")

    def test_explicitly_unverified_article_is_blocked_but_legacy_null_is_not(self):
        from stable.services.validation import validate_rewrite

        common = {
            "source_site": SourceSite.FRANCE_GALOP_NEWS,
            "source_mode": SourceMode.OFFICIAL,
            "racing_region": RacingRegion.FRANCE,
            "source_language": SourceLanguage.ENGLISH,
            "title_ja": "French racing update",
            "body_ja_raw": "French racing body " * 30,
            "body_ja_normalized": "French racing body " * 30,
            "translated_title_zh": "法国赛马新闻",
            "title_zh": "法国赛马新闻",
            "translated_body_zh": "法国赛马正文。" * 80,
            "body_zh": "法国赛马正文。" * 80,
            "translated_summary_zh": "法国赛马摘要",
            "summary_zh": "法国赛马摘要",
            "published_at": NOW,
            "translation_status": ArticleTranslationStatus.TRANSLATED,
            "workflow_status": WorkflowStatus.PENDING_REVIEW,
            "automation_status": AutomationStatus.PENDING,
        }
        explicit = NewsArticle.objects.create(
            **common,
            source_article_id="explicit-unverified",
            source_url="https://example.com/explicit-unverified",
            published_at_verified=False,
        )
        legacy = NewsArticle.objects.create(
            **common,
            source_article_id="legacy-unknown",
            source_url="https://example.com/legacy-unknown",
            published_at_verified=None,
        )

        explicit_result = validate_rewrite(explicit)
        legacy_result = validate_rewrite(legacy)

        self.assertIn("published_at_unverified", {issue["code"] for issue in explicit_result.issues})
        self.assertNotIn("published_at_unverified", {issue["code"] for issue in legacy_result.issues})


class FranceGalopTimeRepairCommandTests(TestCase):
    def _article(self, source_article_id: str = "repair-me") -> NewsArticle:
        return NewsArticle.objects.create(
            source_site=SourceSite.FRANCE_GALOP_NEWS,
            source_mode=SourceMode.OFFICIAL,
            racing_region=RacingRegion.FRANCE,
            source_language=SourceLanguage.ENGLISH,
            source_article_id=source_article_id,
            source_url=f"https://www.france-galop.com/en/content/{source_article_id}",
            title_ja="Repair me",
            body_ja_raw="Body",
            body_ja_normalized="Body",
            published_at=NOW,
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            published_at_verified=False,
        )

    def test_dry_run_writes_no_article_snapshot_publish_or_qq_side_effect(self):
        article = self._article()
        output = StringIO()

        with patch(
            "stable.management.commands.repair_france_galop_published_at.fetch_verified_evidence",
            return_value={"published_at": NOW - timedelta(days=1), "raw": "12 July 2026", "verified": True},
        ):
            call_command("repair_france_galop_published_at", "--dry-run", "--article-id", article.id, stdout=output)

        article.refresh_from_db()
        self.assertEqual(article.published_at, NOW)
        self.assertFalse(article.published_at_verified)
        self.assertEqual(NewsSnapshot.objects.count(), 0)
        self.assertEqual(QQPushDelivery.objects.count(), 0)
        self.assertIn("manifest_sha256", output.getvalue())

    def test_commit_requires_matching_dry_run_manifest(self):
        article = self._article()

        with self.assertRaises(CommandError):
            call_command(
                "repair_france_galop_published_at",
                "--commit",
                "--article-id",
                article.id,
                "--manifest-sha256",
                "0" * 64,
            )

    def test_commit_rejects_article_drift_and_does_not_publish(self):
        article = self._article()
        from stable.services.published_time_repair import create_time_repair_dry_run, commit_time_repair

        run = create_time_repair_dry_run(
            [article],
            evidence_by_article={article.id: {"published_at": NOW - timedelta(days=1), "raw": "12 July 2026"}},
        )
        article.title_ja = "Changed after dry run"
        article.save(update_fields=["title_ja", "updated_at"])

        result = commit_time_repair(run_id=run.id, manifest_sha256=run.manifest_sha256)

        article.refresh_from_db()
        self.assertEqual(result.drifted_ids, [article.id])
        self.assertIsNone(article.published_to_web_at)
        self.assertEqual(QQPushDelivery.objects.count(), 0)

    def test_commit_skips_missing_date_without_aborting_verified_rows(self):
        from stable.services.published_time_repair import create_time_repair_dry_run, commit_time_repair

        verified = self._article()
        missing = self._article("repair-missing-date")
        run = create_time_repair_dry_run(
            [verified, missing],
            evidence_by_article={
                verified.id: {"published_at": NOW - timedelta(days=1), "raw": "12 July 2026"},
                missing.id: {"published_at": None, "raw": "", "error": "missing_date"},
            },
        )

        result = commit_time_repair(run_id=run.id, manifest_sha256=run.manifest_sha256)

        verified.refresh_from_db()
        missing.refresh_from_db()
        self.assertEqual(result.applied_ids, [verified.id])
        self.assertEqual(result.skipped[missing.id], "missing_date")
        self.assertTrue(verified.published_at_verified)
        self.assertFalse(missing.published_at_verified)

    def test_commit_skips_deleted_article_and_invalid_datetime(self):
        from stable.services.published_time_repair import create_time_repair_dry_run, commit_time_repair

        deleted = self._article("deleted-before-commit")
        invalid = self._article("invalid-date")
        run = create_time_repair_dry_run(
            [deleted, invalid],
            evidence_by_article={
                deleted.id: {"published_at": NOW - timedelta(days=1), "raw": "12 July 2026"},
                invalid.id: {"published_at": NOW - timedelta(days=1), "raw": "bad"},
            },
        )
        rows = list(run.candidate_payload)
        rows[1]["published_at"] = "not-a-date"
        run.candidate_payload = rows
        run.save(update_fields=["candidate_payload", "updated_at"])
        deleted_id = deleted.id
        invalid_id = invalid.id
        deleted.delete()

        result = commit_time_repair(run_id=run.id, manifest_sha256=run.manifest_sha256)

        self.assertEqual(result.skipped[deleted_id], "article_missing")
        self.assertEqual(result.skipped[invalid_id], "invalid_published_at")
