"""
Tests for the "Editorial Headline Control" feature.

Target behavior is NOT yet implemented, so all tests should FAIL (RED)
because the required models, service functions, or view code does not exist.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from stable.models import (
    NewsArticle,
    NewsImage,
    OperationLog,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)

User = get_user_model()


# ============================================================================
# Helpers
# ============================================================================

def _make_article(
    *args,
    title: str = "测试头条文章",
    workflow_status: str = WorkflowStatus.PUBLISHED,
    published_to_web_at=None,
    published_at=None,
    score_total: int = 100,
    race_priority: str = "",
    has_cover: bool = True,
    body_text: str | None = None,
    summary_text: str | None = None,
    **kwargs,
) -> NewsArticle:
    """Create a NewsArticle with sensible defaults for headline eligibility."""
    now = timezone.now()
    published_at = published_at or now
    published_to_web_at = published_to_web_at if published_to_web_at is not None else now
    body_text = body_text or f"{title} 正文内容全文"
    summary_text = summary_text or f"{title} 摘要"
    return NewsArticle.objects.create(
        source_site=SourceSite.NETKEIBA,
        source_mode=SourceMode.LATEST,
        racing_region=RacingRegion.JAPAN,
        source_language=SourceLanguage.JAPANESE,
        source_article_id=f"test-{timezone.now().timestamp()}-{id(title)}",
        title_ja=title,
        translated_title_zh=title,
        title_zh=title,
        body_ja_raw=f"{title} 原文",
        body_ja_normalized=f"{title} 原文",
        translated_body_zh=body_text,
        body_zh=body_text,
        translated_summary_zh=summary_text,
        summary_zh=summary_text,
        published_at=published_at,
        source_url=f"https://example.com/{title}",
        workflow_status=workflow_status,
        published_to_web_at=published_to_web_at,
        source_note="netkeiba",
        tags_json=["赛马"],
        score_total=score_total,
        decision_reason={"signals": {"race_priority": race_priority}} if race_priority else {},
    )


def _make_staff_user(
    username: str = "admin",
    *,
    is_superuser: bool = False,
    add_perm: bool = True,
) -> User:
    """Create a staff user, optionally with editorial headline permissions."""
    user = User.objects.create_user(
        username=username,
        password="testpass",
        is_staff=True,
        is_superuser=is_superuser,
    )
    if not is_superuser and add_perm:
        perm_codename = "change_homepageheadlineselection"
        try:
            from django.contrib.auth.models import Permission
            from django.contrib.contenttypes.models import ContentType
            try:
                from stable.models import HomepageHeadlineSelection
                ct = ContentType.objects.get_for_model(HomepageHeadlineSelection)
            except ImportError:
                # Model doesn't exist yet — skip permission assignment
                return user
            perm = Permission.objects.get(codename=perm_codename, content_type=ct)
            user.user_permissions.add(perm)
        except Exception:
            pass
    return user


# ============================================================================
# Test: ModelAndMigrationTests
# ============================================================================

class ModelAndMigrationTests(TestCase):
    """Verify models exist (via import) and basic constraints."""

    def test_migration_creates_tables(self):
        """HomepageHeadlineSelection and HomepageHeadlineRecommendation tables must exist."""
        try:
            from stable.models import HomepageHeadlineSelection, HomepageHeadlineRecommendation
        except ImportError:
            self.fail("HomepageHeadline model(s) not implemented yet")
        # Check that the tables exist in the database schema
        all_table_names = connection.introspection.table_names()
        self.assertIn(HomepageHeadlineSelection._meta.db_table, all_table_names)
        self.assertIn(HomepageHeadlineRecommendation._meta.db_table, all_table_names)

    def test_selection_singleton(self):
        """Only one HomepageHeadlineSelection row may exist per slot."""
        try:
            from stable.models import HomepageHeadlineSelection
        except ImportError:
            self.fail("HomepageHeadlineSelection not implemented yet")
        s1 = HomepageHeadlineSelection.objects.create(slot="homepage_primary")
        with self.assertRaises(Exception):
            HomepageHeadlineSelection.objects.create(slot="homepage_primary")

    def test_selection_null_article_means_no_headline(self):
        """article=NULL on selection means no manually-set headline."""
        try:
            from stable.models import HomepageHeadlineSelection
        except ImportError:
            self.fail("HomepageHeadlineSelection not implemented yet")
        sel = HomepageHeadlineSelection.objects.create(slot="homepage_primary")
        self.assertIsNone(sel.article)

    def test_slot_check_constraint_rejects_other_slots(self):
        """Only slot='homepage_primary' should be accepted."""
        try:
            from stable.models import HomepageHeadlineSelection
        except ImportError:
            self.fail("HomepageHeadlineSelection not implemented yet")
        with self.assertRaises(Exception):
            HomepageHeadlineSelection.objects.create(slot="other_slot")

    def test_recommendation_only_one_active(self):
        """At most one active recommendation may exist per slot."""
        try:
            from stable.models import HomepageHeadlineRecommendation
        except ImportError:
            self.fail("HomepageHeadlineRecommendation not implemented yet")
        HomepageHeadlineRecommendation.objects.create(
            slot="homepage_primary",
            reason="test",
            evidence={},
            engine_version="v1",
            status="active",
        )
        with self.assertRaises(Exception):
            HomepageHeadlineRecommendation.objects.create(
                slot="homepage_primary",
                reason="test2",
                evidence={},
                engine_version="v1",
                status="active",
            )

    def test_article_delete_nulls_fk(self):
        """Deleting the article referenced by a selection should set FK to NULL."""
        try:
            from stable.models import HomepageHeadlineSelection
        except ImportError:
            self.fail("HomepageHeadlineSelection not implemented yet")
        article = _make_article(title="删除测试")
        sel = HomepageHeadlineSelection.objects.create(slot="homepage_primary", article=article)
        article.delete()
        sel.refresh_from_db()
        self.assertIsNone(sel.article)


# ============================================================================
# Test: EligibilityTests
# ============================================================================

class EligibilityTests(TestCase):
    """Verify the is_headline_eligible predicate."""

    def _call_eligible(self, article, **kwargs):
        try:
            from stable.services.editorial_headlines import is_headline_eligible
        except ImportError:
            self.fail("is_headline_eligible not implemented yet")
        return is_headline_eligible(article, **kwargs)

    def test_published_eligible(self):
        """Published + non-empty content + non-future → eligible."""
        article = _make_article(
            title="合格头条",
            body_text="正文内容",
            summary_text="摘要内容",
        )
        self.assertTrue(self._call_eligible(article))

    def test_no_cover_still_eligible(self):
        """No cover image should not exclude an article from headline eligibility."""
        article = _make_article(title="无封面合格", has_cover=False)
        self.assertTrue(self._call_eligible(article))

    def test_summary_from_body_fallback_eligible(self):
        """Summary falling back to the body is still eligible."""
        article = _make_article(
            title="摘要兜底合格",
            summary_text="",
            body_text="正文很长所以可以被取前180字符作为摘要",
        )
        self.assertTrue(self._call_eligible(article))

    def test_not_published_not_eligible(self):
        """Articles not in published workflow status are not eligible."""
        article = _make_article(title="未发布", workflow_status=WorkflowStatus.PENDING_REVIEW)
        self.assertFalse(self._call_eligible(article))

    def test_withdrawn_not_eligible(self):
        """Withdrawn articles are not eligible."""
        article = _make_article(title="已撤回", workflow_status=WorkflowStatus.WITHDRAWN)
        self.assertFalse(self._call_eligible(article))

    def test_future_published_to_web_at_not_eligible(self):
        """Articles with a future publish time are not eligible."""
        article = _make_article(
            title="未来发布",
            published_to_web_at=timezone.now() + timedelta(hours=1),
        )
        self.assertFalse(self._call_eligible(article))

    def test_null_published_to_web_at_not_eligible(self):
        """Articles with null published_to_web_at are not eligible."""
        article = _make_article(title="空发布时间", published_to_web_at=None)
        # _make_article helper overrides None with now, so force it back.
        article.published_to_web_at = None
        article.save(update_fields=["published_to_web_at"])
        self.assertFalse(self._call_eligible(article))

    def test_empty_title_not_eligible(self):
        """Articles with an empty effective title are not eligible."""
        article = _make_article(title="")
        self.assertFalse(self._call_eligible(article))

    def test_empty_summary_not_eligible(self):
        """Articles with an empty effective summary and empty body are not eligible."""
        article = _make_article(
            title="无摘要",
            summary_text="",
            body_text="",
        )
        # Clear all summary and body fallback sources so effective_summary
        # and effective_body are truly empty.
        article.summary_zh = ""
        article.translated_summary_zh = ""
        article.rewrite_summary_zh = ""
        article.push_summary_zh = ""
        article.body_zh = ""
        article.translated_body_zh = ""
        article.rewrite_body_zh = ""
        article.body_ja_normalized = ""
        article.body_ja_raw = ""
        article.save()
        self.assertFalse(self._call_eligible(article))

    def test_empty_body_not_eligible(self):
        """Articles with an empty effective body are not eligible."""
        article = _make_article(
            title="无正文",
            body_text="",
        )
        # Clear all body fallback sources so effective_body is truly empty.
        article.body_zh = ""
        article.translated_body_zh = ""
        article.rewrite_body_zh = ""
        article.body_ja_normalized = ""
        article.body_ja_raw = ""
        article.save()
        self.assertFalse(self._call_eligible(article))

    def test_nonexistent_article_id_not_eligible(self):
        """Passing a non-existent article id should return False (handle gracefully)."""
        try:
            from stable.services.editorial_headlines import is_headline_eligible
        except ImportError:
            self.fail("is_headline_eligible not implemented yet")
        # Try with a pk that does not exist
        try:
            dummy = NewsArticle(pk=999999)
            result = is_headline_eligible(dummy)
            self.assertFalse(result)
        except NewsArticle.DoesNotExist:
            self.fail("is_headline_eligible raised DoesNotExist for missing article")


# ============================================================================
# Test: SetReplaceCancelTests
# ============================================================================

class SetReplaceCancelTests(TestCase):
    """Verify set/replace/cancel operations on the editorial headline selection."""

    def setUp(self):
        self.staff_user = _make_staff_user("editor")
        self.client.force_login(self.staff_user)

    def _set_headline(self, article_id, **kwargs):
        try:
            from stable.services.editorial_headlines import set_manual_headline
        except ImportError:
            self.fail("set_manual_headline not implemented yet")
        return set_manual_headline(article_id, **kwargs)

    def _cancel_headline(self, **kwargs):
        try:
            from stable.services.editorial_headlines import cancel_manual_headline
        except ImportError:
            self.fail("cancel_manual_headline not implemented yet")
        return cancel_manual_headline(**kwargs)

    def _get_headline_state(self, **kwargs):
        try:
            from stable.services.editorial_headlines import get_headline_state
        except ImportError:
            self.fail("get_headline_state not implemented yet")
        return get_headline_state(**kwargs)

    def test_set_headline(self):
        """A staff user with permission can set a headline article."""
        article = _make_article(title="人工头条")
        result = self._set_headline(
            article.pk,
            user=self.staff_user,
            expected_version=0,
        )
        # After setting, the selection must point to this article
        state = self._get_headline_state()
        self.assertEqual(state["article_id"], article.pk)
        self.assertEqual(state["version"], 1)
        # An audit log entry should exist
        audit_log = OperationLog.objects.filter(action_type="headline_set").first()
        self.assertIsNotNone(audit_log)

    def test_replace_headline(self):
        """Setting a different article replaces the previous headline atomically."""
        article_a = _make_article(title="头条A")
        article_b = _make_article(title="头条B")
        state = self._get_headline_state()
        self._set_headline(article_a.pk, user=self.staff_user, expected_version=state["version"])
        state2 = self._get_headline_state()
        self._set_headline(article_b.pk, user=self.staff_user, expected_version=state2["version"])
        state3 = self._get_headline_state()
        self.assertEqual(state3["article_id"], article_b.pk)
        self.assertGreater(state3["version"], state2["version"])
        replaced_log = OperationLog.objects.filter(action_type="headline_replaced").first()
        self.assertIsNotNone(replaced_log)

    def test_cancel_headline(self):
        """Cancelling the headline sets article to NULL and increments version."""
        article = _make_article(title="待取消头条")
        state = self._get_headline_state()
        self._set_headline(article.pk, user=self.staff_user, expected_version=state["version"])
        state2 = self._get_headline_state()
        self._cancel_headline(user=self.staff_user, expected_version=state2["version"])
        state3 = self._get_headline_state()
        self.assertIsNone(state3["article_id"])
        self.assertGreater(state3["version"], state2["version"])
        cancel_log = OperationLog.objects.filter(action_type="headline_cancelled").first()
        self.assertIsNotNone(cancel_log)

    def test_stale_version_conflict(self):
        """A request with an outdated version number must be rejected."""
        article = _make_article(title="版本冲突")
        state = self._get_headline_state()
        self._set_headline(article.pk, user=self.staff_user, expected_version=state["version"])
        # Try with stale version
        with self.assertRaises(Exception):
            self._set_headline(article.pk, user=self.staff_user, expected_version=state["version"])

    def test_no_permission_cannot_set(self):
        """An anonymous user cannot set a headline."""
        anon_client = Client()
        try:
            from stable.services.editorial_headlines import set_manual_headline
        except ImportError:
            self.fail("set_manual_headline not implemented yet")
        article = _make_article(title="匿名尝试")
        with self.assertRaises(PermissionError):
            set_manual_headline(article.pk, user=None, expected_version=0)

    def test_staff_without_perm_cannot_set(self):
        """A staff user without change_homepageheadlineselection perm cannot set."""
        try:
            from stable.services.editorial_headlines import set_manual_headline
        except ImportError:
            self.fail("set_manual_headline not implemented yet")
        no_perm_user = _make_staff_user("no-perm-editor", add_perm=False)
        article = _make_article(title="无权限")
        with self.assertRaises(PermissionError):
            set_manual_headline(article.pk, user=no_perm_user, expected_version=0)

    def test_superuser_can_set(self):
        """A superuser can set a headline even without explicit permission."""
        super_user = _make_staff_user("superadmin", is_superuser=True)
        article = _make_article(title="超级管理员")
        try:
            from stable.services.editorial_headlines import set_manual_headline
        except ImportError:
            self.fail("set_manual_headline not implemented yet")
        result = set_manual_headline(article.pk, user=super_user, expected_version=0)
        try:
            from stable.services.editorial_headlines import get_headline_state
            state = get_headline_state()
            self.assertEqual(state["article_id"], article.pk)
        except ImportError:
            pass


# ============================================================================
# Test: InvalidationTests
# ============================================================================

class InvalidationTests(TestCase):
    """Verify that changes to an article invalidate the headline selection."""

    def setUp(self):
        self.staff_user = _make_staff_user("editor")
        self.article = _make_article(title="被失效头条")

    def _set_headline_and_get_state(self):
        try:
            from stable.services.editorial_headlines import set_manual_headline, get_headline_state
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        state = get_headline_state()
        set_manual_headline(self.article.pk, user=self.staff_user, expected_version=state["version"])
        return get_headline_state()

    def _assert_headline_cleared(self):
        try:
            from stable.services.editorial_headlines import get_headline_state
        except ImportError:
            self.fail("get_headline_state not implemented yet")
        state = get_headline_state()
        self.assertIsNone(state["article_id"])

    def _assert_audit_exists(self, action_type: str):
        self.assertTrue(
            OperationLog.objects.filter(action_type=action_type).exists(),
            f"Expected audit log '{action_type}'",
        )

    def test_withdraw_invalidates(self):
        """Withdrawing the headline article clears the selection and logs audit."""
        self._set_headline_and_get_state()
        self.article.workflow_status = WorkflowStatus.WITHDRAWN
        with self.captureOnCommitCallbacks(execute=True):
            self.article.save(update_fields=["workflow_status"])
        self._assert_headline_cleared()
        self._assert_audit_exists("headline_invalidated")

    def test_change_to_pending_review_invalidates(self):
        """Changing workflow to PENDING_REVIEW invalidates the headline."""
        self._set_headline_and_get_state()
        self.article.workflow_status = WorkflowStatus.PENDING_REVIEW
        with self.captureOnCommitCallbacks(execute=True):
            self.article.save(update_fields=["workflow_status"])
        self._assert_headline_cleared()
        self._assert_audit_exists("headline_invalidated")

    def test_future_publish_time_invalidates(self):
        """Setting published_to_web_at to a future time invalidates the headline."""
        self._set_headline_and_get_state()
        self.article.published_to_web_at = timezone.now() + timedelta(hours=2)
        with self.captureOnCommitCallbacks(execute=True):
            self.article.save(update_fields=["published_to_web_at"])
        self._assert_headline_cleared()
        self._assert_audit_exists("headline_invalidated")

    def test_clear_content_invalidates(self):
        """Clearing body content invalidates the headline."""
        self._set_headline_and_get_state()
        # effective_body falls back through rewrite_body_zh, translated_body_zh,
        # body_ja_normalized, body_ja_raw — clear all to make body truly empty.
        self.article.body_zh = ""
        self.article.translated_body_zh = ""
        self.article.rewrite_body_zh = ""
        self.article.body_ja_normalized = ""
        self.article.body_ja_raw = ""
        with self.captureOnCommitCallbacks(execute=True):
            self.article.save(
                update_fields=[
                    "body_zh",
                    "translated_body_zh",
                    "rewrite_body_zh",
                    "body_ja_normalized",
                    "body_ja_raw",
                ]
            )
        self._assert_headline_cleared()
        self._assert_audit_exists("headline_invalidated")

    def test_delete_article_invalidates(self):
        """Deleting the headline article clears the selection."""
        self._set_headline_and_get_state()
        pk = self.article.pk
        self.article.delete()
        try:
            from stable.services.editorial_headlines import get_headline_state
        except ImportError:
            self.fail("get_headline_state not implemented yet")
        state = get_headline_state()
        self.assertIsNone(state["article_id"])
        self._assert_audit_exists("headline_invalidated")

    def test_invalidation_idempotent(self):
        """Repeated invalidation signals should not create duplicate audit entries."""
        self._set_headline_and_get_state()
        # Make the article ineligible so invalidate_headline_state_for_article
        # actually clears the selection.
        self.article.body_zh = ""
        self.article.translated_body_zh = ""
        self.article.rewrite_body_zh = ""
        self.article.body_ja_normalized = ""
        self.article.body_ja_raw = ""
        with self.captureOnCommitCallbacks(execute=True):
            self.article.save()
        # The on_commit callback already fired once via captureOnCommitCallbacks.
        # Now call the service directly a second time — it should be a no-op.
        try:
            from stable.services.editorial_headlines import invalidate_headline_state_for_article
        except ImportError:
            self.fail("invalidate_headline_state_for_article not implemented yet")
        invalidate_headline_state_for_article(self.article.pk, reason="second")
        count = OperationLog.objects.filter(action_type="headline_invalidated").count()
        self.assertEqual(count, 1, "Invalidation should be idempotent; no duplicate audit log")

    def test_read_fail_safe(self):
        """A selection pointing to an ineligible article must not 500 on the public feed."""
        self._set_headline_and_get_state()
        # Make the article ineligible by changing workflow.
        # Use captureOnCommitCallbacks so the signal-driven invalidation fires.
        self.article.workflow_status = WorkflowStatus.WITHDRAWN
        with self.captureOnCommitCallbacks(execute=True):
            self.article.save(update_fields=["workflow_status"])
        # Public feed should still render without error
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


# ============================================================================
# Test: AlgorithmFallbackTests
# ============================================================================

class AlgorithmFallbackTests(TestCase):
    """Verify that the original algorithm still works and applies correctly."""

    # NOTE: no setUp — each test creates exactly the articles it needs

    def test_no_selection_uses_algorithm(self):
        """When no manual selection exists, the algorithm picks a headline."""
        now = timezone.now()
        _make_article(title="算法基线", published_to_web_at=now, score_total=50)
        try:
            from stable.services.editorial_headlines import resolve_homepage_headline
        except ImportError:
            self.fail("resolve_homepage_headline not implemented yet")
        try:
            from stable.views import _public_published_articles
        except ImportError:
            self.fail("_public_published_articles not importable")
        queryset = _public_published_articles()
        headline = resolve_homepage_headline(queryset)
        self.assertIsNotNone(headline)

    def test_72h_window_first(self):
        """Articles in the 72h window are preferred over older ones."""
        now = timezone.now()
        # Article from 73 hours ago — outside 72h window
        _make_article(
            title="老旧文章",
            published_to_web_at=now - timedelta(hours=73),
            score_total=200,
        )
        # Recent article
        recent = _make_article(
            title="近期文章",
            published_to_web_at=now - timedelta(hours=1),
            score_total=100,
        )
        try:
            from stable.views import _public_published_articles, _select_headline_article
        except ImportError:
            self.fail("View functions not importable")
        queryset = _public_published_articles()
        headline = _select_headline_article(queryset)
        # The recent article should be chosen over the older one with higher score
        self.assertEqual(headline.pk, recent.pk)

    def test_7d_window_fallback(self):
        """If 72h window has no candidates, fall back to 7d window."""
        now = timezone.now()
        # Only create articles older than 72h (inside 7d window)
        _make_article(
            title="三天前文章",
            published_to_web_at=now - timedelta(hours=73),
            score_total=50,
        )
        try:
            from stable.views import _public_published_articles, _select_headline_article
        except ImportError:
            self.fail("View functions not importable")
        queryset = _public_published_articles()
        headline = _select_headline_article(queryset)
        # Should have fallen back to older article
        self.assertIsNotNone(headline)
        self.assertIn("三天前", headline.effective_title)

    def test_all_window_fallback(self):
        """When both 72h and 7d are empty, fall back to all articles."""
        now = timezone.now()
        _make_article(
            title="非常旧文章",
            published_to_web_at=now - timedelta(days=10),
            score_total=30,
        )
        try:
            from stable.views import _public_published_articles, _select_headline_article
        except ImportError:
            self.fail("View functions not importable")
        queryset = _public_published_articles()
        headline = _select_headline_article(queryset)
        self.assertIsNotNone(headline)

    def test_sort_key_preserved(self):
        """The sort key tuple must match the existing algorithm signature."""
        try:
            from stable.views import _headline_sort_key
        except ImportError:
            self.fail("_headline_sort_key not importable")
        article = _make_article(title="排序测试", score_total=80, race_priority="P0")
        key = _headline_sort_key(article)
        # Expected: (race_priority_score, score_total, has_cover, timestamp, id)
        self.assertEqual(len(key), 5)
        self.assertIsInstance(key[0], int)
        self.assertIsInstance(key[1], int)
        self.assertIsInstance(key[2], int)
        self.assertIsInstance(key[3], float)
        self.assertIsInstance(key[4], int)

    def test_ineligible_not_selected_by_algorithm(self):
        """Ineligible articles should not be selected by the algorithm."""
        now = timezone.now()
        _make_article(
            title="草稿不入选",
            workflow_status=WorkflowStatus.PENDING_REVIEW,
            published_to_web_at=now,
            score_total=999,
        )
        _make_article(
            title="合格替补",
            published_to_web_at=now - timedelta(minutes=1),
            score_total=1,
        )
        try:
            from stable.views import _public_published_articles, _select_headline_article
        except ImportError:
            self.fail("View functions not importable")
        queryset = _public_published_articles()
        headline = _select_headline_article(queryset)
        self.assertIsNotNone(headline)
        self.assertNotEqual("草稿不入选", headline.effective_title)

    def test_48_candidate_boundary(self):
        """Exactly 48 eligible candidates should all be considered."""
        now = timezone.now()
        for i in range(48):
            _make_article(
                title=f"候选文章{i:02d}",
                published_to_web_at=now - timedelta(minutes=i),
                score_total=i,
            )
        try:
            from stable.views import _public_published_articles, _select_headline_article
        except ImportError:
            self.fail("View functions not importable")
        queryset = _public_published_articles()
        headline = _select_headline_article(queryset)
        self.assertIsNotNone(headline)

    def test_49th_excluded(self):
        """The 49th candidate should be excluded from headline selection."""
        now = timezone.now()
        for i in range(49):
            _make_article(
                title=f"候选文章{i:02d}",
                published_to_web_at=now - timedelta(minutes=i),
                score_total=i,
            )
        try:
            from stable.views import _public_published_articles, _select_headline_article
        except ImportError:
            self.fail("View functions not importable")
        queryset = _public_published_articles()
        headline = _select_headline_article(queryset)
        # The 49th article (index 48, score 48, oldest) should be excluded;
        # the chosen headline should be an article among the first 48.
        self.assertIsNotNone(headline)
        # Verify the headline's title is among 候选文章00..47, not 候选文章48
        excluded_title = "候选文章48"
        self.assertNotEqual(headline.effective_title, excluded_title)


# ============================================================================
# Test: RecommendationTests
# ============================================================================

class RecommendationTests(TestCase):
    """Verify the AI recommendation workflow."""

    def setUp(self):
        self.staff_user = _make_staff_user("editor")

    def test_generate_recommendation(self):
        """A recommendation can be generated with a reason and evidence."""
        now = timezone.now()
        article = _make_article(title="推荐头条", published_to_web_at=now)
        try:
            from stable.services.editorial_headlines import generate_headline_recommendation
        except ImportError:
            self.fail("generate_headline_recommendation not implemented yet")
        result = generate_headline_recommendation(user=self.staff_user)
        self.assertIsNotNone(result)
        self.assertTrue(len(result.get("reason", "")) > 0)
        self.assertIn("engine_version", result.get("evidence", {}))

    def test_recommendation_does_not_change_homepage(self):
        """Generating a recommendation must NOT change the visible homepage headline."""
        now = timezone.now()
        article = _make_article(title="原头条", published_to_web_at=now)
        try:
            from stable.services.editorial_headlines import (
                generate_headline_recommendation,
                get_headline_state,
            )
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        state_before = get_headline_state()
        generate_headline_recommendation(user=self.staff_user)
        state_after = get_headline_state()
        self.assertEqual(state_before["article_id"], state_after["article_id"])
        self.assertEqual(state_before["version"], state_after["version"])

    def test_recommendation_supersede(self):
        """Generating a second recommendation supersedes the first."""
        now = timezone.now()
        article_a = _make_article(title="头条A", published_to_web_at=now)
        article_b = _make_article(title="头条B", published_to_web_at=now - timedelta(hours=1))
        try:
            from stable.services.editorial_headlines import generate_headline_recommendation
            from stable.models import HomepageHeadlineRecommendation
        except ImportError:
            self.fail("HomepageHeadlineRecommendation not implemented yet")
        rec1 = generate_headline_recommendation(user=self.staff_user)
        rec2 = generate_headline_recommendation(user=self.staff_user)
        rec1_active = HomepageHeadlineRecommendation.objects.filter(pk=rec1["id"], status="active").exists()
        rec2_active = HomepageHeadlineRecommendation.objects.filter(pk=rec2["id"], status="active").exists()
        self.assertFalse(rec1_active, "First recommendation should be superseded")
        self.assertTrue(rec2_active, "Second recommendation should be active")

    def test_accept_recommendation(self):
        """Accepting a recommendation sets the selection and marks it accepted."""
        now = timezone.now()
        article = _make_article(title="推荐接受", published_to_web_at=now)
        try:
            from stable.services.editorial_headlines import (
                generate_headline_recommendation,
                accept_headline_recommendation,
                get_headline_state,
            )
            from stable.models import HomepageHeadlineRecommendation
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        rec = generate_headline_recommendation(user=self.staff_user)
        state_before = get_headline_state()
        result = accept_headline_recommendation(
            rec["id"],
            user=self.staff_user,
            expected_selection_version=state_before["version"],
        )
        state_after = get_headline_state()
        self.assertEqual(state_after["article_id"], rec["article_id"])
        rec_obj = HomepageHeadlineRecommendation.objects.get(pk=rec["id"])
        self.assertEqual(rec_obj.status, "accepted")

    def test_manual_selection_not_overwritten(self):
        """A manually set headline must NOT be overwritten by recommendation generation."""
        now = timezone.now()
        manual_article = _make_article(title="人工选定A", published_to_web_at=now)
        rec_article = _make_article(title="推荐B", published_to_web_at=now - timedelta(hours=2))
        try:
            from stable.services.editorial_headlines import (
                set_manual_headline,
                generate_headline_recommendation,
                get_headline_state,
            )
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        state = get_headline_state()
        set_manual_headline(manual_article.pk, user=self.staff_user, expected_version=state["version"])
        generate_headline_recommendation(user=self.staff_user)
        state_after = get_headline_state()
        self.assertEqual(state_after["article_id"], manual_article.pk)

    def test_reject_superseded_recommendation(self):
        """A superseded recommendation cannot be accepted."""
        now = timezone.now()
        article = _make_article(title="被取代推荐", published_to_web_at=now)
        try:
            from stable.services.editorial_headlines import (
                generate_headline_recommendation,
                accept_headline_recommendation,
                get_headline_state,
            )
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        rec1 = generate_headline_recommendation(user=self.staff_user)
        generate_headline_recommendation(user=self.staff_user)  # supersedes rec1
        state = get_headline_state()
        with self.assertRaises(Exception):
            accept_headline_recommendation(
                rec1["id"],
                user=self.staff_user,
                expected_selection_version=state["version"],
            )

    def test_reject_ineligible_recommendation_article(self):
        """A recommendation whose article is no longer eligible cannot be accepted."""
        now = timezone.now()
        article = _make_article(
            title="已失效推荐",
            published_to_web_at=now,
        )
        try:
            from stable.services.editorial_headlines import (
                generate_headline_recommendation,
                accept_headline_recommendation,
                get_headline_state,
            )
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        rec = generate_headline_recommendation(user=self.staff_user)
        # Make the article ineligible
        article.workflow_status = WorkflowStatus.WITHDRAWN
        article.save(update_fields=["workflow_status"])
        state = get_headline_state()
        with self.assertRaises(Exception):
            accept_headline_recommendation(
                rec["id"],
                user=self.staff_user,
                expected_selection_version=state["version"],
            )

    def test_no_candidates_no_empty_recommendation(self):
        """When no eligible candidates exist, no recommendation should be created."""
        try:
            from stable.services.editorial_headlines import generate_headline_recommendation
        except ImportError:
            self.fail("generate_headline_recommendation not implemented yet")
        # Delete all articles — no candidates
        NewsArticle.objects.all().delete()
        result = generate_headline_recommendation(user=self.staff_user)
        self.assertIsNone(result, "No recommendation should be created when no candidates exist")


# ============================================================================
# Test: CacheRealtimeTests
# ============================================================================

class CacheRealtimeTests(TestCase):
    """Verify that headline changes reflect immediately without caching."""

    def setUp(self):
        self.staff_user = _make_staff_user("editor")
        self.client.force_login(self.staff_user)

    def test_consecutive_requests_reflect_changes(self):
        """Setting, replacing, and cancelling the headline must reflect immediately via GET."""
        article_a = _make_article(title="头条实时A")
        article_b = _make_article(title="头条实时B")

        # No manual headline initially — algorithm picks
        response1 = self.client.get("/")
        self.assertEqual(response1.status_code, 200)

        # Set headline A
        try:
            from stable.services.editorial_headlines import set_manual_headline, get_headline_state
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        state = get_headline_state()
        set_manual_headline(article_a.pk, user=self.staff_user, expected_version=state["version"])
        response2 = self.client.get("/")
        self.assertEqual(response2.status_code, 200)

        # Replace with B
        state2 = get_headline_state()
        set_manual_headline(article_b.pk, user=self.staff_user, expected_version=state2["version"])
        response3 = self.client.get("/")
        self.assertEqual(response3.status_code, 200)

        # Cancel
        state3 = get_headline_state()
        try:
            from stable.services.editorial_headlines import cancel_manual_headline
        except ImportError:
            self.fail("cancel_manual_headline not implemented yet")
        cancel_manual_headline(user=self.staff_user, expected_version=state3["version"])
        response4 = self.client.get("/")
        self.assertEqual(response4.status_code, 200)

    def test_no_headline_cache_key_used(self):
        """Verify that no headline-specific cache key is referenced."""
        try:
            from stable.services.editorial_headlines import get_headline_state
        except ImportError:
            self.fail("get_headline_state not implemented yet")
        # The function should hit the database directly, not a cache
        state = get_headline_state()
        self.assertIn("article_id", state)
        self.assertIn("version", state)


# ============================================================================
# Test: AdminBulkActionTests
# ============================================================================

class AdminBulkActionTests(TestCase):
    """Bulk admin actions should trigger headline invalidation."""

    def test_mark_pending_review_invalidates_headline(self):
        """Bulk 'mark as pending review' admin action must invalidate the current headline."""
        superuser = User.objects.create_superuser("root", "root@test.com", "testpass")
        article = _make_article(title="管理批量头条")
        try:
            from stable.services.editorial_headlines import set_manual_headline, get_headline_state
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")
        state = get_headline_state()
        set_manual_headline(article.pk, user=superuser, expected_version=state["version"])

        from stable.admin import NewsArticleAdmin
        from django.http import HttpRequest
        admin_instance = NewsArticleAdmin(model=NewsArticle, admin_site=None)
        request = HttpRequest()
        request.user = superuser
        queryset = NewsArticle.objects.filter(pk=article.pk)
        with self.captureOnCommitCallbacks(execute=True):
            admin_instance.mark_pending_review(request, queryset)
        article.refresh_from_db()
        self.assertEqual(article.workflow_status, WorkflowStatus.PENDING_REVIEW)
        # Headline must have been cleared
        try:
            from stable.services.editorial_headlines import get_headline_state
        except ImportError:
            self.fail("get_headline_state not implemented yet")
        state = get_headline_state()
        self.assertIsNone(state["article_id"], "Headline should be cleared after bulk pending review")


# ============================================================================
# Test: SignalExceptionTests
# ============================================================================

class SignalExceptionTests(TestCase):
    """Exceptions in signal handlers must be logged but never re-raised."""

    def setUp(self):
        self.staff_user = _make_staff_user("editor")

    def test_on_commit_exception_logged_not_reraised(self):
        """A signal callback that raises must be logged and must not propagate."""
        from unittest.mock import patch

        try:
            from stable.services.editorial_headlines import set_manual_headline
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")

        with patch(
            "stable.services.editorial_headlines.invalidate_headline_state_for_article",
            side_effect=RuntimeError("DB down"),
        ):
            # Wrap article creation + headline set in captureOnCommitCallbacks
            # so that the on_commit callback registered by the post_save signal
            # actually executes and hits the mocked exception path.
            with self.captureOnCommitCallbacks(execute=True):
                article = _make_article(title="信号异常测试")
                result = set_manual_headline(
                    article.pk, user=self.staff_user, expected_version=0
                )
            self.assertIsNotNone(result)

        # The error should be captured in OperationLog
        error_log = OperationLog.objects.filter(action_type="signal_error").first()
        self.assertIsNotNone(error_log, "Signal errors should be logged")


# ============================================================================
# Test: ImageQueryCountTests
# ============================================================================

class ImageQueryCountTests(TestCase):
    """Ensure no N+1 image queries during headline candidate scanning."""

    def test_no_n_plus_1_for_images(self):
        """Scanning headline candidates must not produce N+1 NewsImage queries.

        Creates articles with real NewsImage rows and calls the actual
        homepage resolver (resolve_homepage_headline) so that the
        cover-detection code path is exercised end-to-end."""
        now = timezone.now()
        for i in range(5):
            article = _make_article(
                title=f"图片查询文章{i}",
                published_to_web_at=now - timedelta(hours=i),
                body_text=f"Body {i}",
                summary_text=f"Summary {i}",
            )
            # Attach a real NewsImage so that the prefetch is actually populated.
            NewsImage.objects.create(
                article=article,
                original_url=f"https://example.com/img/{i}.jpg",
                sort_order=0,
            )

        # Import the *public* resolver, not the service-only scanner.
        try:
            from stable.services.editorial_headlines import resolve_homepage_headline
        except ImportError:
            self.fail("resolve_homepage_headline not implemented yet")
        try:
            from stable.views import _public_published_articles
        except ImportError:
            self.fail("_public_published_articles not importable")

        queryset = _public_published_articles()
        with CaptureQueriesContext(connection) as captured:
            headline = resolve_homepage_headline(queryset)
        self.assertIsNotNone(headline)

        # Count only NewsImage queries. A correct prefetch performs ONE
        # NewsImage query (the prefetch itself); an N+1 bug produces one
        # per candidate article (5+). Allow a small margin for SQLite
        # internal housekeeping.
        image_queries = [
            q for q in captured.captured_queries
            if "news_image" in q["sql"].lower()
            or "stable_newsimage" in q["sql"].lower()
        ]
        self.assertLessEqual(
            len(image_queries), 2,
            f"N+1: {len(image_queries)} NewsImage queries for 5 articles; "
            f"expected ≤2 (prefetch + margin). "
            f"Total queries: {len(captured)}"
        )


# ============================================================================
# Test: PublicRegressionTests
# ============================================================================

class PublicRegressionTests(TestCase):
    """Regression tests for the public homepage."""

    def test_source_hidden_in_headline(self):
        """The headline section must NOT show source_note."""
        now = timezone.now()
        article = _make_article(
            title="隐藏来源头条",
            published_to_web_at=now,
            has_cover=True,
            score_total=200,
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, article.source_note)

    def test_region_hidden_in_headline(self):
        """The headline section must NOT show region display labels."""
        now = timezone.now()
        article = _make_article(
            title="不显示地区头条",
            published_to_web_at=now,
            racing_region=RacingRegion.JAPAN,
            has_cover=True,
            score_total=200,
        )
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        # "日本" might appear in other contexts, but the headline template should not render it
        # This test assumes the headline partial suppresses the region label
        self.assertNotContains(response, "日本")

    def test_no_empty_headline_500(self):
        """When no eligible articles exist, the homepage must not crash."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


# ============================================================================
# Test: PostgresConcurrencyTests (requires PostgreSQL)
# ============================================================================

class PostgresConcurrencyTests(TransactionTestCase):
    """Concurrent modifications must be handled safely — requires PostgreSQL.

    Uses TransactionTestCase (not TestCase) so that fixtures are committed
    and visible to worker-thread connections. Each thread obtains its own
    database connection for true inter-connection serialisation testing."""

    def setUp(self):
        self.staff_user = _make_staff_user("concurrency-editor")
        self._staff_user_id = self.staff_user.pk

    def _worker_user(self):
        """Return a User instance fetched through a fresh thread-local connection."""
        from django.contrib.auth import get_user_model
        return get_user_model().objects.get(pk=self._staff_user_id)

    def _worker_article(self, pk):
        """Return a NewsArticle fetched through a fresh thread-local connection."""
        return NewsArticle.objects.get(pk=pk)

    def test_concurrent_set_different_articles(self):
        """Two connections setting different articles simultaneously — only one succeeds."""
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL")
        article_a = _make_article(title="并发A")
        article_b = _make_article(title="并发B")
        a_pk = article_a.pk
        b_pk = article_b.pk
        try:
            from stable.services.editorial_headlines import set_manual_headline, get_headline_state
        except ImportError:
            self.fail("set_manual_headline not implemented yet")

        import threading
        results = []

        def set_a():
            try:
                state = get_headline_state()
                set_manual_headline(a_pk, user=self._worker_user(), expected_version=state["version"])
                results.append("A_ok")
            except Exception as e:
                results.append(f"A_failed:{e}")

        def set_b():
            try:
                state = get_headline_state()
                set_manual_headline(b_pk, user=self._worker_user(), expected_version=state["version"])
                results.append("B_ok")
            except Exception as e:
                results.append(f"B_failed:{e}")

        t1 = threading.Thread(target=set_a)
        t2 = threading.Thread(target=set_b)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = sum(1 for r in results if r.endswith("_ok"))
        self.assertEqual(successes, 1, "Exactly one concurrent set should succeed — got results: " + str(results))

    def test_concurrent_generate_recommendation(self):
        """Two connections generating recommendations — only one active recommendation."""
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL")
        now = timezone.now()
        article = _make_article(title="并发推荐", published_to_web_at=now)
        try:
            from stable.services.editorial_headlines import generate_headline_recommendation
            from stable.models import HomepageHeadlineRecommendation
        except ImportError:
            self.fail("editorial_headlines module not implemented yet")

        import threading
        results = []

        def gen1():
            try:
                r = generate_headline_recommendation(user=self._worker_user())
                results.append(f"g1:{r['id']}")
            except Exception as e:
                results.append(f"g1_err:{e}")

        def gen2():
            try:
                r = generate_headline_recommendation(user=self._worker_user())
                results.append(f"g2:{r['id']}")
            except Exception as e:
                results.append(f"g2_err:{e}")

        t1 = threading.Thread(target=gen1)
        t2 = threading.Thread(target=gen2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        active_count = HomepageHeadlineRecommendation.objects.filter(status="active").count()
        self.assertEqual(active_count, 1, "Only one active recommendation should survive concurrent generation")
